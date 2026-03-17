from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_admin_user
from app.database import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])

VALID_USER_STATUS_FILTERS = {"all", "active", "inactive"}
VALID_USER_ROLE_FILTERS = {"all", "student", "staff", "admin", "developer"}
PRICING_MODEL_SIX_MONTH = "pro_six_month"


def _assert_manageable_target(target_user: models.User, acting_user: models.User) -> None:
    """Guardrails for privileged account management actions."""
    if target_user.id == acting_user.id:
        raise HTTPException(status_code=400, detail="You cannot perform this action on your own account.")

    if target_user.is_developer and not acting_user.is_developer:
        raise HTTPException(status_code=403, detail="Only a developer can manage developer accounts.")

    if target_user.is_admin and not acting_user.is_developer:
        raise HTTPException(status_code=403, detail="Only a developer can manage admin accounts.")


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


@router.get("/users", response_model=schemas.AdminUserListResponse)
def list_users_admin(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, min_length=1, max_length=120),
    status_filter: str = Query("all", alias="status"),
    role_filter: str = Query("all", alias="role"),
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """
    List users for admin dashboard with search + filters + pagination.
    """
    del current_user  # access gate handled by dependency

    normalized_status = (status_filter or "all").strip().lower()
    if normalized_status not in VALID_USER_STATUS_FILTERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status filter. Use one of: {', '.join(sorted(VALID_USER_STATUS_FILTERS))}",
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

    if normalized_status == "active":
        query = query.filter(models.User.is_active.is_(True))
    elif normalized_status == "inactive":
        query = query.filter(models.User.is_active.is_(False))

    if normalized_role == "student":
        query = query.filter(models.User.is_admin.is_(False), models.User.is_developer.is_(False))
    elif normalized_role == "staff":
        query = query.filter(or_(models.User.is_admin.is_(True), models.User.is_developer.is_(True)))
    elif normalized_role == "admin":
        query = query.filter(models.User.is_admin.is_(True))
    elif normalized_role == "developer":
        query = query.filter(models.User.is_developer.is_(True))

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


@router.patch("/users/{user_id}/status", response_model=schemas.AdminUserSummary)
def update_user_status_admin(
    user_id: int,
    payload: schemas.AdminUserStatusUpdateRequest,
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """
    Activate or deactivate a user account (admin/developer only).
    """
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
    user_id: int,
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """
    Permanently delete a user account (admin/developer only).
    """
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

        db.delete(user)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete user account. Please try again.",
        )

    return {"message": "User account deleted successfully."}
