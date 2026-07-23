"""Public careers hub API — job listings + job-application endpoint.

The careers hub (static/careers.html, served at /careers and /careers/{slug}) reads the
job catalog from here and posts applications back. Every application is emailed — all
fields plus the uploaded resume as an attachment — to the careers inbox (contact@rilono.com
by default, overridable via CAREERS_EMAIL). No authentication required; IP rate-limited.

- GET  /api/careers/positions   list open job postings (source of truth: careers_catalog)
- POST /api/careers/apply       multipart form: applicant fields + resume file
"""
import os
import re

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app import careers_catalog
from app.email_service import (
    send_job_application_email,
    send_job_application_ack_email,
)
from app.utils.rate_limiter import check_ip_rate_limit

router = APIRouter(prefix="/api/careers", tags=["careers"])

# Applications are heavier (file upload) and rarer than contact messages, so a tight cap.
CAREERS_RATE_LIMIT = int(os.getenv("CAREERS_RATE_LIMIT", "5"))
CAREERS_RATE_WINDOW_SECONDS = int(os.getenv("CAREERS_RATE_WINDOW_SECONDS", "3600"))

MAX_RESUME_BYTES = int(os.getenv("CAREERS_MAX_RESUME_BYTES", str(8 * 1024 * 1024)))  # 8 MB

# Accept the common resume formats. Keyed by extension; value is the canonical MIME type.
ALLOWED_RESUME_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".rtf": "application/rtf",
    ".txt": "text/plain",
    ".odt": "application/vnd.oasis.opendocument.text",
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean(value: str | None, limit: int) -> str:
    """Collapse newlines, trim, and cap length for a single-line field."""
    return re.sub(r"[\r\n]+", " ", (value or "").strip())[:limit]


@router.get("/positions")
def list_positions():
    """Open job postings, rendered by the careers hub. Public, no auth."""
    jobs = careers_catalog.list_jobs()
    return {"positions": jobs, "count": len(jobs)}


@router.post("/apply")
async def submit_job_application(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    position: str = Form(""),
    phone: str = Form(""),
    location: str = Form(""),
    links: str = Form(""),
    cover_note: str = Form(""),
    resume: UploadFile = File(...),
):
    """Accept a job application and email it (with the resume) to the careers inbox."""
    _enforce_rate_limit(
        request,
        scope="careers.apply",
        limit=CAREERS_RATE_LIMIT,
        window_seconds=CAREERS_RATE_WINDOW_SECONDS,
    )

    name = _clean(full_name, 120)
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Please provide your full name.")

    applicant_email = _clean(email, 254)
    if not _EMAIL_RE.match(applicant_email):
        raise HTTPException(status_code=400, detail="Please provide a valid email address.")

    phone_clean = _clean(phone, 40)
    location_clean = _clean(location, 120)
    links_clean = _clean(links, 500)
    cover_clean = (cover_note or "").strip()[:5000]

    # Resolve the applied-for slug to a trustworthy title via the catalog. Unknown /
    # stale / tampered slugs collapse to the general "Talent Pool" label.
    position_key = _clean(position, 80).lower()
    role = careers_catalog.resolve_position_title(position_key)

    # Validate the resume: extension, size, and non-empty.
    original_name = _clean(resume.filename or "", 200) or "resume"
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in ALLOWED_RESUME_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Resume must be a PDF, DOC, DOCX, RTF, ODT, or TXT file.",
        )

    max_mb = MAX_RESUME_BYTES // (1024 * 1024)
    # Cheap early reject when the client advertised a size (Content-Length of the part).
    if getattr(resume, "size", None) and resume.size > MAX_RESUME_BYTES:
        raise HTTPException(status_code=400, detail=f"Resume is too large (max {max_mb} MB).")

    # Bounded read: pull at most MAX+1 bytes so an oversized upload can't balloon memory.
    resume_bytes = await resume.read(MAX_RESUME_BYTES + 1)
    if not resume_bytes:
        raise HTTPException(status_code=400, detail="Your resume file appears to be empty.")
    if len(resume_bytes) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=400, detail=f"Resume is too large (max {max_mb} MB).")

    content_type = (resume.content_type or "").strip() or ALLOWED_RESUME_TYPES[ext]

    sent = send_job_application_email(
        full_name=name,
        email=applicant_email,
        position=role,
        phone=phone_clean,
        location=location_clean,
        links=links_clean,
        cover_note=cover_clean,
        resume_bytes=resume_bytes,
        resume_filename=original_name,
        resume_content_type=content_type,
    )

    if not sent:
        raise HTTPException(
            status_code=500,
            detail="We couldn't submit your application right now. Please try again shortly, "
                   "or email your resume to contact@rilono.com.",
        )

    # Warm acknowledgement to the applicant — best-effort, never fails the submit.
    try:
        send_job_application_ack_email(to_email=applicant_email, full_name=name, position=role)
    except Exception:
        pass

    return {"message": "Thanks for applying! We've received your application and will be in touch."}


def _enforce_rate_limit(request: Request, scope: str, limit: int, window_seconds: int) -> None:
    allowed, retry_after = check_ip_rate_limit(
        request=request,
        scope=scope,
        limit=limit,
        window_seconds=window_seconds,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many applications from this network. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )
