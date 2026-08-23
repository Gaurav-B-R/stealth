"""University shortlist helpers shared by the B2C shortlist router, the B2C Course Finder
and the enterprise per-client shortlist: entry serialization, status normalization and
the URL/rank sanitizers applied to AI-authored values before they are stored.

The Gemini recommendation engine that used to live here (recommend_universities and its
prompt/parser) was removed on 2026-08-22 together with the "Shortlist & Recommendations"
page and the enterprise per-client "AI shortlist" route — Course Finder's catalog-grounded
AI shortlist (app/course_catalog.py) replaced both.
"""
from __future__ import annotations

import json
import re
from typing import Optional

VALID_STATUSES = ("considering", "applied", "admitted", "rejected")
DEFAULT_STATUS = "considering"


def _clean_url(value) -> Optional[str]:
    """Only http(s) absolute URLs survive.

    These are rendered as clickable links, so anything else (javascript:, data:, a bare
    hostname, or the model's "N/A") must be dropped rather than trusted — a model-authored
    `javascript:` href would otherwise be a stored-XSS vector. Quotes/angle-brackets/
    backticks are rejected too: they are never needed in a real URL, and a quote inside
    an href attribute breaks out of it (`.../x"onmouseover="...`) even when the scheme
    is a legitimate https.
    """
    s = str(value or "").strip()
    if not s or s.lower() in {"n/a", "na", "none", "null", "unknown", "-"}:
        return None
    if any(c in s for c in "\"'<>`"):
        return None
    if not re.match(r"^https?://[^\s/$.?#].[^\s]*$", s, re.I):
        return None
    return s[:400]


def _clean_rank(value) -> Optional[str]:
    """Normalize a ranking value to a short display string, or None when unknown."""
    s = str(value or "").strip().lstrip("#").strip()
    if not s or s.lower() in {"n/a", "na", "none", "null", "unknown", "unranked", "-"}:
        return None
    return s[:20]


def serialize_entry(entry) -> dict:
    try:
        requirements = json.loads(entry.key_requirements) if getattr(entry, "key_requirements", None) else []
        if not isinstance(requirements, list):
            requirements = []
    except Exception:
        requirements = []
    return {
        "id": int(entry.id),
        "university_name": entry.university_name,
        "program": entry.program,
        "location": entry.location,
        "country_code": entry.country_code,
        "status": entry.status or DEFAULT_STATUS,
        "source": entry.source or "manual",
        "est_tuition": entry.est_tuition,
        "rationale": entry.rationale,
        "notes": entry.notes,
        "qs_world_rank": getattr(entry, "qs_world_rank", None),
        "country_rank": getattr(entry, "country_rank", None),
        "admission_difficulty": getattr(entry, "admission_difficulty", None),
        "key_requirements": [str(r)[:140] for r in requirements][:6],
        "application_fee": getattr(entry, "application_fee", None),
        "website_url": getattr(entry, "website_url", None),
        "admissions_url": getattr(entry, "admissions_url", None),
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def normalize_status(raw: str | None) -> str:
    value = str(raw or "").strip().lower()
    return value if value in VALID_STATUSES else DEFAULT_STATUS
