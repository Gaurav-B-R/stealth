"""Careers catalog — the single source of truth for open job postings.

The public careers hub (static/careers.html, served at /careers) renders this list, and
/api/careers/apply validates the applied-for position against it so the emailed role is
always trustworthy (never attacker-controlled free text).

To open a new role: add a dict to JOBS. To close one: set "open": False (or remove it).
Everything else — the listing card, the detail page, the apply form, the JobPosting SEO
data — is generated from this structure automatically.
"""
from __future__ import annotations

from typing import Optional

# A pseudo-slug for open/general applications ("don't see your role? introduce yourself").
TALENT_POOL_SLUG = "talent-pool"
TALENT_POOL_TITLE = "General Application · Talent Pool"

JOBS: list[dict] = [
    {
        "slug": "ai-product-tester-intern",
        "title": "AI Product Tester Intern (QA)",
        "team": "Quality & AI Safety",
        "type": "Internship",
        "location": "Remote · Anywhere",
        "openings": 2,
        "posted": "2026-07-22",
        "employment_type": "INTERN",  # schema.org JobPosting value
        "tagline": "Red-team our AI, break our workflows, and help catch bugs before a "
                   "student's visa ever depends on them.",
        "about": "Rilono is an AI-powered immigration tech startup. We use advanced AI to audit "
                 "complex financial documents, conduct voice mock interviews, and prevent visa "
                 "rejections for international students.",
        "role": "We are looking for a detail-oriented AI Product Tester Intern with a “hacker” "
                "mindset. Your mission is to rigorously test our AI agents and web workflows to find "
                "edge cases, logic flaws, and bugs before we ship new features.",
        "responsibilities": [
            {
                "title": "AI Red-Teaming",
                "body": "Chat with our AI Visa Bot, intentionally trying to trick it, confuse it, "
                        "or make it generate inaccurate responses.",
            },
            {
                "title": "Document Auditing",
                "body": "Upload test documents (bank statements, passports) with intentional "
                        "mathematical errors to ensure our Rilono AI integration catches every mismatch.",
            },
            {
                "title": "Manual UI Testing",
                "body": "Navigate our B2C student portal and B2B CRM to ensure all paywalls, API "
                        "limits, and buttons function perfectly.",
            },
            {
                "title": "Bug Reporting",
                "body": "Clearly document UI glitches and prompt-hallucinations, working directly "
                        "with the Product Manager to improve the system.",
            },
        ],
        "requirements": [
            "No degree required — pure passion and effort matter.",
            "A strong eye for detail and a passion for User Experience (UX).",
            "Ability to think creatively about how software can break.",
            "Clear written communication skills for documenting reproduction steps.",
        ],
        "bonus": "Basic understanding of Prompt Engineering or the study-abroad / visa process.",
        "open": True,
    },
]


def list_jobs(include_closed: bool = False) -> list[dict]:
    """All postings, open ones first. Returns copies so callers can't mutate the catalog."""
    jobs = [dict(job) for job in JOBS if include_closed or job.get("open", True)]
    return jobs


def get_job(slug: Optional[str]) -> Optional[dict]:
    """Look up a single posting by slug (open postings only). None if not found."""
    if not slug:
        return None
    slug = slug.strip().lower()
    for job in JOBS:
        if job.get("slug") == slug and job.get("open", True):
            return dict(job)
    return None


def resolve_position_title(slug: Optional[str]) -> str:
    """Map an applied-for slug to a trustworthy, human-readable position title.

    Known open role -> its title. Talent-pool / empty / unknown -> the general label, so a
    tampered or stale slug can never inject arbitrary text into the emailed "position".
    """
    job = get_job(slug)
    if job:
        return job["title"]
    return TALENT_POOL_TITLE


def open_openings_count() -> int:
    return sum(int(job.get("openings", 1) or 0) for job in list_jobs())
