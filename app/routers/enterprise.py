import os
import re
import hmac
import json
import uuid
import secrets
import logging
import hashlib
import threading
from typing import Optional
from urllib.parse import quote, urlparse

import requests
from jose import jwt as jose_jwt, JWTError
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from datetime import timedelta, datetime, date, timezone as dt_timezone
from pydantic import BaseModel, EmailStr, Field

from app.database import get_db, SessionLocal
from app import models
from app import enterprise_catalog as catalog
from app import enterprise_billing as billing
from app import enterprise_credits as credits
from app import enterprise_coupons
from app import enterprise_payments
from app import enterprise_ai
from app import enterprise_copilot
from app import enterprise_interview
from app import ai_guardrails
from app import ai_usage
from app import enterprise_storage
from app import enterprise_notifications as notif
from app.utils import gemini_service
from app.routers.ai_chat import ChatSessionAttachment
from app.auth import (
    authenticate_user,
    create_access_token,
    get_current_active_user,
    get_password_hash,
    validate_password_strength,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    SECRET_KEY as AUTH_SECRET_KEY,
    ALGORITHM as AUTH_ALGORITHM,
    set_auth_cookie,
)
from app.utils.rate_limiter import (
    check_ip_rate_limit,
    extract_client_ip,
    is_request_ip_whitelisted,
)
from app.utils.turnstile import is_turnstile_enabled, verify_turnstile_token
from app.email_service import send_enterprise_team_invite_email, send_enterprise_client_email
from app.email_service import send_enterprise_inbound_reply_alert_email
from app import enterprise_inbound_email as inbound_email
from app.email_service import send_enterprise_interview_invite_email, send_enterprise_interview_code_email
from app.email_service import send_enterprise_interview_report_email
from app.email_service import send_enterprise_document_request_email, send_enterprise_document_request_code_email
from app.email_service import send_enterprise_portal_share_email, send_enterprise_portal_code_email
from app.email_service import send_enterprise_payment_request_email
from app.email_service import send_enterprise_payment_dispute_alert_email
from app.email_service import generate_verification_token, DEFAULT_PUBLIC_BASE_URL
from app.email_service import send_enterprise_support_request_email, send_enterprise_demo_request_email
from app.email_service import send_feature_request_confirmation
from app.email_service import send_enterprise_welcome_email
from app.email_service import send_email_otp
from app.utils.token_security import hash_token, token_matches

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
        ],
        "intakes_by_visa": {
            "Study Permit": ["January", "May", "September"],
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
    # Company location (org records). country_code also drives the portal display currency.
    country_code: Optional[str] = Field(default=None, max_length=8)
    state_region: Optional[str] = Field(default=None, max_length=80)


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


class EnterpriseDemoRequestBody(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=120)
    work_email: EmailStr
    company: Optional[str] = Field(default=None, max_length=160)
    phone: Optional[str] = Field(default=None, max_length=40)
    team_size: Optional[str] = Field(default=None, max_length=40)
    students_count: Optional[str] = Field(default=None, max_length=40)
    message: Optional[str] = Field(default=None, max_length=2000)
    source: Optional[str] = Field(default=None, max_length=200)


@router.post("/demo")
def enterprise_public_demo_request(
    payload: EnterpriseDemoRequestBody,
    request: Request,
    db: Session = Depends(get_db),
):
    """PUBLIC (no auth) 'book a demo' lead from the enterprise landing page. Stores the
    lead (so none is lost) and best-effort emails the sales inbox."""
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.demo_request", limit=8, window_seconds=3600,
    )
    name = (payload.full_name or "").strip()
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Please enter your name.")

    lead = models.EnterpriseDemoRequest(
        full_name=name[:120],
        work_email=str(payload.work_email).strip()[:200],
        company=(payload.company or "").strip()[:160] or None,
        phone=(payload.phone or "").strip()[:40] or None,
        team_size=(payload.team_size or "").strip()[:40] or None,
        students_count=(payload.students_count or "").strip()[:40] or None,
        message=(payload.message or "").strip()[:2000] or None,
        source=(payload.source or "").strip()[:200] or None,
        ip_address=(extract_client_ip(request) if request else None),
        status="new",
    )
    db.add(lead)
    db.commit()

    try:
        send_enterprise_demo_request_email(
            full_name=lead.full_name,
            work_email=lead.work_email,
            company=lead.company or "",
            phone=lead.phone or "",
            team_size=lead.team_size or "",
            students_count=lead.students_count or "",
            message=lead.message or "",
        )
    except Exception:
        logger.exception("Demo-request notification email failed (lead=%s)", lead.id)

    return {"message": "Thanks! Our team will email you shortly to schedule your demo."}


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
        # Uploaded logos are stored privately and served via our own public streaming
        # route — a same-origin relative URL that works on every portal subdomain.
        if raw_logo.startswith("/api/enterprise/public/org-logo/"):
            return raw_logo
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
    # SECURITY NOTE: x-forwarded-host is client-controllable unless the edge proxy overwrites
    # it. The value here only drives the *cosmetic* subdomain guard (_enforce_request_subdomain_
    # matches_org) — the acting org is ALWAYS resolved from the caller's membership, never from
    # the host — so a spoofed header cannot cross tenants, only bypass a "use your org URL" 403.
    # Harden at the infra layer: configure the proxy (Render/Cloudflare) to STRIP any inbound
    # X-Forwarded-Host and set it itself, so clients can't inject it. (Kept XFH-first here to
    # match app-wide host resolution in main.py:_request_host and avoid breaking prod routing.)
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


_CURRENCY_SYMBOLS = {
    "INR": "₹", "USD": "$", "GBP": "£", "EUR": "€", "CAD": "CA$",
    "AUD": "A$", "AED": "AED ", "SGD": "S$", "JPY": "¥",
}


def _org_display_currency(organization) -> dict:
    """The portal's DISPLAY currency, derived from the company's country in Settings.
    Billing stays in INR — this only converts what the UI shows, at the live exchange
    rate (Frankfurter via /api/pricing/exchange-rates, 24h-cached, safe fallbacks).
    India (or unset) → INR; unlisted countries → USD like the B2C pricing page."""
    from app.routers import pricing as pricing_fx

    country_code = (getattr(organization, "country_code", None) or "").strip().upper()
    code = pricing_fx._COUNTRY_TO_CURRENCY.get(country_code, "USD") if country_code else "INR"
    if code == "INR":
        return {"code": "INR", "symbol": "₹", "rate_from_inr": 1.0, "source": "native", "provider_date": None}

    rate = None
    source = "fallback"
    provider_date = None
    try:
        payload = pricing_fx.get_exchange_rates(refresh=False)
        rates = payload.get("rates") or {}
        inr = float(rates.get("INR") or 0.0)
        target = float(rates.get(code) or 0.0)
        if inr > 0 and target > 0:
            rate = target / inr
            source = payload.get("source") or "live"
            provider_date = payload.get("provider_date")
    except Exception:
        logger.exception("Display-currency rate lookup failed (org_id=%s)", getattr(organization, "id", None))
    if not rate:
        fallback = pricing_fx.FALLBACK_RATES
        rate = float(fallback.get(code, 1.0)) / float(fallback.get("INR", 83.2))
    return {
        "code": code,
        "symbol": _CURRENCY_SYMBOLS.get(code, code + " "),
        "rate_from_inr": round(rate, 6),
        "source": source,
        "provider_date": provider_date,
    }


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
    credits_summary = None
    if not onboarding_required:
        try:
            subscription_summary = _serialize_subscription_state(
                billing.build_subscription_state(db, organization.id)
            )
        except Exception:
            logger.exception("Failed to build subscription state for org_id=%s", organization.id)
        try:
            credits_summary = credits.wallet_state(db, organization.id)
        except Exception:
            logger.exception("Failed to build credit wallet state for org_id=%s", organization.id)

    return {
        "onboarding_required": onboarding_required,
        "organization": {
            "id": organization.id,
            "company_name": company_name or organization.company_name,
            "subdomain_slug": subdomain_slug or None,
            "logo_url": logo_url,
            "portal_url": _build_enterprise_portal_url(subdomain_slug, request),
            "created_at": organization.created_at,
            "country_code": organization.country_code,
            "state_region": organization.state_region,
            "display_currency": _org_display_currency(organization),
        },
        "membership": {
            "role": normalized_role,
            "is_active": bool(membership.is_active),
            "joined_at": membership.created_at,
        },
        "subscription": subscription_summary,
        "credits": credits_summary,
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


def backfill_enterprise_account_flag(db: Session) -> None:
    """Idempotent backfill of users.is_enterprise_account for accounts that predate the B2B/B2C
    product separation. Flags enterprise-CREATED accounts (so they're blocked from the B2C app)
    using RELIABLE positive signals only — never a "B2C footprint" heuristic, which is unsafe on
    this shared users table (a one-time journey migration blanket-set destination_country_code /
    onboarding_completed_at on every row, and a dormant password B2C signup has no footprint at
    all — so footprint-guessing both misses old enterprise owners and wrongly locks out real
    consumers who were later invited to a team).

    Policy ("block only enterprise-created"; keep B2C access for anyone who was a B2C user first):
      * Workspace OWNERS (EnterpriseOrganization.created_by_user_id) are flagged UNCONDITIONALLY:
        enterprise signup rejects an existing email, so an owner's account was created BY the
        enterprise product and was never a prior B2C user.
      * MEMBERS are flagged only when the account's `university` equals their org's company_name —
        the exact value the invite flow writes when it CREATES a brand-new teammate. The invite
        REUSE branch never rewrites an existing user's university, so a person who was a B2C user
        first keeps their own university (or NULL) and is left untouched → keeps consumer access.
        Membership rows are considered regardless of is_active: origin doesn't change when a
        teammate is removed (their going-forward flag would have survived deactivation too), and
        the university==company_name gate keeps this false-positive-safe.

    Only ever SETS the flag (additive/idempotent); never clears it and never touches
    admins/developers. Safe to run on every startup.

    KNOWN RESIDUAL (accepted): a member is matched against the org's CURRENT company_name. If an
    org renamed its company AFTER a historical teammate was invite-created (their frozen university
    holds the OLD name, and there is no name history to recover it), the backfill won't flag that
    teammate — they keep B2C access. This is bounded to pre-separation renamed orgs; every account
    created from now on is flagged at creation, which is the real source of truth.
    """
    organizations = db.query(
        models.EnterpriseOrganization.id,
        models.EnterpriseOrganization.company_name,
        models.EnterpriseOrganization.created_by_user_id,
    ).all()
    if not organizations:
        return

    owner_ids: set[int] = set()
    company_by_org: dict[int, str] = {}
    for org_id, company_name, created_by in organizations:
        company_by_org[org_id] = (company_name or "").strip()
        if created_by is not None:
            owner_ids.add(int(created_by))

    # For each member (active OR not — membership indicates enterprise origin, which removal from
    # the team doesn't undo), the set of company names of the org(s) they belong to.
    member_companies: dict[int, set[str]] = {}
    for user_id, org_id in (
        db.query(
            models.EnterpriseOrganizationMember.user_id,
            models.EnterpriseOrganizationMember.organization_id,
        )
        .all()
    ):
        if user_id is None:
            continue
        company = company_by_org.get(org_id)
        if company:
            member_companies.setdefault(int(user_id), set()).add(company)

    candidate_ids = owner_ids | set(member_companies.keys())
    if not candidate_ids:
        return

    changed = 0
    for user in db.query(models.User).filter(models.User.id.in_(candidate_ids)).all():
        if getattr(user, "is_enterprise_account", False):
            continue
        if user.is_admin or user.is_developer:
            continue
        is_owner = user.id in owner_ids
        # Positive enterprise-origin marker for members: the account's university was set to the
        # org's company name — which only the invite CREATE path does (reuse leaves it as-is).
        university = (user.university or "").strip()
        member_created_by_org = bool(university) and university in member_companies.get(user.id, set())
        if is_owner or member_created_by_org:
            user.is_enterprise_account = True
            changed += 1

    if changed:
        db.commit()
        logger.info(
            "Backfilled is_enterprise_account=True for %d enterprise-origin account(s).", changed
        )


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
            "heard_about_answered": getattr(current_user, "heard_about_us_at", None) is not None,
        },
        **_build_enterprise_context(db, current_user, request),
    }


class EnterpriseHeardAboutRequest(BaseModel):
    source: str = Field(..., min_length=1, max_length=40)
    detail: Optional[str] = Field(default=None, max_length=200)


@router.get("/heard-about")
def enterprise_heard_about_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Options + answered state for the enterprise post-signup 'How did you hear' prompt."""
    from app import acquisition
    _enforce_enterprise_access_or_403(db, current_user)
    return {
        "answered": getattr(current_user, "heard_about_us_at", None) is not None,
        "selected": getattr(current_user, "heard_about_us", None),
        "options": acquisition.HEARD_ABOUT_OPTIONS,
    }


@router.post("/heard-about")
def enterprise_submit_heard_about(
    payload: EnterpriseHeardAboutRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Save the self-reported 'How did you hear about us?' answer for an enterprise user."""
    from app import acquisition
    _enforce_enterprise_access_or_403(db, current_user)
    if (payload.source or "").strip().lower() == "skip":
        current_user.heard_about_us_at = datetime.utcnow()  # mark asked; don't nag again
        db.commit()
        return {"ok": True, "selected": None}
    vid = acquisition.apply_self_reported_source(current_user, payload.source, payload.detail)
    if not vid:
        raise HTTPException(status_code=400, detail="Please choose a valid option.")
    db.commit()
    return {"ok": True, "selected": vid}


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

    if payload.country_code is not None:
        country_code = (payload.country_code or "").strip().upper()
        if country_code and (len(country_code) != 2 or not country_code.isalpha()):
            raise HTTPException(status_code=400, detail="Enter a valid 2-letter country code.")
        organization.country_code = country_code or None
        has_update = True
    if payload.state_region is not None:
        organization.state_region = (payload.state_region or "").strip()[:80] or None
        has_update = True

    if not has_update:
        raise HTTPException(status_code=400, detail="Nothing to update.")

    db.commit()

    context = _build_enterprise_context(db, current_user, request)
    return {
        "message": "Organization branding updated successfully.",
        "organization": context.get("organization"),
    }


ENTERPRISE_LOGO_MAX_BYTES = 2 * 1024 * 1024  # 2 MB upload cap
_ENTERPRISE_LOGO_FILENAME_RE = re.compile(r"^logo-[0-9a-f]{32}\.png$")


def _normalize_logo_image_or_400(data: bytes) -> bytes:
    """Validate an uploaded logo and re-encode it. Only a real PNG/JPEG/WebP raster is
    accepted; it is downscaled to ≤512px and re-encoded to a fresh PNG, so nothing but a
    clean, metadata-free raster we produced ourselves is ever stored or served."""
    import io
    try:
        from PIL import Image
        probe = Image.open(io.BytesIO(data))
        probe.verify()  # detects truncated/corrupt files (invalidates the handle)
        img = Image.open(io.BytesIO(data))
        if (img.format or "").upper() not in {"PNG", "JPEG", "WEBP"}:
            raise ValueError("unsupported format")
        img = img.convert("RGBA")
        img.thumbnail((512, 512))
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception:
        raise HTTPException(status_code=400, detail="Please upload a valid PNG, JPG, or WebP image.")


