"""
Reference files attached to enterprise calendar events.

Staff pin the things they will actually need in the room to the event itself — a VFS
appointment letter, the agenda for a counselling call, a checklist to run through, the
courier receipt to quote. Those do not belong in the client's document locker: a calendar
event is often about no single client at all (team meetings, office deadlines), and "the
file for Tuesday 3pm" is a different retrieval problem from "this student's passport".

Storage model — deliberately identical to every other private file in the enterprise app
(see app/enterprise_storage.py):

  * Bytes go to Cloudflare R2 under an unguessable key, encrypted at rest, so a bucket or
    credential leak exposes nothing readable.
  * Nothing is ever served from a public URL. The only way back out is the authenticated,
    org-scoped download endpoint, which derives Content-Type from the validated extension
    rather than from anything the uploader claimed.
  * The row is the index, the blob is the payload. Rows are deleted first and blobs second,
    so a rolled-back commit can never leave a live row pointing at bytes that are gone.

Draft lifecycle: a brand-new reminder has no id yet, and the calendar form posts JSON (so a
file input cannot ride along on submit). Files therefore upload immediately — for an event
that already exists they bind straight to it, and for one still being composed they land
under a per-modal `draft_token` with `event_id = NULL` and are bound when the event saves.
This is the same draft-then-bind dance the email composer does, keyed on a token rather than
on the uploader alone so a cancelled modal's files can never leak into the next reminder.
Abandoned drafts are swept on the next upload, so a closed modal cannot slowly fill the
bucket.

These files are INTERNAL. They are not exposed in the client portal and are never attached
to the reminder emails the daily job sends clients — a consultant's checklist for a case is
not the student's to read.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Iterable, Optional

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app import enterprise_storage, models

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Limits. Generous enough for real agency paperwork, small enough that a
# compromised editor account cannot use the calendar as free object storage.
# There is no per-org storage quota anywhere in this app; these caps and the
# endpoint's rate limit are the only ceilings, so they have to be real ones.
# ---------------------------------------------------------------------------

MAX_FILES_PER_EVENT = int(os.getenv("ENTERPRISE_CAL_ATTACH_MAX_FILES", "6"))
MAX_BYTES_PER_FILE = int(os.getenv("ENTERPRISE_CAL_ATTACH_MAX_BYTES", str(15 * 1024 * 1024)))
MAX_BYTES_PER_EVENT = int(os.getenv("ENTERPRISE_CAL_ATTACH_MAX_TOTAL_BYTES", str(40 * 1024 * 1024)))
# How long an abandoned draft upload survives before the next sweep reclaims it.
DRAFT_TTL_HOURS = int(os.getenv("ENTERPRISE_CAL_ATTACH_DRAFT_TTL_HOURS", "24"))
DRAFT_TOKEN_MAX_LEN = 64

# Kept in step with ENTERPRISE_DOC_ALLOWED_EXT in routers/enterprise.py rather than imported
# from it — importing the router here would close an import cycle (the router imports this
# module). Same safe set: no executables, no archives, nothing that runs.
ALLOWED_EXT: frozenset[str] = frozenset({
    ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic",
    ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt",
})
# Types a browser may render in a tab. Everything else downloads.
INLINE_EXT: frozenset[str] = frozenset({".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif"})
# The served Content-Type comes from THIS map, keyed by the validated extension — never from
# the stored mime_type. A file named *.pdf can arrive claiming text/html with a <script>
# body; served inline under this app's 'unsafe-inline' CSP that would execute on the
# workspace origin (session theft). Deriving from the extension makes that impossible.
EXT_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif", ".heic": "image/heic",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv", ".txt": "text/plain",
}

UNSUPPORTED_TYPE_MESSAGE = (
    "Unsupported file type. Attach a PDF, image, Word/Excel file, CSV or text file."
)


class CalendarFileError(Exception):
    """A rejection whose message the user should read verbatim. Callers raise HTTP 400 with it."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def safe_filename(name: str) -> str:
    """Strip any path, quote or newline, so a filename can never forge a header."""
    base = os.path.basename(str(name or "").strip()) or "file"
    base = re.sub(r"[\r\n\"]+", "", base)
    return base[:160]


def extension_of(filename: str) -> str:
    return os.path.splitext(safe_filename(filename))[1].lower()


