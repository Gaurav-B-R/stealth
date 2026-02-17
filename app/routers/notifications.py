from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_active_user, get_current_admin_user
from app.database import get_db
from app.notification_center import (
    get_unread_notification_count,
    list_user_notifications,
    mark_all_user_notifications_read,
    mark_user_notification_read,
)
from app.services.daily_ai_notifications import run_daily_ai_notification_job

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=schemas.NotificationListResponse)
def get_my_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    notifications = list_user_notifications(db, current_user.id, limit=limit)
    unread_count = get_unread_notification_count(db, current_user.id)
    return schemas.NotificationListResponse(notifications=notifications, unread_count=unread_count)


@router.post("/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    notification = mark_user_notification_read(db, current_user.id, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    unread_count = get_unread_notification_count(db, current_user.id)
    return {
        "ok": True,
        "notification_id": notification.id,
        "unread_count": unread_count,
    }


@router.post("/read-all")
def mark_all_notifications_read(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    updated_count = mark_all_user_notifications_read(db, current_user.id)
    return {
        "ok": True,
        "updated": updated_count,
        "unread_count": 0,
    }


@router.post("/daily/run-now")
def run_daily_notifications_now(
    force: bool = Query(default=True),
    _: models.User = Depends(get_current_admin_user),
):
    result = run_daily_ai_notification_job(force=force)
    return result