@router.post("/organization/logo")
async def enterprise_upload_org_logo(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Upload a custom organization logo. Stored encrypted like other enterprise assets and
    served back through the unguessable public logo route below."""
    _, organization, _ = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_manage_users=True
    )
    if not enterprise_storage.is_configured():
        raise HTTPException(status_code=503, detail="Logo storage is not configured.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The file is empty.")
    if len(data) > ENTERPRISE_LOGO_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Logo is too large. Maximum size is 2 MB.")
    png_bytes = _normalize_logo_image_or_400(data)

    filename = f"logo-{uuid.uuid4().hex}.png"
    try:
        enterprise_storage.store_document(
            f"enterprise/{organization.id}/branding/{filename}", png_bytes, content_type="image/png"
        )
    except Exception:
        logger.exception("Failed to store org logo (org_id=%s)", organization.id)
        raise HTTPException(status_code=502, detail="Could not store the logo right now. Please try again.")

    # Best-effort cleanup of the previously uploaded logo (generated/external URLs untouched).
    old_match = re.match(
        r"^/api/enterprise/public/org-logo/(\d+)/(logo-[0-9a-f]{32}\.png)$",
        str(organization.logo_url or ""),
    )
    if old_match and int(old_match.group(1)) == organization.id:
        enterprise_storage.delete_document(f"enterprise/{organization.id}/branding/{old_match.group(2)}")

    organization.logo_url = f"/api/enterprise/public/org-logo/{organization.id}/{filename}"
    db.commit()

    context = _build_enterprise_context(db, current_user, request)
    return {"message": "Logo updated.", "organization": context.get("organization")}


@router.get("/public/org-logo/{org_id}/{filename}")
def enterprise_public_org_logo(org_id: int, filename: str):
    """Serve an uploaded organization logo. Unauthenticated by design: the filename embeds an
    unguessable 128-bit token, and a logo is public branding (never client data). Only files
    matching our own generated pattern under the org's branding prefix can be addressed."""
    if not _ENTERPRISE_LOGO_FILENAME_RE.fullmatch(str(filename or "")):
        raise HTTPException(status_code=404, detail="Not found")
    try:
        data = enterprise_storage.fetch_document(f"enterprise/{int(org_id)}/branding/{filename}")
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


# ---------------------------------------------------------------------------
# In-portal notifications (topbar bell)
# ---------------------------------------------------------------------------

class EnterpriseNotificationsReadRequest(BaseModel):
    ids: Optional[list[int]] = None
    all: bool = False


@router.get("/notifications")
def enterprise_notifications_list(
    request: Request,
    limit: int = 30,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """The signed-in member's notifications (newest first) + unread count."""
    _, organization, _role = _require_enterprise_membership(db=db, user=current_user, request=request)
    take = max(1, min(int(limit or 30), 50))
    rows = (
        db.query(models.EnterpriseNotification)
        .filter(
            models.EnterpriseNotification.organization_id == organization.id,
            models.EnterpriseNotification.recipient_user_id == current_user.id,
        )
        .order_by(models.EnterpriseNotification.created_at.desc(), models.EnterpriseNotification.id.desc())
        .limit(take)
        .all()
    )
    unread = (
        db.query(func.count(models.EnterpriseNotification.id))
        .filter(
            models.EnterpriseNotification.organization_id == organization.id,
            models.EnterpriseNotification.recipient_user_id == current_user.id,
            models.EnterpriseNotification.is_read.is_(False),
        )
        .scalar() or 0
    )
    member_names = _org_member_name_map(db, organization.id)
    return {
        "unread_count": int(unread),
        "notifications": [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "body": n.body,
                "actor_name": member_names.get(n.actor_user_id) if n.actor_user_id else None,
                "reference_type": n.reference_type,
                "reference_id": n.reference_id,
                "is_read": bool(n.is_read),
                "created_at": _iso(n.created_at),
            }
            for n in rows
        ],
    }


@router.post("/notifications/read")
def enterprise_notifications_mark_read(
    payload: EnterpriseNotificationsReadRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Mark the given notifications (or all of them) as read for this member."""
    _, organization, _role = _require_enterprise_membership(db=db, user=current_user, request=request)
    q = db.query(models.EnterpriseNotification).filter(
        models.EnterpriseNotification.organization_id == organization.id,
        models.EnterpriseNotification.recipient_user_id == current_user.id,
        models.EnterpriseNotification.is_read.is_(False),
    )
    if not payload.all:
        ids = [int(i) for i in (payload.ids or []) if i]
        if not ids:
            return {"updated": 0}
        q = q.filter(models.EnterpriseNotification.id.in_(ids))
    updated = q.update({models.EnterpriseNotification.is_read: True}, synchronize_session=False)
    db.commit()
    return {"updated": int(updated)}


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
            # Account created BY the org for a brand-new teammate → enterprise-origin, so it's
            # blocked from the B2C consumer app. (When the invite REUSES an existing user row
            # below, we deliberately leave the flag untouched so a prior B2C user keeps access.)
            is_enterprise_account=True,
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

    notif.notify_org(
        db, organization.id, type="member_added",
        title=f"{current_user.full_name or current_user.email} added {user.full_name or target_email} to the team",
        body=f"Role: {target_role}",
        actor_user_id=current_user.id, reference_type="team", commit=True,
    )

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

# Version (Last Updated date) of the Terms & Conditions / Privacy Policy a user
# accepts at signup. Defined centrally in app.legal so B2C, OAuth, and enterprise
# signups all record the same value. Keep app.legal in sync with
# LEGAL_LAST_UPDATED.terms / .privacy in static/app.js.
from app.legal import LEGAL_TERMS_PRIVACY_VERSION, LEGAL_DPA_VERSION, FINANCE_ATTESTATION_VERSION


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
    accepted_terms_privacy: bool = False
    accepted_dpa: bool = False
    marketing_emails_consent: bool = False
    cf_turnstile_token: Optional[str] = None
    # 6-digit email-verification code from /signup/send-code (required to create the workspace).
    email_otp: Optional[str] = Field(default=None, max_length=10)


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
    # Staff attestation that the client consented to having their data processed
    # through Rilono. Enforced in the UI; recorded here as proof-of-consent.
    client_consent_confirmed: bool = False


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
    coupon_code: Optional[str] = Field(default=None, max_length=40)


class EnterpriseBillingVerifyRequest(BaseModel):
    razorpay_order_id: str = Field(..., min_length=6, max_length=64)
    razorpay_payment_id: str = Field(..., min_length=6, max_length=64)
    razorpay_signature: str = Field(..., min_length=6, max_length=256)


class EnterpriseCreditTopupRequest(BaseModel):
    package: str = Field(..., min_length=2, max_length=30)
    coupon_code: Optional[str] = Field(default=None, max_length=40)


class EnterpriseCouponValidateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=40)
    context: str = Field(default="credits", max_length=12)  # credits | billing
    package: Optional[str] = Field(default=None, max_length=30)
    plan: Optional[str] = Field(default=None, max_length=30)
    billing_cycle: Optional[str] = Field(default="monthly", max_length=12)


class EnterpriseCreditVerifyRequest(BaseModel):
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


def _apply_status_change(client: models.EnterpriseClient, new_status: str) -> None:
    """Set client.status while maintaining held_from_status: putting a case On Hold
    remembers the stage it was held FROM (so the UI can show its real position and
    offer one-click Resume); moving to any other stage clears the marker."""
    old = client.status
    if new_status == catalog.STAGE_ON_HOLD:
        if old != catalog.STAGE_ON_HOLD:
            client.held_from_status = old if (old in catalog.CLIENT_STAGE_KEYS and old != catalog.STAGE_ON_HOLD) else None
    else:
        client.held_from_status = None
    client.status = new_status


def _load_stage_data(client: models.EnterpriseClient) -> dict:
    """Parse the client's per-stage record JSON. Always returns a dict of dicts."""
    raw = getattr(client, "stage_data", None)
    if not raw:
        return {}
    try:
        import json
        parsed = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {k: v for k, v in parsed.items() if isinstance(v, dict)}


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
        "held_from_status": getattr(client, "held_from_status", None),
        "held_from_stage": _stage_brief(client.held_from_status) if getattr(client, "held_from_status", None) else None,
        "priority": client.priority,
        "target_date": _iso(client.target_date),
        # Per-stage case record: {"<stage_key>": {"<field_key>": value}}. Field definitions
        # come from the destination-aware catalog served by /catalog.
        "stage_data": _load_stage_data(client),
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
        "direction": getattr(row, "direction", None) or "outbound",
        "from_email": getattr(row, "from_email", None),
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
    return catalog.build_catalog_payload(db=db)


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
            # passport_number is encrypted at rest and therefore not substring-searchable.
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
    # Free CRM up to the student limit; beyond it the monthly infra fee must be active.
    credits.enforce_infra_fee_or_402(db, organization.id)

    full_name = (payload.full_name or "").strip()
    if len(full_name) < 2:
        raise HTTPException(status_code=400, detail="Client name must be at least 2 characters.")

    # The org is the data controller and must attest the client consented to having
    # their data processed through Rilono. Enforce it server-side (not just in the UI)
    # so the DPA proof-of-consent trail can't have gaps.
    if not payload.client_consent_confirmed:
        raise HTTPException(
            status_code=400,
            detail="Please confirm this client has consented to having their data processed through Rilono before adding them.",
        )

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
        client_consent_confirmed_at=(datetime.utcnow() if payload.client_consent_confirmed else None),
        client_consent_confirmed_by_user_id=(current_user.id if payload.client_consent_confirmed else None),
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

    notif.notify_org(
        db, organization.id, type="client_added",
        title=f"{current_user.full_name or current_user.email} added client {client.full_name}",
        body=f"{client.destination_country_name or client.destination_country_code or ''} · {client.visa_type or 'student visa'}".strip(" ·"),
        actor_user_id=current_user.id, reference_type="client", reference_id=client.id, commit=True,
    )

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
    status_before_edit = client.status

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
        _apply_status_change(client, catalog.normalize_stage(data["status"]))
    if "assigned_to_user_id" in data:
        new_assignee = data["assigned_to_user_id"]
        if new_assignee and not _is_active_org_member(db, organization.id, new_assignee):
            raise HTTPException(status_code=400, detail="Assigned team member is not part of this organization.")
        client.assigned_to_user_id = new_assignee

    db.commit()
    db.refresh(client)
    if client.status != status_before_edit:
        stage_label = (catalog.CLIENT_STAGE_MAP.get(client.status) or {}).get("label", client.status)
        notif.notify_org(
            db, organization.id, type="status_changed",
            title=f"{current_user.full_name or current_user.email} moved {client.full_name} to {stage_label}",
            actor_user_id=current_user.id, reference_type="client", reference_id=client.id, commit=True,
        )
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
    old_status = client.status
    _apply_status_change(client, new_status)
    db.commit()
    db.refresh(client)
    if new_status != old_status:
        stage_label = (catalog.CLIENT_STAGE_MAP.get(new_status) or {}).get("label", new_status)
        notif.notify_org(
            db, organization.id, type="status_changed",
            title=f"{current_user.full_name or current_user.email} moved {client.full_name} to {stage_label}",
            actor_user_id=current_user.id, reference_type="client", reference_id=client.id, commit=True,
        )
    member_names = _org_member_name_map(db, organization.id)
    return {
        "message": "Status updated.",
        "permissions": _enterprise_permissions_for_role(role),
        "client": _serialize_client(client, member_names),
    }


class EnterpriseStageDataUpdateRequest(BaseModel):
    """Save the case record for ONE stage. `values` is {field_key: value}; an empty/omitted
    value clears that field. Unknown keys (e.g. after a catalog change) are ignored."""
    stage_key: str
    values: dict = {}


@router.patch("/clients/{client_id}/stage-data")
def enterprise_update_client_stage_data(
    client_id: int,
    payload: EnterpriseStageDataUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Record the destination-specific case details a counselor captures at a pipeline stage
    (e.g. US: SEVIS ID / DS-160 confirmation; UK: CAS number / IHS reference)."""
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    client = _get_org_client_or_404(db, organization.id, client_id)

    stage_key = str(payload.stage_key or "").strip().lower()
    if stage_key not in catalog.CLIENT_STAGE_KEYS:
        raise HTTPException(status_code=400, detail="Unknown stage.")

    # Only fields defined for THIS client's destination + stage are accepted, so a stale or
    # tampered payload can't write arbitrary keys into the record.
    allowed = {f["key"] for f in catalog.stage_fields_for(client.destination_country_code, stage_key)}
    if not allowed:
        raise HTTPException(status_code=400, detail="This stage has no record fields for this destination.")

    incoming = payload.values if isinstance(payload.values, dict) else {}
    cleaned: dict[str, str] = {}
    for key, value in incoming.items():
        if key not in allowed:
            continue
        text_value = ("" if value is None else str(value)).strip()
        if len(text_value) > 500:
            raise HTTPException(status_code=400, detail=f"'{key}' is too long (max 500 characters).")
        if text_value:
            cleaned[key] = text_value

    data = _load_stage_data(client)
    if cleaned:
        data[stage_key] = cleaned
    else:
        data.pop(stage_key, None)
    import json
    client.stage_data = json.dumps(data) if data else None
    db.commit()
    db.refresh(client)

    member_names = _org_member_name_map(db, organization.id)
    return {
        "message": "Case record saved.",
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


@router.delete("/clients/{client_id}/notes/{note_id}")
def enterprise_delete_client_note(
    client_id: int,
    note_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Delete a client note. Admins can delete any note (including AI-generated ones);
    editors can only delete notes they authored."""
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    client = _get_org_client_or_404(db, organization.id, client_id)
    note = (
        db.query(models.EnterpriseClientNote)
        .filter(
            models.EnterpriseClientNote.id == int(note_id),
            models.EnterpriseClientNote.organization_id == organization.id,
            models.EnterpriseClientNote.client_id == client.id,
        )
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    if role != ENTERPRISE_ROLE_ADMIN and note.author_user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You can only delete your own notes. Ask an organization admin to remove this one.",
        )
    db.delete(note)
    db.commit()
    return {"message": "Note deleted.", "permissions": _enterprise_permissions_for_role(role)}


def _send_and_log_client_email(
    db: Session,
    *,
    organization: models.EnterpriseOrganization,
    client: models.EnterpriseClient,
    subject: str,
    body: str,
    current_user: models.User,
) -> models.EnterpriseClientEmail:
    # Replies: route into the CRM thread via a tokenized Reply-To when Resend
    # Inbound is configured; otherwise fall back to the staffer's own inbox.
    reply_to = current_user.email
    direct_reply_hint = False
    if inbound_email.reply_routing_enabled():
        tokenized = inbound_email.reply_address_for_client(client.id)
        if tokenized:
            reply_to = tokenized
            direct_reply_hint = True
    success, message_id, error = send_enterprise_client_email(
        to_email=client.email,
        subject=subject,
        body=body,
        organization_name=organization.company_name,
        sender_name=current_user.full_name or current_user.email,
        logo_url=_resolve_enterprise_logo_url(organization),
        reply_to=reply_to,
        direct_reply_hint=direct_reply_hint,
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
# Calendar — timelines, deadlines & next steps (derived + manual events)
# ===========================================================================

CALENDAR_EVENT_TYPES = {
    "reminder":    {"label": "Reminder",    "color": "#6366f1"},
    "task":        {"label": "Task",        "color": "#0ea5e9"},
    "follow_up":   {"label": "Follow-up",   "color": "#8b5cf6"},
    "appointment": {"label": "Appointment", "color": "#10b981"},
    "deadline":    {"label": "Deadline",    "color": "#f97316"},
    "other":       {"label": "Other",       "color": "#64748b"},
}
DEFAULT_CALENDAR_EVENT_TYPE = "reminder"
CALENDAR_DERIVED_TYPES = {
    "client_deadline": {"label": "Key date / deadline", "color": "#f97316"},
    "passport_expiry": {"label": "Passport expires",    "color": "#f59e0b"},
}
CALENDAR_MAX_RANGE_DAYS = int(os.getenv("ENTERPRISE_CALENDAR_MAX_RANGE_DAYS", "100"))


def _calendar_event_types_payload() -> list[dict]:
    return [{"key": k, "label": v["label"], "color": v["color"]} for k, v in CALENDAR_EVENT_TYPES.items()]


def _normalize_calendar_event_type(raw: str | None) -> str:
    value = str(raw or "").strip().lower()
    return value if value in CALENDAR_EVENT_TYPES else DEFAULT_CALENDAR_EVENT_TYPE


def _parse_calendar_time_or_400(raw: str | None) -> Optional[str]:
    value = str(raw or "").strip()
    if not value:
        return None
    if not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", value):
        raise HTTPException(status_code=400, detail="Time must be in HH:MM 24-hour format.")
    hh, mm = value.split(":")
    return f"{int(hh):02d}:{mm}"


def _serialize_calendar_manual_event(ev: models.EnterpriseCalendarEvent, client_name: str | None) -> dict:
    cfg = CALENDAR_EVENT_TYPES.get(ev.event_type, CALENDAR_EVENT_TYPES[DEFAULT_CALENDAR_EVENT_TYPE])
    ev_date = ev.event_date
    overdue = bool(ev_date and ev_date < date.today() and not ev.is_done)
    return {
        "id": f"manual-{ev.id}",
        "event_id": ev.id,
        "source": "manual",
        "type": ev.event_type,
        "type_label": cfg["label"],
        "color": cfg["color"],
        "date": ev_date.isoformat() if ev_date else None,
        "time": ev.event_time,
        "title": ev.title,
        "notes": ev.notes,
        "client_id": ev.client_id,
        "client_name": client_name,
        "notify_client": bool(ev.notify_client),
        "is_done": bool(ev.is_done),
        "editable": True,
        "overdue": overdue,
        "created_by_name": ev.created_by_name,
    }


def _serialize_calendar_derived_event(kind: str, client: models.EnterpriseClient, when) -> dict:
    cfg = CALENDAR_DERIVED_TYPES[kind]
    overdue = bool(when and when < date.today())
    return {
        "id": f"{kind}-{client.id}",
        "event_id": None,
        "source": "client",
        "type": kind,
        "type_label": cfg["label"],
        "color": cfg["color"],
        "date": when.isoformat() if when else None,
        "time": None,
        "title": client.full_name,
        "notes": None,
        "client_id": client.id,
        "client_name": client.full_name,
        "stage": _stage_brief(client.status),
        "is_done": False,
        "editable": False,
        "overdue": overdue,
    }


def _collect_calendar_events(
    db: Session, organization_id: int, start: date, end: date,
    *, include_done: bool = True,
) -> list[dict]:
    member_names = _org_member_name_map(db, organization_id)

    # Manual events
    manual_q = (
        db.query(models.EnterpriseCalendarEvent)
        .filter(
            models.EnterpriseCalendarEvent.organization_id == organization_id,
            models.EnterpriseCalendarEvent.event_date >= start,
            models.EnterpriseCalendarEvent.event_date <= end,
        )
    )
    if not include_done:
        manual_q = manual_q.filter(models.EnterpriseCalendarEvent.is_done.is_(False))

    client_name_cache: dict[int, str] = {}

    def _client_name(cid: Optional[int]) -> Optional[str]:
        if not cid:
            return None
        if cid not in client_name_cache:
            row = (
                db.query(models.EnterpriseClient.full_name)
                .filter(
                    models.EnterpriseClient.id == cid,
                    models.EnterpriseClient.organization_id == organization_id,
                )
                .first()
            )
            client_name_cache[cid] = row[0] if row else None
        return client_name_cache[cid]

    events = [_serialize_calendar_manual_event(ev, _client_name(ev.client_id)) for ev in manual_q.all()]

    # Derived: client key dates (target_date) — skip terminal cases
    for client in (
        db.query(models.EnterpriseClient)
        .filter(
            models.EnterpriseClient.organization_id == organization_id,
            models.EnterpriseClient.target_date.isnot(None),
            models.EnterpriseClient.target_date >= start,
            models.EnterpriseClient.target_date <= end,
            models.EnterpriseClient.status.notin_([catalog.STAGE_APPROVED, catalog.STAGE_REJECTED]),
        )
        .all()
    ):
        events.append(_serialize_calendar_derived_event("client_deadline", client, client.target_date))

    # Derived: passport expiries in range (any active client)
    for client in (
        db.query(models.EnterpriseClient)
        .filter(
            models.EnterpriseClient.organization_id == organization_id,
            models.EnterpriseClient.passport_expiry.isnot(None),
            models.EnterpriseClient.passport_expiry >= start,
            models.EnterpriseClient.passport_expiry <= end,
        )
        .all()
    ):
        events.append(_serialize_calendar_derived_event("passport_expiry", client, client.passport_expiry))

    events.sort(key=lambda e: (e["date"] or "", e["time"] or "99:99", e["title"] or ""))
    return events


class EnterpriseCalendarEventCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    event_date: str = Field(..., min_length=8, max_length=10)
    event_type: str = Field(default=DEFAULT_CALENDAR_EVENT_TYPE, max_length=20)
    event_time: Optional[str] = Field(default=None, max_length=5)
    notes: Optional[str] = Field(default=None, max_length=2000)
    client_id: Optional[int] = None
    notify_client: Optional[bool] = None


class EnterpriseCalendarEventUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    event_date: Optional[str] = Field(default=None, min_length=8, max_length=10)
    event_type: Optional[str] = Field(default=None, max_length=20)
    event_time: Optional[str] = Field(default=None, max_length=5)
    notes: Optional[str] = Field(default=None, max_length=2000)
    client_id: Optional[int] = None
    notify_client: Optional[bool] = None
    is_done: Optional[bool] = None


@router.get("/calendar")
def enterprise_calendar(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)

    today = date.today()
    if start:
        start_date = _parse_iso_date_or_400(start, "start")
    else:
        start_date = today.replace(day=1)
    if end:
        end_date = _parse_iso_date_or_400(end, "end")
    else:
        # default to the end of the start month
        nm = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        end_date = nm - timedelta(days=1)
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="End date must be on or after the start date.")
    if (end_date - start_date).days > CALENDAR_MAX_RANGE_DAYS:
        raise HTTPException(status_code=400, detail=f"Date range too large (max {CALENDAR_MAX_RANGE_DAYS} days).")

    events = _collect_calendar_events(db, organization.id, start_date, end_date)
    return {
        "permissions": _enterprise_permissions_for_role(role),
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "today": today.isoformat(),
        "event_types": _calendar_event_types_payload(),
        "events": events,
    }


@router.get("/calendar/upcoming")
def enterprise_calendar_upcoming(
    request: Request,
    days: int = 14,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """The 'what's next' feed: overdue + the next N days of deadlines and reminders."""
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    days = max(1, min(int(days or 14), 90))
    today = date.today()
    # Look back 30 days so overdue items still surface, forward `days`.
    window = _collect_calendar_events(
        db, organization.id, today - timedelta(days=30), today + timedelta(days=days), include_done=False,
    )
    overdue = [e for e in window if e.get("overdue")]
    upcoming = [e for e in window if not e.get("overdue") and (e["date"] or "") >= today.isoformat()]
    return {
        "permissions": _enterprise_permissions_for_role(role),
        "today": today.isoformat(),
        "horizon_days": days,
        "overdue": overdue,
        "upcoming": upcoming[:40],
    }


@router.get("/calendar/clients")
def enterprise_calendar_clients(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Lightweight client list for the @-mention autocomplete in the reminder form.
    Returns every client in the org (id, name, email) sourced from the SQL DB."""
    _, organization, _role = _require_enterprise_membership(db=db, user=current_user, request=request)
    rows = (
        db.query(
            models.EnterpriseClient.id,
            models.EnterpriseClient.full_name,
            models.EnterpriseClient.email,
        )
        .filter(models.EnterpriseClient.organization_id == organization.id)
        .order_by(models.EnterpriseClient.full_name.asc())
        .all()
    )
    return {
        "clients": [
            {"id": r[0], "name": r[1], "email": (r[2] or None), "has_email": bool((r[2] or "").strip())}
            for r in rows
        ]
    }


@router.post("/calendar/events")
def enterprise_calendar_create_event(
    payload: EnterpriseCalendarEventCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="A title is required.")
    event_date = _parse_iso_date_or_400(payload.event_date, "event_date")
    event_time = _parse_calendar_time_or_400(payload.event_time)
    if payload.client_id is not None:
        _get_org_client_or_404(db, organization.id, payload.client_id)

    ev = models.EnterpriseCalendarEvent(
        organization_id=organization.id,
        client_id=payload.client_id,
        title=title[:200],
        notes=(payload.notes or None),
        event_type=_normalize_calendar_event_type(payload.event_type),
        event_date=event_date,
        event_time=event_time,
        is_done=False,
        # Only meaningful when a client is linked; the client is emailed when due.
        notify_client=bool(payload.notify_client) and payload.client_id is not None,
        created_by_user_id=current_user.id,
        created_by_name=current_user.full_name or current_user.email,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    client_name = None
    if ev.client_id:
        c = _get_org_client_or_404(db, organization.id, ev.client_id)
        client_name = c.full_name
    return {
        "message": "Event added.",
        "permissions": _enterprise_permissions_for_role(role),
        "event": _serialize_calendar_manual_event(ev, client_name),
    }


def _get_org_calendar_event_or_404(db: Session, organization_id: int, event_id: int) -> models.EnterpriseCalendarEvent:
    ev = (
        db.query(models.EnterpriseCalendarEvent)
        .filter(
            models.EnterpriseCalendarEvent.id == int(event_id),
            models.EnterpriseCalendarEvent.organization_id == int(organization_id),
        )
        .first()
    )
    if not ev:
        raise HTTPException(status_code=404, detail="Calendar event not found.")
    return ev


@router.patch("/calendar/events/{event_id}")
def enterprise_calendar_update_event(
    event_id: int,
    payload: EnterpriseCalendarEventUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    ev = _get_org_calendar_event_or_404(db, organization.id, event_id)

    if payload.title is not None:
        t = payload.title.strip()
        if not t:
            raise HTTPException(status_code=400, detail="A title is required.")
        ev.title = t[:200]
    if payload.event_date is not None:
        ev.event_date = _parse_iso_date_or_400(payload.event_date, "event_date")
    if payload.event_type is not None:
        ev.event_type = _normalize_calendar_event_type(payload.event_type)
    if payload.event_time is not None:
        ev.event_time = _parse_calendar_time_or_400(payload.event_time)
    if payload.notes is not None:
        ev.notes = payload.notes or None
    if payload.client_id is not None:
        new_cid = None if payload.client_id == 0 else payload.client_id
        if new_cid is not None:
            _get_org_client_or_404(db, organization.id, new_cid)
        if new_cid != ev.client_id:
            # Re-link → allow the new client to be notified afresh.
            ev.client_notified_at = None
        ev.client_id = new_cid
        if new_cid is None:
            ev.notify_client = False
    if payload.notify_client is not None:
        ev.notify_client = bool(payload.notify_client) and ev.client_id is not None
    if payload.is_done is not None:
        ev.is_done = bool(payload.is_done)

    db.commit()
    db.refresh(ev)
    client_name = None
    if ev.client_id:
        c = _get_org_client_or_404(db, organization.id, ev.client_id)
        client_name = c.full_name
    return {
        "message": "Event updated.",
        "permissions": _enterprise_permissions_for_role(role),
        "event": _serialize_calendar_manual_event(ev, client_name),
    }


@router.delete("/calendar/events/{event_id}")
def enterprise_calendar_delete_event(
    event_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    ev = _get_org_calendar_event_or_404(db, organization.id, event_id)
    db.delete(ev)
    db.commit()
    return {"message": "Event deleted.", "permissions": _enterprise_permissions_for_role(role)}


# ===========================================================================
# Help & Support + feature requests
# ===========================================================================

ENTERPRISE_SUPPORT_RATE_LIMIT = int(os.getenv("ENTERPRISE_SUPPORT_RATE_LIMIT", "8"))
ENTERPRISE_SUPPORT_RATE_WINDOW_SECONDS = int(os.getenv("ENTERPRISE_SUPPORT_RATE_WINDOW_SECONDS", "3600"))
SUPPORT_REQUEST_TYPES = {"support", "feature_request"}


class EnterpriseSupportRequestCreate(BaseModel):
    request_type: str = Field(default="support", max_length=24)
    subject: str = Field(..., min_length=3, max_length=160)
    message: str = Field(..., min_length=5, max_length=4000)


def _normalize_support_type(raw: str | None) -> str:
    value = str(raw or "").strip().lower()
    if value in {"feature", "feature_request", "feature-request", "idea"}:
        return "feature_request"
    return "support"


def _serialize_support_request(r: models.EnterpriseSupportRequest) -> dict:
    return {
        "id": r.id,
        "request_type": r.request_type,
        "type_label": "Feature request" if r.request_type == "feature_request" else "Help & support",
        "subject": r.subject,
        "message": r.message,
        "status": r.status,
        "requester_name": r.requester_name,
        "created_at": _iso(r.created_at),
    }


@router.get("/support")
def enterprise_support_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    rows = (
        db.query(models.EnterpriseSupportRequest)
        .filter(models.EnterpriseSupportRequest.organization_id == organization.id)
        .order_by(models.EnterpriseSupportRequest.created_at.desc(), models.EnterpriseSupportRequest.id.desc())
        .limit(25)
        .all()
    )
    return {
        "permissions": _enterprise_permissions_for_role(role),
        "support_email": os.getenv("ENTERPRISE_SUPPORT_INBOX", "contact@rilono.com").strip() or "contact@rilono.com",
        "requests": [_serialize_support_request(r) for r in rows],
    }


@router.post("/support")
def enterprise_support_create(
    payload: EnterpriseSupportRequestCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    _enforce_rate_limit_or_429(
        request=request,
        scope="enterprise.support",
        limit=ENTERPRISE_SUPPORT_RATE_LIMIT,
        window_seconds=ENTERPRISE_SUPPORT_RATE_WINDOW_SECONDS,
        extra_key=str(current_user.id),
    )
    request_type = _normalize_support_type(payload.request_type)
    subject = (payload.subject or "").strip()
    message = (payload.message or "").strip()
    if len(subject) < 3:
        raise HTTPException(status_code=400, detail="Please add a short subject.")
    if len(message) < 5:
        raise HTTPException(status_code=400, detail="Please describe your request.")

    requester_name = current_user.full_name or current_user.email
    row = models.EnterpriseSupportRequest(
        organization_id=organization.id,
        user_id=current_user.id,
        requester_name=requester_name,
        requester_email=current_user.email,
        request_type=request_type,
        subject=subject[:160],
        message=message[:4000],
        status="open",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    # Notify the support inbox (best-effort — never fail the request on email error).
    try:
        send_enterprise_support_request_email(
            request_type=request_type,
            subject=subject,
            message=message,
            org_name=organization.company_name or "Unknown organization",
            requester_name=requester_name,
            requester_email=current_user.email or "",
        )
    except Exception:
        logger.exception("Failed to email enterprise support request (org_id=%s)", organization.id)

    # Feature requests get a warm confirmation back to the requester (best-effort — a
    # confirmation-email failure must never fail the request, mirroring the block above).
    if request_type == "feature_request" and (current_user.email or "").strip():
        try:
            send_feature_request_confirmation(
                to_email=current_user.email,
                full_name=requester_name,
                request_summary=subject,
                product="Rilono Enterprise",
            )
        except Exception:
            logger.exception("Failed to send enterprise feature-request confirmation (org_id=%s)", organization.id)

    friendly = "Thanks! Your feature request is in — we read every one." if request_type == "feature_request" \
        else "Thanks! Our team has your message and will get back to you by email."
    return {
        "message": friendly,
        "permissions": _enterprise_permissions_for_role(role),
        "request": _serialize_support_request(row),
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


# ---------------------------------------------------------------------------
# Finance / marketplace payments (Razorpay Route) — Phase 1: onboarding
#
# The "Finance" portal section: collect payments from students, and (later)
# revenue analytics + usage billing as nested sub-views. Rilono is a technology
# platform, NOT a payment aggregator — student money is collected into Razorpay's
# PA escrow and settled by Razorpay directly to the consultancy's own linked-account
# bank; Rilono never takes custody of it. This phase lets a consultancy connect its
# company bank account (a Route Linked Account). Collection/checkout, webhooks and
# refunds are later phases.
# ---------------------------------------------------------------------------

class EnterpriseLinkedAccountRequest(BaseModel):
    legal_business_name: str | None = Field(None, max_length=200)
    business_type: str | None = Field(None, max_length=60)
    contact_name: str | None = Field(None, max_length=120)
    contact_email: str | None = Field(None, max_length=200)
    contact_phone: str | None = Field(None, max_length=20)
    business_pan: str | None = Field(None, max_length=20)
    gst_number: str | None = Field(None, max_length=20)
    bank_account_number: str | None = Field(None, max_length=40)
    bank_ifsc: str | None = Field(None, max_length=20)
    beneficiary_name: str | None = Field(None, max_length=200)
    attested_service_delivery: bool = False
    attested_turnover_ok: bool = False


@router.get("/finance/summary")
def enterprise_finance_summary(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    la = enterprise_payments.get_linked_account(db, organization.id)
    # Only admins may see the settlement identity fields (bank IFSC/last4, beneficiary, GST,
    # Razorpay account id). Viewers/editors get the non-sensitive status only (least privilege).
    is_admin = role == ENTERPRISE_ROLE_ADMIN
    return {
        "payments_enabled": enterprise_payments.razorpay_enabled(),
        "linked_account": enterprise_payments.serialize_linked_account(la, include_sensitive=is_admin),
        "fee": enterprise_payments.fee_config_public(),
        "permissions": _enterprise_permissions_for_role(role),
    }


@router.post("/finance/linked-account")
def enterprise_finance_connect_bank(
    payload: EnterpriseLinkedAccountRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Connect (or update) the consultancy's Razorpay Route linked account.

    Admin-only. Requires the eligibility attestation (the consultancy itself delivers the
    service to the student and meets the turnover threshold) — RBI/Route only permits a
    split payee that interfaces with the payer for the goods/services. When Razorpay Route
    is enabled, this runs the v2 Accounts onboarding sequence and stores the returned ids +
    activation status; otherwise it saves the local record so activation can begin later.
    """
    _, organization, _ = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_manage_users=True
    )
    if not (payload.attested_service_delivery and payload.attested_turnover_ok):
        raise HTTPException(
            status_code=400,
            detail=(
                "To collect payments, please confirm that your organization directly delivers the "
                "service to the student and meets the eligibility criteria."
            ),
        )

    la = enterprise_payments.get_linked_account(db, organization.id)
    if la is None:
        la = models.EnterpriseLinkedAccount(
            organization_id=organization.id,
            created_by_user_id=current_user.id,
        )
        db.add(la)

    # Record the business + settlement details (display-safe only) and the attestation.
    la.legal_business_name = (payload.legal_business_name or "").strip() or la.legal_business_name
    la.business_type = (payload.business_type or "").strip() or la.business_type
    la.contact_name = (payload.contact_name or "").strip() or la.contact_name
    la.contact_email = (payload.contact_email or "").strip() or la.contact_email
    la.contact_phone = (payload.contact_phone or "").strip() or la.contact_phone
    la.business_pan = (payload.business_pan or "").strip().upper() or la.business_pan
    la.gst_number = (payload.gst_number or "").strip().upper() or la.gst_number
    la.beneficiary_name = (payload.beneficiary_name or "").strip() or la.beneficiary_name
    if payload.bank_ifsc:
        la.bank_ifsc = payload.bank_ifsc.strip().upper()
    if payload.bank_account_number:
        digits = re.sub(r"\D", "", payload.bank_account_number)
        la.bank_account_last4 = digits[-4:] if digits else la.bank_account_last4
    la.attested_service_delivery = True
    la.attested_turnover_ok = True
    la.attested_at = datetime.utcnow()
    la.attested_ip = extract_client_ip(request) if request else None
    la.attested_version = FINANCE_ATTESTATION_VERSION

    if not enterprise_payments.razorpay_enabled():
        # Route not switched on yet — keep the details, don't attempt live KYC.
        if la.activation_status in (None, "", "not_started"):
            la.activation_status = "not_started"
        db.commit()
        db.refresh(la)
        return {
            "payments_enabled": False,
            "linked_account": enterprise_payments.serialize_linked_account(la),
            "message": (
                "Your details are saved. Online collection will activate once Rilono enables "
                "Razorpay Route for your account."
            ),
        }

    # Razorpay Route is live: run the v2 onboarding sequence server-side (order enforced).
    la = enterprise_payments.onboard_linked_account(
        db=db,
        linked_account=la,
        payload=payload,
        request_ip=(extract_client_ip(request) if request else None),
    )
    db.commit()
    db.refresh(la)
    return {
        "payments_enabled": True,
        "linked_account": enterprise_payments.serialize_linked_account(la),
        "message": "Bank account submitted to Razorpay for verification.",
    }


@router.post("/finance/linked-account/refresh")
def enterprise_finance_refresh(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Re-sync the linked account's activation status + requirements from Razorpay."""
    _, organization, _ = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_manage_users=True
    )
    la = enterprise_payments.get_linked_account(db, organization.id)
    if la is None or not la.razorpay_account_id:
        raise HTTPException(status_code=404, detail="No connected bank account to refresh.")
    la = enterprise_payments.refresh_linked_account_status(db=db, linked_account=la)
    db.commit()
    db.refresh(la)
    return {"linked_account": enterprise_payments.serialize_linked_account(la)}


# ---------------------------------------------------------------------------
# Finance Phase 2 — collect payments from a client (secure emailed pay-link),
# webhook reconciliation, refunds. Money-moving writes are admin-only.
# ---------------------------------------------------------------------------

class EnterprisePaymentRequestCreate(BaseModel):
    amount_paise: int = Field(gt=0)
    description: str = Field(min_length=3, max_length=300)
    due_date: Optional[date] = None


class EnterpriseManualPaymentCreate(BaseModel):
    """Record a payment collected off-platform (cash / bank transfer / UPI / …)."""
    amount_paise: int = Field(gt=0)
    method: str = Field(min_length=2, max_length=30)
    description: Optional[str] = Field(default=None, max_length=300)
    reference: Optional[str] = Field(default=None, max_length=80)
    received_on: Optional[date] = None


class EnterprisePublicPayVerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class EnterprisePaymentRefundRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


def _build_pay_link_url(subdomain_slug, token: str, request: Request | None) -> str:
    """Public pay-page URL for the emailed secure link (mirrors the interview invite URL)."""
    subdomain = str(subdomain_slug or "").strip().lower()
    base = None
    if subdomain:
        host = f"{subdomain}.{ENTERPRISE_ROOT_DOMAIN}"
        port = _request_port_for_local_enterprise_url(request)
        if port:
            host = f"{host}:{port}"
        base = f"{ENTERPRISE_PORTAL_SCHEME}://{host}"
    if not base:
        base = ENTERPRISE_PASSWORD_SETUP_BASE_URL
    return f"{base.rstrip('/')}/pay/{token}"


def _get_org_payment_or_404(db: Session, organization_id: int, payment_id: int) -> models.EnterpriseStudentPayment:
    row = (
        db.query(models.EnterpriseStudentPayment)
        .filter(
            models.EnterpriseStudentPayment.id == int(payment_id),
            models.EnterpriseStudentPayment.organization_id == int(organization_id),
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Payment not found.")
    return row


def _send_payment_request_email_safe(payment, organization, client_email, pay_url):
    due = payment.due_date.strftime("%d %b %Y") if payment.due_date else None
    return send_enterprise_payment_request_email(
        to_email=client_email,
        client_name=payment.client_name_snapshot or "there",
        organization_name=organization.company_name,
        amount_rupees=f"{payment.amount_paise / 100:,.2f}",
        description=payment.description or "Visa service payment",
        pay_url=pay_url,
        invoice_number=payment.invoice_number or "",
        due_date_text=due,
        logo_url=_resolve_enterprise_logo_url(organization),
    )


@router.get("/clients/{client_id}/payments")
def enterprise_client_payments(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """The client dossier's Payments tab: totals + the request ledger for this client."""
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    client = _get_org_client_or_404(db, organization.id, client_id)
    rows = (
        db.query(models.EnterpriseStudentPayment)
        .filter(
            models.EnterpriseStudentPayment.organization_id == organization.id,
            models.EnterpriseStudentPayment.client_id == client.id,
        )
        .order_by(models.EnterpriseStudentPayment.created_at.desc(), models.EnterpriseStudentPayment.id.desc())
        .all()
    )
    la = enterprise_payments.get_linked_account(db, organization.id)
    return {
        "payments": [enterprise_payments.serialize_payment(p) for p in rows],
        "totals": enterprise_payments.client_payment_totals(db, organization.id, client.id),
        "collect_enabled": bool(
            enterprise_payments.razorpay_enabled() and la is not None and la.is_payable
        ),
        "linked_account_status": (la.activation_status if la else "not_started"),
        "fee": enterprise_payments.fee_config_public(),
        "client_email": (client.email or "").strip().lower() or None,
        "permissions": _enterprise_permissions_for_role(role),
    }


@router.post("/clients/{client_id}/payments")
def enterprise_create_client_payment(
    client_id: int,
    payload: EnterprisePaymentRequestCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Raise a payment request for this client and email them a secure pay-link.

    Hard compliance gates: Razorpay live + the org's linked account activated
    (a marketplace must never collect for a non-onboarded payee)."""
    _, organization, _ = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_manage_users=True
    )
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.payment_request",
        limit=30, window_seconds=3600, extra_key=str(organization.id),
    )
    client = _get_org_client_or_404(db, organization.id, client_id)
    client_email = (client.email or "").strip().lower()
    if not client_email:
        raise HTTPException(status_code=400, detail="Add an email to this client before requesting a payment.")
    if not enterprise_payments.razorpay_enabled():
        raise HTTPException(
            status_code=409,
            detail="Online collection isn't live yet — you can connect your bank account in Finance meanwhile.",
        )
    la = enterprise_payments.get_linked_account(db, organization.id)

    raw_token = generate_verification_token()
    payment = enterprise_payments.create_payment_request(
        db=db,
        organization=organization,
        linked_account=la,
        client=client,
        amount_paise=int(payload.amount_paise),
        description=payload.description,
        due_date=payload.due_date,
        created_by=current_user,
        pay_token_hash=hash_token(raw_token),
        payer_email=client_email,
    )
    pay_url = _build_pay_link_url(organization.subdomain_slug, raw_token, request)
    sent, _mid, err = _send_payment_request_email_safe(payment, organization, client_email, pay_url)
    if sent:
        payment.email_sent_at = datetime.utcnow()
    db.commit()
    db.refresh(payment)
    message = (
        f"Payment request for ₹{payment.amount_paise / 100:,.2f} sent to {client_email}."
        if sent else
        f"Payment request created, but the email could not be sent right now. {err or ''}".strip()
    )
    return {
        "message": message,
        "email_sent": sent,
        "pay_url": pay_url,  # returned once — only the hash is stored
        "payment": enterprise_payments.serialize_payment(payment),
        "totals": enterprise_payments.client_payment_totals(db, organization.id, client.id),
    }


@router.post("/clients/{client_id}/payments/manual")
def enterprise_record_manual_payment(
    client_id: int,
    payload: EnterpriseManualPaymentCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Record a payment the org collected OUTSIDE Rilono (cash / bank transfer / UPI / cheque / …).

    Bookkeeping only — no money moves through the platform, so it needs no linked account and works
    even when online collection isn't live. Lands as a 'paid' row in this client's ledger."""
    _, organization, _ = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_manage_users=True
    )
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.payment_manual",
        limit=120, window_seconds=3600, extra_key=str(organization.id),
    )
    client = _get_org_client_or_404(db, organization.id, client_id)
    payment = enterprise_payments.record_manual_payment(
        db=db,
        organization=organization,
        client=client,
        amount_paise=int(payload.amount_paise),
        method=payload.method,
        description=payload.description,
        reference=payload.reference,
        received_on=payload.received_on,
        created_by=current_user,
    )
    db.commit()
    db.refresh(payment)
    return {
        "message": f"Recorded ₹{payment.amount_paise / 100:,.2f} received from {client.full_name}.",
        "payment": enterprise_payments.serialize_payment(payment),
        "totals": enterprise_payments.client_payment_totals(db, organization.id, client.id),
    }


@router.delete("/finance/payments/{payment_id}/manual")
def enterprise_delete_manual_payment(
    payment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Remove a manually-recorded (off-platform) payment — e.g. to correct a mistake. Only manual
    rows can be removed; real Razorpay payments are immutable financial records."""
    _, organization, _ = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_manage_users=True
    )
    payment = _get_org_payment_or_404(db, organization.id, payment_id)
    if (payment.provider or "") != "manual":
        raise HTTPException(status_code=409, detail="Only manually-recorded payments can be removed.")
    client_id = payment.client_id
    db.delete(payment)
    db.commit()
    totals = (
        enterprise_payments.client_payment_totals(db, organization.id, client_id)
        if client_id else None
    )
    return {"message": "Payment record removed.", "totals": totals}


@router.post("/finance/payments/{payment_id}/resend-email")
def enterprise_resend_payment_email(
    payment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Rotate the secure token and re-send the pay-link (also returns it for copying)."""
    _, organization, _ = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_manage_users=True
    )
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.payment_resend",
        limit=10, window_seconds=3600, extra_key=str(payment_id),
    )
    payment = _get_org_payment_or_404(db, organization.id, payment_id)
    if payment.status != "created":
        raise HTTPException(status_code=409, detail="Only an unpaid request's link can be re-sent.")
    to_email = payment.payer_email_snapshot
    if not to_email:
        raise HTTPException(status_code=400, detail="This request has no email on file.")

    raw_token = generate_verification_token()
    payment.pay_token_hash = hash_token(raw_token)  # rotates: the old link stops working
    pay_url = _build_pay_link_url(organization.subdomain_slug, raw_token, request)
    sent, _mid, err = _send_payment_request_email_safe(payment, organization, to_email, pay_url)
    if sent:
        payment.email_sent_at = datetime.utcnow()
    db.commit()
    return {
        "message": f"Pay link re-sent to {to_email}." if sent
                   else f"Link rotated, but the email could not be sent. {err or ''}".strip(),
        "email_sent": sent,
        "pay_url": pay_url,
        "payment": enterprise_payments.serialize_payment(payment),
    }


@router.post("/finance/payments/{payment_id}/cancel")
def enterprise_cancel_payment_request(
    payment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, _ = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_manage_users=True
    )
    payment = _get_org_payment_or_404(db, organization.id, payment_id)
    if payment.status not in ("created", "failed"):
        raise HTTPException(status_code=409, detail="Only an unpaid request can be cancelled.")
    payment.status = "cancelled"
    payment.cancelled_at = datetime.utcnow()
    db.commit()
    return {"message": "Payment request cancelled.", "payment": enterprise_payments.serialize_payment(payment)}


@router.post("/finance/payments/{payment_id}/refund")
def enterprise_refund_payment(
    payment_id: int,
    payload: EnterprisePaymentRefundRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Refund the student in full (original instrument). Gateway-first: if Razorpay rejects
    it (e.g. the payout already settled), nothing is persisted and the reason is surfaced."""
    _, organization, _ = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_manage_users=True
    )
    payment = _get_org_payment_or_404(db, organization.id, payment_id)
    audit = enterprise_payments.issue_full_refund(
        db=db, payment=payment, by_user=current_user, reason=(payload.reason or None),
    )
    db.commit()
    return {
        "message": f"Refund of ₹{audit.amount_paise / 100:,.2f} initiated to the student's original payment method.",
        "payment": enterprise_payments.serialize_payment(payment),
    }


# ---- Public pay page (no auth; token = capability) -------------------------

def _public_payment_or_404(db: Session, token: str) -> models.EnterpriseStudentPayment:
    token_hash = hash_token((token or "").strip())
    row = (
        db.query(models.EnterpriseStudentPayment)
        .filter(models.EnterpriseStudentPayment.pay_token_hash == token_hash)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="This payment link is invalid or has been replaced.")
    return row


@router.get("/pay/{token}")
def enterprise_public_pay_info(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Everything the public pay page needs. The full amount charged is disclosed to the
    student up-front; the consultancy (not Rilono) is named as the payee."""
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.pay_public",
        limit=ENTERPRISE_PUBLIC_RATE_LIMIT, window_seconds=ENTERPRISE_PUBLIC_RATE_WINDOW,
        extra_key=hash_token(token)[:16],
    )
    payment = _public_payment_or_404(db, token)
    organization = db.query(models.EnterpriseOrganization).filter(
        models.EnterpriseOrganization.id == payment.organization_id
    ).first()
    la = enterprise_payments.get_linked_account(db, payment.organization_id)
    payable = (
        payment.status == "created"
        and enterprise_payments.razorpay_enabled()
        and la is not None and bool(la.is_payable)
    )
    info = {
        "organization_name": organization.company_name if organization else "Your consultancy",
        "organization_logo_url": _resolve_enterprise_logo_url(organization) if organization else None,
        "client_name": payment.client_name_snapshot,
        "invoice_number": payment.invoice_number,
        "description": payment.description,
        "amount_paise": payment.amount_paise,
        "currency": payment.currency,
        "status": payment.status,
        "due_date": payment.due_date.isoformat() if payment.due_date else None,
        "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
        "payable": payable,
    }
    if payable:
        info["razorpay_key_id"] = os.getenv("RAZORPAY_KEY_ID", "").strip()
        info["razorpay_order_id"] = payment.razorpay_order_id
        info["payer_email"] = payment.payer_email_snapshot
    return info


@router.post("/pay/{token}/verify")
def enterprise_public_pay_verify(
    token: str,
    payload: EnterprisePublicPayVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Checkout callback: verify the Razorpay signature AND confirm capture with the API
    before marking paid (a signature alone proves authenticity, not capture). Webhooks
    remain the reconciliation source of truth for transfer/settlement states."""
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.pay_verify",
        limit=ENTERPRISE_PUBLIC_RATE_LIMIT, window_seconds=ENTERPRISE_PUBLIC_RATE_WINDOW,
        extra_key=hash_token(token)[:16],
    )
    payment = _public_payment_or_404(db, token)
    if payment.status == "cancelled":
        raise HTTPException(status_code=409, detail="This payment request was cancelled.")
    if (payload.razorpay_order_id or "").strip() != (payment.razorpay_order_id or ""):
        raise HTTPException(status_code=400, detail="Payment does not match this request.")
    if not enterprise_payments.verify_checkout_signature(
        payload.razorpay_order_id, payload.razorpay_payment_id, payload.razorpay_signature
    ):
        raise HTTPException(status_code=400, detail="Payment verification failed.")
    enterprise_payments.confirm_captured_and_mark_paid(
        db=db, payment=payment, razorpay_payment_id=payload.razorpay_payment_id.strip()
    )
    db.commit()
    return {"status": "paid", "message": "Payment received. You can close this page."}


# ---- Razorpay Route webhook (reconciliation source of truth) ---------------

@router.post("/webhook/razorpay-route")
async def enterprise_route_webhook(request: Request, db: Session = Depends(get_db)):
    """Idempotent, out-of-order-tolerant reconciliation of Route events. Signature is
    HMAC-SHA256 of the RAW body with a dedicated secret (distinct from the API keys and
    the B2C subscription webhook secret); events dedupe on the unique event id."""
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.route_webhook", limit=300, window_seconds=60,
    )
    secret = os.getenv("RAZORPAY_ROUTE_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook not configured.")
    body = await request.body()
    signature = (request.headers.get("X-Razorpay-Signature") or "").strip()
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    try:
        event = json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook payload.")
    event_type = str(event.get("event") or "").strip()
    event_id = (request.headers.get("x-razorpay-event-id") or "").strip() or None

    container = (event.get("payload") or {})
    entity = {}
    for kind in ("payment", "transfer", "refund", "order", "dispute"):
        maybe = (container.get(kind) or {}).get("entity") if isinstance(container.get(kind), dict) else None
        if maybe:
            entity = maybe
            break

    # Peek at the target row so the ledger row carries org/payment links, then dedupe-insert.
    target = enterprise_payments._find_payment_for_event(db, entity) if entity else None
    fresh = enterprise_payments.record_webhook_event(
        db,
        event_id=event_id,
        event_type=event_type,
        entity_type=str(entity.get("entity") or "") or None,
        entity_id=str(entity.get("id") or "") or None,
        amount_paise=int(entity.get("amount") or 0) or None,
        payload_json=body.decode("utf-8", errors="replace"),
        organization_id=target.organization_id if target else None,
        student_payment_id=target.id if target else None,
    )
    if not fresh:
        return {"status": "duplicate"}
    applied = enterprise_payments.apply_webhook_event(db, event_type, event)
    db.commit()

    # Chargebacks demand staff action before the evidence deadline — alert org admins.
    # Best-effort: an email failure must never make the webhook 5xx (Razorpay retries).
    if event_type.startswith("payment.dispute.") and applied is not None:
        try:
            _send_dispute_alert_to_org_admins(db, payment=applied, event_type=event_type, entity=entity)
        except Exception:
            logger.exception("route-webhook: dispute alert email failed (payment_id=%s)", applied.id)

    return {"status": "ok"}


def _send_dispute_alert_to_org_admins(
    db: Session, *, payment: "models.EnterpriseStudentPayment", event_type: str, entity: dict
) -> None:
    """Email every active org admin when a dispute opens or needs action. Won/lost/closed
    updates are also sent so staff see the outcome without polling the dashboard."""
    admins = (
        db.query(models.User)
        .join(
            models.EnterpriseOrganizationMember,
            models.EnterpriseOrganizationMember.user_id == models.User.id,
        )
        .filter(
            models.EnterpriseOrganizationMember.organization_id == payment.organization_id,
            models.EnterpriseOrganizationMember.is_active.is_(True),
            models.EnterpriseOrganizationMember.role == ENTERPRISE_ROLE_ADMIN,
            models.User.is_active.is_(True),
        )
        .all()
    )
    organization = db.query(models.EnterpriseOrganization).filter(
        models.EnterpriseOrganization.id == payment.organization_id
    ).first()
    if not admins or organization is None:
        return

    suffix = event_type.rsplit(".", 1)[-1].replace("_", " ")
    respond_by_text = None
    try:
        raw = entity.get("respond_by")
        if raw:
            respond_by_text = datetime.utcfromtimestamp(int(raw)).strftime("%d %b %Y, %H:%M UTC")
    except (TypeError, ValueError, OSError, OverflowError):
        respond_by_text = None

    for admin in admins:
        if getattr(admin, "email_notifications_enabled", True) is False:
            continue
        send_enterprise_payment_dispute_alert_email(
            to_email=admin.email,
            organization_name=organization.company_name,
            client_name=payment.client_name_snapshot or "a client",
            amount_rupees=f"{(int(entity.get('amount') or payment.amount_paise or 0)) / 100:,.2f}",
            invoice_number=payment.invoice_number or "",
            dispute_state=suffix,
            reason_code=str(entity.get("reason_code") or "") or None,
            respond_by_text=respond_by_text,
        )


# ---- Resend inbound-email webhook (client replies -> Emails thread) ---------

@router.post("/webhooks/inbound-email")
async def enterprise_inbound_email_webhook(request: Request, db: Session = Depends(get_db)):
    """Receive Resend Inbound `email.received` events (Svix-signed over the RAW body)
    and thread client replies into the CRM. Replies arrive on the tokenized
    reply+c{id}-{sig}@{inbound domain} address set as Reply-To on outbound client
    emails; the HMAC token resolves the client. Unmatched/duplicate mail returns
    200 so the provider doesn't retry forever."""
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.inbound_email_webhook", limit=300, window_seconds=60,
    )
    secret = inbound_email.webhook_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook not configured.")
    try:
        declared_length = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared_length = 0
    if declared_length > 1_000_000:
        raise HTTPException(status_code=413, detail="Payload too large.")
    body = await request.body()
    if len(body) > 1_000_000:
        raise HTTPException(status_code=413, detail="Payload too large.")
    if not inbound_email.verify_svix_signature(secret=secret, headers=request.headers, body=body):
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    try:
        event = json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook payload.")
    if str(event.get("type") or "").strip() != "email.received":
        return {"status": "ignored"}
    data = event.get("data") or {}
    if not isinstance(data, dict):
        return {"status": "ignored"}

    # Resolve the client from our tokenized reply+ recipient address.
    client_id = None
    matched_address = None
    recipients = inbound_email.recipient_addresses(data)
    for addr in recipients:
        client_id = inbound_email.parse_reply_address(addr)
        if client_id is not None:
            matched_address = addr
            break
    if client_id is None:
        # 200 so the provider doesn't retry, but leave an operator trace —
        # a real reply landing here means a stale/foreign token.
        logger.info("inbound-email webhook: no reply-token match (recipients=%s)", recipients[:10])
        return {"status": "no_match"}
    client = (
        db.query(models.EnterpriseClient)
        .filter(models.EnterpriseClient.id == int(client_id))
        .first()
    )
    if client is None:
        return {"status": "no_match"}

    provider_message_id = str(data.get("email_id") or data.get("id") or "").strip() or None
    if provider_message_id:
        duplicate = (
            db.query(models.EnterpriseClientEmail)
            .filter(
                models.EnterpriseClientEmail.provider_message_id == provider_message_id,
                models.EnterpriseClientEmail.direction == "inbound",
            )
            .first()
        )
        if duplicate:
            return {"status": "duplicate"}

    from_email = inbound_email.sender_address(data)
    subject = str(data.get("subject") or "").strip()[:300] or "(no subject)"
    # The body fetch is a blocking HTTP call (the webhook carries metadata only) —
    # run it off the event loop. On fetch failure, 5xx so Svix retries with the
    # same email_id instead of us committing an empty reply forever.
    reply_text, fetch_failed = await run_in_threadpool(inbound_email.extract_reply_text, data)
    if fetch_failed and not reply_text:
        logger.warning("inbound-email webhook: body fetch failed for %s; asking provider to retry",
                       provider_message_id)
        raise HTTPException(status_code=500, detail="Inbound body fetch failed — retry.")
    if not reply_text:
        reply_text = "(Empty message — the reply may only contain an attachment.)"

    # From: is spoofable and the reply+ address is forwardable — never assert the
    # client wrote it unless the sender matches the email we have on file.
    sender_matches = bool(
        from_email and (client.email or "").strip() and from_email == client.email.strip().lower()
    )
    row = models.EnterpriseClientEmail(
        organization_id=client.organization_id,
        client_id=client.id,
        sent_by_user_id=None,
        sent_by_name=client.full_name,
        to_email=matched_address or (inbound_email.reply_address_for_client(client.id) or "inbound"),
        subject=subject,
        body=reply_text[:20000],
        status="received",
        provider_message_id=provider_message_id,
        direction="inbound",
        from_email=from_email,
    )
    db.add(row)
    notif.notify_org(
        db,
        client.organization_id,
        type="client_email_reply",
        # Subject in the title keeps distinct replies from tripping notify_org's
        # 10-minute identical-title dedupe.
        title=(f"✉️ {client.full_name} replied: {subject}" if sender_matches
               else f"✉️ Reply from {from_email or 'unknown sender'} on {client.full_name}'s thread"),
        body=reply_text[:140] or None,
        reference_type="client",
        reference_id=client.id,
    )
    try:
        db.commit()
    except IntegrityError:
        # Unique index on inbound provider_message_id: a concurrent Svix
        # redelivery beat us to the insert.
        db.rollback()
        return {"status": "duplicate"}

    # Email heads-up so staff don't have to be watching the portal. Best-effort:
    # a mail failure must never make the webhook 5xx (the reply is already saved).
    try:
        await _alert_staff_of_inbound_reply(
            db, organization_id=client.organization_id, client=client,
            reply_subject=subject, reply_snippet=reply_text,
        )
    except Exception:
        logger.exception("inbound-email: staff heads-up email failed (client_id=%s)", client.id)
    return {"status": "ok"}


def _inbound_reply_recipients(
    db: Session, *, organization_id: int, client: models.EnterpriseClient
) -> list[models.User]:
    """Who gets the email nudge for an inbound reply: the staffer who sent the most
    recent outbound message in this thread (the person waiting on the reply); fall
    back to active org admins. Honors each user's email-notification preference."""
    def _wants_email(u: models.User) -> bool:
        return (
            u is not None and u.is_active
            and getattr(u, "email_notifications_enabled", True) is not False
            and bool((u.email or "").strip())
        )

    recipients: list[models.User] = []
    last_out = (
        db.query(models.EnterpriseClientEmail)
        .filter(
            models.EnterpriseClientEmail.client_id == client.id,
            models.EnterpriseClientEmail.direction == "outbound",
            models.EnterpriseClientEmail.sent_by_user_id.isnot(None),
        )
        .order_by(models.EnterpriseClientEmail.created_at.desc())
        .first()
    )
    if last_out and last_out.sent_by_user_id:
        sender = db.query(models.User).filter(models.User.id == last_out.sent_by_user_id).first()
        if _wants_email(sender):
            recipients.append(sender)
    if not recipients:
        admins = (
            db.query(models.User)
            .join(
                models.EnterpriseOrganizationMember,
                models.EnterpriseOrganizationMember.user_id == models.User.id,
            )
            .filter(
                models.EnterpriseOrganizationMember.organization_id == organization_id,
                models.EnterpriseOrganizationMember.is_active.is_(True),
                models.EnterpriseOrganizationMember.role == ENTERPRISE_ROLE_ADMIN,
                models.User.is_active.is_(True),
            )
            .all()
        )
        recipients.extend(a for a in admins if _wants_email(a))

    seen: set[str] = set()
    deduped: list[models.User] = []
    for u in recipients:
        key = (u.email or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(u)
    return deduped


async def _alert_staff_of_inbound_reply(
    db: Session, *, organization_id: int, client: models.EnterpriseClient,
    reply_subject: str, reply_snippet: str,
) -> None:
    """Send the 'client replied — view in portal' nudge. The thread lives in the
    portal; this is only awareness. Resend calls run off the event loop."""
    recipients = _inbound_reply_recipients(db, organization_id=organization_id, client=client)
    if not recipients:
        return
    organization = (
        db.query(models.EnterpriseOrganization)
        .filter(models.EnterpriseOrganization.id == organization_id)
        .first()
    )
    org_name = organization.company_name if organization else "your consultancy"
    logo_url = _resolve_enterprise_logo_url(organization) if organization else None
    for user in recipients:
        try:
            await run_in_threadpool(
                send_enterprise_inbound_reply_alert_email,
                to_email=user.email,
                staff_name=user.full_name or user.email,
                organization_name=org_name,
                client_name=client.full_name,
                client_id=client.id,
                reply_subject=reply_subject,
                reply_snippet=reply_snippet,
                logo_url=logo_url,
            )
        except Exception:
            logger.exception("inbound-email: alert email to %s failed", user.email)


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
    base_amount = billing.plan_amount_paise(plan["key"], cycle)
    if base_amount <= 0:
        raise HTTPException(status_code=400, detail="This plan is not available for online checkout.")

    # Per-account discount code (admin-managed). Reduces the payable amount.
    amount = base_amount
    coupon_code = None
    coupon_percent = None
    raw_coupon = (payload.coupon_code or "").strip()
    if raw_coupon:
        coupon = enterprise_coupons.resolve_active_coupon_or_400(
            db, organization.id, raw_coupon, context="billing"
        )
        coupon_percent = enterprise_coupons.parse_percent_off(coupon.percent_off)
        coupon_code = enterprise_coupons.normalize_code(coupon.code)
        amount = enterprise_coupons.apply_to_amount_or_400(base_amount, coupon_percent)

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
            "coupon_code": coupon_code or "",
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
        original_amount_paise=base_amount,
        coupon_code=coupon_code,
        coupon_percent_off=coupon_percent,
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
        "original_amount": base_amount,
        "discount_paise": base_amount - amount,
        "coupon_code": coupon_code,
        "coupon_percent_off": float(coupon_percent) if coupon_percent is not None else None,
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

    # Idempotency: a payment may be redeemed only once. Replaying a valid (order, payment,
    # signature) triple must NOT re-extend the plan (that would allow renewal-without-payment),
    # matching the credit/infra verify paths. Return the current state instead of re-activating.
    if payment_row.status == "verified":
        return {
            "message": "This payment has already been verified.",
            "subscription": _serialize_subscription_state(billing.build_subscription_state(db, organization.id)),
        }

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


# ===========================================================================
# Rilono Credits — prepaid wallet for premium AI features (the revenue model)
# ===========================================================================

ENTERPRISE_CREDIT_TXN_PAGE_SIZE = int(os.getenv("ENTERPRISE_CREDIT_TXN_PAGE_SIZE", "25"))


def _serialize_credit_txn(
    txn: models.EnterpriseCreditTransaction,
    client_names: Optional[dict] = None,
) -> dict:
    # Resolve the client name when this entry was a per-client action (Deep Scan,
    # mock interview) so the ledger shows *where* the credits were used.
    client_name = None
    if txn.reference_type == "client" and txn.reference_id is not None and client_names:
        client_name = client_names.get(txn.reference_id)
    return {
        "id": txn.id,
        "type": txn.type,
        "action_key": txn.action_key,
        "credits": int(txn.credits),
        "balance_after": int(txn.balance_after),
        "description": txn.description,
        "created_by_name": txn.created_by_name,
        "reference_type": txn.reference_type,
        "reference_id": txn.reference_id,
        "client_name": client_name,
        "created_at": _iso(txn.created_at),
    }


@router.get("/credits/wallet")
def enterprise_credits_wallet(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    return {
        "permissions": _enterprise_permissions_for_role(role),
        "wallet": credits.wallet_state(db, organization.id),
        "usage": credits.usage_breakdown(db, organization.id),
        "packages": credits.packages_payload(),
        "checkout_enabled": _razorpay_enabled(),
        "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID", "").strip() or None,
    }


@router.get("/credits/transactions")
def enterprise_credits_transactions(
    request: Request,
    limit: int = 25,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    limit = max(1, min(int(limit or 25), 100))
    rows = (
        db.query(models.EnterpriseCreditTransaction)
        .filter(models.EnterpriseCreditTransaction.organization_id == organization.id)
        .order_by(
            models.EnterpriseCreditTransaction.created_at.desc(),
            models.EnterpriseCreditTransaction.id.desc(),
        )
        .limit(limit)
        .all()
    )
    # Batch-resolve client names for per-client actions so each ledger row can
    # show which client the credits were spent on.
    client_ids = {
        t.reference_id for t in rows
        if t.reference_type == "client" and t.reference_id is not None
    }
    client_names: dict = {}
    if client_ids:
        for cid, name in (
            db.query(models.EnterpriseClient.id, models.EnterpriseClient.full_name)
            .filter(
                models.EnterpriseClient.organization_id == organization.id,
                models.EnterpriseClient.id.in_(client_ids),
            )
            .all()
        ):
            client_names[cid] = name
    return {
        "permissions": _enterprise_permissions_for_role(role),
        "transactions": [_serialize_credit_txn(t, client_names) for t in rows],
    }


@router.post("/coupons/validate")
def enterprise_coupon_validate(
    payload: EnterpriseCouponValidateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Preview a per-account discount code for a given purchase before checkout."""
    _, organization, _ = _require_enterprise_membership(db=db, user=current_user, request=request)
    context = (payload.context or "credits").strip().lower()
    if context not in ("credits", "billing"):
        raise HTTPException(status_code=400, detail="Unknown checkout context.")

    if context == "credits":
        package = credits.get_package(payload.package)
        if not package:
            raise HTTPException(status_code=400, detail="Please choose a valid credit package.")
        base_amount = int(package["amount_paise"])
    else:
        plan = billing.get_plan(payload.plan)
        if not plan or plan["key"] not in billing.PAID_PLAN_KEYS:
            raise HTTPException(status_code=400, detail="Please choose a valid paid plan.")
        cycle = billing.normalize_billing_cycle(payload.billing_cycle)
        base_amount = billing.plan_amount_paise(plan["key"], cycle)
    if base_amount <= 0:
        raise HTTPException(status_code=400, detail="This item is not available for checkout.")

    coupon = enterprise_coupons.resolve_active_coupon_or_400(
        db, organization.id, payload.code, context=context
    )
    percent = enterprise_coupons.parse_percent_off(coupon.percent_off)
    # A fully-covering discount (e.g. 100% off) leaves a ₹0 amount. Don't block —
    # report it as free; checkout will grant the credits without Razorpay.
    amount = enterprise_coupons.compute_discounted_amount_paise(base_amount, percent)
    is_free = enterprise_coupons.is_free_checkout(amount)
    return {
        "valid": True,
        "free": is_free,
        "code": enterprise_coupons.normalize_code(coupon.code),
        "percent_off": float(percent),
        "percent_display": enterprise_coupons.format_percent_off(percent) + "%",
        "base_amount_paise": base_amount,
        "amount_paise": amount,
        "discount_paise": base_amount - amount,
        "base_amount_display": credits.format_inr(base_amount),
        "amount_display": credits.format_inr(amount),
    }


def _grant_free_credit_topup(
    db, organization, current_user, package, base_amount, amount, coupon_code, coupon_percent,
):
    """A discount covered the full amount (e.g. 100% off) → add the credits without
    Razorpay. Records a verified 'free' payment so the redemption is counted and the
    purchase shows in history, then credits the wallet (idempotent ledger reference)."""
    total_credits = int(package["credits"]) + int(package["bonus_credits"])
    payment = models.EnterpriseCreditPayment(
        organization_id=organization.id,
        created_by_user_id=current_user.id,
        provider="free",
        kind="credits",
        package_key=package["key"],
        credits=int(package["credits"]),
        bonus_credits=int(package["bonus_credits"]),
        amount_paise=int(amount),
        original_amount_paise=int(base_amount),
        coupon_code=coupon_code,
        coupon_percent_off=coupon_percent,
        currency=credits.CURRENCY,
        razorpay_order_id=f"free_{secrets.token_hex(8)}",  # NOT NULL + unique column
        status="verified",
        verified_at=datetime.utcnow(),
    )
    db.add(payment)
    db.flush()  # assign payment.id for the ledger reference
    pct = enterprise_coupons.format_percent_off(coupon_percent) if coupon_percent is not None else ""
    credits.add_credits(
        db, organization.id, total_credits,
        txn_type="topup",
        description=f"{package['label']} (+{total_credits} credits · {coupon_code} {pct}% off)",
        reference_type="payment", reference_id=payment.id,
        user=current_user, commit=False,
    )
    db.commit()
    return {
        "action": "granted",
        "message": f"{coupon_code} covered the full amount — {total_credits} credits added to your wallet.",
        "total_credits": total_credits,
        "coupon_code": coupon_code,
        "wallet": credits.wallet_state(db, organization.id),
    }


@router.post("/credits/topup/checkout")
def enterprise_credits_topup_checkout(
    payload: EnterpriseCreditTopupRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, _ = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_manage_users=True
    )
    package = credits.get_package(payload.package)
    if not package:
        raise HTTPException(status_code=400, detail="Please choose a valid credit package.")
    base_amount = int(package["amount_paise"])
    if base_amount <= 0:
        raise HTTPException(status_code=400, detail="This package is not available for checkout.")

    # Per-account discount code (admin-managed). Reduces the payable amount.
    amount = base_amount
    coupon_code = None
    coupon_percent = None
    raw_coupon = (payload.coupon_code or "").strip()
    if raw_coupon:
        coupon = enterprise_coupons.resolve_active_coupon_or_400(
            db, organization.id, raw_coupon, context="credits"
        )
        coupon_percent = enterprise_coupons.parse_percent_off(coupon.percent_off)
        coupon_code = enterprise_coupons.normalize_code(coupon.code)
        amount = enterprise_coupons.compute_discounted_amount_paise(base_amount, coupon_percent)

    # Fully covered by the discount → grant the credits for free (no Razorpay order).
    if coupon_code and enterprise_coupons.is_free_checkout(amount):
        return _grant_free_credit_topup(
            db, organization, current_user, package, base_amount, amount, coupon_code, coupon_percent,
        )
    if amount < enterprise_coupons.MIN_CHECKOUT_PAISE:
        raise HTTPException(status_code=400, detail="This amount is too low for online checkout.")

    if not _razorpay_enabled():
        return {
            "action": "contact_sales",
            "message": "Online top-up is being enabled. Please contact us to add credits.",
        }

    receipt = f"reln_cr_{organization.id}_{secrets.token_hex(5)}"[:40]
    order = _razorpay_request("POST", "/orders", {
        "amount": amount,
        "currency": credits.CURRENCY,
        "receipt": receipt,
        "notes": {
            "organization_id": str(organization.id),
            "kind": "credits",
            "package": package["key"],
            "user_id": str(current_user.id),
            "coupon_code": coupon_code or "",
        },
    })
    order_id = str(order.get("id") or "").strip()
    if not order_id:
        raise HTTPException(status_code=502, detail="Could not create the payment order.")

    db.add(models.EnterpriseCreditPayment(
        organization_id=organization.id,
        created_by_user_id=current_user.id,
        provider="razorpay",
        kind="credits",
        package_key=package["key"],
        credits=int(package["credits"]),
        bonus_credits=int(package["bonus_credits"]),
        amount_paise=amount,
        original_amount_paise=base_amount,
        coupon_code=coupon_code,
        coupon_percent_off=coupon_percent,
        currency=credits.CURRENCY,
        razorpay_order_id=order_id,
        status="created",
    ))
    db.commit()

    return {
        "action": "checkout",
        "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID", "").strip(),
        "order_id": order_id,
        "amount": amount,
        "original_amount": base_amount,
        "discount_paise": base_amount - amount,
        "coupon_code": coupon_code,
        "coupon_percent_off": float(coupon_percent) if coupon_percent is not None else None,
        "currency": credits.CURRENCY,
        "package": package["key"],
        "package_label": package["label"],
        "total_credits": int(package["credits"]) + int(package["bonus_credits"]),
        "organization_name": organization.company_name,
        "prefill": {
            "name": current_user.full_name or "",
            "email": current_user.email or "",
        },
    }


@router.post("/credits/topup/verify")
def enterprise_credits_topup_verify(
    payload: EnterpriseCreditVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, _ = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_manage_users=True
    )
    payment_row = _verify_credit_payment_or_402(
        db=db, organization=organization, payload=payload, expected_kind="credits"
    )

    total_credits = int(payment_row.credits) + int(payment_row.bonus_credits)
    # Idempotency: credit the wallet only once (skip if a ledger row already exists).
    already = (
        db.query(models.EnterpriseCreditTransaction)
        .filter(
            models.EnterpriseCreditTransaction.organization_id == organization.id,
            models.EnterpriseCreditTransaction.reference_type == "payment",
            models.EnterpriseCreditTransaction.reference_id == payment_row.id,
        )
        .first()
    )
    if not already and total_credits > 0:
        pkg = credits.get_package(payment_row.package_key)
        label = pkg["label"] if pkg else "Credit top-up"
        credits.add_credits(
            db, organization.id, total_credits,
            txn_type="topup",
            description=f"{label} (+{total_credits} credits)",
            reference_type="payment", reference_id=payment_row.id,
            user=current_user, commit=False,
        )
    db.commit()

    return {
        "message": f"{total_credits} credits added to your wallet.",
        "wallet": credits.wallet_state(db, organization.id),
    }


@router.post("/credits/infra/checkout")
def enterprise_infra_fee_checkout(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, _ = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_manage_users=True
    )
    amount = int(credits.INFRA_FEE_PAISE)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="The infrastructure fee is not configured.")
    if not _razorpay_enabled():
        return {
            "action": "contact_sales",
            "message": "Online payment is being enabled. Please contact us to activate the infrastructure fee.",
        }

    receipt = f"reln_infra_{organization.id}_{secrets.token_hex(5)}"[:40]
    order = _razorpay_request("POST", "/orders", {
        "amount": amount,
        "currency": credits.CURRENCY,
        "receipt": receipt,
        "notes": {
            "organization_id": str(organization.id),
            "kind": "infra_fee",
            "user_id": str(current_user.id),
        },
    })
    order_id = str(order.get("id") or "").strip()
    if not order_id:
        raise HTTPException(status_code=502, detail="Could not create the payment order.")

    db.add(models.EnterpriseCreditPayment(
        organization_id=organization.id,
        created_by_user_id=current_user.id,
        provider="razorpay",
        kind="infra_fee",
        package_key="infra",
        credits=0,
        bonus_credits=0,
        amount_paise=amount,
        currency=credits.CURRENCY,
        razorpay_order_id=order_id,
        status="created",
    ))
    db.commit()

    return {
        "action": "checkout",
        "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID", "").strip(),
        "order_id": order_id,
        "amount": amount,
        "currency": credits.CURRENCY,
        "organization_name": organization.company_name,
        "prefill": {
            "name": current_user.full_name or "",
            "email": current_user.email or "",
        },
    }


@router.post("/credits/infra/verify")
def enterprise_infra_fee_verify(
    payload: EnterpriseCreditVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, _ = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_manage_users=True
    )
    payment_row = _verify_credit_payment_or_402(
        db=db, organization=organization, payload=payload, expected_kind="infra_fee"
    )
    # Idempotency: only extend the paid-until window once per payment.
    already = (
        db.query(models.EnterpriseCreditTransaction)
        .filter(
            models.EnterpriseCreditTransaction.organization_id == organization.id,
            models.EnterpriseCreditTransaction.reference_type == "infra_payment",
            models.EnterpriseCreditTransaction.reference_id == payment_row.id,
        )
        .first()
    )
    if not already:
        credits.mark_infra_fee_paid(db, organization.id, commit=False)
        # Record a zero-credit ledger marker so the credit ledger shows the charge.
        wallet = credits.get_or_create_wallet(db, organization.id, commit=False)
        db.add(models.EnterpriseCreditTransaction(
            organization_id=organization.id,
            type="infra_fee",
            credits=0,
            balance_after=int(wallet.balance_credits),
            description=f"Infrastructure server fee ({credits.format_inr(credits.INFRA_FEE_PAISE)}/mo)",
            reference_type="infra_payment",
            reference_id=payment_row.id,
            created_by_user_id=current_user.id,
            created_by_name=current_user.full_name or current_user.email,
        ))
    db.commit()

    return {
        "message": "Infrastructure server fee activated.",
        "wallet": credits.wallet_state(db, organization.id),
    }


def _verify_credit_payment_or_402(
    *,
    db: Session,
    organization: models.EnterpriseOrganization,
    payload: EnterpriseCreditVerifyRequest,
    expected_kind: str,
) -> models.EnterpriseCreditPayment:
    """Validate a Razorpay signature for a credit/infra payment and mark it verified."""
    key_id, key_secret = _razorpay_credentials()
    if not key_id or not key_secret:
        raise HTTPException(status_code=503, detail="Payment verification is not configured.")

    payment_row = (
        db.query(models.EnterpriseCreditPayment)
        .filter(
            models.EnterpriseCreditPayment.razorpay_order_id == payload.razorpay_order_id.strip(),
            models.EnterpriseCreditPayment.organization_id == organization.id,
            models.EnterpriseCreditPayment.kind == expected_kind,
        )
        # Lock the payment row (Postgres) so two concurrent verifies for the SAME payment
        # serialize: the second blocks here until the first commits, then the caller's
        # "already credited?" ledger check sees the committed row and skips — closing the
        # non-atomic check-then-insert race that could otherwise double-credit the wallet.
        .with_for_update()
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

    if payment_row.status != "verified":
        payment_row.razorpay_payment_id = payload.razorpay_payment_id.strip()
        payment_row.status = "verified"
        payment_row.verified_at = datetime.utcnow()
        payment_row.error_message = None
    return payment_row


ENTERPRISE_SIGNUP_OTP_EXPIRES_MINUTES = int(os.getenv("ENTERPRISE_SIGNUP_OTP_EXPIRES_MINUTES", "10") or "10")
ENTERPRISE_SIGNUP_OTP_MAX_ATTEMPTS = int(os.getenv("ENTERPRISE_SIGNUP_OTP_MAX_ATTEMPTS", "5") or "5")


class EnterpriseSignupSendCodeRequest(BaseModel):
    email: EmailStr
    cf_turnstile_token: Optional[str] = None


@router.post("/signup/send-code")
def enterprise_signup_send_code(
    payload: EnterpriseSignupSendCodeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Step 1 of workspace signup: email the owner a 6-digit code. The workspace itself
    is only created by /signup once the code is verified — so unverified emails never
    produce junk workspaces or claim subdomains."""
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.signup_send_code", limit=6, window_seconds=3600,
    )

    # Bot gate lives on this step (the final /signup is gated by the code itself).
    turnstile_token = (payload.cf_turnstile_token or "").strip()
    if is_turnstile_enabled() and not is_request_ip_whitelisted(request):
        if turnstile_token:
            client_ip = extract_client_ip(request) if request else None
            if not verify_turnstile_token(turnstile_token, client_ip):
                raise HTTPException(status_code=400, detail="Security verification failed. Please try again.")
        elif _is_turnstile_required():
            raise HTTPException(status_code=400, detail="Security verification is required.")

    email = payload.email.lower().strip()
    if db.query(models.User).filter(models.User.email == email).first():
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists. Please sign in instead.",
        )

    code = f"{secrets.randbelow(1_000_000):06d}"
    row = (
        db.query(models.EnterpriseSignupOtp)
        .filter(models.EnterpriseSignupOtp.email == email)
        .first()
    )
    expires_at = datetime.utcnow() + timedelta(minutes=ENTERPRISE_SIGNUP_OTP_EXPIRES_MINUTES)
    if row:
        row.code_hash = hash_token(code)
        row.expires_at = expires_at
        row.attempts = 0
    else:
        db.add(models.EnterpriseSignupOtp(email=email, code_hash=hash_token(code), expires_at=expires_at))
    db.commit()

    sent = send_email_otp(email, code, expires_in_minutes=ENTERPRISE_SIGNUP_OTP_EXPIRES_MINUTES)
    result = {
        "message": f"We've emailed a 6-digit code to {email}.",
        "expires_in_minutes": ENTERPRISE_SIGNUP_OTP_EXPIRES_MINUTES,
    }
    if not sent:
        if _is_development_env():
            # Local sandbox without an email provider — surface the code for testing.
            result["dev_code"] = code
        else:
            raise HTTPException(
                status_code=502,
                detail="We couldn't send the verification email right now. Please try again in a moment.",
            )
    return result


def _verify_signup_otp_or_400(db: Session, email: str, code: Optional[str]) -> models.EnterpriseSignupOtp:
    """Validate the signup email code; raises 400 with a friendly message otherwise."""
    code_clean = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code_clean) != 6:
        raise HTTPException(status_code=400, detail="Enter the 6-digit code we emailed you.")
    row = (
        db.query(models.EnterpriseSignupOtp)
        .filter(models.EnterpriseSignupOtp.email == email)
        .first()
    )
    if not row:
        raise HTTPException(status_code=400, detail="No verification code found for this email — please request a new one.")
    expires = row.expires_at.replace(tzinfo=None) if getattr(row.expires_at, "tzinfo", None) else row.expires_at
    if expires < datetime.utcnow():
        raise HTTPException(status_code=400, detail="That code has expired — please request a new one.")
    if int(row.attempts or 0) >= ENTERPRISE_SIGNUP_OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=400, detail="Too many incorrect attempts — please request a new code.")
    if not token_matches(code_clean, row.code_hash):
        row.attempts = int(row.attempts or 0) + 1
        db.commit()
        raise HTTPException(status_code=400, detail="That code isn't right — please check the email and try again.")
    return row


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

    # Bot-gating (Turnstile) happens at /signup/send-code; this step is gated by the
    # emailed code itself, which is a stronger proof (a verified, reachable inbox).

    if not payload.accepted_terms_privacy:
        raise HTTPException(
            status_code=400,
            detail="You must accept the Terms & Conditions and Privacy Policy to create your workspace.",
        )

    if not payload.accepted_dpa:
        raise HTTPException(
            status_code=400,
            detail="You must accept the Data Processing Agreement to manage client data in your workspace.",
        )

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

    # The owner must prove the inbox before anything is created (or a subdomain claimed).
    otp_row = _verify_signup_otp_or_400(db, email, payload.email_otp)

    _assert_subdomain_available(db=db, subdomain_slug=subdomain_slug)

    password_hash = get_password_hash(payload.password)

    # Capture proof-of-consent: when, from where, and which version of the legal
    # documents the owner agreed to. Stored on the user row for audit/compliance.
    consent_ip = extract_client_ip(request) if request else None
    consent_user_agent = (request.headers.get("user-agent") if request else None) or None
    if consent_user_agent:
        consent_user_agent = consent_user_agent[:1000]

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
        # Enterprise-created account (workspace owner) → blocked from the B2C consumer app.
        is_enterprise_account=True,
        accepted_terms_privacy_at=datetime.utcnow(),
        accepted_terms_privacy_ip=consent_ip,
        accepted_terms_privacy_user_agent=consent_user_agent,
        accepted_terms_privacy_version=LEGAL_TERMS_PRIVACY_VERSION,
        age_confirmed_at=datetime.utcnow(),
        marketing_emails_consent=bool(payload.marketing_emails_consent),
        marketing_emails_consent_at=(datetime.utcnow() if payload.marketing_emails_consent else None),
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
        # Proof the organization accepted the Data Processing Agreement (it is the
        # controller of its clients' data; Rilono is the processor).
        dpa_accepted_at=datetime.utcnow(),
        dpa_accepted_version=LEGAL_DPA_VERSION,
        dpa_accepted_by_user_id=user.id,
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
    # The signup code is single-use: burn it with the same commit that creates the workspace.
    db.delete(otp_row)
    db.commit()
    db.refresh(user)

    portal_url = _build_enterprise_portal_url(subdomain_slug, request)

    # Warm welcome email to the new workspace owner — best-effort, never block signup.
    try:
        send_enterprise_welcome_email(
            to_email=user.email,
            full_name=user.full_name or "",
            company=company_name,
            portal_url=portal_url,
        )
    except Exception:
        logger.exception("Enterprise welcome email failed for %s", user.email)

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
        "portal_url": portal_url,
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

    # Cost guardrail: reject obviously off-topic prompts before spending model tokens.
    # (A refused off-topic message is free — it doesn't touch the copilot meter.)
    if ai_guardrails.is_off_topic(payload.message):
        ai_guardrails.record_block(source="enterprise_copilot", detail="enterprise")
        return {"answer": ai_guardrails.OFF_TOPIC_REFUSAL, "permissions": _enterprise_permissions_for_role(role)}

    # Meter the copilot: free daily allowance, then 1 credit per bundle of messages.
    # Block a paid message the wallet can't cover BEFORE spending any Gemini tokens.
    credits.copilot_precheck_or_402(db, organization.id)

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

    # Answered successfully → record the message against the meter (may debit a credit).
    meter = credits.record_copilot_message(db, organization.id, user=current_user)
    response = {
        "answer": answer,
        "permissions": _enterprise_permissions_for_role(role),
        "credits_meter": meter,
    }
    if meter.get("credits_charged"):
        response["wallet"] = credits.wallet_state(db, organization.id)
    return response


# ===========================================================================
# Rilono Copilot (Chrome extension) — enterprise staff mode
#
# Staff authenticate as themselves and pick a CLIENT (EnterpriseClient CRM row)
# to work on behalf of; the client only shapes the AI context, so every message
# stays attributable to the staff user. Metered on the same org copilot meter
# as the dashboard assistant (free daily allowance, then credits).
# ===========================================================================

ENTERPRISE_COPILOT_CLIENT_LIMIT = 300
ENTERPRISE_COPILOT_MAX_ATTACHMENTS = 8


class EnterpriseCopilotChatRequest(BaseModel):
    client_id: int = Field(..., ge=1)
    message: str = Field(..., min_length=1, max_length=8000)
    conversation_history: Optional[list[dict]] = None
    session_attachments: Optional[list[ChatSessionAttachment]] = None


@router.get("/copilot/context")
def enterprise_copilot_extension_context(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Session probe for the Chrome extension: is this signed-in user enterprise
    staff? Returns 200 with enterprise=False for regular students (no error), so
    the extension can fall back to the B2C copilot silently."""
    membership, organization = _get_active_enterprise_membership(db, current_user.id)
    if not membership or not organization or not (organization.subdomain_slug or "").strip():
        return {"enterprise": False}
    _enforce_request_subdomain_matches_org(request, organization)
    role = _normalize_enterprise_role(membership.role)
    client_count = (
        db.query(func.count(models.EnterpriseClient.id))
        .filter(models.EnterpriseClient.organization_id == organization.id)
        .scalar()
    )
    return {
        "enterprise": True,
        "organization": {
            "id": organization.id,
            "company_name": organization.company_name,
            "subdomain_slug": (organization.subdomain_slug or "").strip().lower() or None,
            "logo_url": _resolve_enterprise_logo_url(organization),
        },
        "role": role,
        "permissions": _enterprise_permissions_for_role(role),
        "copilot_enabled": enterprise_copilot.is_provider_available(),
        "client_count": int(client_count or 0),
    }


@router.get("/copilot/clients")
def enterprise_copilot_extension_clients(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Compact client list for the extension's on-behalf-of picker (view-level).
    Deliberately excludes sensitive fields like passport numbers — the chat
    context is assembled server-side, so the extension never needs them."""
    _, organization, _ = _require_enterprise_membership(db=db, user=current_user, request=request)
    base = db.query(models.EnterpriseClient).filter(
        models.EnterpriseClient.organization_id == organization.id
    )
    total = base.count()
    rows = (
        base.order_by(models.EnterpriseClient.updated_at.desc())
        .limit(ENTERPRISE_COPILOT_CLIENT_LIMIT)
        .all()
    )
    member_names = _org_member_name_map(db, organization.id)
    clients = []
    for client in rows:
        assigned_name = None
        if client.assigned_to_user_id:
            assigned_name = member_names.get(int(client.assigned_to_user_id))
        clients.append({
            "id": client.id,
            "full_name": client.full_name,
            "email": client.email,
            "visa_category": client.visa_category,
            "visa_category_label": _category_label(client.visa_category),
            "destination_country_code": client.destination_country_code,
            "destination_country_name": client.destination_country_name,
            "visa_type": client.visa_type,
            "intake": client.intake,
            "status": client.status,
            "stage": _stage_brief(client.status),
            "priority": client.priority,
            "assigned_to_name": assigned_name,
            "updated_at": _iso(client.updated_at),
        })
    return {
        "clients": clients,
        "total": int(total or 0),
        "capped": bool(total and total > ENTERPRISE_COPILOT_CLIENT_LIMIT),
    }


@router.post("/copilot/chat")
def enterprise_copilot_extension_chat(
    payload: EnterpriseCopilotChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """One staff-mode Copilot turn about a specific client. Mirrors /ai/chat's
    guardrail → precheck → generate → meter flow; the response field is named
    `response` to match the extension's B2C chat contract."""
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    _enforce_rate_limit_or_429(
        request=request,
        scope="enterprise.copilot",
        limit=ENTERPRISE_AI_RATE_LIMIT,
        window_seconds=ENTERPRISE_AI_RATE_WINDOW_SECONDS,
        extra_key=str(current_user.id),
    )

    if not enterprise_copilot.is_provider_available():
        raise HTTPException(
            status_code=503,
            detail="Rilono Copilot isn't available right now. Please try again later.",
        )

    client = _get_org_client_or_404(db, organization.id, payload.client_id)

    if len(payload.session_attachments or []) > ENTERPRISE_COPILOT_MAX_ATTACHMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"At most {ENTERPRISE_COPILOT_MAX_ATTACHMENTS} attachments are allowed per message.",
        )

    # Cost guardrail: refuse obviously off-topic prompts before spending tokens.
    # Also screen the newest user turn in the supplied history — otherwise a
    # short "continue" message with the real (off-topic) request smuggled into
    # conversation_history bypasses this free pre-model check entirely.
    latest_history_turn = ""
    for turn in reversed(payload.conversation_history or []):
        if isinstance(turn, dict) and (turn.get("role") or "user") != "assistant":
            latest_history_turn = str(turn.get("content") or "")
            break
    if ai_guardrails.is_off_topic(payload.message) or (
        len(payload.message) < 200
        and latest_history_turn
        and ai_guardrails.is_off_topic(latest_history_turn)
    ):
        ai_guardrails.record_block(source=enterprise_copilot.USAGE_SOURCE, detail="enterprise_extension")
        return {"response": ai_guardrails.OFF_TOPIC_REFUSAL}

    # Meter: free daily allowance, then credits — block unaffordable paid
    # messages BEFORE any Gemini tokens are spent.
    credits.copilot_precheck_or_402(db, organization.id)

    try:
        answer = enterprise_copilot.run_enterprise_copilot_chat(
            db,
            organization=organization,
            staff_user=current_user,
            role=role,
            client=client,
            message=payload.message,
            conversation_history=payload.conversation_history,
            session_attachments=payload.session_attachments,
        )
    except Exception:
        logger.exception(
            "Enterprise extension copilot failed (org_id=%s client_id=%s)",
            organization.id, client.id,
        )
        raise HTTPException(
            status_code=502,
            detail="Rilono Copilot ran into a problem answering that. Please try again.",
        )

    # Answered successfully → record the message against the meter (may debit a
    # credit). Metering failures must never destroy the already-generated (and
    # already-paid-for) answer: deliver it unmetered and log loudly instead —
    # a 500 here would just make the org re-spend the full Gemini cost on retry.
    response = {
        "response": answer,
        "client": {"id": client.id, "full_name": client.full_name},
    }
    try:
        meter = credits.record_copilot_message(db, organization.id, user=current_user)
        response["credits_meter"] = meter
        if meter.get("credits_charged"):
            response["wallet"] = credits.wallet_state(db, organization.id)
    except Exception:
        logger.exception(
            "Copilot metering failed after successful generation (org_id=%s) — answer delivered unmetered",
            organization.id,
        )
    return response


# ===========================================================================
# Per-client documents (private R2 storage, authenticated streaming)
# ===========================================================================

ENTERPRISE_DOC_MAX_BYTES = int(os.getenv("ENTERPRISE_DOC_MAX_BYTES", str(25 * 1024 * 1024)))
ENTERPRISE_DOC_ALLOWED_EXT = {
    ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic",
    ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt",
}
ENTERPRISE_DOC_INLINE_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif"}
# Safe served Content-Type per (validated) extension. The download endpoint uses THIS, never
# the uploader-supplied mime_type — a file named *.pdf can arrive with Content-Type text/html
# and a <script> body, which served inline under our 'unsafe-inline' CSP would execute in the
# portal origin (account takeover). Deriving from the extension makes that impossible.
ENTERPRISE_DOC_EXT_MIME = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif", ".heic": "image/heic",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv", ".txt": "text/plain",
}


def _serialize_client_document(doc: models.EnterpriseClientDocument) -> dict:
    extracted = None
    if doc.extracted_fields:
        try:
            import json
            extracted = json.loads(doc.extracted_fields)
        except Exception:
            extracted = None
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
        # AI validation (null status = still scanning in the background).
        "validation_status": doc.validation_status,
        "validation_message": doc.validation_message,
        "validated_at": _iso(doc.validated_at),
        "extracted": extracted,
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


def _ent_flexible_parse_date(value):
    """Best-effort parse of a human-readable date (passport/ID dates come in many formats)
    into a date. Prefers day-first (most passports). Returns None if unparseable."""
    s = str(value or "").strip()
    if not s or s.lower() in {"null", "none", "n/a", "na", "not available", "unknown"}:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%m/%d/%Y",
                "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d %b, %Y", "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        from dateutil import parser as _dateparser
        return _dateparser.parse(s, dayfirst=True, fuzzy=True).date()
    except Exception:
        return None


def _ent_clean_extracted(validation: dict) -> dict:
    """Pull identity fields out of validate_and_extract_document()'s response, dropping
    empty/placeholder values."""
    def val(key):
        raw = validation.get(key)
        if raw is None:
            return None
        s = str(raw).strip()
        if not s or s.lower() in {"null", "none", "n/a", "na", "not available", "unknown", "-"}:
            return None
        return s
    return {
        "name": val("Name"),
        "date_of_birth": val("Date of Birth"),
        "document_number": val("Document Number"),
        "expiration_date": val("Expiration Date"),
        "issue_date": val("Issue Date"),
        "country": val("Country"),
        "other": val("Other Information"),
    }


def _ent_profile_field_plan(document_type: str, fields: dict):
    """Which extracted fields map onto the client profile, per document type. Only identity
    documents (passport) populate the profile today; extend this for more types later."""
    dt = (document_type or "").lower()
    is_passport = ("passport" in dt) and ("photo" not in dt)
    if not is_passport:
        return []
    return [  # (client attribute, human label, extracted value, kind)
        ("full_name", "Name", fields.get("name"), "text"),
        ("date_of_birth", "Date of birth", fields.get("date_of_birth"), "date"),
        ("nationality", "Nationality", fields.get("country"), "text"),
        ("passport_number", "Passport number", fields.get("document_number"), "text"),
        ("passport_expiry", "Passport expiry", fields.get("expiration_date"), "date"),
    ]


# Upload-time AI cross-validation context. No hardcoded identity/consistency rules live
# in this codebase: we hand the AI the client's profile and their other documents, and the
# AI decides — per document type and destination — what to check (identity, dates, funds,
# study plan, …). A material conflict makes the AI fail the validation itself.
_ENT_VALIDATION_PROFILE_CHARS = 4000
_ENT_VALIDATION_DOCS_CHARS = 12000
_ENT_VALIDATION_MAX_RELATED_DOCS = 6
_ENT_VALIDATION_TEXT_PER_DOC_CHARS = 1800


def _ent_client_profile_context(client) -> str:
    """Compact snapshot of the client profile for AI cross-validation at upload time."""
    if client is None:
        return ""

    def _d(v):
        return v.isoformat() if hasattr(v, "isoformat") else ("" if v is None else str(v).strip())

    dest_name = (getattr(client, "destination_country_name", "") or "").strip()
    dest_code = (getattr(client, "destination_country_code", "") or "").strip()
    destination = f"{dest_name} ({dest_code})" if dest_name and dest_code else (dest_name or dest_code)
    rows = [
        ("Full name", getattr(client, "full_name", None)),
        ("Date of birth", _d(getattr(client, "date_of_birth", None))),
        ("Nationality", getattr(client, "nationality", None)),
        ("Passport number", getattr(client, "passport_number", None)),
        ("Passport expiry", _d(getattr(client, "passport_expiry", None))),
        ("Destination", destination),
        ("Visa type", getattr(client, "visa_type", None)),
        ("Intake", getattr(client, "intake", None)),
        ("Key date / deadline", _d(getattr(client, "target_date", None))),
        ("Email", getattr(client, "email", None)),
    ]
    lines = [f"{label}: {str(value).strip()}" for label, value in rows if value and str(value).strip()]
    if not lines:
        return ""
    text = (
        "This is the visa applicant (client) this document was uploaded for. Cross-check the "
        "document against this profile — including that the document actually belongs to this "
        "person:\n" + "\n".join(lines)
    )
    return text[:_ENT_VALIDATION_PROFILE_CHARS]


def _ent_related_documents_context(db: Session, client, exclude_document_id) -> str:
    """Bounded snapshots of the client's OTHER documents so the AI can cross-validate names,
    dates, numbers, universities and timelines across everything on file."""
    if client is None:
        return ""
    try:
        rows = (
            db.query(models.EnterpriseClientDocument)
            .filter(
                models.EnterpriseClientDocument.client_id == client.id,
                models.EnterpriseClientDocument.id != int(exclude_document_id or 0),
            )
            .order_by(models.EnterpriseClientDocument.created_at.desc())
            .limit(_ENT_VALIDATION_MAX_RELATED_DOCS)
            .all()
        )
    except Exception:
        logger.exception("Failed to load related documents for validation context (client_id=%s)", client.id)
        return ""
    blocks, used = [], 0
    for index, doc in enumerate(rows, start=1):
        header = (
            f"\n--- PRIOR DOCUMENT {index}: {(doc.document_type or 'document').upper()} "
            f"({doc.original_filename}) [{(doc.validation_status or 'not scanned').upper()}] ---\n"
        )
        body = ""
        if doc.extracted_fields:
            try:
                fields = (json.loads(doc.extracted_fields) or {}).get("fields") or {}
                if fields:
                    body += "Extracted fields: " + json.dumps(fields, default=str) + "\n"
            except Exception:
                pass
        if doc.extracted_text:
            body += str(doc.extracted_text)[:_ENT_VALIDATION_TEXT_PER_DOC_CHARS] + "\n"
        remaining = _ENT_VALIDATION_DOCS_CHARS - used - len(header)
        if remaining <= 0:
            break
        block = header + body[: max(0, remaining)]
        blocks.append(block)
        used += len(block)
    if not blocks:
        return ""
    return "Previously uploaded documents for this client (for cross-validation):" + "".join(blocks)


def _ent_autofill_profile(db: Session, client: models.EnterpriseClient, document_type: str, fields: dict) -> dict:
    """Fill EMPTY client profile fields from a validated document's details. Never overwrites an
    existing value — a differing value is returned as a 'conflict' for staff to review. Adds an
    audit note. Returns {'filled': [...], 'conflicts': [...]}."""
    filled, conflicts = [], []

    def _disp(v):
        return v.isoformat() if hasattr(v, "isoformat") else str(v)

    for attr, label, raw_value, kind in _ent_profile_field_plan(document_type, fields):
        if not raw_value:
            continue
        if kind == "date":
            new_value = _ent_flexible_parse_date(raw_value)
            if new_value is None:
                continue
        else:
            new_value = str(raw_value).strip()
        current = getattr(client, attr, None)
        current_empty = current is None or (isinstance(current, str) and not current.strip())
        if current_empty:
            setattr(client, attr, new_value)
            filled.append({"field": label, "value": _disp(new_value)})
        else:
            if kind == "date":
                same = (current == new_value)
            else:
                same = (str(current).strip().lower() == new_value.strip().lower())
            if not same:
                conflicts.append({"field": label, "existing": _disp(current), "document": _disp(new_value)})

    if filled or conflicts:
        lines = []
        if filled:
            lines.append("Auto-filled from validated " + str(document_type) + ": "
                         + ", ".join(f["field"] for f in filled) + ".")
        if conflicts:
            lines.append("Needs review — document differs from existing profile: "
                         + "; ".join(f'{c["field"]} (profile "{c["existing"]}" vs document "{c["document"]}")'
                                     for c in conflicts) + ".")
        try:
            db.add(models.EnterpriseClientNote(
                organization_id=client.organization_id,
                client_id=client.id,
                author_user_id=None,
                author_name="Rilono AI",
                body=" ".join(lines),
            ))
        except Exception:
            logger.exception("Failed to add autofill audit note (client_id=%s)", client.id)
    return {"filled": filled, "conflicts": conflicts}


def _start_document_text_extraction(document_id: int, data: bytes, filename: str, mime_type: str | None) -> None:
    """Background: extract the document's text (for the AI copilot) AND run Rilono AI validation
    + structured extraction. When a validated identity document (passport) comes in, empty client
    profile fields are auto-filled — differences are flagged, never overwritten. Used by both the
    staff upload and the client secure-link upload."""
    def _worker():
        import json
        from datetime import timezone
        db2 = SessionLocal()
        try:
            row = (
                db2.query(models.EnterpriseClientDocument)
                .filter(models.EnterpriseClientDocument.id == int(document_id))
                .first()
            )
            if row is None:
                return
            client = (
                db2.query(models.EnterpriseClient)
                .filter(models.EnterpriseClient.id == row.client_id)
                .first()
            )

            # 1) Full-text extraction for the copilot (best-effort).
            try:
                extracted = gemini_service.extract_text_from_document(
                    data, filename, mime_type or "application/octet-stream"
                )
                if extracted:
                    row.extracted_text = extracted[:200000]
            except Exception:
                logger.exception("Enterprise doc text extraction failed (document_id=%s)", document_id)

            # 2) Validate the document + extract structured identity fields.
            destination_code = client.destination_country_code if client is not None else None
            destination_summary = (
                f"{client.destination_country_name} — {client.visa_type}" if client is not None else None
            )
            validation = None
            try:
                # Hand the AI the client's profile + their other documents: the AI decides,
                # per document type and destination, what to cross-check (identity, dates,
                # funds, study plan, …) and FAILS the validation itself on any material
                # conflict — e.g. a passport that belongs to a different person.
                validation = gemini_service.validate_and_extract_document(
                    data, filename, mime_type or "application/octet-stream",
                    document_type=row.document_type,
                    current_date_for_evaluation=datetime.now(timezone.utc).isoformat(),
                    student_profile_context=_ent_client_profile_context(client),
                    related_documents_context=_ent_related_documents_context(db2, client, row.id),
                    destination_country_code=destination_code,
                    destination_summary=destination_summary,
                )
            except Exception:
                logger.exception("Enterprise doc validation failed (document_id=%s)", document_id)

            row.validated_at = datetime.now(timezone.utc)
            payload: dict = {}
            if isinstance(validation, dict):
                verdict = str(validation.get("Document Validation", "")).strip().lower()
                row.validation_status = "valid" if verdict == "yes" else ("invalid" if verdict == "no" else "error")
                row.validation_message = (str(validation.get("Message") or "").strip() or None)
                fields = _ent_clean_extracted(validation)
                payload["fields"] = fields
                cvf = validation.get("Cross Validation Flags")
                if cvf:
                    payload["cross_validation_flags"] = cvf
                # Auto-fill ONLY runs when the AI passed the document — a red-flagged
                # document (wrong person, expired, inconsistent) never touches the profile.
                if row.validation_status == "valid" and client is not None:
                    autofill = _ent_autofill_profile(db2, client, row.document_type, fields)
                    payload["autofill"] = autofill
                    filled, conflicts = autofill.get("filled") or [], autofill.get("conflicts") or []
                    if filled or conflicts:
                        bits = []
                        if filled:
                            bits.append("auto-filled " + ", ".join(f["field"] for f in filled))
                        if conflicts:
                            bits.append(f"{len(conflicts)} field(s) to review")
                        try:
                            notif.notify_org(
                                db2, row.organization_id, type="document_validated",
                                title=f"Rilono AI validated {row.document_type} for {client.full_name} — " + "; ".join(bits),
                                reference_type="client", reference_id=client.id, commit=False,
                            )
                        except Exception:
                            pass
                elif row.validation_status == "invalid" and client is not None:
                    # Surface the AI's red flag to the whole org, not just the uploader.
                    # The filename keeps re-uploads distinct (notify_org dedupes on title).
                    try:
                        notif.notify_org(
                            db2, row.organization_id, type="document_flagged",
                            title=(f"⚠ Rilono AI flagged {row.document_type} "
                                   f"({row.original_filename}) for {client.full_name} — needs review"),
                            reference_type="client", reference_id=client.id, commit=False,
                        )
                    except Exception:
                        pass
            else:
                row.validation_status = "error"
                row.validation_message = "Rilono AI could not validate this document automatically."

            if payload:
                row.extracted_fields = json.dumps(payload)[:100000]
            db2.commit()
        except Exception:
            logger.exception("Background document processing failed (document_id=%s)", document_id)
        finally:
            db2.close()

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
    # Serve a Content-Type derived from the validated extension — NEVER the uploader-supplied
    # doc.mime_type. Only known-safe visual types (PDF/images) render inline; everything else is
    # forced to an octet-stream attachment. This prevents a *.pdf uploaded as text/html+<script>
    # from executing in the portal origin (stored XSS / account takeover).
    if ext in ENTERPRISE_DOC_INLINE_EXT:
        disposition = "inline"
        media_type = ENTERPRISE_DOC_EXT_MIME.get(ext, "application/octet-stream")
    else:
        disposition = "attachment"
        media_type = "application/octet-stream"
    filename = _safe_filename(doc.original_filename)
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
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


@router.post("/clients/{client_id}/documents/{document_id}/accept")
def enterprise_accept_client_document(
    client_id: int,
    document_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Human-in-the-loop override: staff accepts a document that Rilono AI red-flagged
    (after checking it themselves). Flips it to valid — with an audit trail — and runs
    the normal profile auto-fill. The AI stays the default gatekeeper; this is the escape
    hatch for its false alarms."""
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
    if doc.validation_status not in ("invalid", "error"):
        raise HTTPException(status_code=400, detail="Only documents Rilono AI flagged can be accepted manually.")
    client = _get_org_client_or_404(db, organization.id, client_id)

    staff_name = (current_user.full_name or current_user.email or "staff").strip()
    prior_message = (doc.validation_message or "").strip()
    try:
        payload = json.loads(doc.extracted_fields) if doc.extracted_fields else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    doc.validation_status = "valid"
    doc.validation_message = (
        f"Accepted by {staff_name} after manual review."
        + (f" Rilono AI had flagged: {prior_message}" if prior_message else "")
    )[:2000]
    payload["accepted_by"] = staff_name
    payload["accepted_at"] = datetime.now(dt_timezone.utc).isoformat()

    fields = payload.get("fields") or {}
    if client is not None and isinstance(fields, dict) and fields:
        payload["autofill"] = _ent_autofill_profile(db, client, doc.document_type, fields)
    doc.extracted_fields = json.dumps(payload)[:100000]

    try:
        db.add(models.EnterpriseClientNote(
            organization_id=organization.id,
            client_id=int(client_id),
            author_user_id=current_user.id,
            author_name=staff_name,
            body=(f"Manually accepted the {doc.document_type} ({doc.original_filename}) that "
                  f"Rilono AI had flagged" + (f': "{prior_message[:300]}"' if prior_message else ".")),
        ))
    except Exception:
        logger.exception("Failed to add accept audit note (document_id=%s)", document_id)
    db.commit()
    return {
        "document": _serialize_client_document(doc),
        "permissions": _enterprise_permissions_for_role(role),
    }


@router.post("/clients/{client_id}/deep-scan")
def enterprise_client_deep_scan(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Premium credit-billed action: Gemini cross-references the client's documents
    to catch mismatches/missing funds before the visa appointment."""
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    client = _get_org_client_or_404(db, organization.id, client_id)

    if not enterprise_ai.is_ai_configured():
        raise HTTPException(status_code=503, detail="Deep Scan isn't available right now.")

    # Hard-block before spending any Gemini tokens if the wallet can't cover it.
    credits.enforce_action_or_402(db, organization.id, "deep_scan")

    documents = (
        db.query(models.EnterpriseClientDocument)
        .filter(models.EnterpriseClientDocument.client_id == client.id)
        .order_by(models.EnterpriseClientDocument.created_at.asc(), models.EnterpriseClientDocument.id.asc())
        .all()
    )
    try:
        result = enterprise_ai.run_deep_scan_audit(
            db=db,
            client=client,
            organization=organization,
            documents=documents,
            current_date=datetime.utcnow().date().isoformat(),
        )
    except ValueError as exc:
        # Nothing to audit yet — do NOT charge credits.
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("Deep Scan failed (org_id=%s, client_id=%s)", organization.id, client.id)
        raise HTTPException(status_code=502, detail="The Deep Scan ran into a problem. Please try again.")

    # Charge only after a successful audit.
    txn = credits.charge_action(
        db, organization.id, "deep_scan",
        user=current_user, reference_type="client", reference_id=client.id,
        description=f"Deep Scan — {client.full_name}", commit=True,
    )

    return {
        "permissions": _enterprise_permissions_for_role(role),
        "report": result["report"],
        "risk_level": result["risk_level"],
        "documents_analyzed": result["documents_analyzed"],
        "documents_total": result.get("documents_total"),
        "documents_skipped": result.get("documents_skipped"),
        "documents_over_cap": result.get("documents_over_cap"),
        "extraction_failures": result.get("extraction_failures"),
        "credits_charged": credits.action_cost("deep_scan"),
        "wallet": credits.wallet_state(db, organization.id),
    }


# ===========================================================================
# Mock visa interview (Gemini role-plays the visa officer)
# ===========================================================================

import json as _json

ENTERPRISE_INTERVIEW_RATE_LIMIT = int(os.getenv("ENTERPRISE_INTERVIEW_RATE_LIMIT", "60"))
ENTERPRISE_INTERVIEW_RATE_WINDOW_SECONDS = int(os.getenv("ENTERPRISE_INTERVIEW_RATE_WINDOW_SECONDS", "300"))


class EnterpriseInterviewTurn(BaseModel):
    role: str = Field(..., max_length=16)
    content: str = Field(..., max_length=8000)


class EnterpriseInterviewChatRequest(BaseModel):
    message: Optional[str] = Field(default=None, max_length=4000)
    history: Optional[list[EnterpriseInterviewTurn]] = None
    start: bool = False


class EnterpriseInterviewFeedbackRequest(BaseModel):
    history: list[EnterpriseInterviewTurn] = Field(..., min_length=1)
    mode: str = Field(default="chat", max_length=12)


def _recent_client_notes(db: Session, client_id: int, limit: int = 6):
    return (
        db.query(models.EnterpriseClientNote)
        .filter(models.EnterpriseClientNote.client_id == int(client_id))
        .order_by(models.EnterpriseClientNote.created_at.desc())
        .limit(limit)
        .all()
    )


def _recent_client_documents(db: Session, client_id: int, limit: int = 12):
    """This client's uploaded documents (newest first) so the mock interview can be
    grounded in — and cross-examine against — the applicant's real evidence."""
    return (
        db.query(models.EnterpriseClientDocument)
        .filter(models.EnterpriseClientDocument.client_id == int(client_id))
        .order_by(
            models.EnterpriseClientDocument.created_at.desc(),
            models.EnterpriseClientDocument.id.desc(),
        )
        .limit(limit)
        .all()
    )


def _serialize_interview_session(s: models.EnterpriseInterviewSession, include_detail: bool = False) -> dict:
    data = {
        "id": s.id,
        "conducted_by_name": s.conducted_by_name,
        "mode": s.mode,
        "verdict": s.verdict,
        "created_at": _iso(s.created_at),
    }
    if include_detail:
        try:
            data["transcript"] = _json.loads(s.transcript) if s.transcript else []
        except Exception:
            data["transcript"] = []
        data["feedback"] = s.feedback
    return data


@router.post("/clients/{client_id}/interview/chat")
def enterprise_interview_chat(
    client_id: int,
    payload: EnterpriseInterviewChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    client = _get_org_client_or_404(db, organization.id, client_id)
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.interview", limit=ENTERPRISE_INTERVIEW_RATE_LIMIT,
        window_seconds=ENTERPRISE_INTERVIEW_RATE_WINDOW_SECONDS, extra_key=str(current_user.id),
    )
    if not enterprise_interview.is_ai_configured():
        raise HTTPException(status_code=503, detail="The mock interview isn't available right now.")

    is_start = bool(payload.start)
    # A STAFF-run interview is a preview/test tool — the self-serve link a student takes
    # is the real product. Staff get a few free previews per org, then it costs the normal
    # mock_interview price. Hard-block before any tokens are spent if unaffordable.
    if is_start:
        credits.enforce_staff_interview_or_402(db, organization.id)

    history = [t.model_dump() for t in (payload.history or [])]
    try:
        turn = enterprise_interview.run_interview_turn(
            client=client,
            organization=organization,
            recent_notes=_recent_client_notes(db, client.id),
            documents=_recent_client_documents(db, client.id),
            history=history,
            message=payload.message or "",
            is_start=is_start,
        )
    except Exception:
        logger.exception("Mock interview turn failed (org_id=%s, client_id=%s)", organization.id, client.id)
        raise HTTPException(status_code=502, detail="The interviewer ran into a problem. Please try again.")

    response_payload = {
        "reply": turn["reply"],
        "finished": turn["finished"],
        "decision": turn["decision"],
        "permissions": _enterprise_permissions_for_role(role),
    }
    if is_start:
        meter = credits.consume_staff_interview(
            db, organization.id,
            user=current_user, reference_id=client.id,
            description=f"Mock interview (staff preview) — {client.full_name}",
        )
        response_payload["credits_charged"] = meter["charged"]
        response_payload["was_preview"] = meter["was_preview"]
        response_payload["previews_remaining"] = meter["previews_remaining"]
        response_payload["wallet"] = credits.wallet_state(db, organization.id)
    return response_payload


@router.post("/clients/{client_id}/interview/feedback")
def enterprise_interview_feedback(
    client_id: int,
    payload: EnterpriseInterviewFeedbackRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    client = _get_org_client_or_404(db, organization.id, client_id)
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.interview", limit=ENTERPRISE_INTERVIEW_RATE_LIMIT,
        window_seconds=ENTERPRISE_INTERVIEW_RATE_WINDOW_SECONDS, extra_key=str(current_user.id),
    )
    if not enterprise_interview.is_ai_configured():
        raise HTTPException(status_code=503, detail="Feedback isn't available right now.")

    history = [t.model_dump() for t in payload.history]
    try:
        feedback = enterprise_interview.generate_interview_feedback(
            client=client, organization=organization, history=history,
            documents=_recent_client_documents(db, client.id),
        )
    except Exception:
        logger.exception("Mock interview feedback failed (org_id=%s, client_id=%s)", organization.id, client.id)
        raise HTTPException(status_code=502, detail="Could not generate feedback. Please try again.")

    verdict = enterprise_interview.extract_verdict(feedback)
    session = models.EnterpriseInterviewSession(
        organization_id=organization.id,
        client_id=client.id,
        conducted_by_user_id=current_user.id,
        conducted_by_name=current_user.full_name or current_user.email,
        mode=("voice" if payload.mode == "voice" else "chat"),
        transcript=_json.dumps(history)[:400000],
        feedback=feedback,
        verdict=verdict,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return {
        "feedback": feedback,
        "verdict": verdict,
        "session": _serialize_interview_session(session),
        "permissions": _enterprise_permissions_for_role(role),
    }


@router.get("/clients/{client_id}/interview/sessions")
def enterprise_interview_sessions(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    client = _get_org_client_or_404(db, organization.id, client_id)
    rows = (
        db.query(models.EnterpriseInterviewSession)
        .filter(models.EnterpriseInterviewSession.client_id == client.id)
        .order_by(models.EnterpriseInterviewSession.created_at.desc(), models.EnterpriseInterviewSession.id.desc())
        .all()
    )
    return {
        "permissions": _enterprise_permissions_for_role(role),
        "ai_enabled": enterprise_interview.is_ai_configured(),
        "sessions": [_serialize_interview_session(s) for s in rows],
    }


@router.get("/clients/{client_id}/interview/sessions/{session_id}")
def enterprise_interview_session_detail(
    client_id: int,
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    client = _get_org_client_or_404(db, organization.id, client_id)
    s = (
        db.query(models.EnterpriseInterviewSession)
        .filter(
            models.EnterpriseInterviewSession.id == int(session_id),
            models.EnterpriseInterviewSession.client_id == client.id,
            models.EnterpriseInterviewSession.organization_id == organization.id,
        )
        .first()
    )
    if not s:
        raise HTTPException(status_code=404, detail="Interview session not found.")
    return {
        "permissions": _enterprise_permissions_for_role(role),
        "session": _serialize_interview_session(s, include_detail=True),
    }


# ===========================================================================
# Send mock interview to client via secure email link (self-serve)
# ===========================================================================

import secrets as _secrets

ENTERPRISE_INTERVIEW_INVITE_EXPIRES_DAYS = int(os.getenv("ENTERPRISE_INTERVIEW_INVITE_EXPIRES_DAYS", "30"))
ENTERPRISE_INTERVIEW_SESSION_HOURS = int(os.getenv("ENTERPRISE_INTERVIEW_SESSION_HOURS", "3"))
ENTERPRISE_INTERVIEW_CODE_EXPIRES_MIN = int(os.getenv("ENTERPRISE_INTERVIEW_CODE_EXPIRES_MIN", "15"))
ENTERPRISE_INTERVIEW_CODE_MAX_ATTEMPTS = int(os.getenv("ENTERPRISE_INTERVIEW_CODE_MAX_ATTEMPTS", "6"))
ENTERPRISE_INTERVIEW_INVITE_MAX_COUNT = int(os.getenv("ENTERPRISE_INTERVIEW_INVITE_MAX_COUNT", "20"))
ENTERPRISE_PUBLIC_RATE_LIMIT = int(os.getenv("ENTERPRISE_PUBLIC_INTERVIEW_RATE_LIMIT", "30"))
ENTERPRISE_PUBLIC_RATE_WINDOW = int(os.getenv("ENTERPRISE_PUBLIC_INTERVIEW_RATE_WINDOW", "300"))
ENTERPRISE_CODE_RATE_LIMIT = int(os.getenv("ENTERPRISE_INTERVIEW_CODE_RATE_LIMIT", "6"))
ENTERPRISE_CODE_RATE_WINDOW = int(os.getenv("ENTERPRISE_INTERVIEW_CODE_RATE_WINDOW", "900"))


class EnterpriseInterviewInviteRequest(BaseModel):
    allowed_count: int = Field(default=3, ge=1, le=ENTERPRISE_INTERVIEW_INVITE_MAX_COUNT)


class PublicInterviewVerifyRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=10)


class PublicInterviewChatRequest(BaseModel):
    session_token: str = Field(..., min_length=10, max_length=4000)
    message: Optional[str] = Field(default=None, max_length=4000)
    history: Optional[list[EnterpriseInterviewTurn]] = None
    start: bool = False


class PublicInterviewFeedbackRequest(BaseModel):
    session_token: str = Field(..., min_length=10, max_length=4000)
    history: list[EnterpriseInterviewTurn] = Field(..., min_length=1)
    mode: str = Field(default="chat", max_length=12)
    decision: Optional[str] = Field(default=None, max_length=20)


def _mask_email(email: str) -> str:
    e = (email or "").strip()
    if "@" not in e:
        return e
    local, dom = e.split("@", 1)
    ml = (local[0] + "*") if len(local) <= 2 else (local[0] + "*" * (len(local) - 2) + local[-1])
    return f"{ml}@{dom}"


def _build_interview_invite_url(subdomain_slug, token: str, request: Request | None) -> str:
    subdomain = str(subdomain_slug or "").strip().lower()
    base = None
    if subdomain:
        host = f"{subdomain}.{ENTERPRISE_ROOT_DOMAIN}"
        port = _request_port_for_local_enterprise_url(request)
        if port:
            host = f"{host}:{port}"
        base = f"{ENTERPRISE_PORTAL_SCHEME}://{host}"
    if not base:
        base = ENTERPRISE_PASSWORD_SETUP_BASE_URL
    return f"{base.rstrip('/')}/interview/{token}"


def _interview_invite_remaining(invite: models.EnterpriseInterviewInvite) -> int:
    return max(0, int(invite.allowed_count or 0) - int(invite.used_count or 0))


def _interview_invite_is_live(invite: models.EnterpriseInterviewInvite) -> bool:
    if invite.revoked:
        return False
    if invite.expires_at:
        exp = invite.expires_at.replace(tzinfo=None) if getattr(invite.expires_at, "tzinfo", None) else invite.expires_at
        if exp < datetime.utcnow():
            return False
    return True


def _serialize_invite_status(invite: models.EnterpriseInterviewInvite | None) -> Optional[dict]:
    if not invite:
        return None
    started = int(invite.used_count or 0)
    completed = int(getattr(invite, "completed_count", 0) or 0)
    return {
        "id": invite.id,
        "email": invite.email,
        "allowed_count": invite.allowed_count,
        "used_count": invite.used_count,
        "started_count": started,
        "completed_count": completed,
        "last_completed_at": _iso(getattr(invite, "last_completed_at", None)),
        "remaining": _interview_invite_remaining(invite),
        "revoked": bool(invite.revoked),
        "live": _interview_invite_is_live(invite),
        "created_by_name": invite.created_by_name,
        "created_at": _iso(invite.created_at),
        "expires_at": _iso(invite.expires_at),
    }


def _latest_client_invite(db: Session, organization_id: int, client_id: int):
    return (
        db.query(models.EnterpriseInterviewInvite)
        .filter(
            models.EnterpriseInterviewInvite.organization_id == int(organization_id),
            models.EnterpriseInterviewInvite.client_id == int(client_id),
        )
        .order_by(models.EnterpriseInterviewInvite.created_at.desc(), models.EnterpriseInterviewInvite.id.desc())
        .first()
    )


def _issue_interview_session_token(invite_id: int) -> str:
    return create_access_token(
        data={"sub": f"entiv:{int(invite_id)}", "scope": "ent_interview", "inv": int(invite_id)},
        expires_delta=timedelta(hours=ENTERPRISE_INTERVIEW_SESSION_HOURS),
    )


def _decode_interview_session_token(token: str) -> int:
    try:
        payload = jose_jwt.decode(token, AUTH_SECRET_KEY, algorithms=[AUTH_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Your interview session has expired. Please verify your email again.")
    if payload.get("scope") != "ent_interview" or not payload.get("inv"):
        raise HTTPException(status_code=401, detail="Invalid interview session.")
    return int(payload["inv"])


def _public_invite_or_404(db: Session, token: str) -> models.EnterpriseInterviewInvite:
    token_hash = hash_token((token or "").strip())
    invite = (
        db.query(models.EnterpriseInterviewInvite)
        .filter(models.EnterpriseInterviewInvite.token_hash == token_hash)
        .first()
    )
    if not invite or not _interview_invite_is_live(invite):
        raise HTTPException(status_code=404, detail="This interview link is invalid or has expired.")
    return invite


# ---- Staff: create / view / revoke the invite -----------------------------

@router.post("/clients/{client_id}/interview/invite")
def enterprise_create_interview_invite(
    client_id: int,
    payload: EnterpriseInterviewInviteRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    client = _get_org_client_or_404(db, organization.id, client_id)
    email = (client.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Add an email to this client before sending an interview link.")

    # Don't send a link the wallet can't fund — otherwise the client receives the
    # email, tries to start, and hits a confusing "contact your consultancy" wall.
    # Require enough credits up-front to cover every interview this link offers.
    credits.enforce_units_or_402(db, organization.id, "mock_interview", int(payload.allowed_count))

    # Supersede any prior invites for this client.
    db.query(models.EnterpriseInterviewInvite).filter(
        models.EnterpriseInterviewInvite.client_id == client.id,
        models.EnterpriseInterviewInvite.revoked.is_(False),
    ).update({"revoked": True})

    raw_token = generate_verification_token()
    invite = models.EnterpriseInterviewInvite(
        organization_id=organization.id,
        client_id=client.id,
        token_hash=hash_token(raw_token),
        email=email,
        allowed_count=int(payload.allowed_count),
        used_count=0,
        expires_at=datetime.utcnow() + timedelta(days=ENTERPRISE_INTERVIEW_INVITE_EXPIRES_DAYS),
        created_by_user_id=current_user.id,
        created_by_name=current_user.full_name or current_user.email,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    link = _build_interview_invite_url(organization.subdomain_slug, raw_token, request)
    sent, _mid, err = send_enterprise_interview_invite_email(
        to_email=email,
        client_name=client.full_name,
        organization_name=organization.company_name,
        interview_url=link,
        allowed_count=invite.allowed_count,
        destination_country=client.destination_country_name,
        visa_type=client.visa_type,
        logo_url=_resolve_enterprise_logo_url(organization),
    )
    message = (f"Sent {invite.allowed_count} mock interview(s) to {email}."
               if sent else f"Invite created but the email could not be sent right now. {err or ''}".strip())
    return {
        "message": message,
        "email_sent": sent,
        "invite": _serialize_invite_status(invite),
        "permissions": _enterprise_permissions_for_role(role),
    }


@router.get("/clients/{client_id}/interview/invite")
def enterprise_get_interview_invite(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    client = _get_org_client_or_404(db, organization.id, client_id)
    invite = _latest_client_invite(db, organization.id, client.id)
    return {
        "permissions": _enterprise_permissions_for_role(role),
        "invite": _serialize_invite_status(invite),
    }


@router.post("/clients/{client_id}/interview/invite/revoke")
def enterprise_revoke_interview_invite(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    client = _get_org_client_or_404(db, organization.id, client_id)
    db.query(models.EnterpriseInterviewInvite).filter(
        models.EnterpriseInterviewInvite.client_id == client.id,
        models.EnterpriseInterviewInvite.revoked.is_(False),
    ).update({"revoked": True})
    db.commit()
    return {"message": "Interview link revoked.", "permissions": _enterprise_permissions_for_role(role)}


# ---- Public (client-facing, token-scoped, no staff auth) ------------------

@router.get("/public/interview/{token}")
def public_interview_info(token: str, db: Session = Depends(get_db)):
    invite = _public_invite_or_404(db, token)
    client = db.query(models.EnterpriseClient).filter(models.EnterpriseClient.id == invite.client_id).first()
    org = db.query(models.EnterpriseOrganization).filter(models.EnterpriseOrganization.id == invite.organization_id).first()
    if not client or not org:
        raise HTTPException(status_code=404, detail="This interview link is no longer available.")
    remaining = _interview_invite_remaining(invite)
    return {
        "organization_name": org.company_name,
        "logo_url": _resolve_enterprise_logo_url(org),
        "client_first_name": (client.full_name or "there").split(" ")[0],
        "destination_country": client.destination_country_name,
        "visa_type": client.visa_type,
        "masked_email": _mask_email(invite.email),
        "remaining": remaining,
        "exhausted": remaining <= 0,
    }


@router.post("/public/interview/{token}/send-code")
def public_interview_send_code(token: str, request: Request, db: Session = Depends(get_db)):
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.interview_code",
        limit=ENTERPRISE_CODE_RATE_LIMIT, window_seconds=ENTERPRISE_CODE_RATE_WINDOW, extra_key=hash_token(token)[:16],
    )
    invite = _public_invite_or_404(db, token)
    org = db.query(models.EnterpriseOrganization).filter(models.EnterpriseOrganization.id == invite.organization_id).first()
    client = db.query(models.EnterpriseClient).filter(models.EnterpriseClient.id == invite.client_id).first()
    if not org or not client:
        raise HTTPException(status_code=404, detail="This interview link is no longer available.")

    code = f"{_secrets.randbelow(900000) + 100000:06d}"
    invite.code_hash = hash_token(code)
    invite.code_expires_at = datetime.utcnow() + timedelta(minutes=ENTERPRISE_INTERVIEW_CODE_EXPIRES_MIN)
    invite.code_attempts = 0
    db.commit()

    sent, _mid, err = send_enterprise_interview_code_email(
        to_email=invite.email, client_name=client.full_name, organization_name=org.company_name, code=code,
    )
    if not sent:
        logger.warning("Interview code email failed for invite %s: %s", invite.id, err)
    return {"sent": bool(sent), "masked_email": _mask_email(invite.email)}


@router.post("/public/interview/{token}/verify")
def public_interview_verify(token: str, payload: PublicInterviewVerifyRequest, request: Request, db: Session = Depends(get_db)):
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.interview_verify",
        limit=ENTERPRISE_PUBLIC_RATE_LIMIT, window_seconds=ENTERPRISE_PUBLIC_RATE_WINDOW, extra_key=hash_token(token)[:16],
    )
    invite = _public_invite_or_404(db, token)
    if not invite.code_hash or not invite.code_expires_at:
        raise HTTPException(status_code=400, detail="Please request a verification code first.")
    code_exp = invite.code_expires_at.replace(tzinfo=None) if getattr(invite.code_expires_at, "tzinfo", None) else invite.code_expires_at
    if code_exp < datetime.utcnow():
        raise HTTPException(status_code=400, detail="That code has expired. Please request a new one.")
    if int(invite.code_attempts or 0) >= ENTERPRISE_INTERVIEW_CODE_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts. Please request a new code.")

    invite.code_attempts = int(invite.code_attempts or 0) + 1
    if hash_token((payload.code or "").strip()) != invite.code_hash:
        db.commit()
        raise HTTPException(status_code=400, detail="That code is incorrect. Please try again.")

    # Verified — consume the code and issue a short-lived interview session token.
    invite.code_hash = None
    invite.code_expires_at = None
    db.commit()
    client = db.query(models.EnterpriseClient).filter(models.EnterpriseClient.id == invite.client_id).first()
    return {
        "session_token": _issue_interview_session_token(invite.id),
        "client_first_name": (client.full_name or "there").split(" ")[0] if client else "there",
        "destination_country": client.destination_country_name if client else "",
        "visa_type": client.visa_type if client else "",
        "remaining": _interview_invite_remaining(invite),
        "session_hours": ENTERPRISE_INTERVIEW_SESSION_HOURS,
    }


def _public_load_invite_context(db: Session, session_token: str):
    invite_id = _decode_interview_session_token(session_token)
    invite = db.query(models.EnterpriseInterviewInvite).filter(models.EnterpriseInterviewInvite.id == invite_id).first()
    if not invite or not _interview_invite_is_live(invite):
        raise HTTPException(status_code=401, detail="This interview link is no longer active.")
    client = db.query(models.EnterpriseClient).filter(models.EnterpriseClient.id == invite.client_id).first()
    org = db.query(models.EnterpriseOrganization).filter(models.EnterpriseOrganization.id == invite.organization_id).first()
    if not client or not org:
        raise HTTPException(status_code=404, detail="This interview is no longer available.")
    return invite, client, org


@router.post("/public/interview/chat")
def public_interview_chat(payload: PublicInterviewChatRequest, request: Request, db: Session = Depends(get_db)):
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.interview_public",
        limit=ENTERPRISE_PUBLIC_RATE_LIMIT, window_seconds=ENTERPRISE_PUBLIC_RATE_WINDOW,
    )
    if not enterprise_interview.is_ai_configured():
        raise HTTPException(status_code=503, detail="The mock interview isn't available right now.")
    invite, client, org = _public_load_invite_context(db, payload.session_token)

    if payload.start:
        if _interview_invite_remaining(invite) <= 0:
            raise HTTPException(status_code=403, detail="You've used all your mock interviews for this link.")
        # Meter the org's wallet — a self-serve interview costs the same 20 credits as a
        # staff-run one, so the "send to student" links can't be used to run Gemini for free.
        if not credits.can_afford(db, org.id, "mock_interview"):
            raise HTTPException(
                status_code=402,
                detail="This mock interview isn't available right now. Please contact your consultancy.",
            )
        invite.used_count = int(invite.used_count or 0) + 1  # a start consumes one interview
        db.commit()
        credits.charge_action(
            db, org.id, "mock_interview",
            reference_type="client", reference_id=client.id,
            description=f"Mock interview (self-serve) — {client.full_name}", commit=True,
        )

    history = [t.model_dump() for t in (payload.history or [])]
    try:
        turn = enterprise_interview.run_interview_turn(
            client=client, organization=org, recent_notes=[],  # never leak staff notes to the client
            documents=_recent_client_documents(db, client.id),  # the applicant's own documents
            history=history, message=payload.message or "", is_start=bool(payload.start),
        )
    except Exception:
        logger.exception("Public interview turn failed (invite=%s)", invite.id)
        raise HTTPException(status_code=502, detail="The interviewer ran into a problem. Please try again.")
    return {
        "reply": turn["reply"],
        "finished": turn["finished"],
        "decision": turn["decision"],
        "remaining": _interview_invite_remaining(invite),
    }


@router.post("/public/interview/feedback")
def public_interview_feedback(payload: PublicInterviewFeedbackRequest, request: Request, db: Session = Depends(get_db)):
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.interview_public",
        limit=ENTERPRISE_PUBLIC_RATE_LIMIT, window_seconds=ENTERPRISE_PUBLIC_RATE_WINDOW,
    )
    if not enterprise_interview.is_ai_configured():
        raise HTTPException(status_code=503, detail="Feedback isn't available right now.")
    invite, client, org = _public_load_invite_context(db, payload.session_token)

    history = [t.model_dump() for t in payload.history]
    raw_decision = (payload.decision or "").strip().lower()
    officer_decision = raw_decision if raw_decision in ("approved", "refused") else None
    try:
        feedback = enterprise_interview.generate_interview_feedback(
            client=client, organization=org, history=history, officer_decision=officer_decision,
            documents=_recent_client_documents(db, client.id),  # the applicant's own documents
        )
    except Exception:
        logger.exception("Public interview feedback failed (invite=%s)", invite.id)
        raise HTTPException(status_code=502, detail="Could not generate feedback. Please try again.")

    decision_label = {"approved": "Approved", "refused": "Refused"}.get(officer_decision)
    verdict = enterprise_interview.extract_verdict(feedback)
    # Keep the officer's decision separate from the coaching feedback so it isn't
    # shown twice in the UI/email; fold it into the *stored* copy for staff.
    stored_feedback = (
        f"**Officer's decision (simulated): Visa {decision_label}**\n\n" + feedback
        if decision_label else feedback
    )
    session = models.EnterpriseInterviewSession(
        organization_id=org.id, client_id=client.id, conducted_by_user_id=None,
        conducted_by_name=f"{client.full_name} (self · via link)",
        mode=("voice" if payload.mode == "voice" else "chat"),
        transcript=_json.dumps(history)[:400000], feedback=stored_feedback, verdict=verdict,
    )
    db.add(session)
    # Mark the invite as having a completed interview so staff can see the student
    # actually finished it (used_count only tells us they *started*).
    invite.completed_count = int(invite.completed_count or 0) + 1
    invite.last_completed_at = datetime.utcnow()
    db.commit()

    # Tell the whole team (actor is the external student, so nobody is excluded).
    notif.notify_org(
        db, org.id, type="interview_completed",
        title=f"🎤 {client.full_name} completed their mock interview",
        body=(f"Verdict: {verdict}" if verdict else None),
        reference_type="client", reference_id=client.id, commit=True,
    )

    # Email the report to the applicant who took the interview (best-effort).
    emailed = False
    try:
        emailed, _mid, err = send_enterprise_interview_report_email(
            to_email=invite.email,
            client_name=client.full_name,
            organization_name=org.company_name,
            destination_country=client.destination_country_name,
            visa_type=client.visa_type,
            decision_label=decision_label,
            feedback_markdown=feedback,
            logo_url=_resolve_enterprise_logo_url(org),
        )
        if not emailed:
            logger.warning("Interview report email failed for invite %s: %s", invite.id, err)
    except Exception:
        logger.exception("Interview report email crashed (invite=%s)", invite.id)

    return {
        "feedback": feedback,
        "verdict": verdict,
        "decision": decision_label,
        "remaining": _interview_invite_remaining(invite),
        "emailed": emailed,
        "masked_email": _mask_email(invite.email),
    }


# ===========================================================================
# Secure document requests — email a client a tokenized, OTP-verified link so
# they can upload the specific documents staff asked for. Files land in the same
# private encrypted storage as staff uploads. Mirrors the interview-invite model.
# ===========================================================================

ENTERPRISE_DOCREQ_EXPIRES_DAYS = int(os.getenv("ENTERPRISE_DOCREQ_EXPIRES_DAYS", "30"))
ENTERPRISE_DOCREQ_SESSION_HOURS = int(os.getenv("ENTERPRISE_DOCREQ_SESSION_HOURS", "6"))
ENTERPRISE_DOCREQ_MAX_TYPES = int(os.getenv("ENTERPRISE_DOCREQ_MAX_TYPES", "20"))


class EnterpriseDocumentRequestCreate(BaseModel):
    document_types: list[str] = Field(..., min_length=1, max_length=ENTERPRISE_DOCREQ_MAX_TYPES)
    message: Optional[str] = Field(default=None, max_length=2000)


class PublicDocRequestVerifyRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=10)


def _build_document_request_url(subdomain_slug, token: str, request: Request | None) -> str:
    subdomain = str(subdomain_slug or "").strip().lower()
    base = None
    if subdomain:
        host = f"{subdomain}.{ENTERPRISE_ROOT_DOMAIN}"
        port = _request_port_for_local_enterprise_url(request)
        if port:
            host = f"{host}:{port}"
        base = f"{ENTERPRISE_PORTAL_SCHEME}://{host}"
    if not base:
        base = ENTERPRISE_PASSWORD_SETUP_BASE_URL
    return f"{base.rstrip('/')}/upload/{token}"


def _docreq_is_live(req: models.EnterpriseDocumentRequest) -> bool:
    if req.revoked:
        return False
    if req.expires_at:
        exp = req.expires_at.replace(tzinfo=None) if getattr(req.expires_at, "tzinfo", None) else req.expires_at
        if exp < datetime.utcnow():
            return False
    return True


def _recompute_docreq_status(req: models.EnterpriseDocumentRequest) -> None:
    items = req.items or []
    received = sum(1 for i in items if i.status == "received")
    if received == 0:
        req.status = "pending"
        req.completed_at = None
    elif received >= len(items):
        req.status = "completed"
        if not req.completed_at:
            req.completed_at = datetime.utcnow()
    else:
        req.status = "partial"
        req.completed_at = None


def _serialize_docreq_item(item: models.EnterpriseDocumentRequestItem) -> dict:
    return {
        "id": item.id,
        "document_type": item.document_type,
        "status": item.status,
        "received": item.status == "received",
        "received_at": _iso(item.received_at),
        "document_id": item.document_id,
    }


def _serialize_docreq(req: models.EnterpriseDocumentRequest | None) -> Optional[dict]:
    if not req:
        return None
    items = list(req.items or [])
    received = sum(1 for i in items if i.status == "received")
    return {
        "id": req.id,
        "email": req.email,
        "message": req.message,
        "status": req.status,
        "revoked": bool(req.revoked),
        "live": _docreq_is_live(req),
        "total": len(items),
        "received": received,
        "pending": len(items) - received,
        "items": [_serialize_docreq_item(i) for i in items],
        "created_by_name": req.created_by_name,
        "created_at": _iso(req.created_at),
        "expires_at": _iso(req.expires_at),
        "completed_at": _iso(req.completed_at),
    }


def _latest_client_docreq(db: Session, organization_id: int, client_id: int):
    return (
        db.query(models.EnterpriseDocumentRequest)
        .filter(
            models.EnterpriseDocumentRequest.organization_id == int(organization_id),
            models.EnterpriseDocumentRequest.client_id == int(client_id),
        )
        .order_by(models.EnterpriseDocumentRequest.created_at.desc(), models.EnterpriseDocumentRequest.id.desc())
        .first()
    )


def _public_docreq_or_404(db: Session, token: str) -> models.EnterpriseDocumentRequest:
    token_hash = hash_token((token or "").strip())
    req = (
        db.query(models.EnterpriseDocumentRequest)
        .filter(models.EnterpriseDocumentRequest.token_hash == token_hash)
        .first()
    )
    if not req or not _docreq_is_live(req):
        raise HTTPException(status_code=404, detail="This upload link is invalid or has expired.")
    return req


def _issue_docreq_session_token(request_id: int) -> str:
    return create_access_token(
        data={"sub": f"entdr:{int(request_id)}", "scope": "ent_docreq", "dr": int(request_id)},
        expires_delta=timedelta(hours=ENTERPRISE_DOCREQ_SESSION_HOURS),
    )


def _decode_docreq_session_token(token: str) -> int:
    try:
        payload = jose_jwt.decode(token, AUTH_SECRET_KEY, algorithms=[AUTH_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Your upload session has expired. Please verify your email again.")
    if payload.get("scope") != "ent_docreq" or not payload.get("dr"):
        raise HTTPException(status_code=401, detail="Invalid upload session.")
    return int(payload["dr"])


def _public_load_docreq_context(db: Session, session_token: str):
    request_id = _decode_docreq_session_token(session_token)
    req = (
        db.query(models.EnterpriseDocumentRequest)
        .filter(models.EnterpriseDocumentRequest.id == request_id)
        .first()
    )
    if not req or not _docreq_is_live(req):
        raise HTTPException(status_code=401, detail="This upload link is no longer active.")
    client = db.query(models.EnterpriseClient).filter(models.EnterpriseClient.id == req.client_id).first()
    org = db.query(models.EnterpriseOrganization).filter(models.EnterpriseOrganization.id == req.organization_id).first()
    if not client or not org:
        raise HTTPException(status_code=404, detail="This upload link is no longer available.")
    return req, client, org


# ---- Staff: create / view / revoke the document request -------------------

@router.post("/clients/{client_id}/document-requests")
def enterprise_create_document_request(
    client_id: int,
    payload: EnterpriseDocumentRequestCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    client = _get_org_client_or_404(db, organization.id, client_id)
    email = (client.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Add an email to this client before requesting documents.")

    # Normalize + de-duplicate the requested document types (preserve order).
    seen: set[str] = set()
    doc_types: list[str] = []
    for raw in payload.document_types:
        normalized = catalog.normalize_document_type(raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            doc_types.append(normalized)
    if not doc_types:
        raise HTTPException(status_code=400, detail="Choose at least one document to request.")

    # Supersede any prior active requests for this client.
    db.query(models.EnterpriseDocumentRequest).filter(
        models.EnterpriseDocumentRequest.client_id == client.id,
        models.EnterpriseDocumentRequest.revoked.is_(False),
    ).update({"revoked": True})

    raw_token = generate_verification_token()
    req = models.EnterpriseDocumentRequest(
        organization_id=organization.id,
        client_id=client.id,
        token_hash=hash_token(raw_token),
        email=email,
        message=(payload.message or "").strip() or None,
        status="pending",
        expires_at=datetime.utcnow() + timedelta(days=ENTERPRISE_DOCREQ_EXPIRES_DAYS),
        created_by_user_id=current_user.id,
        created_by_name=current_user.full_name or current_user.email,
    )
    db.add(req)
    db.flush()
    for dt in doc_types:
        db.add(models.EnterpriseDocumentRequestItem(
            request_id=req.id,
            organization_id=organization.id,
            document_type=dt,
            status="pending",
        ))
    db.commit()
    db.refresh(req)

    link = _build_document_request_url(organization.subdomain_slug, raw_token, request)
    sent, _mid, err = send_enterprise_document_request_email(
        to_email=email,
        client_name=client.full_name,
        organization_name=organization.company_name,
        upload_url=link,
        document_types=doc_types,
        message=req.message,
        logo_url=_resolve_enterprise_logo_url(organization),
    )
    message = (f"Document request sent to {email}."
               if sent else f"Request created but the email could not be sent right now. {err or ''}".strip())
    return {
        "message": message,
        "email_sent": sent,
        "request": _serialize_docreq(req),
        "permissions": _enterprise_permissions_for_role(role),
    }


@router.get("/clients/{client_id}/document-requests")
def enterprise_get_document_request(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    client = _get_org_client_or_404(db, organization.id, client_id)
    req = _latest_client_docreq(db, organization.id, client.id)
    return {
        "permissions": _enterprise_permissions_for_role(role),
        "document_types": list(catalog.STUDENT_DOCUMENT_TYPES),
        "request": _serialize_docreq(req),
    }


@router.post("/clients/{client_id}/document-requests/revoke")
def enterprise_revoke_document_request(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    client = _get_org_client_or_404(db, organization.id, client_id)
    db.query(models.EnterpriseDocumentRequest).filter(
        models.EnterpriseDocumentRequest.client_id == client.id,
        models.EnterpriseDocumentRequest.revoked.is_(False),
    ).update({"revoked": True})
    db.commit()
    return {"message": "Document request revoked.", "permissions": _enterprise_permissions_for_role(role)}


# ---- Public (client-facing, token-scoped, no staff auth) ------------------

@router.get("/public/document-request/{token}")
def public_document_request_info(token: str, db: Session = Depends(get_db)):
    req = _public_docreq_or_404(db, token)
    client = db.query(models.EnterpriseClient).filter(models.EnterpriseClient.id == req.client_id).first()
    org = db.query(models.EnterpriseOrganization).filter(models.EnterpriseOrganization.id == req.organization_id).first()
    if not client or not org:
        raise HTTPException(status_code=404, detail="This upload link is no longer available.")
    return {
        "organization_name": org.company_name,
        "logo_url": _resolve_enterprise_logo_url(org),
        "client_first_name": (client.full_name or "there").split(" ")[0],
        "masked_email": _mask_email(req.email),
        "message": req.message,
        "status": req.status,
        "items": [_serialize_docreq_item(i) for i in (req.items or [])],
        "expires_at": _iso(req.expires_at),
    }


@router.post("/public/document-request/{token}/send-code")
def public_document_request_send_code(token: str, request: Request, db: Session = Depends(get_db)):
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.docreq_code",
        limit=ENTERPRISE_CODE_RATE_LIMIT, window_seconds=ENTERPRISE_CODE_RATE_WINDOW, extra_key=hash_token(token)[:16],
    )
    req = _public_docreq_or_404(db, token)
    org = db.query(models.EnterpriseOrganization).filter(models.EnterpriseOrganization.id == req.organization_id).first()
    client = db.query(models.EnterpriseClient).filter(models.EnterpriseClient.id == req.client_id).first()
    if not org or not client:
        raise HTTPException(status_code=404, detail="This upload link is no longer available.")

    code = f"{_secrets.randbelow(900000) + 100000:06d}"
    req.code_hash = hash_token(code)
    req.code_expires_at = datetime.utcnow() + timedelta(minutes=ENTERPRISE_INTERVIEW_CODE_EXPIRES_MIN)
    req.code_attempts = 0
    db.commit()

    sent, _mid, err = send_enterprise_document_request_code_email(
        to_email=req.email, client_name=client.full_name, organization_name=org.company_name, code=code,
    )
    if not sent:
        logger.warning("Document request code email failed for request %s: %s", req.id, err)
    return {"sent": bool(sent), "masked_email": _mask_email(req.email)}


@router.post("/public/document-request/{token}/verify")
def public_document_request_verify(token: str, payload: PublicDocRequestVerifyRequest, request: Request, db: Session = Depends(get_db)):
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.docreq_verify",
        limit=ENTERPRISE_PUBLIC_RATE_LIMIT, window_seconds=ENTERPRISE_PUBLIC_RATE_WINDOW, extra_key=hash_token(token)[:16],
    )
    req = _public_docreq_or_404(db, token)
    if not req.code_hash or not req.code_expires_at:
        raise HTTPException(status_code=400, detail="Please request a verification code first.")
    code_exp = req.code_expires_at.replace(tzinfo=None) if getattr(req.code_expires_at, "tzinfo", None) else req.code_expires_at
    if code_exp < datetime.utcnow():
        raise HTTPException(status_code=400, detail="That code has expired. Please request a new one.")
    if int(req.code_attempts or 0) >= ENTERPRISE_INTERVIEW_CODE_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts. Please request a new code.")

    req.code_attempts = int(req.code_attempts or 0) + 1
    if hash_token((payload.code or "").strip()) != req.code_hash:
        db.commit()
        raise HTTPException(status_code=400, detail="That code is incorrect. Please try again.")

    # Verified — consume the code and issue a short-lived upload session token.
    req.code_hash = None
    req.code_expires_at = None
    db.commit()
    client = db.query(models.EnterpriseClient).filter(models.EnterpriseClient.id == req.client_id).first()
    return {
        "session_token": _issue_docreq_session_token(req.id),
        "client_first_name": (client.full_name or "there").split(" ")[0] if client else "there",
        "message": req.message,
        "items": [_serialize_docreq_item(i) for i in (req.items or [])],
        "session_hours": ENTERPRISE_DOCREQ_SESSION_HOURS,
    }


@router.post("/public/document-request/upload")
async def public_document_request_upload(
    request: Request,
    session_token: str = Form(...),
    item_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.docreq_upload",
        limit=ENTERPRISE_PUBLIC_RATE_LIMIT, window_seconds=ENTERPRISE_PUBLIC_RATE_WINDOW,
    )
    req, client, org = _public_load_docreq_context(db, session_token)

    item = (
        db.query(models.EnterpriseDocumentRequestItem)
        .filter(
            models.EnterpriseDocumentRequestItem.id == int(item_id),
            models.EnterpriseDocumentRequestItem.request_id == req.id,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="That document is not part of this request.")

    if not enterprise_storage.is_configured():
        raise HTTPException(status_code=503, detail="Document upload is not available right now. Please contact your consultancy.")

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

    storage_key = f"enterprise/{org.id}/clients/{client.id}/{uuid.uuid4().hex}{ext}"
    try:
        enterprise_storage.store_document(storage_key, data, content_type=file.content_type)
    except Exception:
        logger.exception("Failed to store client-uploaded document (org_id=%s, client_id=%s)", org.id, client.id)
        raise HTTPException(status_code=502, detail="Could not store the document right now. Please try again.")

    doc = models.EnterpriseClientDocument(
        organization_id=org.id,
        client_id=client.id,
        document_type=item.document_type,
        original_filename=original,
        storage_key=storage_key,
        file_size=len(data),
        mime_type=(file.content_type or None),
        uploaded_by_user_id=None,
        uploaded_by_name=f"{client.full_name} (uploaded via secure link)",
    )
    db.add(doc)
    db.flush()

    item.document_id = doc.id
    item.status = "received"
    item.received_at = datetime.utcnow()
    was_completed = bool(req.completed_at)
    _recompute_docreq_status(req)
    db.commit()
    db.refresh(req)

    # Notify the team when the request BECOMES complete (not on every file — limited comms).
    if req.completed_at and not was_completed:
        notif.notify_org(
            db, org.id, type="docs_submitted",
            title=f"📁 {client.full_name} submitted all requested documents",
            reference_type="client", reference_id=client.id, commit=True,
        )

    # Extract text in the background so the AI copilot can read the new document.
    _start_document_text_extraction(doc.id, data, original, file.content_type)

    return {
        "message": "Uploaded.",
        "items": [_serialize_docreq_item(i) for i in (req.items or [])],
        "status": req.status,
    }


# ===========================================================================
# Per-client university shortlisting (B2B)
#
# Each consultancy client gets their own shortlist, tailored to THAT student's
# destination country. Reuses the proven B2C recommendation engine
# (app/university_shortlist.py) — it is a pure function over a country name — but
# every row here is org+client scoped, staff-attributed, and the AI action is
# metered against the organization's Rilono Credits wallet.
# ===========================================================================

UNIVERSITY_ACTION_KEY = "university_match"
_UNIVERSITY_DIFFICULTY = {"reach", "match", "safety"}


def _serialize_client_university(row: models.EnterpriseClientUniversity) -> dict:
    try:
        requirements = json.loads(row.key_requirements) if row.key_requirements else []
        if not isinstance(requirements, list):
            requirements = []
    except Exception:
        requirements = []
    return {
        "id": int(row.id),
        "university_name": row.university_name,
        "program": row.program,
        "location": row.location,
        "country_code": row.country_code,
        "status": row.status or "considering",
        "source": row.source or "manual",
        "est_tuition": row.est_tuition,
        "rationale": row.rationale,
        "notes": row.notes,
        "qs_world_rank": row.qs_world_rank,
        "country_rank": row.country_rank,
        "admission_difficulty": row.admission_difficulty,
        "application_fee": row.application_fee,
        "website_url": row.website_url,
        "admissions_url": row.admissions_url,
        "key_requirements": [str(x)[:140] for x in requirements][:6],
        "added_by_name": row.added_by_name,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _safe_external_url(value) -> Optional[str]:
    """Only absolute http(s) URLs are stored — these are rendered as hrefs, so a
    javascript:/data: value from the model (or a crafted API call) must never persist."""
    s = str(value or "").strip()
    if not s or not re.match(r"^https?://[^\s/$.?#].[^\s]*$", s, re.I):
        return None
    return s[:400]


def _normalize_university_status(value) -> str:
    from app.university_shortlist import VALID_STATUSES, DEFAULT_STATUS
    normalized = str(value or "").strip().lower()
    return normalized if normalized in VALID_STATUSES else DEFAULT_STATUS


def _client_universities_query(db: Session, organization_id: int, client_id: int):
    return (
        db.query(models.EnterpriseClientUniversity)
        .filter(
            models.EnterpriseClientUniversity.organization_id == organization_id,
            models.EnterpriseClientUniversity.client_id == client_id,
        )
        .order_by(
            models.EnterpriseClientUniversity.created_at.desc(),
            models.EnterpriseClientUniversity.id.desc(),
        )
    )


class EnterpriseUniversityCreate(BaseModel):
    university_name: str = Field(..., min_length=1, max_length=200)
    program: Optional[str] = Field(None, max_length=200)
    location: Optional[str] = Field(None, max_length=160)
    status: Optional[str] = None
    source: Optional[str] = "manual"
    est_tuition: Optional[str] = Field(None, max_length=80)
    rationale: Optional[str] = Field(None, max_length=600)
    notes: Optional[str] = Field(None, max_length=1000)
    qs_world_rank: Optional[str] = Field(None, max_length=20)
    country_rank: Optional[str] = Field(None, max_length=20)
    admission_difficulty: Optional[str] = Field(None, max_length=20)
    application_fee: Optional[str] = Field(None, max_length=60)
    website_url: Optional[str] = Field(None, max_length=400)
    admissions_url: Optional[str] = Field(None, max_length=400)
    key_requirements: Optional[list[str]] = None


class EnterpriseUniversityUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=1000)


class EnterpriseUniversityRecommend(BaseModel):
    field_of_study: str = Field(..., min_length=1, max_length=120)
    level: Optional[str] = Field(None, max_length=60)
    budget: Optional[str] = Field(None, max_length=60)
    gpa: Optional[str] = Field(None, max_length=60)
    test_scores: Optional[str] = Field(None, max_length=160)
    preferences: Optional[str] = Field(None, max_length=300)
    max_results: int = Field(6, ge=1, le=8)


@router.get("/clients/{client_id}/universities")
def enterprise_client_universities_list(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """The client's shortlist + the destination context the UI tailors itself to."""
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    client = _get_org_client_or_404(db, organization.id, client_id)
    rows = _client_universities_query(db, organization.id, client.id).all()
    from app import university_shortlist

    return {
        "permissions": _enterprise_permissions_for_role(role),
        "entries": [_serialize_client_university(r) for r in rows],
        "destination_country_code": client.destination_country_code,
        "destination_country": client.destination_country_name,
        "client_name": client.full_name,
        "recommend_available": university_shortlist.ai_available(),
        "recommend_cost": credits.action_cost(UNIVERSITY_ACTION_KEY),
    }


@router.get("/clients/{client_id}/universities/search")
def enterprise_client_universities_search(
    client_id: int,
    request: Request,
    q: str = "",
    limit: int = 8,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Typeahead over the shared registry, scoped to THIS client's destination country,
    so a UK applicant never sees US-only schools."""
    _, organization, _role = _require_enterprise_membership(db=db, user=current_user, request=request)
    client = _get_org_client_or_404(db, organization.id, client_id)

    term = (q or "").strip()
    if len(term) < 2:
        return {"country_code": client.destination_country_code, "results": []}
    take = max(1, min(int(limit or 8), 15))
    code = (client.destination_country_code or "").strip().upper()

    rows = (
        db.query(models.USUniversity)
        .filter(
            models.USUniversity.country_code == code,
            models.USUniversity.university_name.ilike(f"%{term}%"),
        )
        .limit(take * 6)
        .all()
    )
    # One university can hold several rows (the registry PK is the email domain), so
    # dedupe by name, then surface prefix matches before mid-string matches.
    seen, prefix, contains = set(), [], []
    lowered = term.lower()
    for row in rows:
        name = (row.university_name or "").strip()
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        item = {"name": name, "location": row.location}
        (prefix if key.startswith(lowered) else contains).append(item)
    return {"country_code": code, "results": (prefix + contains)[:take]}


@router.post("/clients/{client_id}/universities", status_code=status.HTTP_201_CREATED)
def enterprise_client_university_add(
    client_id: int,
    payload: EnterpriseUniversityCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    client = _get_org_client_or_404(db, organization.id, client_id)

    name = (payload.university_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="University name is required.")

    difficulty = str(payload.admission_difficulty or "").strip().lower()
    requirements = [str(x).strip()[:140] for x in (payload.key_requirements or []) if str(x).strip()][:6]

    row = models.EnterpriseClientUniversity(
        organization_id=organization.id,
        client_id=client.id,
        # Snapshot the destination the shortlist was built for (server-decided, never client-supplied).
        country_code=client.destination_country_code,
        university_name=name[:200],
        program=(payload.program or "").strip()[:200] or None,
        location=(payload.location or "").strip()[:160] or None,
        status=_normalize_university_status(payload.status),
        source="ai" if str(payload.source or "").strip().lower() == "ai" else "manual",
        est_tuition=(payload.est_tuition or "").strip()[:80] or None,
        rationale=(payload.rationale or "").strip()[:600] or None,
        notes=(payload.notes or "").strip()[:1000] or None,
        qs_world_rank=(payload.qs_world_rank or "").strip()[:20] or None,
        country_rank=(payload.country_rank or "").strip()[:20] or None,
        admission_difficulty=difficulty if difficulty in _UNIVERSITY_DIFFICULTY else None,
        application_fee=(payload.application_fee or "").strip()[:60] or None,
        # Re-validate server-side: these render as clickable links, so only absolute
        # http(s) URLs are stored (a javascript:/data: href would be a stored-XSS vector).
        website_url=_safe_external_url(payload.website_url),
        admissions_url=_safe_external_url(payload.admissions_url),
        key_requirements=json.dumps(requirements) if requirements else None,
        added_by_user_id=current_user.id,
        added_by_name=(current_user.full_name or current_user.email or "")[:120] or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "permissions": _enterprise_permissions_for_role(role),
        "entry": _serialize_client_university(row),
    }


@router.patch("/clients/{client_id}/universities/{entry_id}")
def enterprise_client_university_update(
    client_id: int,
    entry_id: int,
    payload: EnterpriseUniversityUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    client = _get_org_client_or_404(db, organization.id, client_id)
    row = (
        db.query(models.EnterpriseClientUniversity)
        .filter(
            models.EnterpriseClientUniversity.id == entry_id,
            models.EnterpriseClientUniversity.organization_id == organization.id,
            models.EnterpriseClientUniversity.client_id == client.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="University not found.")

    fields = payload.model_dump(exclude_unset=True)
    if "status" in fields:
        row.status = _normalize_university_status(fields.get("status"))
    if "notes" in fields:
        note = (fields.get("notes") or "").strip()
        row.notes = note[:1000] or None
    db.commit()
    db.refresh(row)
    return {
        "permissions": _enterprise_permissions_for_role(role),
        "entry": _serialize_client_university(row),
    }


@router.delete("/clients/{client_id}/universities/{entry_id}")
def enterprise_client_university_delete(
    client_id: int,
    entry_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    client = _get_org_client_or_404(db, organization.id, client_id)
    deleted = (
        db.query(models.EnterpriseClientUniversity)
        .filter(
            models.EnterpriseClientUniversity.id == entry_id,
            models.EnterpriseClientUniversity.organization_id == organization.id,
            models.EnterpriseClientUniversity.client_id == client.id,
        )
        .delete(synchronize_session=False)
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="University not found.")
    db.commit()
    return {"deleted": True, "id": entry_id, "permissions": _enterprise_permissions_for_role(role)}


@router.post("/clients/{client_id}/universities/recommend")
def enterprise_client_university_recommend(
    client_id: int,
    payload: EnterpriseUniversityRecommend,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """AI university matches for this client, tailored to their destination country.

    Choreography mirrors the proven B2C/Deep-Scan ordering: rate-limit → wallet
    pre-check → generate → fail without charging → charge ONLY on a usable result.
    """
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    client = _get_org_client_or_404(db, organization.id, client_id)

    _enforce_rate_limit_or_429(
        request=request,
        scope="enterprise.university_recommend",
        limit=20,
        window_seconds=600,
        extra_key=str(current_user.id),
    )

    from app import university_shortlist

    if not university_shortlist.ai_available():
        raise HTTPException(status_code=503, detail="AI recommendations are not configured.")

    destination = (client.destination_country_name or "").strip()
    if not destination:
        raise HTTPException(status_code=400, detail="Set this client's destination country first.")

    # Hard-block a broke wallet BEFORE spending any Gemini tokens.
    credits.enforce_action_or_402(db, organization.id, UNIVERSITY_ACTION_KEY)

    ai_usage.set_usage_account(organization_id=organization.id)
    result = university_shortlist.recommend_universities(
        destination_country=destination,
        field_of_study=payload.field_of_study,
        level=payload.level,
        budget=payload.budget,
        gpa=payload.gpa,
        test_scores=payload.test_scores,
        home_country=client.nationality,
        preferences=payload.preferences,
        max_results=payload.max_results,
        usage_source="enterprise_university_shortlist",
    )

    if not result.get("available"):
        raise HTTPException(status_code=503, detail=result.get("message") or "Recommendations are unavailable right now.")
    universities = result.get("universities") or []
    if not universities:
        # Nothing usable came back — never bill the consultancy for an empty result.
        raise HTTPException(
            status_code=502,
            detail="Couldn't generate recommendations. Refine the field of study or preferences and retry.",
        )

    txn = credits.charge_action(
        db, organization.id, UNIVERSITY_ACTION_KEY,
        user=current_user, reference_type="client", reference_id=client.id,
        description=f"University shortlist — {client.full_name}", commit=True,
    )
    return {
        "permissions": _enterprise_permissions_for_role(role),
        "universities": universities,
        "destination_country": destination,
        "grounded": bool(result.get("grounded")),
        "credits_charged": credits.action_cost(UNIVERSITY_ACTION_KEY) if txn else 0,
        "wallet": credits.wallet_state(db, organization.id),
    }


# ===========================================================================
# Client portal share — read-only case tracking for the client
#
# Staff share a client's case as a secure emailed link. The client verifies an
# OTP sent to their own email, then sees a VIEW-ONLY portal: journey stages with
# the per-stage case record, profile details, documents, universities and their
# payment history. Security model mirrors interview invites / document requests
# (hashed capability token + OTP + short-lived signed session token). There is
# deliberately NO write path, and staff notes / internal financials (commission
# split, settlement state) are never included in the payload.
# ===========================================================================

ENTERPRISE_PORTAL_SHARE_EXPIRES_DAYS = int(os.getenv("ENTERPRISE_PORTAL_SHARE_EXPIRES_DAYS", "180"))
ENTERPRISE_PORTAL_SESSION_HOURS = int(os.getenv("ENTERPRISE_PORTAL_SESSION_HOURS", "24"))


class PublicPortalVerifyRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=10)


class PublicPortalDataRequest(BaseModel):
    session_token: str = Field(..., min_length=10, max_length=4000)


def _build_portal_share_url(subdomain_slug, token: str, request: Request | None) -> str:
    subdomain = str(subdomain_slug or "").strip().lower()
    base = None
    if subdomain:
        host = f"{subdomain}.{ENTERPRISE_ROOT_DOMAIN}"
        port = _request_port_for_local_enterprise_url(request)
        if port:
            host = f"{host}:{port}"
        base = f"{ENTERPRISE_PORTAL_SCHEME}://{host}"
    if not base:
        base = ENTERPRISE_PASSWORD_SETUP_BASE_URL
    return f"{base.rstrip('/')}/portal/{token}"


def _portal_share_is_live(share: models.EnterpriseClientPortalShare) -> bool:
    if share.revoked:
        return False
    if share.expires_at:
        exp = share.expires_at.replace(tzinfo=None) if getattr(share.expires_at, "tzinfo", None) else share.expires_at
        if exp < datetime.utcnow():
            return False
    return True


def _serialize_portal_share_status(share: models.EnterpriseClientPortalShare | None) -> Optional[dict]:
    if not share:
        return None
    return {
        "id": share.id,
        "email": share.email,
        "revoked": bool(share.revoked),
        "live": _portal_share_is_live(share),
        "last_opened_at": _iso(share.last_opened_at),
        "open_count": int(share.open_count or 0),
        "created_by_name": share.created_by_name,
        "created_at": _iso(share.created_at),
        "expires_at": _iso(share.expires_at),
    }


def _latest_client_portal_share(db: Session, organization_id: int, client_id: int):
    return (
        db.query(models.EnterpriseClientPortalShare)
        .filter(
            models.EnterpriseClientPortalShare.organization_id == int(organization_id),
            models.EnterpriseClientPortalShare.client_id == int(client_id),
        )
        .order_by(models.EnterpriseClientPortalShare.created_at.desc(), models.EnterpriseClientPortalShare.id.desc())
        .first()
    )


def _issue_portal_session_token(share_id: int) -> str:
    return create_access_token(
        data={"sub": f"entps:{int(share_id)}", "scope": "ent_portal", "psh": int(share_id)},
        expires_delta=timedelta(hours=ENTERPRISE_PORTAL_SESSION_HOURS),
    )


def _decode_portal_session_token(token: str) -> int:
    try:
        payload = jose_jwt.decode(token, AUTH_SECRET_KEY, algorithms=[AUTH_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Your portal session has expired. Please verify your email again.")
    if payload.get("scope") != "ent_portal" or not payload.get("psh"):
        raise HTTPException(status_code=401, detail="Invalid portal session.")
    return int(payload["psh"])


def _public_portal_share_or_404(db: Session, token: str) -> models.EnterpriseClientPortalShare:
    token_hash = hash_token((token or "").strip())
    share = (
        db.query(models.EnterpriseClientPortalShare)
        .filter(models.EnterpriseClientPortalShare.token_hash == token_hash)
        .first()
    )
    if not share or not _portal_share_is_live(share):
        raise HTTPException(status_code=404, detail="This portal link is invalid or has expired.")
    return share


def _public_load_portal_context(db: Session, session_token: str):
    share_id = _decode_portal_session_token(session_token)
    share = db.query(models.EnterpriseClientPortalShare).filter(models.EnterpriseClientPortalShare.id == share_id).first()
    if not share or not _portal_share_is_live(share):
        raise HTTPException(status_code=401, detail="This portal link is no longer active.")
    client = db.query(models.EnterpriseClient).filter(models.EnterpriseClient.id == share.client_id).first()
    org = db.query(models.EnterpriseOrganization).filter(models.EnterpriseOrganization.id == share.organization_id).first()
    if not client or not org:
        raise HTTPException(status_code=404, detail="This portal is no longer available.")
    return share, client, org


# Payment states a student should see. Route plumbing states (transferred /
# settled / on_hold) are all just "paid" from the payer's side; the fee split
# (commission/payout) is consultancy-internal and never serialized here.
_PORTAL_PAYMENT_STATUS = {
    "created": ("pending", "Payment requested"),
    "paid": ("paid", "Paid"),
    "transferred": ("paid", "Paid"),
    "on_hold": ("paid", "Paid"),
    "settled": ("paid", "Paid"),
    "failed": ("failed", "Failed"),
    "refunded": ("refunded", "Refunded"),
    "partially_refunded": ("partially_refunded", "Partially refunded"),
    "cancelled": ("cancelled", "Cancelled"),
}


def _mask_passport_number(value) -> Optional[str]:
    """'M1234567' -> '•••• 567'. Short values mask fully; None stays None."""
    p = str(value or "").strip()
    if not p:
        return None
    if len(p) < 6:
        return "••••"
    return f"•••• {p[-3:]}"


def _portal_stage_records(client: models.EnterpriseClient) -> dict:
    """Per-stage recorded fields, resolved against the destination-aware catalog.

    Returns {stage_key: [{label, value, type}, …]} containing only fields with a
    recorded value, in catalog order — the client sees exactly what staff filled in."""
    data = _load_stage_data(client)
    out: dict[str, list] = {}
    for stage in catalog.CLIENT_STAGES:
        stage_key = stage["key"]
        recorded = data.get(stage_key) or {}
        if not recorded:
            continue
        fields = []
        for field in catalog.stage_fields_for(client.destination_country_code, stage_key):
            # Textarea fields are counselor free-text (hold_notes, refusal_notes,
            # shortfall notes, "rebuttal plan" debriefs …) written before any
            # client-visible surface existed. The share modal promises staff that
            # internal notes are never shown — only structured facts go out.
            if (field.get("type") or "").strip().lower() == "textarea":
                continue
            value = recorded.get(field["key"])
            if value is None or str(value).strip() == "":
                continue
            fields.append({"label": field.get("label") or field["key"], "value": str(value)[:2000], "type": field.get("type") or "text"})
        if fields:
            out[stage_key] = fields
    return out


def _build_client_portal_payload(db: Session, share: models.EnterpriseClientPortalShare,
                                 client: models.EnterpriseClient, org: models.EnterpriseOrganization) -> dict:
    documents = (
        db.query(models.EnterpriseClientDocument)
        .filter(models.EnterpriseClientDocument.client_id == client.id)
        .order_by(models.EnterpriseClientDocument.created_at.desc())
        .all()
    )
    universities = _client_universities_query(db, org.id, client.id).all()
    payments = (
        db.query(models.EnterpriseStudentPayment)
        .filter(
            models.EnterpriseStudentPayment.organization_id == org.id,
            models.EnterpriseStudentPayment.client_id == client.id,
        )
        .order_by(models.EnterpriseStudentPayment.created_at.desc())
        .all()
    )
    interviews_done = (
        db.query(func.count(models.EnterpriseInterviewSession.id))
        .filter(models.EnterpriseInterviewSession.client_id == client.id)
        .scalar()
    ) or 0

    doc_status = {"valid": "verified", "invalid": "needs_review", "error": None, None: None}
    pay_rows = []
    for p in payments:
        state, state_label = _PORTAL_PAYMENT_STATUS.get(p.status, ("pending", "Payment requested"))
        pay_rows.append({
            "invoice_number": p.invoice_number,
            "description": p.description or "Consultancy fee",
            "amount": round((p.amount_paise or 0) / 100, 2),
            "refunded_amount": round((p.refunded_amount_paise or 0) / 100, 2),
            "currency": p.currency or "INR",
            "status": state,
            "status_label": state_label,
            "due_date": _iso(p.due_date),
            "paid_at": _iso(p.paid_at),
            "created_at": _iso(p.created_at),
        })

    return {
        "organization": {
            "name": org.company_name,
            "logo_url": _resolve_enterprise_logo_url(org),
        },
        "client": {
            "full_name": client.full_name,
            "email": client.email,
            "phone": client.phone,
            "nationality": client.nationality,
            "date_of_birth": _iso(client.date_of_birth),
            # Masked: the portal's only auth anchor is the client's inbox (link + OTP),
            # so a compromised inbox must not yield a full identity kit. Last 3 chars
            # are enough for the client to confirm which passport is on file.
            "passport_number": _mask_passport_number(client.passport_number),
            "passport_expiry": _iso(client.passport_expiry),
            "visa_category_label": _category_label(client.visa_category),
            "destination_country_code": client.destination_country_code,
            "destination_country_name": client.destination_country_name,
            "country": _country_brief(client.destination_country_code),
            "visa_type": client.visa_type,
            "intake": client.intake,
            "application_reference": client.application_reference,
            "target_date": _iso(client.target_date),
            "created_at": _iso(client.created_at),
            "updated_at": _iso(client.updated_at or client.created_at),
        },
        "status": client.status,
        "stage": _stage_brief(client.status),
        "held_from_status": getattr(client, "held_from_status", None),
        "held_from_stage": _stage_brief(client.held_from_status) if getattr(client, "held_from_status", None) else None,
        "stages": [
            {k: s[k] for k in ("key", "label", "description", "order", "color")}
            for s in catalog.CLIENT_STAGES
        ],
        "stage_records": _portal_stage_records(client),
        "documents": [
            {
                "document_type": d.document_type,
                "original_filename": d.original_filename,
                "file_size": d.file_size,
                "status": doc_status.get(d.validation_status),
                "uploaded_at": _iso(d.created_at),
            }
            for d in documents
        ],
        "universities": [
            {
                "university_name": u.university_name,
                "program": u.program,
                "location": u.location,
                "status": u.status or "considering",
                "est_tuition": u.est_tuition,
                "application_fee": u.application_fee,
                "qs_world_rank": u.qs_world_rank,
                "country_rank": u.country_rank,
                "admission_difficulty": u.admission_difficulty,
                "key_requirements": _serialize_client_university(u)["key_requirements"],
                "website_url": _safe_external_url(u.website_url),
                "admissions_url": _safe_external_url(u.admissions_url),
                "rationale": u.rationale,
            }
            for u in universities
        ],
        "payments": pay_rows,
        "mock_interviews_completed": int(interviews_done),
    }


# ---- Staff: create / view / revoke the share ------------------------------

@router.post("/clients/{client_id}/portal-share")
def enterprise_create_portal_share(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    client = _get_org_client_or_404(db, organization.id, client_id)
    email = (client.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Add an email to this client before sharing their portal.")

    # Supersede any prior shares for this client — one live link at a time.
    db.query(models.EnterpriseClientPortalShare).filter(
        models.EnterpriseClientPortalShare.client_id == client.id,
        models.EnterpriseClientPortalShare.revoked.is_(False),
    ).update({"revoked": True})

    raw_token = generate_verification_token()
    share = models.EnterpriseClientPortalShare(
        organization_id=organization.id,
        client_id=client.id,
        token_hash=hash_token(raw_token),
        email=email,
        expires_at=datetime.utcnow() + timedelta(days=ENTERPRISE_PORTAL_SHARE_EXPIRES_DAYS),
        created_by_user_id=current_user.id,
        created_by_name=current_user.full_name or current_user.email,
    )
    db.add(share)
    db.commit()
    db.refresh(share)

    link = _build_portal_share_url(organization.subdomain_slug, raw_token, request)
    sent, _mid, err = send_enterprise_portal_share_email(
        to_email=email,
        client_name=client.full_name,
        organization_name=organization.company_name,
        portal_url=link,
        destination_country=client.destination_country_name,
        visa_type=client.visa_type,
        logo_url=_resolve_enterprise_logo_url(organization),
    )
    message = (f"Portal access sent to {email}."
               if sent else f"Share created but the email could not be sent right now. {err or ''}".strip())
    return {
        "message": message,
        "email_sent": sent,
        # Returned once for copy/WhatsApp convenience. Opening it still requires the
        # OTP sent to the client's own email, so the link alone grants nothing.
        "link": link,
        "share": _serialize_portal_share_status(share),
        "permissions": _enterprise_permissions_for_role(role),
    }


@router.get("/clients/{client_id}/portal-share")
def enterprise_get_portal_share(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(db=db, user=current_user, request=request)
    client = _get_org_client_or_404(db, organization.id, client_id)
    share = _latest_client_portal_share(db, organization.id, client.id)
    return {
        "permissions": _enterprise_permissions_for_role(role),
        "share": _serialize_portal_share_status(share),
    }


@router.post("/clients/{client_id}/portal-share/revoke")
def enterprise_revoke_portal_share(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    _, organization, role = _require_enterprise_membership(
        db=db, user=current_user, request=request, require_edit_data=True
    )
    client = _get_org_client_or_404(db, organization.id, client_id)
    db.query(models.EnterpriseClientPortalShare).filter(
        models.EnterpriseClientPortalShare.client_id == client.id,
        models.EnterpriseClientPortalShare.revoked.is_(False),
    ).update({"revoked": True})
    db.commit()
    return {"message": "Portal access revoked.", "permissions": _enterprise_permissions_for_role(role)}


# ---- Public (client-facing, token-scoped, no staff auth) ------------------

@router.get("/public/portal/{token}")
def public_portal_info(token: str, db: Session = Depends(get_db)):
    share = _public_portal_share_or_404(db, token)
    client = db.query(models.EnterpriseClient).filter(models.EnterpriseClient.id == share.client_id).first()
    org = db.query(models.EnterpriseOrganization).filter(models.EnterpriseOrganization.id == share.organization_id).first()
    if not client or not org:
        raise HTTPException(status_code=404, detail="This portal link is no longer available.")
    return {
        "organization_name": org.company_name,
        "logo_url": _resolve_enterprise_logo_url(org),
        "client_first_name": (client.full_name or "there").split(" ")[0],
        "destination_country": client.destination_country_name,
        "visa_type": client.visa_type,
        "masked_email": _mask_email(share.email),
    }


@router.post("/public/portal/{token}/send-code")
def public_portal_send_code(token: str, request: Request, db: Session = Depends(get_db)):
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.portal_code",
        limit=ENTERPRISE_CODE_RATE_LIMIT, window_seconds=ENTERPRISE_CODE_RATE_WINDOW, extra_key=hash_token(token)[:16],
    )
    share = _public_portal_share_or_404(db, token)
    org = db.query(models.EnterpriseOrganization).filter(models.EnterpriseOrganization.id == share.organization_id).first()
    client = db.query(models.EnterpriseClient).filter(models.EnterpriseClient.id == share.client_id).first()
    if not org or not client:
        raise HTTPException(status_code=404, detail="This portal link is no longer available.")

    code = f"{_secrets.randbelow(900000) + 100000:06d}"
    share.code_hash = hash_token(code)
    share.code_expires_at = datetime.utcnow() + timedelta(minutes=ENTERPRISE_INTERVIEW_CODE_EXPIRES_MIN)
    share.code_attempts = 0
    db.commit()

    sent, _mid, err = send_enterprise_portal_code_email(
        to_email=share.email, client_name=client.full_name, organization_name=org.company_name, code=code,
    )
    if not sent:
        logger.warning("Portal code email failed for share %s: %s", share.id, err)
    return {"sent": bool(sent), "masked_email": _mask_email(share.email)}


@router.post("/public/portal/{token}/verify")
def public_portal_verify(token: str, payload: PublicPortalVerifyRequest, request: Request, db: Session = Depends(get_db)):
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.portal_verify",
        limit=ENTERPRISE_PUBLIC_RATE_LIMIT, window_seconds=ENTERPRISE_PUBLIC_RATE_WINDOW, extra_key=hash_token(token)[:16],
    )
    share = _public_portal_share_or_404(db, token)
    if not share.code_hash or not share.code_expires_at:
        raise HTTPException(status_code=400, detail="Please request a verification code first.")
    code_exp = share.code_expires_at.replace(tzinfo=None) if getattr(share.code_expires_at, "tzinfo", None) else share.code_expires_at
    if code_exp < datetime.utcnow():
        raise HTTPException(status_code=400, detail="That code has expired. Please request a new one.")
    if int(share.code_attempts or 0) >= ENTERPRISE_INTERVIEW_CODE_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts. Please request a new code.")

    share.code_attempts = int(share.code_attempts or 0) + 1
    if hash_token((payload.code or "").strip()) != share.code_hash:
        db.commit()
        raise HTTPException(status_code=400, detail="That code is incorrect. Please try again.")

    # Verified — consume the code and issue a short-lived read-only session token.
    share.code_hash = None
    share.code_expires_at = None
    db.commit()
    return {
        "session_token": _issue_portal_session_token(share.id),
        "session_hours": ENTERPRISE_PORTAL_SESSION_HOURS,
    }


@router.post("/public/portal/data")
def public_portal_data(payload: PublicPortalDataRequest, request: Request, db: Session = Depends(get_db)):
    _enforce_rate_limit_or_429(
        request=request, scope="enterprise.portal_data",
        limit=ENTERPRISE_PUBLIC_RATE_LIMIT, window_seconds=ENTERPRISE_PUBLIC_RATE_WINDOW,
    )
    share, client, org = _public_load_portal_context(db, payload.session_token)
    # Atomic SQL increment — concurrent portal loads must not lose updates.
    db.query(models.EnterpriseClientPortalShare).filter(
        models.EnterpriseClientPortalShare.id == share.id
    ).update({
        "last_opened_at": datetime.utcnow(),
        "open_count": models.EnterpriseClientPortalShare.open_count + 1,
    }, synchronize_session=False)
    db.commit()
    return _build_client_portal_payload(db, share, client, org)