def human_size(num_bytes: int) -> str:
    value = float(max(0, int(num_bytes or 0)))
    if value < 1024:
        return f"{int(value)} B"
    for unit in ("KB", "MB", "GB"):
        value /= 1024
        if value < 1024 or unit == "GB":
            text = f"{value:.1f}"
            return f"{text[:-2] if text.endswith('.0') else text} {unit}"
    return f"{value:.1f} GB"


def normalize_draft_token(raw: Optional[str]) -> Optional[str]:
    """Opaque client-generated modal id. Constrained to a short safe alphabet because it
    reaches a SQL filter and a log line — never rendered, never a path segment."""
    token = re.sub(r"[^A-Za-z0-9_-]", "", str(raw or "").strip())[:DRAFT_TOKEN_MAX_LEN]
    return token or None


def storage_key_for(organization_id: int, ext: str) -> str:
    """An unguessable key. Calendar files are org-scoped rather than client-scoped: plenty
    of events (team meetings, office deadlines) belong to no client at all."""
    return f"enterprise/{int(organization_id)}/calendar/{uuid.uuid4().hex}{ext}"


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def serialize(row: models.EnterpriseCalendarEventAttachment) -> dict:
    return {
        "id": row.id,
        "event_id": row.event_id,
        "filename": row.original_filename,
        "file_size": row.file_size,
        "size_label": human_size(row.file_size or 0),
        "uploaded_by_name": row.uploaded_by_name,
        "created_at": _iso(row.created_at),
        "download_url": f"/api/enterprise/calendar/attachments/{row.id}/download",
        # Lets the UI pick "open in a tab" vs "download" without re-deriving the rule the
        # download endpoint actually enforces.
        "inline": extension_of(row.original_filename) in INLINE_EXT,
    }


def download_headers_for(filename: str) -> tuple[str, str]:
    """(media_type, content_disposition) for an already-validated filename."""
    ext = extension_of(filename)
    if ext in INLINE_EXT:
        return EXT_MIME.get(ext, "application/octet-stream"), "inline"
    return "application/octet-stream", "attachment"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_new_file(
    *,
    filename: str,
    size: int,
    existing_count: int,
    existing_bytes: int,
) -> str:
    """Check one incoming file against the per-event caps. Returns the validated extension,
    or raises CalendarFileError carrying a message written for the user."""
    ext = extension_of(filename)
    if ext not in ALLOWED_EXT:
        raise CalendarFileError(UNSUPPORTED_TYPE_MESSAGE)
    if size <= 0:
        raise CalendarFileError("That file is empty.")
    if size > MAX_BYTES_PER_FILE:
        raise CalendarFileError(
            f"Each file can be up to {human_size(MAX_BYTES_PER_FILE)}. Compress it, or add it "
            "to the client's documents instead."
        )
    if existing_count >= MAX_FILES_PER_EVENT:
        raise CalendarFileError(f"An event can hold {MAX_FILES_PER_EVENT} reference files.")
    if existing_bytes + size > MAX_BYTES_PER_EVENT:
        raise CalendarFileError(
            f"Reference files for one event can total {human_size(MAX_BYTES_PER_EVENT)}."
        )
    return ext


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def _base_query(db: Session, organization_id: int):
    return db.query(models.EnterpriseCalendarEventAttachment).filter(
        models.EnterpriseCalendarEventAttachment.organization_id == int(organization_id)
    )


def for_event(db: Session, organization_id: int, event_id: int) -> list:
    return (
        _base_query(db, organization_id)
        .filter(models.EnterpriseCalendarEventAttachment.event_id == int(event_id))
        .order_by(models.EnterpriseCalendarEventAttachment.id.asc())
        .all()
    )


def for_draft(db: Session, organization_id: int, token: str, user_id: int) -> list:
    """This user's still-unbound uploads for one modal session. Scoped to the uploader as
    well as the token so a guessed token can never reach someone else's file."""
    if not token:
        return []
    return (
        _base_query(db, organization_id)
        .filter(
            models.EnterpriseCalendarEventAttachment.event_id.is_(None),
            models.EnterpriseCalendarEventAttachment.draft_token == token,
            models.EnterpriseCalendarEventAttachment.uploaded_by_user_id == int(user_id),
        )
        .order_by(models.EnterpriseCalendarEventAttachment.id.asc())
        .all()
    )


def _usage(rows: Iterable) -> tuple[int, int]:
    rows = list(rows)
    return len(rows), sum(int(r.file_size or 0) for r in rows)


