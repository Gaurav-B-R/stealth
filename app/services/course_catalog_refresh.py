"""Background course-catalog refresh agent.

Keeps the Course Finder's universities/courses database current: each daily run
(1) discovers missing top-N universities per destination country (one grounded
Gemini call per country that needs seeding) and (2) enriches/re-verifies the
stalest universities — profile + courses, fees, deadlines, score cutoffs — via
Google-Search-grounded Gemini, batch-capped so daily spend is bounded.

Scheduling follows the proven daily_ai_notifications template: a daemon-thread
poll loop started from main.py's startup hook, with once-per-day idempotency
enforced by course_catalog_refresh_runs.run_date (UNIQUE) + IntegrityError skip,
so concurrent workers can never double-run (the f1_news service predates this
pattern and is explicitly NOT the template to copy).

Cost model (defaults): ≤ ~1 discovery call + COURSE_CATALOG_DAILY_BATCH (12)
enrichment calls per day ≈ $1-1.5/day while seeding, then the same budget rolls
through re-verification (COURSE_CATALOG_REVERIFY_DAYS, 30) so every university is
re-checked roughly monthly at Top-50-per-country scale.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError

from app import models
from app.database import SessionLocal

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


COURSE_CATALOG_REFRESH_ENABLED = _env_flag("COURSE_CATALOG_REFRESH_ENABLED", "true")
COURSE_CATALOG_REFRESH_HOUR_UTC = max(0, min(23, int(os.getenv("COURSE_CATALOG_REFRESH_HOUR_UTC", "4") or "4")))
COURSE_CATALOG_REFRESH_MINUTE_UTC = max(0, min(59, int(os.getenv("COURSE_CATALOG_REFRESH_MINUTE_UTC", "15") or "15")))
COURSE_CATALOG_REFRESH_POLL_SECONDS = max(60, int(os.getenv("COURSE_CATALOG_REFRESH_POLL_SECONDS", "300") or "300"))
# Catalog size target per destination country (the user-facing "Top N").
COURSE_CATALOG_TARGET_PER_COUNTRY = max(1, int(os.getenv("COURSE_CATALOG_TARGET_PER_COUNTRY", "50") or "50"))
# Enrichment calls per daily run — the spend throttle.
COURSE_CATALOG_DAILY_BATCH = max(1, int(os.getenv("COURSE_CATALOG_DAILY_BATCH", "12") or "12"))
# A university is due for re-verification after this many days.
COURSE_CATALOG_REVERIFY_DAYS = max(1, int(os.getenv("COURSE_CATALOG_REVERIFY_DAYS", "30") or "30"))

USAGE_SOURCE = "course_catalog_refresh"

# A stub that fails enrichment this many times in a row is deactivated (it's almost
# certainly a hallucinated/defunct entry); already-enriched universities are never
# deactivated for failures — they just sort behind healthier work in the queue.
STUB_FAILURE_DEACTIVATE_AFTER = 6
# After an outer-loop failure, wait this long before the poll loop retries the day's
# run — without it a systemic failure would re-burn Gemini spend every 5 minutes.
FAILED_RUN_RETRY_COOLDOWN = timedelta(hours=6)


def run_in_progress(existing_run: Optional[models.CourseCatalogRefreshRun]) -> bool:
    """True while a run row is legitimately mid-flight (running, started <2h ago).
    Older 'running' rows are stale (a hot-reload killed the thread) and may be seized."""
    if existing_run is None or existing_run.status != "running" or not existing_run.started_at:
        return False
    started = existing_run.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - started) < timedelta(hours=2)


def _catalog_country_codes() -> list[str]:
    raw = os.getenv("COURSE_CATALOG_COUNTRIES", "").strip()
    if raw:
        return [c.strip().upper() for c in raw.split(",") if c.strip()]
    from app.visa_catalog import LAUNCH_COUNTRY_CODES
    return list(LAUNCH_COUNTRY_CODES)


def _is_due_for_today(now_utc: datetime) -> bool:
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    target = now_utc.replace(
        hour=COURSE_CATALOG_REFRESH_HOUR_UTC,
        minute=COURSE_CATALOG_REFRESH_MINUTE_UTC,
        second=0,
        microsecond=0,
    )
    return now_utc >= target


def run_course_catalog_refresh_job(
    force: bool = False,
    *,
    limit: Optional[int] = None,
    countries: Optional[list[str]] = None,
) -> dict:
    """One catalog refresh cycle. course_catalog_refresh_runs.run_date is the
    idempotency guard (UNIQUE + IntegrityError skip → multi-worker safe).

    `limit`/`countries` let the admin trigger burst beyond the daily defaults
    (e.g. to seed faster); scheduled runs pass neither.
    """
    from app import course_catalog

    now_utc = datetime.now(timezone.utc)
    run_date = now_utc.date()

    if not course_catalog.ai_available():
        return {"status": "skipped", "reason": "ai_not_configured"}

    db = SessionLocal()
    run_row: Optional[models.CourseCatalogRefreshRun] = None
    try:
        existing_run = (
            db.query(models.CourseCatalogRefreshRun)
            .filter(models.CourseCatalogRefreshRun.run_date == run_date)
            .first()
        )
        if existing_run and not force and existing_run.status == "completed":
            return {"status": "skipped", "reason": "already_ran_for_today", "run_date": run_date.isoformat()}
        # force may re-run a COMPLETED day, but never stack onto a live run — each
        # concurrent run would burn the full grounded-call batch again.
        if run_in_progress(existing_run):
            return {"status": "skipped", "reason": "run_already_in_progress", "run_date": run_date.isoformat()}
        if existing_run and not force and existing_run.status == "failed":
            last = existing_run.completed_at or existing_run.started_at
            if last is not None:
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - last < FAILED_RUN_RETRY_COOLDOWN:
                    return {"status": "skipped", "reason": "failed_recently_cooldown", "run_date": run_date.isoformat()}

        if existing_run:
            # Optimistic seize: two workers can pass the guards in the same instant
            # (poll loop vs admin trigger), so only the one whose conditional UPDATE
            # lands may run — the other sees 0 rows changed and backs off.
            seize = db.query(models.CourseCatalogRefreshRun).filter(
                models.CourseCatalogRefreshRun.id == existing_run.id,
                models.CourseCatalogRefreshRun.status == existing_run.status,
            )
            if existing_run.started_at is None:
                seize = seize.filter(models.CourseCatalogRefreshRun.started_at.is_(None))
            else:
                seize = seize.filter(models.CourseCatalogRefreshRun.started_at == existing_run.started_at)
            taken = seize.update(
                {
                    "status": "running",
                    "started_at": datetime.now(timezone.utc),
                    "completed_at": None,
                    "error_message": None,
                },
                synchronize_session=False,
            )
            db.commit()
            if not taken:
                return {"status": "skipped", "reason": "run_already_in_progress", "run_date": run_date.isoformat()}
            run_row = existing_run
            db.refresh(run_row)
        else:
            run_row = models.CourseCatalogRefreshRun(run_date=run_date, status="running")
            db.add(run_row)
            try:
                db.commit()
                db.refresh(run_row)
            except IntegrityError:
                db.rollback()
                return {"status": "skipped", "reason": "already_ran_for_today", "run_date": run_date.isoformat()}

        codes = [c for c in (countries or _catalog_country_codes())]
        batch = max(1, int(limit)) if limit else COURSE_CATALOG_DAILY_BATCH
        detail: dict = {"countries": {}, "refreshed": [], "errors": []}
        discovered_total = 0
        refreshed_total = 0
        courses_total = 0

        # Phase 1 — discovery: top-N stubs for any country below target.
        for code in codes:
            try:
                added = course_catalog.discover_universities(
                    db, code, COURSE_CATALOG_TARGET_PER_COUNTRY, usage_source=USAGE_SOURCE
                )
                discovered_total += added
                detail["countries"][code] = {"discovered": added}
            except Exception as exc:  # noqa: BLE001 — one country must not block the rest
                db.rollback()
                logger.exception("Course catalog discovery failed for %s", code)
                detail["errors"].append(f"discovery:{code}: {str(exc)[:200]}")

        # Phase 2 — enrichment/re-verification: stubs first, then stalest.
        cutoff = datetime.now(timezone.utc) - timedelta(days=COURSE_CATALOG_REVERIFY_DAYS)
        queue = (
            db.query(models.CourseCatalogUniversity)
            .filter(
                models.CourseCatalogUniversity.country_code.in_(codes),
                models.CourseCatalogUniversity.is_active.is_(True),
            )
            .all()
        )

        def _staleness(uni: models.CourseCatalogUniversity):
            # Never-enriched stubs first (in discovery order), then oldest-verified.
            # Repeat failers sort behind healthy peers so they can't starve the batch.
            fails = int(getattr(uni, "consecutive_failures", 0) or 0)
            if uni.last_verified_at is None:
                return (0, fails, uni.seed_rank if uni.seed_rank is not None else 10_000, "")
            ts = uni.last_verified_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return (1, fails, 0, ts.isoformat())

        queue = [
            u for u in sorted(queue, key=_staleness)
            if u.last_verified_at is None
            or (u.last_verified_at.replace(tzinfo=timezone.utc) if u.last_verified_at.tzinfo is None else u.last_verified_at) < cutoff
        ][:batch]

        for uni in queue:
            try:
                result = course_catalog.refresh_university(db, uni, usage_source=USAGE_SOURCE)
                refreshed_total += 1
                courses_total += int(result.get("courses_upserted") or 0)
                detail["refreshed"].append(f"{uni.country_code}:{uni.name}")
            except Exception as exc:  # noqa: BLE001 — one university must not block the batch
                db.rollback()
                logger.exception("Course catalog refresh failed for %s (%s)", uni.name, uni.country_code)
                detail["errors"].append(f"refresh:{uni.country_code}:{uni.name}: {str(exc)[:200]}")
                try:
                    uni.consecutive_failures = int(uni.consecutive_failures or 0) + 1
                    if uni.consecutive_failures >= STUB_FAILURE_DEACTIVATE_AFTER and uni.last_verified_at is None:
                        uni.is_active = False
                        detail["errors"].append(
                            f"deactivated:{uni.country_code}:{uni.name}: never enriched after "
                            f"{uni.consecutive_failures} attempts"
                        )
                    db.commit()
                except Exception:
                    db.rollback()

        run_row.status = "completed"
        run_row.completed_at = datetime.now(timezone.utc)
        run_row.universities_discovered = discovered_total
        run_row.universities_refreshed = refreshed_total
        run_row.courses_upserted = courses_total
        run_row.error_message = "; ".join(detail["errors"])[:2000] if detail["errors"] else None
        # Cap the lists (not the serialized string — a blind slice would persist
        # invalid JSON on large admin burst runs).
        detail["refreshed"] = detail["refreshed"][:150]
        detail["errors"] = detail["errors"][:60]
        run_row.detail = json.dumps(detail)
        db.commit()
        summary = {
            "status": "completed",
            "run_date": run_date.isoformat(),
            "universities_discovered": discovered_total,
            "universities_refreshed": refreshed_total,
            "courses_upserted": courses_total,
            "errors": len(detail["errors"]),
        }
        logger.info("Course catalog refresh run: %s", summary)
        return summary
    except Exception as exc:  # noqa: BLE001
        logger.exception("Course catalog refresh job failed")
        try:
            db.rollback()
            if run_row is not None:
                run_row.status = "failed"
                run_row.completed_at = datetime.now(timezone.utc)
                run_row.error_message = str(exc)[:2000]
                db.commit()
        except Exception:
            pass
        return {"status": "failed", "error": str(exc)[:500]}
    finally:
        db.close()


class CourseCatalogRefreshScheduler:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not COURSE_CATALOG_REFRESH_ENABLED:
            logger.info("Course catalog refresh: disabled (COURSE_CATALOG_REFRESH_ENABLED=false)")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="course-catalog-refresh",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Course catalog refresh: started (schedule=%02d:%02d UTC, batch=%d, target=%d/country, reverify=%dd)",
            COURSE_CATALOG_REFRESH_HOUR_UTC,
            COURSE_CATALOG_REFRESH_MINUTE_UTC,
            COURSE_CATALOG_DAILY_BATCH,
            COURSE_CATALOG_TARGET_PER_COUNTRY,
            COURSE_CATALOG_REVERIFY_DAYS,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                now_utc = datetime.now(timezone.utc)
                if _is_due_for_today(now_utc):
                    result = run_course_catalog_refresh_job(force=False)
                    if result.get("status") != "skipped":
                        logger.info("Course catalog refresh run result: %s", result)
            except Exception as exc:  # noqa: BLE001 — the loop must never die
                logger.warning("Course catalog refresh loop error: %s", exc)
            self._stop_event.wait(COURSE_CATALOG_REFRESH_POLL_SECONDS)


_scheduler = CourseCatalogRefreshScheduler()


def start_course_catalog_refresh_scheduler() -> None:
    _scheduler.start()


def stop_course_catalog_refresh_scheduler() -> None:
    _scheduler.stop()
