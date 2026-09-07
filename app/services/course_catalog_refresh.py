"""Disabled catalog research entrypoints retained for older callers.

The catalog now uses stored records. Scheduled, direct and forced calls cannot
launch internet research, invoke AI, seed records or modify run history.
"""
from __future__ import annotations


# This is a product restriction, not an environment-controlled rollout flag.
COURSE_CATALOG_REFRESH_ENABLED = False
DISABLED_REASON = "internet_research_disabled"
DISABLED_MESSAGE = (
    "Automatic course catalog research and refresh are disabled. "
    "Course Finder uses stored catalog records maintained manually."
)


def run_course_catalog_refresh_job(
    force: bool = False,
    *,
    limit: int | None = None,
    countries: list[str] | None = None,
) -> dict:
    """Return without opening a database session or scheduling any work."""
    return {"status": "disabled", "reason": DISABLED_REASON, "message": DISABLED_MESSAGE,
            "universities_discovered": 0, "universities_refreshed": 0, "courses_upserted": 0}


class CourseCatalogRefreshScheduler:
    """Compatibility object: older startup hooks cannot restart research."""

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def _run_loop(self) -> None:
        return None


_scheduler = CourseCatalogRefreshScheduler()


def start_course_catalog_refresh_scheduler() -> None:
    return None


def stop_course_catalog_refresh_scheduler() -> None:
    return None
