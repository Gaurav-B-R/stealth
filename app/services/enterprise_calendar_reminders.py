"""
Daily enterprise calendar-reminder emails.

Each morning, every staff member who has reminders/tasks due today (or overdue) — plus
the auto-derived client deadlines (client target dates & passport expiries) for clients
they created — gets ONE digest email. Recipient = the event creator (for derived client
deadlines, the client's creator).

Mirrors app.services.daily_ai_notifications: a background thread polls and, once past the
scheduled UTC time, runs the job exactly once per day (idempotency via
enterprise_calendar_reminder_runs.run_date).

Two different clocks are in play here, deliberately:

  * WHEN the job runs is global — once per UTC day, at HOUR_UTC:MINUTE_UTC — because
    `run_date` is uniquely indexed, so one run covers every org. Per-org delivery times
    need that constraint widened to (run_date, organization_id) first.
  * WHAT it says is per-org: "today", "overdue" and the printed clock times are all resolved
    in the org's own zone (app.enterprise_time). Grading a workspace west of UTC against the
    run's UTC date labelled tomorrow's appointment "Today" for most of its afternoon.
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
from app import enterprise_time as ent_time
from app.email_service import (
    send_enterprise_calendar_digest_email,
    send_enterprise_client_calendar_reminder_email,
    DEFAULT_PUBLIC_BASE_URL,
)

logger = logging.getLogger(__name__)

# Tenant portal URLs are subdomain-based (e.g. https://acme.rilono.com). Built purely
# from env here (no request object in a background job) so deployed links are correct.
ENTERPRISE_ROOT_DOMAIN = (os.getenv("ENTERPRISE_ROOT_DOMAIN", "rilono.com").strip().lower() or "rilono.com").lstrip(".")
ENTERPRISE_PORTAL_SCHEME = os.getenv("ENTERPRISE_PORTAL_SCHEME", "https").strip().lower() or "https"

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
            "title": ev.title, "type_label": label, "color": color, "client_id": ev.client_id,
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
            "time": None, "client_name": client.full_name, "client_id": client.id,
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
            "time": None, "client_name": client.full_name, "client_id": client.id,
            "date": client.passport_expiry, "when_label": when_label, "overdue": overdue,
        })

    # The digest is addressed by `created_by_user_id`, which lines up with "clients assigned to
    # them, plus ones they created" but NOT with office scope: a manager who created a client and
    # later filed it under another office would still be emailed about it. Drop anything the
    # recipient could no longer open in the portal — an email is a disclosure like any other.
    return _filter_items_by_scope(db, organization_id, by_recipient)


def _filter_items_by_scope(db, organization_id: int, by_recipient: dict[int, list[dict]]) -> dict[int, list[dict]]:
    if not by_recipient:
        return by_recipient
    try:
        from app import enterprise_notifications as notif

        resolved = {r["user_id"]: r for r in notif._resolved_org_members(db, organization_id)}
        client_ids = {int(i["client_id"]) for items in by_recipient.values()
                      for i in items if i.get("client_id")}
        clients = {}
        if client_ids:
            clients = {
                int(c.id): c
                for c in db.query(models.EnterpriseClient)
                .filter(models.EnterpriseClient.id.in_(client_ids)).all()
            }
        filtered: dict[int, list[dict]] = {}
        for uid, items in by_recipient.items():
            member = resolved.get(int(uid))
            if member is None:
                continue  # no longer an active member — nothing to send
            kept = [
                i for i in items
                if not i.get("client_id")
                or notif._client_scope_predicate(clients.get(int(i["client_id"])), member)
            ]
            if kept:
                filtered[uid] = kept
        return filtered
    except Exception:
        logger.exception("Reminder scope filter failed (org_id=%s); sending unfiltered", organization_id)
        return by_recipient


def _org_portal_url(org) -> str:
    """The org's tenant portal base URL, e.g. https://acme.rilono.com (falls back to
    the root public URL if the org has no subdomain yet)."""
    subdomain = (getattr(org, "subdomain_slug", None) or "").strip().lower()
    if subdomain:
        return f"{ENTERPRISE_PORTAL_SCHEME}://{subdomain}.{ENTERPRISE_ROOT_DOMAIN}"
    return DEFAULT_PUBLIC_BASE_URL.rstrip("/")


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


def _notify_linked_clients(db, org, today: date, floor: date, tz_label: str) -> int:
    """Email clients who were @-mentioned (with notify-on) when their reminder comes due.

    Sent at most once per event (dedup via client_notified_at) so an overdue reminder
    doesn't email the client every day. Future-dated reminders aren't sent until due."""
    sent = 0
    events = (
        db.query(models.EnterpriseCalendarEvent)
        .filter(
            models.EnterpriseCalendarEvent.organization_id == org.id,
            models.EnterpriseCalendarEvent.is_done.is_(False),
            models.EnterpriseCalendarEvent.notify_client.is_(True),
            models.EnterpriseCalendarEvent.client_id.isnot(None),
            models.EnterpriseCalendarEvent.client_notified_at.is_(None),
            models.EnterpriseCalendarEvent.event_date >= floor,
            models.EnterpriseCalendarEvent.event_date <= today,
        )
        .all()
    )
    for ev in events:
        client = (
            db.query(models.EnterpriseClient)
            .filter(
                models.EnterpriseClient.id == ev.client_id,
                models.EnterpriseClient.organization_id == org.id,
            )
            .first()
        )
        # Mark handled regardless, so we don't re-scan a client with no email forever.
        ev.client_notified_at = datetime.utcnow()
        if not client or not (client.email or "").strip():
            continue
        when_label, _overdue = _when_label(ev.event_date, today)
        try:
            ok = send_enterprise_client_calendar_reminder_email(
                to_email=client.email.strip(),
                client_name=client.full_name or "there",
                org_name=org.company_name or "Your consultancy",
                title=ev.title,
                when_label=when_label,
                # The student is very often in a different country to the consultancy, so a
                # bare "14:00" is the one place this ambiguity actually costs someone a slot.
                # No configured office zone → no label, rather than a guess dressed as fact.
                event_time=(f"{ev.event_time} {tz_label}".strip() if ev.event_time else None),
                notes=ev.notes,
            )
            if ok:
                sent += 1
        except Exception:
            logger.exception("Client calendar reminder send failed (org=%s, event=%s)", org.id, ev.id)
    db.commit()
    return sent


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

        emailed = 0
        considered = 0
        clients_emailed = 0

        org_ids = [oid for (oid,) in db.query(models.EnterpriseOrganization.id).all()]
        for org_id in org_ids:
            org = db.query(models.EnterpriseOrganization).filter(models.EnterpriseOrganization.id == org_id).first()
            if not org:
                continue
            # "Today" is the ORG's date, not the run's UTC date. A workspace west of UTC is
            # still on the previous calendar day when this job fires, so grading its events
            # against `run_date` labelled tomorrow's appointment "Today" and today's own
            # items "1 day overdue" — the digest was wrong for exactly the offices whose
            # evening it was. The job still runs once per UTC day (delivery time is global);
            # this fixes what the email says, not yet when it lands.
            _org_tz, today, org_tz_label = ent_time.org_clock(db, org_id)
            floor = today - timedelta(days=OVERDUE_DAYS)
            # Notify @-mentioned clients whose reminders are due (once each).
            try:
                clients_emailed += _notify_linked_clients(db, org, today, floor, org_tz_label)
            except Exception:
                logger.exception("Client notification pass failed (org=%s)", org_id)
                db.rollback()
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
                        portal_url=_org_portal_url(org),
                        timezone_label=org_tz_label,
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
            "recipients_emailed": emailed, "clients_emailed": clients_emailed,
            "events_considered": considered, "orgs": len(org_ids),
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