def usage_for_event(db: Session, organization_id: int, event_id: int) -> tuple[int, int]:
    return _usage(for_event(db, organization_id, event_id))


def usage_for_draft(db: Session, organization_id: int, token: str, user_id: int) -> tuple[int, int]:
    return _usage(for_draft(db, organization_id, token, user_id))


def lists_by_event(db: Session, organization_id: int, event_ids: Iterable[int]) -> dict[int, list[dict]]:
    """Batch-load serialized attachments for a whole calendar page in ONE query.

    The month view serializes up to 100 days of events and /calendar/upcoming re-runs the
    same collection on every badge refresh, so a per-event lookup here would be a
    guaranteed N+1 on the app's most-polled endpoint.
    """
    ids = [int(i) for i in event_ids if i]
    if not ids:
        return {}
    out: dict[int, list[dict]] = {}
    rows = (
        _base_query(db, organization_id)
        .filter(models.EnterpriseCalendarEventAttachment.event_id.in_(ids))
        .order_by(models.EnterpriseCalendarEventAttachment.id.asc())
        .all()
    )
    for row in rows:
        out.setdefault(int(row.event_id), []).append(serialize(row))
    return out


def counts_by_event(db: Session, organization_id: int, event_ids: Iterable[int]) -> dict[int, int]:
    """Paperclip counts only, for callers that don't need the filenames."""
    ids = [int(i) for i in event_ids if i]
    if not ids:
        return {}
    rows = (
        db.query(
            models.EnterpriseCalendarEventAttachment.event_id,
            sa_func.count(models.EnterpriseCalendarEventAttachment.id),
        )
        .filter(
            models.EnterpriseCalendarEventAttachment.organization_id == int(organization_id),
            models.EnterpriseCalendarEventAttachment.event_id.in_(ids),
        )
        .group_by(models.EnterpriseCalendarEventAttachment.event_id)
        .all()
    )
    return {int(event_id): int(total) for event_id, total in rows if event_id}


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def store(
    db: Session,
    *,
    organization_id: int,
    event_id: Optional[int],
    draft_token: Optional[str],
    filename: str,
    data: bytes,
    content_type: Optional[str],
    uploaded_by_user_id: Optional[int],
    uploaded_by_name: Optional[str],
    ext: str,
) -> models.EnterpriseCalendarEventAttachment:
    """Put the bytes in R2, then add (not commit) the row, so the caller decides the
    transaction boundary."""
    key = storage_key_for(organization_id, ext)
    enterprise_storage.store_document(key, data, content_type=content_type)
    row = models.EnterpriseCalendarEventAttachment(
        organization_id=int(organization_id),
        event_id=int(event_id) if event_id else None,
        draft_token=(None if event_id else draft_token),
        original_filename=safe_filename(filename),
        storage_key=key,
        file_size=len(data),
        mime_type=(content_type or None),
        uploaded_by_user_id=uploaded_by_user_id,
        uploaded_by_name=uploaded_by_name,
    )
    db.add(row)
    return row


def bind_draft_to_event(
    db: Session,
    *,
    organization_id: int,
    user_id: int,
    token: Optional[str],
    event_id: int,
) -> list:
    """Attach the caller's own pending uploads for `token` to a freshly created event.

    Scoped to (org, uploader, token, event_id IS NULL), so a supplied token can never steal
    another member's file or re-point one already bound elsewhere. An unknown or expired
    token binds nothing and is NOT an error — the reminder still saves. Anything over the
    caps is left behind as a draft for the sweep rather than silently attached.
    """
    token = normalize_draft_token(token)
    if not token:
        return []
    rows = for_draft(db, organization_id, token, user_id)
    bound: list = []
    running = 0
    for row in rows:
        if len(bound) >= MAX_FILES_PER_EVENT:
            break
        size = int(row.file_size or 0)
        if running + size > MAX_BYTES_PER_EVENT:
            continue
        row.event_id = int(event_id)
        row.draft_token = None
        running += size
        bound.append(row)
    return bound


