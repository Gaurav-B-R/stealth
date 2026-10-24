"""Files attached to Admin Console team tasks (console › Tasks).

Plenty of tasks are about something you can only show: the screenshot of the broken page,
the invoice that doesn't reconcile, the CSV a partner sent. Those files live on the task and
follow the task's rules exactly. Whoever can see the task can see and add its files, and
nobody else learns they exist (app/routers/admin_tasks.py does the checks).

Storage is the private, encrypted-at-rest object store the enterprise app already uses for
client documents (app/enterprise_storage.py): unguessable keys, ciphertext in the bucket, no
public URL. The only way back out is the authenticated download route, and it derives the
Content-Type from the validated extension, never from anything the uploader claimed.

Rows go first and blobs second. A delete commits the row removal before dropping the bytes,
so a rolled-back commit can never leave a live row pointing at a file that is gone.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
import uuid
from typing import Iterable
from urllib.parse import quote

from app import enterprise_storage

logger = logging.getLogger(__name__)

# A handful of screenshots and a short screen recording fit easily. The caps are real
# ceilings: nothing else meters this storage.
MAX_FILES_PER_TASK = int(os.getenv("ADMIN_TASK_ATTACH_MAX_FILES", "20"))
MAX_BYTES_PER_FILE = int(os.getenv("ADMIN_TASK_ATTACH_MAX_BYTES", str(25 * 1024 * 1024)))
MAX_BYTES_PER_TASK = int(os.getenv("ADMIN_TASK_ATTACH_MAX_TOTAL_BYTES", str(100 * 1024 * 1024)))
FILENAME_MAX = 160

# The served Content-Type comes from THIS map, keyed by the validated extension. No SVG or
# HTML, nothing executable, no archives: a file named *.png that is really markup must
# never render as markup on the console's origin.
EXT_MIME: dict[str, str] = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".gif": "image/gif", ".heic": "image/heic",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".csv": "text/csv", ".txt": "text/plain", ".md": "text/markdown", ".log": "text/plain",
    ".json": "application/json",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
}
ALLOWED_EXT = frozenset(EXT_MIME)
# Shown as thumbnails in the console. HEIC is accepted but browsers can't draw it.
PREVIEW_EXT = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
# Safe to open in a browser tab. Everything else, text included, downloads as opaque bytes.
INLINE_EXT = PREVIEW_EXT | {".pdf"}

UNSUPPORTED_TYPE_MESSAGE = ("That file type can't be attached. Use an image, PDF, Word, Excel or "
                            "PowerPoint file, CSV, text, JSON, or an MP4/MOV/WebM recording.")

_UNSAFE_NAME_CHARS = re.compile(r"[\x00-\x1f\x7f\"\\/]+")


class AttachmentError(Exception):
    """A rejection written for the person uploading. Callers answer HTTP 400 with it."""


def safe_filename(name: str | None) -> str:
    """The name as people will see it: no path, no control characters or quotes, and the
    extension kept even when a long name has to be shortened."""
    raw = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    # Unicode spacing (macOS puts U+202F in "Screenshot … at 2.03.12 PM.png") becomes plain spaces.
    raw = "".join(" " if unicodedata.category(char) in {"Zs", "Zl", "Zp"} else char for char in raw)
    base = " ".join(_UNSAFE_NAME_CHARS.sub(" ", raw).split()).strip(" .") or "file"
    if len(base) <= FILENAME_MAX:
        return base
    stem, ext = os.path.splitext(base)
    ext = ext[:16]
    return stem[:FILENAME_MAX - len(ext)].rstrip(" .") + ext


def extension_of(filename: str | None) -> str:
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


def validate(*, filename: str | None, size: int, existing_count: int, existing_bytes: int) -> str:
    """Check one incoming file against the type list and the per-task caps. Returns the
    validated extension, or raises AttachmentError with a message for the uploader."""
    ext = extension_of(filename)
    if ext not in ALLOWED_EXT:
        raise AttachmentError(UNSUPPORTED_TYPE_MESSAGE)
    if size <= 0:
        raise AttachmentError("That file is empty.")
    if size > MAX_BYTES_PER_FILE:
        raise AttachmentError(f"Each file can be up to {human_size(MAX_BYTES_PER_FILE)}.")
    if existing_count >= MAX_FILES_PER_TASK:
        raise AttachmentError(f"A task can hold {MAX_FILES_PER_TASK} files. Remove one to add another.")
    if existing_bytes + size > MAX_BYTES_PER_TASK:
        raise AttachmentError(f"A task's files can add up to {human_size(MAX_BYTES_PER_TASK)}.")
    return ext


def storage_key_for(task_id: int, ext: str) -> str:
    return f"admin/tasks/{int(task_id)}/{uuid.uuid4().hex}{ext}"


def is_configured() -> bool:
    return enterprise_storage.is_configured()


def store_blob(key: str, data: bytes) -> None:
    enterprise_storage.store_document(key, data)


def fetch_blob(key: str) -> bytes:
    return enterprise_storage.fetch_document(key)


def drop_blobs(keys: Iterable[str]) -> None:
    """Best effort and always AFTER the commit. delete_document swallows its own errors, so
    a blob that is already gone never blocks the database change before it."""
    for key in keys or ():
        if key:
            enterprise_storage.delete_document(key)


def download_headers(filename: str) -> tuple[str, dict[str, str]]:
    """(media_type, headers) for serving an already-stored file.

    Images and PDFs may render in a tab; everything else is opaque bytes that download.
    The filename goes out twice, as RFC 6266 asks: an ASCII fallback, and the real name
    UTF-8 encoded. Headers are latin-1 only, so a raw non-ASCII name would 500.
    """
    name = safe_filename(filename)
    ext = extension_of(name)
    inline = ext in INLINE_EXT
    media_type = EXT_MIME[ext] if inline else "application/octet-stream"
    stem = os.path.splitext(name)[0]
    ascii_stem = " ".join(unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii").split())
    fallback = f"{ascii_stem or 'file'}{ext}"
    disposition = (f"{'inline' if inline else 'attachment'}; filename=\"{fallback}\"; "
                   f"filename*=UTF-8''{quote(name, safe='')}")
    return media_type, {
        "Content-Disposition": disposition,
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
