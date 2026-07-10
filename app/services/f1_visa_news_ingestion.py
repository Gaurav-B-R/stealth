"""
Background scheduler that ingests student-visa news from Gemini once every 24 hours
and stores them in the f1_visa_news table — one scope per LAUNCH destination
(US, UK, CA, AU, …), so every student's news feed is pre-loaded, not just US F-1.
Users read pre-loaded data; the router's on-demand generation remains a fallback.

Architecture follows the exact same pattern as daily_ai_notifications.py.
"""

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app import models
from app.database import SessionLocal
from app.utils import gemini_service as gemini_utils

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

F1_NEWS_INGESTION_ENABLED = (
    str(os.getenv("F1_NEWS_INGESTION_ENABLED", "true")).strip().lower()
    in {"1", "true", "yes", "on"}
)
F1_NEWS_INGESTION_HOUR_UTC = max(
    0, min(23, int(os.getenv("F1_NEWS_INGESTION_HOUR_UTC", "8") or "8"))
)
F1_NEWS_INGESTION_MINUTE_UTC = max(
    0, min(59, int(os.getenv("F1_NEWS_INGESTION_MINUTE_UTC", "0") or "0"))
)
F1_NEWS_INGESTION_POLL_SECONDS = max(
    60, int(os.getenv("F1_NEWS_INGESTION_POLL_SECONDS", "300") or "300")
)
F1_NEWS_MAX_STORED_ITEMS = max(
    10, int(os.getenv("F1_NEWS_MAX_STORED_ITEMS", "50") or "50")
)


def _ingestion_destinations() -> list[str]:
    """Destination codes to prefetch news for. Defaults to the launched countries that
    the news router knows how to describe; override with F1_NEWS_DESTINATIONS=US,UK,…"""
    _ensure_news_helpers()
    raw = os.getenv("F1_NEWS_DESTINATIONS", "").strip()
    if raw:
        requested = [c.strip().upper() for c in raw.split(",") if c.strip()]
    else:
        from app import visa_catalog
        requested = list(visa_catalog.LAUNCH_COUNTRY_CODES)
    return [c for c in requested if c in _NEWS_DESTINATIONS] or ["US"]

# ---------------------------------------------------------------------------
# Lazy imports from news router (avoids circular-import at module load time)
# ---------------------------------------------------------------------------

_news_helpers_loaded = False
_build_latest_genai_client = None
_generate_content_with_grounding = None
_clean_and_parse_json = None
_normalize_items = None
_sanitize_item_published_date = None
_filter_recent_news_items = None
_extract_grounding_urls = None
_enrich_items_with_grounding_urls = None
_NEWS_MAX_ITEM_AGE_DAYS = 365
_ALLOW_NON_GROUNDED_NEWS_FALLBACK = False
_NEWS_DESTINATIONS: Dict[str, Dict[str, str]] = {}


