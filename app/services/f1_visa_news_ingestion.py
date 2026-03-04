"""
Background scheduler that ingests F1 visa news from Gemini once every 24 hours
and stores them in the f1_visa_news table.  Users read pre-loaded data; no
client-triggered fetching is needed.

Architecture follows the exact same pattern as daily_ai_notifications.py.
"""

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app import models
from app.database import SessionLocal

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


def _ensure_news_helpers():
    """Import shared helpers from news router on first use."""
    global _news_helpers_loaded
    global _build_latest_genai_client, _generate_content_with_grounding
    global _clean_and_parse_json, _normalize_items
    global _sanitize_item_published_date, _filter_recent_news_items
    global _extract_grounding_urls, _enrich_items_with_grounding_urls
    global _NEWS_MAX_ITEM_AGE_DAYS, _ALLOW_NON_GROUNDED_NEWS_FALLBACK

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


def _already_ran_today() -> bool:
    """Check if ingestion already ran today by looking at the most recent item's ingested_at."""
    db = SessionLocal()
    try:
        latest = (
            db.query(models.F1VisaNewsItem)
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

def _load_existing_news_items(db) -> List[Dict[str, str]]:
    """Load all current items from DB to provide as context to Gemini."""
    items = (
        db.query(models.F1VisaNewsItem)
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


def _merge_and_trim(db, new_items: List[Dict[str, str]]) -> int:
    """Insert new items into DB, then trim to keep only the latest N items."""
    if not new_items:
        return 0

    now_utc = datetime.now(timezone.utc)
    for item in new_items:
        news_row = models.F1VisaNewsItem(
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

    # Trim: keep only the most recent F1_NEWS_MAX_STORED_ITEMS
    total_count = db.query(models.F1VisaNewsItem).count()
    if total_count > F1_NEWS_MAX_STORED_ITEMS:
        excess = total_count - F1_NEWS_MAX_STORED_ITEMS
        oldest_to_delete = (
            db.query(models.F1VisaNewsItem)
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

MODEL_CANDIDATES = [
    "gemini-3-pro-preview",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-exp",
    "gemini-1.5-flash",
]


def _build_ingestion_prompt(existing_items: List[Dict[str, str]]) -> str:
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

    return f"""You are a research assistant for F1 student visa applicants.
Task: Provide the latest important updates on US F1 visa news.

Current date/time (UTC): {now_utc_iso}

{existing_context}

Requirements:
- Focus only on recent and relevant updates directly about U.S. F-1 visa policy, process, appointments, or documentation.
- Exclude policy updates primarily about other countries (UK, Australia, Canada, etc.).
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


def _fetch_new_items_from_gemini() -> List[Dict[str, str]]:
    """Call Gemini with existing items as context, return only new items."""
    _ensure_news_helpers()

    db = SessionLocal()
    try:
        existing_items = _load_existing_news_items(db)
    finally:
        db.close()

    # _build_latest_genai_client may raise HTTPException (FastAPI) or RuntimeError
    # which is fine — we catch Exception at the caller level.
    client, auth_mode = _build_latest_genai_client()
    prompt = _build_ingestion_prompt(existing_items)
    now_utc = datetime.now(timezone.utc)
    last_error = None

    for model_name in MODEL_CANDIDATES:
        try:
            response, generation_meta = _generate_content_with_grounding(
                client,
                prompt,
                model_name=model_name,
                label="news.f1_ingestion",
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
                f"F1 news ingestion: model={model_name} "
                f"grounded={generation_meta.get('grounded')} "
                f"new_items={len(items)} "
                f"grounding_urls_available={len(grounding_urls)} "
                f"stale_removed={stale_removed} undated_removed={undated_removed}"
            )
            return items
        except Exception as exc:
            last_error = exc
            print(f"F1 news ingestion model attempt failed [{model_name}]: {str(exc)}")
            continue

    print(f"F1 news ingestion: all model attempts failed: {str(last_error)}")
    return []


# ---------------------------------------------------------------------------
# Main job entry point
# ---------------------------------------------------------------------------

def run_f1_news_ingestion_job(force: bool = False) -> dict:
    """
    Run a single ingestion cycle.  Called by the scheduler or manually.
    Returns a status dict.
    """
    if not force and _already_ran_today():
        return {"status": "skipped", "reason": "already_ran_today"}

    try:
        new_items = _fetch_new_items_from_gemini()
        if not new_items:
            return {"status": "completed", "new_items_added": 0, "reason": "no_new_items"}

        db = SessionLocal()
        try:
            added = _merge_and_trim(db, new_items)
            return {"status": "completed", "new_items_added": added}
        finally:
            db.close()
    except Exception as exc:
        print(f"F1 news ingestion job failed: {str(exc)}")
        return {"status": "failed", "error": str(exc)}


# ---------------------------------------------------------------------------
# Module-level singleton + public start/stop helpers
# ---------------------------------------------------------------------------

_scheduler = F1VisaNewsIngestionScheduler()


def start_f1_news_ingestion_scheduler() -> None:
    _scheduler.start()


def stop_f1_news_ingestion_scheduler() -> None:
    _scheduler.stop()
