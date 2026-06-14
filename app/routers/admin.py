import os
import logging
import secrets
import string
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from jose import JWTError, jwt
from sqlalchemy import bindparam, case, desc, func, inspect, or_, select, text
from sqlalchemy.orm import Session, aliased

from app import models, schemas
from app.auth import (
    ALGORITHM,
    AUTH_COOKIE_DOMAIN,
    AUTH_COOKIE_SAMESITE,
    SECRET_KEY,
    _resolve_auth_cookie_secure,
    get_password_hash,
    get_current_admin_user,
)
from app.database import get_db
from app.utils.rate_limiter import check_ip_rate_limit, extract_client_ip, is_request_ip_whitelisted
from app.utils.turnstile import is_turnstile_enabled, verify_turnstile_token

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger(__name__)

VALID_USER_PLAN_FILTERS = {"all", "free", "pro", "journey"}
VALID_USER_ROLE_FILTERS = {"all", "student", "staff", "admin", "developer"}
PRICING_MODEL_SIX_MONTH = "pro_six_month"
ENTERPRISE_ROLE_ADMIN = "admin"
ENTERPRISE_ROOT_DOMAIN = (
    os.getenv("ENTERPRISE_ROOT_DOMAIN", "rilono.com").strip().lower() or "rilono.com"
).lstrip(".")
ENTERPRISE_PORTAL_SCHEME = os.getenv("ENTERPRISE_PORTAL_SCHEME", "https").strip().lower() or "https"
ENTERPRISE_PORTAL_PORT = os.getenv("ENTERPRISE_PORTAL_PORT", "").strip().lstrip(":")
ADMIN_TURNSTILE_COOKIE_NAME = (
    os.getenv("ADMIN_TURNSTILE_COOKIE_NAME", "rilono_admin_turnstile").strip()
    or "rilono_admin_turnstile"
)
ADMIN_TURNSTILE_COOKIE_TTL_MINUTES = max(
    5,
    int(os.getenv("ADMIN_TURNSTILE_COOKIE_TTL_MINUTES", "45") or "45"),
)
ADMIN_TURNSTILE_VERIFY_RATE_LIMIT = max(
    5,
    int(os.getenv("ADMIN_TURNSTILE_VERIFY_RATE_LIMIT", "15") or "15"),
)
ADMIN_TURNSTILE_VERIFY_RATE_WINDOW_SECONDS = max(
    10,
    int(os.getenv("ADMIN_TURNSTILE_VERIFY_RATE_WINDOW_SECONDS", "60") or "60"),
)
ADMIN_ENDPOINT_RATE_LIMIT = max(
    20,
    int(os.getenv("ADMIN_ENDPOINT_RATE_LIMIT", "240") or "240"),
)
ADMIN_ENDPOINT_RATE_WINDOW_SECONDS = max(
    10,
    int(os.getenv("ADMIN_ENDPOINT_RATE_WINDOW_SECONDS", "60") or "60"),
)


def _assert_manageable_target(target_user: models.User, acting_user: models.User) -> None:
    """Guardrails for privileged account management actions."""
    if target_user.id == acting_user.id:
        raise HTTPException(status_code=400, detail="You cannot perform this action on your own account.")

    if target_user.is_developer and not acting_user.is_developer:
        raise HTTPException(status_code=403, detail="Only a developer can manage developer accounts.")

    if target_user.is_admin and not acting_user.is_developer:
        raise HTTPException(status_code=403, detail="Only a developer can manage admin accounts.")


def _is_development_env() -> bool:
    return os.getenv("ENVIRONMENT", "production").strip().lower() == "development"


def _is_admin_turnstile_required(request: Request) -> bool:
    if not is_turnstile_enabled():
        return False
    if _is_development_env():
        return False
    if is_request_ip_whitelisted(request):
        return False
    return True


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


