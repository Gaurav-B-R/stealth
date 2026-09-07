"""Local recovery and optional daily billing refresh. No external calls by default."""
import logging
import os
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, String, or_
from sqlalchemy.exc import IntegrityError

from app.database import Base, SessionLocal
from app import ai_billing, ai_usage

logger = logging.getLogger(__name__)
_stop = threading.Event()
_thread = None


class AiBillingSyncLease(Base):
    __tablename__ = "ai_billing_sync_leases"
    scope_key = Column(String(64), primary_key=True)
    next_run_at = Column(DateTime(timezone=True), nullable=False)


def run_once(db, *, now=None):
    """Claim one daily run across workers; refresh recent ranges for late corrections."""
    now = now or datetime.now(timezone.utc)
    cfg = ai_billing.configuration()
    if not cfg["configured"] or os.getenv("AI_BILLING_SYNC_ENABLED", "false").lower() not in {"true", "1", "yes"}:
        return False
    key = cfg["scope_key"]
    try:
        db.add(AiBillingSyncLease(scope_key=key, next_run_at=now))
        db.commit()
    except IntegrityError:
        db.rollback()
    claimed = db.query(AiBillingSyncLease).filter(
        AiBillingSyncLease.scope_key == key, AiBillingSyncLease.next_run_at <= now
    ).update({"next_run_at": now + timedelta(days=1)}, synchronize_session=False)
    db.commit()
    if not claimed:
        return False
    today = now.date()
    month = today.replace(day=1)
    previous_end = month - timedelta(days=1)
    ranges = {(today - timedelta(days=29), today), (month, today),
              (previous_end.replace(day=1), previous_end)}
    try:
        for start, end in sorted(ranges):
            ai_billing.sync_billing(db, start=start, end=end)
    except Exception:
        db.rollback()
        db.query(AiBillingSyncLease).filter_by(scope_key=key).update({"next_run_at": now + timedelta(hours=1)})
        db.commit()
        logger.error("Scheduled billing sync failed; previous snapshots retained", exc_info=True)
    return True


def _loop():
    # Give startup migrations time to finish; stop is interruptible.
    while not _stop.wait(60):
        try:
            ai_usage.replay_usage_spool()
            with SessionLocal() as db:
                run_once(db)
        except Exception:
            logger.error("AI accounting maintenance failed", exc_info=True)


def start_ai_accounting_maintenance():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="ai-accounting-maintenance", daemon=True)
    _thread.start()


def stop_ai_accounting_maintenance():
    _stop.set()