def sweep_stale_drafts(db: Session, *, organization_id: int, user_id: int) -> list[str]:
    """Delete this user's abandoned draft rows (modal closed without saving) and return their
    storage keys.

    Rows only — the caller drops the blobs AFTER its commit succeeds. Deleting bytes first
    would, on a rolled-back commit, leave surviving rows pointing at files that are gone.
    Never raises: a failed sweep must not fail the upload that triggered it.
    """
    cutoff = datetime.now(dt_timezone.utc) - timedelta(hours=DRAFT_TTL_HOURS)
    keys: list[str] = []
    try:
        stale = (
            _base_query(db, organization_id)
            .filter(
                models.EnterpriseCalendarEventAttachment.event_id.is_(None),
                models.EnterpriseCalendarEventAttachment.uploaded_by_user_id == int(user_id),
                models.EnterpriseCalendarEventAttachment.created_at < cutoff,
            )
            .limit(50)
            .all()
        )
        for row in stale:
            keys.append(row.storage_key)
            db.delete(row)
    except Exception:
        logger.exception("Calendar draft attachment sweep failed (org_id=%s)", organization_id)
    return keys


def discard_draft(db: Session, *, organization_id: int, user_id: int, token: Optional[str]) -> list[str]:
    """Drop a cancelled modal's uploads immediately. Best-effort courtesy on top of the TTL
    sweep — Escape and overlay-click close the modal with no hook to fire this at all, so it
    can never be the only cleanup."""
    keys: list[str] = []
    try:
        for row in for_draft(db, organization_id, normalize_draft_token(token) or "", user_id):
            keys.append(row.storage_key)
            db.delete(row)
    except Exception:
        logger.exception("Calendar draft discard failed (org_id=%s)", organization_id)
    return keys


def purge_for_events(db: Session, *, organization_id: int, event_ids: Iterable[int]) -> list[str]:
    """Delete the attachment rows of events about to be deleted, returning their storage keys
    so the caller can drop the blobs after committing.

    Called explicitly rather than leaning on ON DELETE CASCADE: the cascade tidies rows (and
    only where the dialect actually enforces FKs — the local sqlite sandbox never issues
    PRAGMA foreign_keys=ON) but nothing tidies R2, and an orphaned ciphertext blob is a bill
    and a liability forever.
    """
    ids = [int(i) for i in event_ids if i]
    if not ids:
        return []
    keys: list[str] = []
    try:
        for row in (
            _base_query(db, organization_id)
            .filter(models.EnterpriseCalendarEventAttachment.event_id.in_(ids))
            .all()
        ):
            keys.append(row.storage_key)
            db.delete(row)
    except Exception:
        logger.exception(
            "Failed to purge calendar attachments (org_id=%s, events=%s)", organization_id, ids[:20]
        )
    return keys


def keys_for_client(db: Session, *, organization_id: int, client_id: int) -> list[str]:
    """Storage keys of every calendar attachment belonging to a client's events — rows left
    alone, for callers that let the DB cascade tidy rows and only need to tell R2.

    Joins through the event because the attachment deliberately carries no client_id of its
    own: the event owns that link and can be re-pointed at another client on edit.
    """
    rows = (
        db.query(models.EnterpriseCalendarEventAttachment.storage_key)
        .join(
            models.EnterpriseCalendarEvent,
            models.EnterpriseCalendarEvent.id == models.EnterpriseCalendarEventAttachment.event_id,
        )
        .filter(
            models.EnterpriseCalendarEvent.client_id == int(client_id),
            models.EnterpriseCalendarEventAttachment.organization_id == int(organization_id),
        )
        .all()
    )
    return [key for (key,) in rows if key]


def purge_for_client(db: Session, *, organization_id: int, client_id: int) -> list[str]:
    """Same, for every calendar event belonging to a client being deleted.

    A client delete cascades to their calendar events, which would cascade these rows away
    without ever telling R2 — so the keys have to be collected up front. Joins through the
    event because the attachment deliberately carries no client_id of its own: the event owns
    that link and can be re-pointed at another client on edit.
    """
    event_ids = [
        int(row[0])
        for row in db.query(models.EnterpriseCalendarEvent.id)
        .filter(
            models.EnterpriseCalendarEvent.organization_id == int(organization_id),
            models.EnterpriseCalendarEvent.client_id == int(client_id),
        )
        .all()
    ]
    return purge_for_events(db, organization_id=organization_id, event_ids=event_ids)


def drop_blobs(keys: Iterable[str]) -> None:
    """Best-effort blob cleanup, always AFTER the commit. delete_document swallows its own
    errors, so a blob that is already gone can never block the DB change that preceded it."""
    for key in keys or ():
        if key:
            enterprise_storage.delete_document(key)