def _generate_enterprise_temp_password(length: int = 16) -> str:
    """
    Generate a strong temporary password with upper/lowercase letters, numbers, and symbols.
    """
    normalized_length = max(int(length), 12)
    rng = secrets.SystemRandom()
    required = [
        rng.choice(string.ascii_lowercase),
        rng.choice(string.ascii_uppercase),
        rng.choice(string.digits),
        rng.choice("!@#$%^&*()-_=+"),
    ]
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    remaining = [rng.choice(alphabet) for _ in range(max(normalized_length - len(required), 0))]
    password_chars = required + remaining
    rng.shuffle(password_chars)
    return "".join(password_chars)


def _enforce_rate_limit_or_429(
    *,
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


def _build_turnstile_proof_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ADMIN_TURNSTILE_COOKIE_TTL_MINUTES)
    payload = {
        "purpose": "admin_console",
        "user_id": int(user_id),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _set_admin_turnstile_cookie(*, request: Request, response: Response, user_id: int) -> None:
    response.set_cookie(
        key=ADMIN_TURNSTILE_COOKIE_NAME,
        value=_build_turnstile_proof_token(user_id),
        max_age=ADMIN_TURNSTILE_COOKIE_TTL_MINUTES * 60,
        httponly=True,
        secure=_resolve_auth_cookie_secure(request),
        samesite=AUTH_COOKIE_SAMESITE,
        domain=AUTH_COOKIE_DOMAIN,
        path="/",
    )


def _clear_admin_turnstile_cookie(response: Response) -> None:
    response.delete_cookie(
        key=ADMIN_TURNSTILE_COOKIE_NAME,
        domain=AUTH_COOKIE_DOMAIN,
        path="/",
    )


def require_admin_turnstile_proof(
    request: Request,
    current_user: models.User = Depends(get_current_admin_user),
) -> None:
    """
    Enforce a successful Cloudflare Turnstile challenge before admin API access.
    """
    if not _is_admin_turnstile_required(request):
        return

    signed_token = request.cookies.get(ADMIN_TURNSTILE_COOKIE_NAME)
    if not signed_token:
        raise HTTPException(
            status_code=403,
            detail="Cloudflare verification required. Complete the admin protection check.",
        )

    try:
        payload = jwt.decode(signed_token, SECRET_KEY, algorithms=[ALGORITHM])
        purpose = str(payload.get("purpose") or "")
        user_id = int(payload.get("user_id") or 0)
    except (JWTError, ValueError, TypeError):
        raise HTTPException(
            status_code=403,
            detail="Cloudflare verification expired. Complete the admin protection check again.",
        )

    if purpose != "admin_console" or user_id != int(current_user.id):
        raise HTTPException(
            status_code=403,
            detail="Cloudflare verification expired. Complete the admin protection check again.",
        )


@router.post("/turnstile/verify")
def verify_admin_turnstile(
    payload: schemas.AdminTurnstileVerifyRequest,
    request: Request,
    response: Response,
    current_user: models.User = Depends(get_current_admin_user),
):
    """
    Verify Cloudflare Turnstile and mint a short-lived admin protection cookie.
    """
    _enforce_rate_limit_or_429(
        request=request,
        scope="admin.turnstile.verify",
        limit=ADMIN_TURNSTILE_VERIFY_RATE_LIMIT,
        window_seconds=ADMIN_TURNSTILE_VERIFY_RATE_WINDOW_SECONDS,
        extra_key=f"user:{current_user.id}",
    )

    if _is_admin_turnstile_required(request):
        token = (payload.token or "").strip()
        if not token:
            raise HTTPException(status_code=400, detail="Turnstile token is required.")
        if not verify_turnstile_token(token, extract_client_ip(request)):
            raise HTTPException(
                status_code=400,
                detail="Cloudflare verification failed. Please try again.",
            )

    _set_admin_turnstile_cookie(request=request, response=response, user_id=current_user.id)
    return {
        "message": "Cloudflare verification completed.",
        "expires_in_seconds": ADMIN_TURNSTILE_COOKIE_TTL_MINUTES * 60,
    }


@router.post("/turnstile/clear")
def clear_admin_turnstile(
    response: Response,
    current_user: models.User = Depends(get_current_admin_user),
):
    """Clear admin protection cookie during logout."""
    del current_user
    _clear_admin_turnstile_cookie(response)
    return {"message": "Cloudflare verification cleared."}


def _build_plan_metrics_for_filtered_users(db: Session, filtered_user_ids_subquery) -> dict[str, int]:
    """
    Build subscription plan metrics for the filtered user population:
    - pro_plan_users: active pro users excluding journey-pass users
    - journey_plan_users: active pro users whose latest verified payment is pro_six_month
    """
    filtered_user_ids_select = select(filtered_user_ids_subquery.c.id)

    active_pro_user_rows = (
        db.query(models.Subscription.user_id)
        .filter(
            models.Subscription.user_id.in_(filtered_user_ids_select),
            models.Subscription.plan == "pro",
            models.Subscription.status == "active",
        )
        .all()
    )
    active_pro_user_ids = [row[0] for row in active_pro_user_rows if row and row[0] is not None]
    if not active_pro_user_ids:
        return {"pro_plan_users": 0, "journey_plan_users": 0}

    ranked_verified_payments = (
        db.query(
            models.SubscriptionPayment.user_id.label("user_id"),
            models.SubscriptionPayment.pricing_model.label("pricing_model"),
            func.row_number().over(
                partition_by=models.SubscriptionPayment.user_id,
                order_by=models.SubscriptionPayment.id.desc(),
            ).label("row_num"),
        )
        .filter(
            models.SubscriptionPayment.status == "verified",
            models.SubscriptionPayment.user_id.in_(active_pro_user_ids),
        )
        .subquery()
    )

    journey_plan_users = (
        db.query(func.count())
        .select_from(ranked_verified_payments)
        .filter(
            ranked_verified_payments.c.row_num == 1,
            ranked_verified_payments.c.pricing_model == PRICING_MODEL_SIX_MONTH,
        )
        .scalar()
        or 0
    )

    pro_plan_users = max(len(active_pro_user_ids) - int(journey_plan_users), 0)
    return {
        "pro_plan_users": int(pro_plan_users),
        "journey_plan_users": int(journey_plan_users),
    }


def _get_table_columns(inspector, table_name: str) -> dict[str, dict]:
    try:
        return {str(col["name"]): col for col in inspector.get_columns(table_name)}
    except Exception:
        return {}


def _cleanup_legacy_marketplace_rows(db: Session, user_id: int) -> None:
    """
    Best-effort cleanup for legacy marketplace tables that may still exist in some DBs.
    These tables are not represented in current ORM models but can block user deletion
    through FK constraints (e.g. test buyer/seller accounts).
    """
    bind = db.get_bind()
    if bind is None:
        return

    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    if not {"items", "messages", "item_images"} & table_names:
        return

    item_columns = _get_table_columns(inspector, "items") if "items" in table_names else {}
    message_columns = _get_table_columns(inspector, "messages") if "messages" in table_names else {}
    item_image_columns = _get_table_columns(inspector, "item_images") if "item_images" in table_names else {}

    # If marketplace items are owned by this user, delete dependent rows first.
    owner_columns = [
        col
        for col in ("seller_id", "user_id", "owner_id", "created_by_id", "creator_id")
        if col in item_columns
    ]
    owned_item_ids: list[int] = []
    if owner_columns:
        owner_where = " OR ".join(f'"{col}" = :uid' for col in owner_columns)
        rows = db.execute(
            text(f'SELECT "id" FROM "items" WHERE {owner_where}'),
            {"uid": int(user_id)},
        ).fetchall()
        owned_item_ids = [int(row[0]) for row in rows if row and row[0] is not None]

    if owned_item_ids:
        if item_image_columns and "item_id" in item_image_columns:
            db.execute(
                text('DELETE FROM "item_images" WHERE "item_id" IN :item_ids').bindparams(
                    bindparam("item_ids", expanding=True)
                ),
                {"item_ids": owned_item_ids},
            )
        if message_columns and "item_id" in message_columns:
            db.execute(
                text('DELETE FROM "messages" WHERE "item_id" IN :item_ids').bindparams(
                    bindparam("item_ids", expanding=True)
                ),
                {"item_ids": owned_item_ids},
            )

    # Remove messages directly tied to the user.
    for column in ("sender_id", "receiver_id", "user_id", "seller_id", "buyer_id"):
        if column in message_columns:
            db.execute(
                text(f'DELETE FROM "messages" WHERE "{column}" = :uid'),
                {"uid": int(user_id)},
            )

    # Null out buyer-like references when possible; otherwise delete matching rows.
    for column in ("buyer_id", "sold_to_user_id", "reserved_by_user_id"):
        if column not in item_columns:
            continue
        if bool(item_columns[column].get("nullable", True)):
            db.execute(
                text(f'UPDATE "items" SET "{column}" = NULL WHERE "{column}" = :uid'),
                {"uid": int(user_id)},
            )
        else:
            db.execute(
                text(f'DELETE FROM "items" WHERE "{column}" = :uid'),
                {"uid": int(user_id)},
            )

    # Finally delete items owned by the user.
    if owner_columns:
        owner_where = " OR ".join(f'"{col}" = :uid' for col in owner_columns)
        db.execute(
            text(f'DELETE FROM "items" WHERE {owner_where}'),
            {"uid": int(user_id)},
        )


@router.get("/users", response_model=schemas.AdminUserListResponse)
def list_users_admin(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, min_length=1, max_length=120),
    plan_filter: str = Query("all", alias="plan"),
    role_filter: str = Query("all", alias="role"),
    current_user: models.User = Depends(get_current_admin_user),
    _: None = Depends(require_admin_turnstile_proof),
    db: Session = Depends(get_db),
):
    """
    List users for admin dashboard with search + filters + pagination.
    """
    _enforce_rate_limit_or_429(
        request=request,
        scope="admin.users.list",
        limit=ADMIN_ENDPOINT_RATE_LIMIT,
        window_seconds=ADMIN_ENDPOINT_RATE_WINDOW_SECONDS,
        extra_key=f"user:{current_user.id}",
    )

    normalized_plan = (plan_filter or "all").strip().lower()
    if normalized_plan not in VALID_USER_PLAN_FILTERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid plan filter. Use one of: {', '.join(sorted(VALID_USER_PLAN_FILTERS))}",
        )

    normalized_role = (role_filter or "all").strip().lower()
    if normalized_role not in VALID_USER_ROLE_FILTERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role filter. Use one of: {', '.join(sorted(VALID_USER_ROLE_FILTERS))}",
        )

    query = db.query(models.User)

    search_term = (search or "").strip()
    if search_term:
        token = f"%{search_term}%"
        query = query.filter(
            or_(
                models.User.email.ilike(token),
                models.User.username.ilike(token),
                models.User.full_name.ilike(token),
                models.User.university.ilike(token),
            )
        )

    if normalized_role == "student":
        query = query.filter(models.User.is_admin.is_(False), models.User.is_developer.is_(False))
    elif normalized_role == "staff":
        query = query.filter(or_(models.User.is_admin.is_(True), models.User.is_developer.is_(True)))
    elif normalized_role == "admin":
        query = query.filter(models.User.is_admin.is_(True))
    elif normalized_role == "developer":
        query = query.filter(models.User.is_developer.is_(True))

    active_pro_user_ids_select = select(models.Subscription.user_id).where(
        models.Subscription.plan == "pro",
        models.Subscription.status == "active",
    )
    ranked_verified_payments = (
        db.query(
            models.SubscriptionPayment.user_id.label("user_id"),
            models.SubscriptionPayment.pricing_model.label("pricing_model"),
            func.row_number().over(
                partition_by=models.SubscriptionPayment.user_id,
                order_by=models.SubscriptionPayment.id.desc(),
            ).label("row_num"),
        )
        .filter(
            models.SubscriptionPayment.status == "verified",
            models.SubscriptionPayment.user_id.in_(active_pro_user_ids_select),
        )
        .subquery()
    )
    journey_pass_user_ids_select = select(ranked_verified_payments.c.user_id).where(
        ranked_verified_payments.c.row_num == 1,
        ranked_verified_payments.c.pricing_model == PRICING_MODEL_SIX_MONTH,
    )

    if normalized_plan == "free":
        query = query.filter(~models.User.id.in_(active_pro_user_ids_select))
    elif normalized_plan == "pro":
        query = query.filter(models.User.id.in_(active_pro_user_ids_select))
        query = query.filter(~models.User.id.in_(journey_pass_user_ids_select))
    elif normalized_plan == "journey":
        query = query.filter(models.User.id.in_(journey_pass_user_ids_select))

    total = query.count()
    filtered_user_ids_subquery = query.with_entities(models.User.id).subquery()
    metrics = _build_plan_metrics_for_filtered_users(db=db, filtered_user_ids_subquery=filtered_user_ids_subquery)
    users = (
        query.order_by(desc(models.User.created_at), desc(models.User.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "users": users,
        "total": total,
        "page": page,
        "page_size": page_size,
        "metrics": metrics,
    }


@router.get("/enterprise/accounts", response_model=schemas.AdminEnterpriseAccountListResponse)
def list_enterprise_accounts_admin(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, min_length=1, max_length=120),
    current_user: models.User = Depends(get_current_admin_user),
    _: None = Depends(require_admin_turnstile_proof),
    db: Session = Depends(get_db),
):
    """
    List enterprise organizations for admin dashboard with search + pagination.
    """
    _enforce_rate_limit_or_429(
        request=request,
        scope="admin.enterprise.list",
        limit=ADMIN_ENDPOINT_RATE_LIMIT,
        window_seconds=ADMIN_ENDPOINT_RATE_WINDOW_SECONDS,
        extra_key=f"user:{current_user.id}",
    )

    creator_user = aliased(models.User)
    query = db.query(models.EnterpriseOrganization).outerjoin(
        creator_user,
        creator_user.id == models.EnterpriseOrganization.created_by_user_id,
    )

    search_term = (search or "").strip()
    if search_term:
        token = f"%{search_term}%"
        query = query.filter(
            or_(
                models.EnterpriseOrganization.company_name.ilike(token),
                models.EnterpriseOrganization.subdomain_slug.ilike(token),
                creator_user.email.ilike(token),
                creator_user.full_name.ilike(token),
            )
        )

    total = int(query.count() or 0)
    filtered_org_ids_subquery = query.with_entities(models.EnterpriseOrganization.id).subquery()
    filtered_org_ids_select = select(filtered_org_ids_subquery.c.id)

    active_members = int(
        db.query(func.count(models.EnterpriseOrganizationMember.id))
        .filter(
            models.EnterpriseOrganizationMember.organization_id.in_(filtered_org_ids_select),
            models.EnterpriseOrganizationMember.is_active.is_(True),
        )
        .scalar()
        or 0
    )
    active_admins = int(
        db.query(func.count(models.EnterpriseOrganizationMember.id))
        .filter(
            models.EnterpriseOrganizationMember.organization_id.in_(filtered_org_ids_select),
            models.EnterpriseOrganizationMember.is_active.is_(True),
            func.lower(models.EnterpriseOrganizationMember.role) == ENTERPRISE_ROLE_ADMIN,
        )
        .scalar()
        or 0
    )

    organizations = (
        query.order_by(desc(models.EnterpriseOrganization.created_at), desc(models.EnterpriseOrganization.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    if not organizations:
        return {
            "accounts": [],
            "total": total,
            "page": page,
            "page_size": page_size,
            "metrics": {
                "active_members": active_members,
                "active_admins": active_admins,
            },
        }

    organization_ids = [int(org.id) for org in organizations if org and org.id is not None]
    creator_ids = [
        int(org.created_by_user_id)
        for org in organizations
        if org and org.created_by_user_id is not None
    ]

    member_rows = (
        db.query(
            models.EnterpriseOrganizationMember.organization_id.label("organization_id"),
            func.count(models.EnterpriseOrganizationMember.id).label("total_members"),
            func.sum(
                case(
                    (models.EnterpriseOrganizationMember.is_active.is_(True), 1),
                    else_=0,
                )
            ).label("active_members"),
            func.sum(
                case(
                    (
                        (models.EnterpriseOrganizationMember.is_active.is_(True))
                        & (func.lower(models.EnterpriseOrganizationMember.role) == ENTERPRISE_ROLE_ADMIN),
                        1,
                    ),
                    else_=0,
                )
            ).label("active_admins"),
        )
        .filter(models.EnterpriseOrganizationMember.organization_id.in_(organization_ids))
        .group_by(models.EnterpriseOrganizationMember.organization_id)
        .all()
    )
    member_stats_by_org_id = {
        int(row.organization_id): {
            "total_members": int(row.total_members or 0),
            "active_members": int(row.active_members or 0),
            "active_admins": int(row.active_admins or 0),
        }
        for row in member_rows
        if row and row.organization_id is not None
    }

    creator_rows = (
        db.query(models.User.id, models.User.email, models.User.full_name)
        .filter(models.User.id.in_(creator_ids))
        .all()
        if creator_ids
        else []
    )
    creators_by_id = {
        int(row.id): {
            "email": row.email,
            "full_name": row.full_name,
        }
        for row in creator_rows
        if row and row.id is not None
    }

    accounts: list[dict] = []
    for org in organizations:
        org_id = int(org.id)
        member_stats = member_stats_by_org_id.get(org_id, {})
        creator = creators_by_id.get(int(org.created_by_user_id), {}) if org.created_by_user_id else {}
        accounts.append(
            {
                "organization_id": org_id,
                "company_name": (org.company_name or "").strip() or "Untitled Organization",
                "subdomain_slug": (org.subdomain_slug or "").strip().lower() or None,
                "portal_url": _build_enterprise_portal_url(org.subdomain_slug, request),
                "created_at": org.created_at,
                "created_by_user_id": int(org.created_by_user_id) if org.created_by_user_id is not None else None,
                "created_by_email": creator.get("email"),
                "created_by_name": creator.get("full_name"),
                "total_members": int(member_stats.get("total_members", 0)),
                "active_members": int(member_stats.get("active_members", 0)),
                "active_admins": int(member_stats.get("active_admins", 0)),
            }
        )

    return {
        "accounts": accounts,
        "total": total,
        "page": page,
        "page_size": page_size,
        "metrics": {
            "active_members": active_members,
            "active_admins": active_admins,
        },
    }


@router.post(
    "/enterprise/credentials",
    response_model=schemas.AdminEnterpriseCredentialCreateResponse,
)
def create_enterprise_credentials_admin(
    payload: schemas.AdminEnterpriseCredentialCreateRequest,
    request: Request,
    current_user: models.User = Depends(get_current_admin_user),
    _: None = Depends(require_admin_turnstile_proof),
    db: Session = Depends(get_db),
):
    """
    Create or update enterprise login access.
    Existing main-platform users keep their current password; new users receive a temporary password.
    """
    _enforce_rate_limit_or_429(
        request=request,
        scope="admin.enterprise.credentials.create",
        limit=ADMIN_ENDPOINT_RATE_LIMIT,
        window_seconds=ADMIN_ENDPOINT_RATE_WINDOW_SECONDS,
        extra_key=f"user:{current_user.id}",
    )

    target_email = str(payload.email or "").strip().lower()
    full_name = str(payload.full_name or "").strip()
    if len(full_name) < 2:
        raise HTTPException(status_code=400, detail="Name must be at least 2 characters.")
    if len(full_name) > 120:
        raise HTTPException(status_code=400, detail="Name must be at most 120 characters.")

    existing_credential = (
        db.query(models.EnterpriseCredential)
        .filter(models.EnterpriseCredential.email == target_email)
        .first()
    )
    existing_user = db.query(models.User).filter(models.User.email == target_email).first()

    if existing_user and existing_user.is_developer:
        raise HTTPException(
            status_code=403,
            detail="Developer accounts cannot be converted into enterprise credentials.",
        )

    # If user already exists in main platform, preserve existing password and enable enterprise login reuse.
    if existing_user:
        credential_created = False
        if not str(existing_user.full_name or "").strip():
            existing_user.full_name = full_name
        if not existing_user.is_active:
            existing_user.is_active = True

        if existing_credential:
            existing_credential.password_hash = existing_user.hashed_password
            existing_credential.full_name = full_name
            existing_credential.is_active = True
        else:
            credential_created = True
            db.add(
                models.EnterpriseCredential(
                    email=target_email,
                    password_hash=existing_user.hashed_password,
                    full_name=full_name,
                    is_active=True,
                )
            )

        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to grant enterprise access for existing email=%s", target_email)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to grant enterprise access. Please try again.",
            )

        return {
            "email": target_email,
            "full_name": full_name,
            "temporary_password": None,
            "uses_existing_main_password": True,
            "credential_created": credential_created,
            "user_created": False,
            "message": (
                "Enterprise access granted. User can login with their existing main platform password."
            ),
        }

    temp_password = _generate_enterprise_temp_password()
    hashed_password = get_password_hash(temp_password)

    credential_created = False
    if existing_credential:
        existing_credential.password_hash = hashed_password
        existing_credential.full_name = full_name
        existing_credential.is_active = True
    else:
        credential_created = True
        db.add(
            models.EnterpriseCredential(
                email=target_email,
                password_hash=hashed_password,
                full_name=full_name,
                is_active=True,
            )
        )

    user_created = True
    db.add(
        models.User(
            email=target_email,
            username=None,
            hashed_password=hashed_password,
            full_name=full_name,
            university="Enterprise Account",
            is_active=True,
            email_verified=True,
            is_admin=True,
            accepted_terms_privacy_at=datetime.utcnow(),
        )
    )

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to create enterprise credentials for email=%s", target_email)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create enterprise credentials. Please try again.",
        )

    return {
        "email": target_email,
        "full_name": full_name,
        "temporary_password": temp_password,
        "uses_existing_main_password": False,
        "credential_created": credential_created,
        "user_created": user_created,
        "message": (
            "Enterprise credentials created successfully."
            if credential_created
            else "Enterprise credentials updated and password rotated successfully."
        ),
    }


@router.patch("/users/{user_id}/status", response_model=schemas.AdminUserSummary)
def update_user_status_admin(
    request: Request,
    user_id: int,
    payload: schemas.AdminUserStatusUpdateRequest,
    current_user: models.User = Depends(get_current_admin_user),
    _: None = Depends(require_admin_turnstile_proof),
    db: Session = Depends(get_db),
):
    """
    Activate or deactivate a user account (admin/developer only).
    """
    _enforce_rate_limit_or_429(
        request=request,
        scope="admin.users.update_status",
        limit=ADMIN_ENDPOINT_RATE_LIMIT,
        window_seconds=ADMIN_ENDPOINT_RATE_WINDOW_SECONDS,
        extra_key=f"user:{current_user.id}",
    )

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not payload.is_active:
        _assert_manageable_target(user, current_user)

    user.is_active = bool(payload.is_active)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}")
def delete_user_admin(
    request: Request,
    user_id: int,
    current_user: models.User = Depends(get_current_admin_user),
    _: None = Depends(require_admin_turnstile_proof),
    db: Session = Depends(get_db),
):
    """
    Permanently delete a user account (admin/developer only).
    """
    _enforce_rate_limit_or_429(
        request=request,
        scope="admin.users.delete",
        limit=ADMIN_ENDPOINT_RATE_LIMIT,
        window_seconds=ADMIN_ENDPOINT_RATE_WINDOW_SECONDS,
        extra_key=f"user:{current_user.id}",
    )

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    _assert_manageable_target(user, current_user)

    try:
        # Clean up referral links from other users to avoid FK constraint failures.
        db.query(models.User).filter(models.User.referred_by_user_id == user.id).update(
            {models.User.referred_by_user_id: None},
            synchronize_session=False,
        )

        # This table currently has no ORM relationship on User, so clear explicitly.
        db.query(models.RilonoAiChatUploadEvent).filter(
            models.RilonoAiChatUploadEvent.user_id == user.id
        ).delete(synchronize_session=False)

        # Some upgraded DBs still include legacy marketplace tables (items/messages/item_images)
        # where user-linked rows must be removed first to satisfy FK constraints.
        _cleanup_legacy_marketplace_rows(db=db, user_id=user.id)

        db.delete(user)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to delete user_id=%s from admin console", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete user account. Please try again.",
        )

    return {"message": "User account deleted successfully."}
