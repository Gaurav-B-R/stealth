"""
Daily enterprise calendar-reminder emails.

Each morning, every staff member who has reminders/tasks due today (or overdue) — plus
the auto-derived client deadlines (client target dates & passport expiries) for clients
they created — gets ONE digest email. Recipient = the event creator (for derived client
deadlines, the client's creator).

Mirrors app.services.daily_ai_notifications: a background thread polls and, once past the
scheduled UTC time, runs the job exactly once per day (idempotency via
enterprise_calendar_reminder_runs.run_date).
"""

from __future__ import annotations

import os
import threading
import logging
from datetime import datetime, timedelta, timezone, date
from typing import Optional

from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app import models
from app import enterprise_catalog as catalog
from app.email_service import send_enterprise_calendar_digest_email, DEFAULT_PUBLIC_BASE_URL

logger = logging.getLogger(__name__)

ENABLED = str(os.getenv("ENTERPRISE_CALENDAR_REMINDER_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}
# India-focused product → default 08:00 IST (02:30 UTC). Override via env.
HOUR_UTC = max(0, min(23, int(os.getenv("ENTERPRISE_CALENDAR_REMINDER_HOUR_UTC", "2") or "2")))
MINUTE_UTC = max(0, min(59, int(os.getenv("ENTERPRISE_CALENDAR_REMINDER_MINUTE_UTC", "30") or "30")))
POLL_SECONDS = max(60, int(os.getenv("ENTERPRISE_CALENDAR_REMINDER_POLL_SECONDS", "300") or "300"))
OVERDUE_DAYS = max(1, int(os.getenv("ENTERPRISE_CALENDAR_REMINDER_OVERDUE_DAYS", "14") or "14"))

_TYPE_META = {
    "reminder":    ("Reminder", "#6366f1"),
    "task":        ("Task", "#0ea5e9"),
    "follow_up":   ("Follow-up", "#8b5cf6"),
    "appointment": ("Appointment", "#10b981"),
    "deadline":    ("Deadline", "#f97316"),
    "other":       ("Other", "#64748b"),
}
_DERIVED_META = {
    "client_deadline": ("Key date / deadline", "#f97316"),
    "passport_expiry": ("Passport expires", "#f59e0b"),
}


def _when_label(when: date, today: date) -> tuple[str, bool]:
    if when == today:
        return "Today", False
    days = (today - when).days
    if days == 1:
        return "1 day overdue", True
    return f"{days} days overdue", True


def _collect_org_items_by_recipient(db, organization_id: int, today: date, floor: date) -> dict[int, list[dict]]:
    """Map recipient_user_id -> list of due/overdue item dicts for one organization."""
    by_recipient: dict[int, list[dict]] = {}

    def add(uid: Optional[int], item: dict):
        if not uid:
            return
        by_recipient.setdefault(int(uid), []).append(item)

    client_name_cache: dict[int, str] = {}

    def cname(cid: Optional[int]) -> Optional[str]:
        if not cid:
            return None
        if cid not in client_name_cache:
            row = db.query(models.EnterpriseClient.full_name).filter(models.EnterpriseClient.id == cid).first()
            client_name_cache[cid] = row[0] if row else None
        return client_name_cache[cid]

    # Manual events (not done) due today or recently overdue
    for ev in (
        db.query(models.EnterpriseCalendarEvent)
        .filter(
            models.EnterpriseCalendarEvent.organization_id == organization_id,
            models.EnterpriseCalendarEvent.is_done.is_(False),
            models.EnterpriseCalendarEvent.event_date >= floor,
            models.EnterpriseCalendarEvent.event_date <= today,
        )
        .all()
    ):
        label, color = _TYPE_META.get(ev.event_type, _TYPE_META["reminder"])
        when_label, overdue = _when_label(ev.event_date, today)
        add(ev.created_by_user_id, {
            "title": ev.title, "type_label": label, "color": color,
            "time": ev.event_time, "client_name": cname(ev.client_id),
            "date": ev.event_date, "when_label": when_label, "overdue": overdue,
        })

    # Derived: client key dates (target_date), non-terminal
    label, color = _DERIVED_META["client_deadline"]
    for client in (
        db.query(models.EnterpriseClient)
        .filter(
            models.EnterpriseClient.organization_id == organization_id,
            models.EnterpriseClient.target_date.isnot(None),
            models.EnterpriseClient.target_date >= floor,
            models.EnterpriseClient.target_date <= today,
            models.EnterpriseClient.status.notin_([catalog.STAGE_APPROVED, catalog.STAGE_REJECTED]),
        )
        .all()
    ):
        when_label, overdue = _when_label(client.target_date, today)
        add(client.created_by_user_id, {
            "title": f"{client.full_name} — key date", "type_label": label, "color": color,
            "time": None, "client_name": client.full_name,
            "date": client.target_date, "when_label": when_label, "overdue": overdue,
        })

    # Derived: passport expiries
    label, color = _DERIVED_META["passport_expiry"]
    for client in (
        db.query(models.EnterpriseClient)
        .filter(
            models.EnterpriseClient.organization_id == organization_id,
            models.EnterpriseClient.passport_expiry.isnot(None),
            models.EnterpriseClient.passport_expiry >= floor,
            models.EnterpriseClient.passport_expiry <= today,
        )
        .all()
    ):
        when_label, overdue = _when_label(client.passport_expiry, today)
        add(client.created_by_user_id, {
            "title": f"{client.full_name} — passport expiry", "type_label": label, "color": color,
            "time": None, "client_name": client.full_name,
            "date": client.passport_expiry, "when_label": when_label, "overdue": overdue,
        })

    return by_recipient


def _is_active_member(db, organization_id: int, user_id: int) -> bool:
    return (
        db.query(models.EnterpriseOrganizationMember.id)
        .filter(
            models.EnterpriseOrganizationMember.organization_id == organization_id,
            models.EnterpriseOrganizationMember.user_id == user_id,
            models.EnterpriseOrganizationMember.is_active.is_(True),
        )
        .first()
        is not None
    )


def run_calendar_reminder_job(force: bool = False) -> dict:
    """Send today's calendar digest to each staff member with due/overdue items.
    Idempotent per UTC day via enterprise_calendar_reminder_runs."""
    now_utc = datetime.now(timezone.utc)
    run_date = now_utc.date()
    db = SessionLocal()
    try:
        existing = (
            db.query(models.EnterpriseCalendarReminderRun)
            .filter(models.EnterpriseCalendarReminderRun.run_date == run_date)
            .first()
        )
        if existing and not force and existing.status == "completed":
            return {"status": "skipped", "reason": "already_ran_for_today", "run_date": run_date.isoformat()}
        if (
            existing and not force and existing.status == "running"
            and existing.started_at and (datetime.utcnow() - existing.started_at) < timedelta(hours=2)
        ):
            return {"status": "skipped", "reason": "run_already_in_progress", "run_date": run_date.isoformat()}

        if existing:
            run_row = existing
            run_row.status = "running"; run_row.started_at = datetime.utcnow()
            run_row.completed_at = None; run_row.recipients_emailed = 0; run_row.events_considered = 0
            run_row.error_message = None
            db.commit()
        else:
            run_row = models.EnterpriseCalendarReminderRun(run_date=run_date, status="running", started_at=datetime.utcnow())
            db.add(run_row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                return {"status": "skipped", "reason": "already_ran_for_today", "run_date": run_date.isoformat()}

        today = run_date
        floor = today - timedelta(days=OVERDUE_DAYS)
        emailed = 0
        considered = 0

        org_ids = [oid for (oid,) in db.query(models.EnterpriseOrganization.id).all()]
        for org_id in org_ids:
            org = db.query(models.EnterpriseOrganization).filter(models.EnterpriseOrganization.id == org_id).first()
            if not org:
                continue
            by_recipient = _collect_org_items_by_recipient(db, org_id, today, floor)
            for user_id, items in by_recipient.items():
                considered += len(items)
                if not _is_active_member(db, org_id, user_id):
                    continue
                user = db.query(models.User).filter(models.User.id == user_id).first()
                if not user or not user.email or user.email_notifications_enabled is False:
                    continue
                items.sort(key=lambda it: (it["date"], it.get("time") or "99:99", it["title"]))
                overdue = [it for it in items if it["overdue"]]
                today_items = [it for it in items if not it["overdue"]]
                try:
                    ok = send_enterprise_calendar_digest_email(
                        to_email=user.email,
                        recipient_name=user.full_name or user.email,
                        org_name=org.company_name or "Your consultancy",
                        overdue_items=overdue,
                        today_items=today_items,
                        portal_url=DEFAULT_PUBLIC_BASE_URL,
                    )
                    if ok:
                        emailed += 1
                except Exception:
                    logger.exception("Calendar digest send failed (org=%s, user=%s)", org_id, user_id)

        run_row.status = "completed"
        run_row.completed_at = datetime.utcnow()
        run_row.recipients_emailed = emailed
        run_row.events_considered = considered
        db.commit()
        return {
            "status": "completed", "run_date": run_date.isoformat(),
            "recipients_emailed": emailed, "events_considered": considered, "orgs": len(org_ids),
        }
    except Exception as exc:
        logger.exception("Calendar reminder job failed")
        try:
            db.rollback()
            row = (
                db.query(models.EnterpriseCalendarReminderRun)
                .filter(models.EnterpriseCalendarReminderRun.run_date == run_date)
                .first()
            )
            if row:
                row.status = "failed"; row.error_message = str(exc)[:500]; db.commit()
        except Exception:
            pass
        return {"status": "failed", "error": str(exc), "run_date": run_date.isoformat()}
    finally:
        db.close()


def _is_due_for_today(now_utc: datetime) -> bool:
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    target = now_utc.replace(hour=HOUR_UTC, minute=MINUTE_UTC, second=0, microsecond=0)
    return now_utc >= target


class EnterpriseCalendarReminderScheduler:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not ENABLED:
            print("Enterprise calendar reminders: disabled (ENTERPRISE_CALENDAR_REMINDER_ENABLED=false)")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="enterprise-calendar-reminders", daemon=True)
        self._thread.start()
        print(f"Enterprise calendar reminders: started (schedule={HOUR_UTC:02d}:{MINUTE_UTC:02d} UTC, poll={POLL_SECONDS}s)")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if _is_due_for_today(datetime.now(timezone.utc)):
                    result = run_calendar_reminder_job(force=False)
                    if result.get("status") not in {"skipped"}:
                        print(f"Enterprise calendar reminder run: {result}")
            except Exception as exc:  # noqa: BLE001
                print(f"Enterprise calendar reminder loop error: {str(exc)}")
            self._stop_event.wait(POLL_SECONDS)


_scheduler = EnterpriseCalendarReminderScheduler()


def start_enterprise_calendar_reminder_scheduler() -> None:
    _scheduler.start()


def stop_enterprise_calendar_reminder_scheduler() -> None:
    _scheduler.stop()
