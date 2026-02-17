from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app import models

_ALLOWED_NOTIFICATION_TYPES = {"success", "error", "warning", "info"}


def normalize_notification_type(value: Optional[str]) -> str:
    normalized = str(value or "info").strip().lower()
    if normalized not in _ALLOWED_NOTIFICATION_TYPES:
        return "info"
    return normalized


def create_user_notification(
    db: Session,
    user_id: int,
    title: str,
    message: str,
    notification_type: str = "info",
    source: Optional[str] = "system",
    commit: bool = True,
) -> models.UserNotification:
    notification = models.UserNotification(
        user_id=user_id,
        title=(title or "Notification").strip()[:200] or "Notification",
        message=(message or "").strip() or "You have a new update.",
        notification_type=normalize_notification_type(notification_type),
        source=(source or "system").strip()[:100] or "system",
        is_read=False,
    )
    db.add(notification)
    if commit:
        db.commit()
        db.refresh(notification)
    else:
        db.flush()
    return notification


def list_user_notifications(db: Session, user_id: int, limit: int = 50) -> list[models.UserNotification]:
    safe_limit = max(1, min(int(limit or 50), 200))
    return (
        db.query(models.UserNotification)
        .filter(models.UserNotification.user_id == user_id)
        .order_by(models.UserNotification.created_at.desc(), models.UserNotification.id.desc())
        .limit(safe_limit)
        .all()
    )


def get_unread_notification_count(db: Session, user_id: int) -> int:
    return int(
        db.query(models.UserNotification)
        .filter(
            models.UserNotification.user_id == user_id,
            models.UserNotification.is_read.is_(False),
        )
        .count()
    )


def mark_user_notification_read(
    db: Session,
    user_id: int,
    notification_id: int,
    commit: bool = True,
) -> Optional[models.UserNotification]:
    notification = (
        db.query(models.UserNotification)
        .filter(
            models.UserNotification.id == notification_id,
            models.UserNotification.user_id == user_id,
        )
        .first()
    )
    if not notification:
        return None

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.utcnow()
        if commit:
            db.commit()
            db.refresh(notification)
        else:
            db.flush()
    return notification


def mark_all_user_notifications_read(db: Session, user_id: int, commit: bool = True) -> int:
    notifications = (
        db.query(models.UserNotification)
        .filter(
            models.UserNotification.user_id == user_id,
            models.UserNotification.is_read.is_(False),
        )
        .all()
    )
    if not notifications:
        return 0

    now = datetime.utcnow()
    for notification in notifications:
        notification.is_read = True
        notification.read_at = now

    if commit:
        db.commit()
    else:
        db.flush()
    return len(notifications)
