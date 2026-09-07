"""Compatibility entry points for the retired latest-news ingestion service.

Latest-news generation is permanently disabled, including forced/manual runs.
Existing stored news records are retained. This module deliberately imports no
AI client, database session, or scheduler and does not read an enablement flag.
Published applicant experiences remain implemented independently in the news router.
"""
from typing import Dict, List

F1_NEWS_INGESTION_ENABLED = False


def _disabled_result() -> dict:
    return {"status": "disabled", "enabled": False,
            "reason": "latest_news_service_disabled", "destinations": {}}


class F1VisaNewsIngestionScheduler:
    """Inert adapter for any old startup caller still importing this service."""

    def __init__(self) -> None:
        self._thread = None

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def _run_loop(self) -> None:
        return None


def _fetch_new_items_from_gemini(destination_code: str = "US") -> List[Dict[str, str]]:
    """Retired direct-fetch entry point; no model or network request is made."""
    return []


def run_f1_news_ingestion_job(force: bool = False) -> dict:
    """Neither a normal nor a forced invocation can reactivate the retired feed."""
    return _disabled_result()


_scheduler = F1VisaNewsIngestionScheduler()


def start_f1_news_ingestion_scheduler() -> None:
    return None


def stop_f1_news_ingestion_scheduler() -> None:
    return None