def _ensure_news_helpers():
    """Import shared helpers from news router on first use."""
    global _news_helpers_loaded
    global _build_latest_genai_client, _generate_content_with_grounding
    global _clean_and_parse_json, _normalize_items
    global _sanitize_item_published_date, _filter_recent_news_items
    global _extract_grounding_urls, _enrich_items_with_grounding_urls
    global _NEWS_MAX_ITEM_AGE_DAYS, _ALLOW_NON_GROUNDED_NEWS_FALLBACK
    global _NEWS_DESTINATIONS

    if _news_helpers_loaded:
        return

    from app.routers.news import (
        _build_latest_genai_client as _blgc,
        _generate_content_with_grounding as _gcwg,
        _clean_and_parse_json as _capj,
        _normalize_items as _ni,
        _sanitize_item_published_date as _sipd,
        _filter_recent_news_items as _frni,
        _extract_grounding_urls as _egu,
        _enrich_items_with_grounding_urls as _eiwgu,
        NEWS_MAX_ITEM_AGE_DAYS,
        ALLOW_NON_GROUNDED_NEWS_FALLBACK,
        NEWS_DESTINATIONS,
    )

    _build_latest_genai_client = _blgc
    _generate_content_with_grounding = _gcwg
    _clean_and_parse_json = _capj
    _normalize_items = _ni
    _sanitize_item_published_date = _sipd
    _filter_recent_news_items = _frni
    _extract_grounding_urls = _egu
    _enrich_items_with_grounding_urls = _eiwgu
    _NEWS_MAX_ITEM_AGE_DAYS = NEWS_MAX_ITEM_AGE_DAYS
    _ALLOW_NON_GROUNDED_NEWS_FALLBACK = ALLOW_NON_GROUNDED_NEWS_FALLBACK
    _NEWS_DESTINATIONS = NEWS_DESTINATIONS
    _news_helpers_loaded = True


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class F1VisaNewsIngestionScheduler:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not F1_NEWS_INGESTION_ENABLED:
            print("F1 news ingestion: disabled (F1_NEWS_INGESTION_ENABLED=false)")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="f1-news-ingestion",
            daemon=True,
        )
        self._thread.start()
        print(
            f"F1 news ingestion: started "
            f"(schedule={F1_NEWS_INGESTION_HOUR_UTC:02d}:{F1_NEWS_INGESTION_MINUTE_UTC:02d} UTC, "
            f"poll={F1_NEWS_INGESTION_POLL_SECONDS}s)"
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
                    result = run_f1_news_ingestion_job(force=False)
                    if result.get("status") != "skipped":
                        print(f"F1 news ingestion run result: {result}")
            except Exception as exc:  # noqa: BLE001
                print(f"F1 news ingestion loop error: {str(exc)}")
            self._stop_event.wait(F1_NEWS_INGESTION_POLL_SECONDS)


# ---------------------------------------------------------------------------
# Scheduling helpers
# ---------------------------------------------------------------------------

def _is_due_for_today(now_utc: datetime) -> bool:
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    target = now_utc.replace(
        hour=F1_NEWS_INGESTION_HOUR_UTC,
        minute=F1_NEWS_INGESTION_MINUTE_UTC,
        second=0,
        microsecond=0,
    )
    return now_utc >= target


# Completed-today marker per destination. The DB check below only sees runs that
# INSERTED rows — a run that found "no new items" writes nothing, and without this
# guard the scheduler would re-call Gemini every poll (~5 min) for the rest of the
# day for that destination. In-memory is fine: a restart costs at most one extra
# check per destination.
_last_completed_utc_date: Dict[str, str] = {}


def _mark_completed_today(destination_code: str) -> None:
    _last_completed_utc_date[destination_code] = datetime.now(timezone.utc).date().isoformat()


def _already_ran_today(destination_code: str = "US") -> bool:
    """Check if ingestion already ran today for this destination (most recent ingested_at)."""
    if _last_completed_utc_date.get(destination_code) == datetime.now(timezone.utc).date().isoformat():
        return True
    db = SessionLocal()
    try:
        latest = (
            db.query(models.F1VisaNewsItem)
            .filter(models.F1VisaNewsItem.destination_country_code == destination_code)
            .order_by(models.F1VisaNewsItem.ingested_at.desc())
            .first()
        )
        if not latest or not latest.ingested_at:
            return False
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        ingested = latest.ingested_at
        if ingested.tzinfo is None:
            ingested = ingested.replace(tzinfo=timezone.utc)
        return ingested >= today_start
    finally:
        db.close()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _load_existing_news_items(db, destination_code: str = "US") -> List[Dict[str, str]]:
    """Load this destination's current items from DB to provide as dedupe context to Gemini."""
    items = (
        db.query(models.F1VisaNewsItem)
        .filter(models.F1VisaNewsItem.destination_country_code == destination_code)
        .order_by(models.F1VisaNewsItem.ingested_at.desc())
        .limit(F1_NEWS_MAX_STORED_ITEMS)
        .all()
    )
    return [
        {
            "title": item.title,
            "summary": item.summary,
            "why_it_matters": item.why_it_matters or "",
            "source_name": item.source_name,
            "source_url": item.source_url or "",
            "published_date": item.published_date or "unknown",
        }
        for item in items
    ]


def _merge_and_trim(db, new_items: List[Dict[str, str]], destination_code: str = "US") -> int:
    """Insert new items into this destination's scope, then trim to the latest N items."""
    if not new_items:
        return 0

    now_utc = datetime.now(timezone.utc)
    for item in new_items:
        news_row = models.F1VisaNewsItem(
            destination_country_code=destination_code,
            title=item["title"],
            summary=item["summary"],
            why_it_matters=item.get("why_it_matters", ""),
            source_name=item.get("source_name", "Source"),
            source_url=item.get("source_url", ""),
            published_date=item.get("published_date", "unknown"),
            ingested_at=now_utc,
        )
        db.add(news_row)
    db.commit()

    # Trim: keep only the most recent F1_NEWS_MAX_STORED_ITEMS (this scope only).
    total_count = (
        db.query(models.F1VisaNewsItem)
        .filter(models.F1VisaNewsItem.destination_country_code == destination_code)
        .count()
    )
    if total_count > F1_NEWS_MAX_STORED_ITEMS:
        excess = total_count - F1_NEWS_MAX_STORED_ITEMS
        oldest_to_delete = (
            db.query(models.F1VisaNewsItem)
            .filter(models.F1VisaNewsItem.destination_country_code == destination_code)
            .order_by(
                models.F1VisaNewsItem.ingested_at.asc(),
                models.F1VisaNewsItem.id.asc(),
            )
            .limit(excess)
            .all()
        )
        for old_item in oldest_to_delete:
            db.delete(old_item)
        db.commit()

    return len(new_items)


# ---------------------------------------------------------------------------
# Gemini interaction
# ---------------------------------------------------------------------------

MODEL_CANDIDATES = gemini_utils.get_model_candidates(
    primary_env="F1_NEWS_MODEL",
    candidates_env="F1_NEWS_MODEL_CANDIDATES",
    defaults=[
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
    ],
)


def _build_ingestion_prompt(
    existing_items: List[Dict[str, str]],
    destination_name: str = "the United States",
    visa_label: str = "F-1 student visa",
) -> str:
    now_utc_iso = datetime.now(timezone.utc).isoformat()

    if existing_items:
        existing_json = json.dumps(existing_items, indent=2)
        existing_context = f"""
Here are the news items we ALREADY have stored. Do NOT repeat any of these.
Only return genuinely NEW items that are not already covered below:

EXISTING ITEMS (DO NOT REPEAT THESE):
{existing_json}
"""
    else:
        existing_context = "We have no existing news items yet. Provide the latest updates."

    return f"""You are a research assistant for {destination_name} {visa_label} applicants.
Task: Provide the latest important updates on the {destination_name} {visa_label}.

Current date/time (UTC): {now_utc_iso}

{existing_context}

Requirements:
- Focus only on recent and relevant updates directly about the {destination_name} {visa_label}: policy, rules, process, appointments, fees, financial requirements, or documentation.
- Exclude policy updates primarily about OTHER countries' visas (e.g. if the destination is the United Kingdom, do not include US F-1, Canada, or Australia news).
- Treat the current UTC date/time above as "now" when determining recency.
- Include only updates published within the last {_NEWS_MAX_ITEM_AGE_DAYS} days.
- Do NOT include any items that duplicate or substantially overlap with the existing items listed above.
- Include source links for each update.
- Keep summaries clear and concise.
- Use a mix of official updates and credible reporting/community coverage.
- Do not invent links. Only return source URLs from grounded web search results.
- Return ONLY valid JSON.

Output JSON format:
{{
  "generated_at_utc": "{now_utc_iso}",
  "items": [
    {{
      "title": "short headline",
      "summary": "2-3 sentence summary",
      "why_it_matters": "1 sentence impact for students",
      "source_name": "publication or official source",
      "source_url": "https://...",
      "published_date": "YYYY-MM-DD or unknown"
    }}
  ]
}}

Provide 4 to 8 NEW items only. If no new qualifying updates exist beyond what is already stored, return an empty items array."""


def _fetch_new_items_from_gemini(destination_code: str = "US") -> List[Dict[str, str]]:
    """Call Gemini with this destination's existing items as context, return only new items."""
    _ensure_news_helpers()

    meta = _NEWS_DESTINATIONS.get(destination_code) or {"name": "the United States", "visa": "F-1 student visa"}

    db = SessionLocal()
    try:
        existing_items = _load_existing_news_items(db, destination_code)
    finally:
        db.close()

    # _build_latest_genai_client may raise HTTPException (FastAPI) or RuntimeError
    # which is fine — we catch Exception at the caller level.
    client, auth_mode = _build_latest_genai_client()
    prompt = _build_ingestion_prompt(existing_items, destination_name=meta["name"], visa_label=meta["visa"])
    now_utc = datetime.now(timezone.utc)
    last_error = None

    for model_name in MODEL_CANDIDATES:
        try:
            response, generation_meta = _generate_content_with_grounding(
                client,
                prompt,
                model_name=model_name,
                label=f"news.ingestion.{destination_code.lower()}",
                allow_non_grounded_fallback=_ALLOW_NON_GROUNDED_NEWS_FALLBACK,
            )
            # Extract real source URLs from grounding metadata.
            grounding_urls = _extract_grounding_urls(response)

            data = _clean_and_parse_json(getattr(response, "text", ""))
            items = _normalize_items(data.get("items", []))

            # Replace broken redirect URLs with real ones from grounding metadata.
            if grounding_urls:
                items = _enrich_items_with_grounding_urls(items, grounding_urls)

            items = [
                _sanitize_item_published_date(item, now_utc=now_utc)
                for item in items
            ]
            items, stale_removed, undated_removed = _filter_recent_news_items(
                items=items,
                now_utc=now_utc,
            )
            print(
                f"News ingestion [{destination_code}]: model={model_name} "
                f"grounded={generation_meta.get('grounded')} "
                f"new_items={len(items)} "
                f"grounding_urls_available={len(grounding_urls)} "
                f"stale_removed={stale_removed} undated_removed={undated_removed}"
            )
            return items
        except Exception as exc:
            last_error = exc
            print(f"News ingestion [{destination_code}] model attempt failed [{model_name}]: {str(exc)}")
            continue

    print(f"News ingestion [{destination_code}]: all model attempts failed: {str(last_error)}")
    return []


# ---------------------------------------------------------------------------
# Main job entry point
# ---------------------------------------------------------------------------

def run_f1_news_ingestion_job(force: bool = False) -> dict:
    """
    Run a single ingestion cycle across ALL launch destinations (US, UK, CA, AU, …).
    Called by the scheduler or manually. Returns a status dict with per-destination
    results; destinations that already ran today are skipped individually, so a
    mid-run failure never blocks the remaining countries the next poll.
    """
    per_destination: Dict[str, dict] = {}
    any_ran = False

    for destination_code in _ingestion_destinations():
        if not force and _already_ran_today(destination_code):
            per_destination[destination_code] = {"status": "skipped", "reason": "already_ran_today"}
            continue

        any_ran = True
        try:
            new_items = _fetch_new_items_from_gemini(destination_code)
            if not new_items:
                _mark_completed_today(destination_code)
                per_destination[destination_code] = {
                    "status": "completed", "new_items_added": 0, "reason": "no_new_items",
                }
                continue

            db = SessionLocal()
            try:
                added = _merge_and_trim(db, new_items, destination_code)
                _mark_completed_today(destination_code)
                per_destination[destination_code] = {"status": "completed", "new_items_added": added}
            finally:
                db.close()
        except Exception as exc:
            print(f"News ingestion job failed [{destination_code}]: {str(exc)}")
            per_destination[destination_code] = {"status": "failed", "error": str(exc)}

    if not any_ran:
        return {"status": "skipped", "reason": "already_ran_today", "destinations": per_destination}
    overall = "failed" if all(
        r.get("status") == "failed" for r in per_destination.values()
    ) else "completed"
    return {"status": overall, "destinations": per_destination}


# ---------------------------------------------------------------------------
# Module-level singleton + public start/stop helpers
# ---------------------------------------------------------------------------

_scheduler = F1VisaNewsIngestionScheduler()


def start_f1_news_ingestion_scheduler() -> None:
    _scheduler.start()


def stop_f1_news_ingestion_scheduler() -> None:
    _scheduler.stop()
