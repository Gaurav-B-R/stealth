"""
Configurable document-retention sweep (data minimization).

Uploaded documents (passports, financial statements, transcripts, …) should not be kept
forever. When DOCUMENT_RETENTION_DAYS > 0, this background job periodically deletes documents
older than that many days, purging BOTH the R2 objects (file + extracted text) and the DB rows.

Default OFF (0): the retention PERIOD is a policy/legal decision, so nothing is deleted until an
operator sets DOCUMENT_RETENTION_DAYS. Whatever period you choose should be disclosed in the
privacy policy's Data Retention section.
"""

import os
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional

from app.database import SessionLocal
from app import models

logger = logging.getLogger(__name__)

DOCUMENT_RETENTION_DAYS = int(os.getenv("DOCUMENT_RETENTION_DAYS", "0") or "0")
DOCUMENT_RETENTION_SWEEP_INTERVAL_SECONDS = int(
    os.getenv("DOCUMENT_RETENTION_SWEEP_INTERVAL_SECONDS", str(24 * 3600)) or str(24 * 3600)
)
DOCUMENT_RETENTION_BATCH = int(os.getenv("DOCUMENT_RETENTION_BATCH", "500") or "500")


def _resolve_r2():
    try:
        from app.routers.documents import r2_client, R2_DOCUMENTS_BUCKET
        return r2_client, R2_DOCUMENTS_BUCKET
    except Exception:
        return None, None


def run_document_retention_sweep(retention_days: Optional[int] = None) -> dict:
    """Delete documents older than the retention window (R2 objects + DB rows). Best-effort.

    Pass retention_days to force a specific window (e.g. for a manual/admin run); otherwise the
    configured DOCUMENT_RETENTION_DAYS is used. Returns a small summary dict.
    """
    days = DOCUMENT_RETENTION_DAYS if retention_days is None else retention_days
    if days <= 0:
        return {"status": "disabled", "deleted": 0}

    cutoff = datetime.utcnow() - timedelta(days=days)
    r2_client, bucket = _resolve_r2()
    db = SessionLocal()
    deleted = 0
    try:
        docs = (
            db.query(models.Document)
            .filter(models.Document.created_at < cutoff)
            .limit(DOCUMENT_RETENTION_BATCH)
            .all()
        )
        for doc in docs:
            if r2_client is not None:
                for key in (doc.filename, doc.extracted_text_file_url):
                    if not key:
                        continue
                    try:
                        r2_client.delete_object(Bucket=bucket, Key=key)
                    except Exception:
                        logger.warning("retention: failed to delete R2 key=%s (doc_id=%s)", key, doc.id)
            db.delete(doc)
            deleted += 1
        db.commit()
        if deleted:
            logger.info("retention: deleted %s document(s) older than %s day(s)", deleted, days)
    except Exception:
        db.rollback()
        logger.exception("retention: sweep failed")
    finally:
        db.close()
    return {"status": "ok", "deleted": deleted, "cutoff": cutoff.isoformat()}


class DocumentRetentionScheduler:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if DOCUMENT_RETENTION_DAYS <= 0:
            logger.info("Document retention sweep disabled (DOCUMENT_RETENTION_DAYS=0).")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="document-retention", daemon=True)
        self._thread.start()
        logger.info(
            "Document retention sweep started (retention=%s days, interval=%ss).",
            DOCUMENT_RETENTION_DAYS,
            DOCUMENT_RETENTION_SWEEP_INTERVAL_SECONDS,
        )

    def stop(self) -> None:
        self._stop_event.set()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                run_document_retention_sweep()
            except Exception:
                logger.exception("retention: unexpected error in sweep loop")
            self._stop_event.wait(DOCUMENT_RETENTION_SWEEP_INTERVAL_SECONDS)


_scheduler = DocumentRetentionScheduler()


def start_document_retention_scheduler() -> None:
    _scheduler.start()


def stop_document_retention_scheduler() -> None:
    _scheduler.stop()
