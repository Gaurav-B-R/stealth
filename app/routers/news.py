from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple
import json
import os
import re
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query

from sqlalchemy.orm import Session

from app import models
from app.auth import get_current_active_user
from app.database import get_db
from app.utils import gemini_service as gemini_utils

try:
    from google import genai as latest_genai
    from google.genai import types as latest_genai_types
    LATEST_GENAI_AVAILABLE = True
except Exception:
    latest_genai = None
    latest_genai_types = None
    LATEST_GENAI_AVAILABLE = False

router = APIRouter(prefix="/api/news", tags=["news"])

INTERVIEW_CACHE_TTL = timedelta(hours=6)
_interview_lock = Lock()
_interview_cache: Dict[str, Dict[str, Any]] = {}


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


NEWS_MAX_ITEM_AGE_DAYS = int(os.getenv("NEWS_MAX_ITEM_AGE_DAYS", "365") or "365")
ALLOW_NON_GROUNDED_NEWS_FALLBACK = _env_flag("NEWS_ALLOW_NON_GROUNDED_FALLBACK", False)
ALLOW_NON_GROUNDED_INTERVIEW_FALLBACK = _env_flag("INTERVIEW_ALLOW_NON_GROUNDED_FALLBACK", False)

INTERVIEW_COUNTRY_CONSULATE_MAP: Dict[str, List[str]] = {
    "India": ["New Delhi", "Mumbai", "Chennai", "Hyderabad", "Kolkata"],
    "United Kingdom": ["London", "Belfast"],
    "Canada": ["Ottawa", "Toronto", "Vancouver", "Montreal", "Calgary", "Halifax", "Quebec City"],
    "Australia": ["Sydney", "Melbourne", "Perth"],
    "Germany": ["Berlin", "Frankfurt", "Munich"],
    "United Arab Emirates": ["Abu Dhabi", "Dubai"],
    "Singapore": ["Singapore"],
    "Japan": ["Tokyo", "Osaka / Kobe", "Naha", "Sapporo", "Fukuoka"],
}

GEMINI_LOG_MAX_CHARS = int(os.getenv("GEMINI_LOG_MAX_CHARS", "0") or "0")


def _cache_entry_is_fresh(entry: Dict[str, Any], now_utc: datetime, ttl: timedelta) -> bool:
    fetched_at = entry.get("fetched_at")
    items = entry.get("items")
    if not fetched_at or not items:
        return False
    return (now_utc - fetched_at) < ttl


def _resolve_user_residence_country(user: models.User) -> str:
    country = (
        getattr(user, "current_residence_country", None)
        or getattr(user, "preferred_country", None)
        or "United States"
    )
    normalized = str(country).strip()
    return normalized or "United States"


def _clean_and_parse_json(text: str) -> Dict[str, Any]:
    response_text = (text or "").strip()
    if response_text.startswith("```json"):
        response_text = response_text[7:].strip()
    elif response_text.startswith("```"):
        response_text = response_text[3:].strip()
    if response_text.endswith("```"):
        response_text = response_text[:-3].strip()

    first_brace = response_text.find("{")
    last_brace = response_text.rfind("}")
    if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
        raise ValueError("No JSON object found in Gemini response")

    return json.loads(response_text[first_brace:last_brace + 1])


def _normalize_items(items: Any) -> List[Dict[str, str]]:
    if not isinstance(items, list):
        return []

    normalized: List[Dict[str, str]] = []
    for raw in items[:8]:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title", "")).strip()
        summary = str(raw.get("summary", "")).strip()
        why_it_matters = str(raw.get("why_it_matters", "")).strip()
        source_name = str(raw.get("source_name", "")).strip()
        source_url = str(raw.get("source_url", "")).strip()
        published_date = str(raw.get("published_date", "")).strip()

        if not title or not summary:
            continue
        if source_url and not source_url.startswith(("http://", "https://")):
            source_url = ""

        normalized.append({
            "title": title,
            "summary": summary,
            "why_it_matters": why_it_matters,
            "source_name": source_name or "Source",
            "source_url": source_url,
            "published_date": published_date,
        })
    return normalized


def _parse_published_date(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw or raw.lower() == "unknown":
        return None

    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass

    supported_formats = ("%Y-%m-%d", "%Y/%m/%d", "%b %d, %Y", "%B %d, %Y")
    for fmt in supported_formats:
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _infer_published_date_from_url(url: str) -> Optional[datetime]:
    path = urlparse(str(url or "")).path or ""
    patterns = [
        r"/(20\d{2})[/-](0[1-9]|1[0-2])[/-](0[1-9]|[12]\d|3[01])(?:/|$)",
        r"/(20\d{2})[/-](0[1-9]|1[0-2])(?:/|$)",
        r"/(20\d{2})(?:/|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, path)
        if not match:
            continue
        year = int(match.group(1))
        month = int(match.group(2)) if match.lastindex and match.lastindex >= 2 else 1
        day = int(match.group(3)) if match.lastindex and match.lastindex >= 3 else 1
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _sanitize_item_published_date(item: Dict[str, str], now_utc: datetime) -> Dict[str, str]:
    updated = dict(item)
    parsed = _parse_published_date(updated.get("published_date", ""))
    inferred = _infer_published_date_from_url(updated.get("source_url", ""))

    # If model date is missing, use URL-inferred date when available.
    if not parsed and inferred:
        updated["published_date"] = inferred.strftime("%Y-%m-%d")
        return updated

    if not parsed:
        updated["published_date"] = "unknown"
        return updated

    # Reject clearly invalid dates.
    if parsed > (now_utc + timedelta(days=2)):
        updated["published_date"] = "unknown"
        return updated

    # If source URL strongly indicates another year, distrust model date.
    if inferred and abs(parsed.year - inferred.year) >= 2:
        updated["published_date"] = "unknown"
        return updated

    updated["published_date"] = parsed.strftime("%Y-%m-%d")
    return updated


def _filter_recent_news_items(
    items: List[Dict[str, str]],
    now_utc: datetime,
) -> Tuple[List[Dict[str, str]], int, int]:
    cutoff = now_utc - timedelta(days=NEWS_MAX_ITEM_AGE_DAYS)
    kept: List[Tuple[datetime, Dict[str, str]]] = []
    stale_count = 0
    undated_count = 0

    for item in items:
        published_at = _parse_published_date(item.get("published_date", ""))
        if not published_at:
            undated_count += 1
            continue
        if published_at < cutoff:
            stale_count += 1
            continue
        kept.append((published_at, item))

    kept.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in kept], stale_count, undated_count


def _extract_grounding_urls(response: Any) -> List[Dict[str, str]]:
    """
    Extract real source URLs from Gemini grounding metadata.

    When Google Search grounding is enabled, the response includes
    ``candidates[0].grounding_metadata.grounding_chunks`` which contain the
    actual URLs (not the broken ``vertexaisearch.cloud.google.com`` redirect
    proxies that Gemini sometimes embeds in its JSON text output).
    """
    urls: List[Dict[str, str]] = []
    try:
        candidates = getattr(response, "candidates", None)
        if not candidates:
            return urls
        metadata = getattr(candidates[0], "grounding_metadata", None)
        if not metadata:
            return urls
        chunks = getattr(metadata, "grounding_chunks", None)
        if not chunks:
            return urls
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            if web:
                uri = getattr(web, "uri", None) or ""
                title = getattr(web, "title", None) or ""
                if uri and uri.startswith(("http://", "https://")):
                    urls.append({"uri": uri, "title": title})
            ctx = getattr(chunk, "retrieved_context", None)
            if ctx:
                uri = getattr(ctx, "uri", None) or ""
                title = getattr(ctx, "title", None) or ""
                if uri and uri.startswith(("http://", "https://")):
                    urls.append({"uri": uri, "title": title})
    except Exception:  # noqa: BLE001
        pass
    return urls


def _is_redirect_url(url: str) -> bool:
    """Return True if *url* looks like a Vertex AI grounding-redirect proxy."""
    return bool(
        url
        and (
            "vertexaisearch.cloud.google.com" in url
            or "grounding-api-redirect" in url
        )
    )


def _enrich_items_with_grounding_urls(
    items: List[Dict[str, str]],
    grounding_urls: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """
    Replace broken redirect ``source_url`` values in *items* with real URLs
    extracted from the Gemini grounding metadata.

    Matching strategy (in priority order):
      1. ``source_name`` ↔ grounding chunk ``title`` (case-insensitive substring)
      2. Keyword overlap between item ``title`` and chunk ``title``
      3. Assign the next unused grounding URL (positional fallback)

    Items whose ``source_url`` is already a real URL are left untouched.
    """
    if not grounding_urls:
        return items

    # Track which grounding URLs have been assigned so we don't reuse them.
    used_indices: set = set()

    def _find_match_by_source_name(source_name: str) -> Optional[int]:
        sn = source_name.lower()
        for idx, g in enumerate(grounding_urls):
            if idx in used_indices:
                continue
            gt = g["title"].lower()
            if sn and gt and (sn in gt or gt in sn):
                return idx
        return None

    def _find_match_by_title_keywords(item_title: str) -> Optional[int]:
        words = {w.lower() for w in item_title.split() if len(w) > 3}
        if not words:
            return None
        best_idx: Optional[int] = None
        best_overlap = 0
        for idx, g in enumerate(grounding_urls):
            if idx in used_indices:
                continue
            gt_words = {w.lower() for w in g["title"].split() if len(w) > 3}
            overlap = len(words & gt_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best_idx = idx
        return best_idx if best_overlap >= 2 else None

    def _next_unused() -> Optional[int]:
        for idx in range(len(grounding_urls)):
            if idx not in used_indices:
                return idx
        return None

    enriched: List[Dict[str, str]] = []
    for item in items:
        item = dict(item)
        source_url = item.get("source_url", "")

        if source_url and not _is_redirect_url(source_url):
            # Already a real URL — keep it.
            enriched.append(item)
            continue

        # Try matching strategies in priority order.
        match_idx = _find_match_by_source_name(item.get("source_name", ""))
        if match_idx is None:
            match_idx = _find_match_by_title_keywords(item.get("title", ""))
        if match_idx is None:
            match_idx = _next_unused()

        if match_idx is not None:
            item["source_url"] = grounding_urls[match_idx]["uri"]
            used_indices.add(match_idx)

        enriched.append(item)

    return enriched


def _normalize_filter_inputs(country: str, consulates: Optional[List[str]]) -> Tuple[str, List[str]]:
    selected_country = (country or "").strip()
    if selected_country not in INTERVIEW_COUNTRY_CONSULATE_MAP:
        supported = ", ".join(sorted(INTERVIEW_COUNTRY_CONSULATE_MAP.keys()))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported country '{selected_country}'. Supported countries: {supported}"
        )

    allowed_consulates = INTERVIEW_COUNTRY_CONSULATE_MAP[selected_country]
    requested_consulates = [str(name).strip() for name in (consulates or []) if str(name).strip()]
    if not requested_consulates:
        return selected_country, allowed_consulates

    invalid_consulates = [name for name in requested_consulates if name not in allowed_consulates]
    if invalid_consulates:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid consulate(s) for {selected_country}: {', '.join(invalid_consulates)}"
        )

    unique_consulates: List[str] = []
    for name in requested_consulates:
        if name not in unique_consulates:
            unique_consulates.append(name)
    return selected_country, unique_consulates


def _build_interview_cache_key(country: str, consulates: List[str]) -> str:
    return f"{country}|{','.join(sorted(consulates))}"


def _match_consulate(raw_value: str, allowed_consulates: List[str]) -> str:
    value = (raw_value or "").strip()
    if not value:
        return ""

    lower_value = value.lower()
    for allowed in allowed_consulates:
        lower_allowed = allowed.lower()
        if lower_value == lower_allowed or lower_allowed in lower_value or lower_value in lower_allowed:
            return allowed
    return value


def _normalize_interview_items(items: Any, allowed_consulates: List[str]) -> List[Dict[str, str]]:
    if not isinstance(items, list):
        return []

    normalized: List[Dict[str, str]] = []
    for raw in items[:12]:
        if not isinstance(raw, dict):
            continue

        summary = str(raw.get("summary", "")).strip()
        source_url = str(raw.get("source_url", "")).strip()
        consulate = _match_consulate(
            str(raw.get("consulate", "")).strip() or str(raw.get("location", "")).strip(),
            allowed_consulates
        )

        if not summary:
            continue
        if source_url and not source_url.startswith(("http://", "https://")):
            source_url = ""

        normalized.append({
            "consulate": consulate or "Consulate not specified",
            "interview_result": str(raw.get("interview_result", "")).strip() or str(raw.get("outcome", "")).strip() or "Reported",
            "summary": summary,
            "key_takeaway": str(raw.get("key_takeaway", "")).strip() or str(raw.get("focus", "")).strip(),
            "platform": str(raw.get("platform", "")).strip() or "Community",
            "source_name": str(raw.get("source_name", "")).strip() or "User report",
            "source_url": source_url,
            "reported_date": str(raw.get("reported_date", "")).strip() or str(raw.get("published_date", "")).strip() or "unknown",
        })
    return normalized


def _clip_for_log(text: str) -> str:
    if text is None:
        return ""
    if GEMINI_LOG_MAX_CHARS <= 0:
        return text
    if len(text) <= GEMINI_LOG_MAX_CHARS:
        return text
    return f"{text[:GEMINI_LOG_MAX_CHARS]}\n\n...[truncated {len(text) - GEMINI_LOG_MAX_CHARS} chars]"


def _log_gemini_prompt(label: str, model_name: str, prompt: str, extra: str = "") -> None:
    print("\n" + "=" * 90)
    print(f"🔵 GEMINI REQUEST [{label}]")
    print(f"Model: {model_name}")
    if extra:
        print(f"Meta: {extra}")
    print("-" * 90)
    print(_clip_for_log(prompt))
    print("=" * 90)


def _log_gemini_response(label: str, model_name: str, response: Any, extra: str = "") -> None:
    response_text = str(getattr(response, "text", "") or "")
    print("\n" + "-" * 90)
    print(f"✅ GEMINI RESPONSE [{label}]")
    print(f"Model: {model_name}")
    if extra:
        print(f"Meta: {extra}")
    print("-" * 90)
    print(_clip_for_log(response_text))
    print("-" * 90 + "\n")


def _resolve_vertex_project_id() -> str:
    if os.getenv("GCP_PROJECT", "").strip():
        return os.getenv("GCP_PROJECT", "").strip()

    service_account_path = gemini_utils.SERVICE_ACCOUNT_PATH
    if not os.path.exists(service_account_path):
        return ""

    try:
        with open(service_account_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
            return str(payload.get("project_id", "")).strip()
    except Exception:
        return ""


def _build_latest_genai_client() -> Tuple[Any, str]:
    if not LATEST_GENAI_AVAILABLE or not latest_genai:
        raise HTTPException(status_code=503, detail="google-genai SDK is not installed")

    api_key = str(gemini_utils.GEMINI_API_KEY or "").strip()
    if api_key.startswith("AIza"):
        return latest_genai.Client(api_key=api_key), "api_key"

    service_account_path = gemini_utils.SERVICE_ACCOUNT_PATH
    if os.path.exists(service_account_path):
        project_id = _resolve_vertex_project_id()
        location = os.getenv("GCP_LOCATION", "us-central1")
        if project_id:
            return latest_genai.Client(vertexai=True, project=project_id, location=location), "vertex"

    raise HTTPException(status_code=503, detail="Gemini is not configured on the server")


def _generate_content_with_grounding(
    client: Any,
    prompt: str,
    model_name: str,
    label: str,
    allow_non_grounded_fallback: bool,
) -> Tuple[Any, Dict[str, Any]]:
    """
    Generate content with Google Search grounding enabled.
    Falls back to regular generation if grounded call path is unavailable.
    This helper is intentionally used only by News/Interview endpoints.
    """
    grounding_errors: List[str] = []
    _log_gemini_prompt(label, model_name, prompt, extra="grounding=enabled")

    # Primary latest SDK path: google_search tool.
    if latest_genai_types:
        try:
            config = latest_genai_types.GenerateContentConfig(
                tools=[latest_genai_types.Tool(google_search=latest_genai_types.GoogleSearch())],
                response_mime_type="application/json",
            )
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            _log_gemini_response(label, model_name, response, extra="grounding_method=google_genai_google_search")
            return response, {
                "grounded": True,
                "grounding_method": "google_genai_google_search",
                "grounding_errors": grounding_errors,
            }
        except Exception as exc:
            grounding_errors.append(f"google_genai_google_search_error={str(exc)}")

        # Compatibility path for model/provider combinations expecting google_search_retrieval.
        try:
            config = latest_genai_types.GenerateContentConfig(
                tools=[latest_genai_types.Tool(google_search_retrieval=latest_genai_types.GoogleSearchRetrieval())],
                response_mime_type="application/json",
            )
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            _log_gemini_response(label, model_name, response, extra="grounding_method=google_genai_google_search_retrieval")
            return response, {
                "grounded": True,
                "grounding_method": "google_genai_google_search_retrieval",
                "grounding_errors": grounding_errors,
            }
        except Exception as exc:
            grounding_errors.append(f"google_genai_google_search_retrieval_error={str(exc)}")

    if not allow_non_grounded_fallback:
        details = "; ".join(grounding_errors) if grounding_errors else "grounding_unavailable"
        raise RuntimeError(f"grounding_required_but_unavailable: {details}")

    # Fallback to non-grounded generation only when explicitly allowed.
    try:
        config = latest_genai_types.GenerateContentConfig(response_mime_type="application/json") if latest_genai_types else None
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config,
        )
        _log_gemini_response(
            label,
            model_name,
            response,
            extra=f"grounding_method=fallback_non_grounded; errors={' | '.join(grounding_errors) if grounding_errors else 'none'}"
        )
        return response, {
            "grounded": False,
            "grounding_method": "fallback_non_grounded",
            "grounding_errors": grounding_errors,
        }
    except Exception as exc:
        details = "; ".join(grounding_errors) if grounding_errors else "grounding_unavailable"
        raise RuntimeError(f"generation_failed_after_grounding_attempts: {details}; base_error={str(exc)}")


def _generate_f1_news_with_gemini(user_country: str) -> Dict[str, Any]:
    client, auth_mode = _build_latest_genai_client()

    now_utc_iso = datetime.now(timezone.utc).isoformat()

    prompt = f"""You are a research assistant for F1 student visa applicants.
Task: Provide the latest important updates on US F1 visa news, tailored for students currently residing in {user_country}.

Student context:
- Current country of residence: {user_country}
- Current date/time (UTC): {now_utc_iso}

Requirements:
- Focus on recent and relevant updates for F1 student visa applicants in this country context.
- Prioritize updates that materially affect students from or residing in {user_country}.
- Treat the current UTC date/time above as "now" when determining recency.
- Include only updates published within the last {NEWS_MAX_ITEM_AGE_DAYS} days.
- Include source links for each update
- Keep summaries clear and concise
- Use a mix of official updates and credible reporting/community coverage when relevant.
- Do not invent links. Only return source URLs that came from grounded web search results.
- Return ONLY valid JSON

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

Provide 4 to 8 items. If no qualifying recent updates exist, return an empty items array."""

    model_candidates = [
        "gemini-3-pro-preview",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.0-flash-exp",
        "gemini-1.5-flash",
    ]
    last_error = None
    empty_result: Optional[Dict[str, Any]] = None

    for model_name in model_candidates:
        try:
            response, generation_meta = _generate_content_with_grounding(
                client,
                prompt,
                model_name=model_name,
                label="news.f1_latest",
                allow_non_grounded_fallback=ALLOW_NON_GROUNDED_NEWS_FALLBACK,
            )
            data = _clean_and_parse_json(getattr(response, "text", ""))
            items = _normalize_items(data.get("items", []))
            items = [_sanitize_item_published_date(item, now_utc=datetime.now(timezone.utc)) for item in items]
            items, stale_removed, undated_removed = _filter_recent_news_items(
                items=items,
                now_utc=datetime.now(timezone.utc),
            )
            if not items:
                empty_result = empty_result or {
                    "items": [],
                    "model_used": model_name,
                    "grounded": bool(generation_meta.get("grounded")),
                    "grounding_method": str(generation_meta.get("grounding_method") or ""),
                    "auth_mode": auth_mode,
                    "stale_items_removed": stale_removed,
                    "undated_items_removed": undated_removed,
                }
                continue
            return {
                "items": items,
                "model_used": model_name,
                "grounded": bool(generation_meta.get("grounded")),
                "grounding_method": str(generation_meta.get("grounding_method") or ""),
                "auth_mode": auth_mode,
                "stale_items_removed": stale_removed,
                "undated_items_removed": undated_removed,
            }
        except Exception as exc:
            last_error = exc
            print(f"⚠ News model attempt failed [{model_name}] auth={auth_mode}: {str(exc)}")
            continue

    if empty_result is not None:
        return empty_result

    print(f"⚠ News generation fallback: returning empty items after model failures: {str(last_error)}")
    return {
        "items": [],
        "model_used": "none",
        "grounded": False,
        "grounding_method": "none",
        "stale_items_removed": 0,
        "undated_items_removed": 0,
    }


def _generate_f1_interview_experiences_with_gemini(country: str, consulates: List[str]) -> Dict[str, Any]:
    client, auth_mode = _build_latest_genai_client()

    consulate_text = ", ".join(consulates)
    now_utc_iso = datetime.now(timezone.utc).isoformat()
    prompt = f"""You are a research assistant helping F1 visa students.
Task: Find recent F-1 visa interview experiences posted by real users online.

Filters:
- Country where interview happened: {country}
- Target consulates: {consulate_text}
- Current date/time (UTC): {now_utc_iso}

Sources to prioritize:
- Reddit
- X (Twitter)
- Telegram communities
- Yocket
- Other active student communities/forums

Strict output requirements:
- Include only experiences relevant to the selected country and consulates.
- Prefer very recent posts.
- Treat the current UTC date/time above as "now" when determining recency.
- Include a direct source link for each item when available.
- Keep each summary short and practical for a student.
- Return ONLY valid JSON. No markdown.

Output JSON format:
{{
  "generated_at_utc": "{now_utc_iso}",
  "items": [
    {{
      "consulate": "Hyderabad",
      "interview_result": "Approved | Refused | Administrative Processing | Unknown",
      "summary": "2-3 sentence concise experience summary",
      "key_takeaway": "single practical takeaway",
      "platform": "Reddit | X | Telegram | Yocket | Forum",
      "source_name": "post author or source label",
      "source_url": "https://...",
      "reported_date": "YYYY-MM-DD or unknown"
    }}
  ]
}}

Provide 5 to 10 items."""

    model_candidates = [
        "gemini-3-pro-preview",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.0-flash-exp",
        "gemini-1.5-flash",
    ]
    last_error = None

    for model_name in model_candidates:
        try:
            response, generation_meta = _generate_content_with_grounding(
                client,
                prompt,
                model_name=model_name,
                label="news.f1_interview_experiences",
                allow_non_grounded_fallback=ALLOW_NON_GROUNDED_INTERVIEW_FALLBACK,
            )
            data = _clean_and_parse_json(getattr(response, "text", ""))
            items = _normalize_interview_items(data.get("items", []), consulates)
            if not items:
                raise ValueError("Gemini returned no usable interview experiences")
            return {
                "items": items,
                "model_used": model_name,
                "grounded": bool(generation_meta.get("grounded")),
                "grounding_method": str(generation_meta.get("grounding_method") or ""),
                "auth_mode": auth_mode,
            }
        except Exception as exc:
            last_error = exc
            print(f"⚠ Interview model attempt failed [{model_name}] auth={auth_mode}: {str(exc)}")
            continue

    raise HTTPException(
        status_code=502,
        detail=f"Failed to generate interview experiences from Gemini: {str(last_error)}"
    )


@router.get("/f1-latest")
def get_f1_latest_news(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Return stored F1 visa news items from the database.
    Items are ingested by the background scheduler every 24 hours.
    """
    items = (
        db.query(models.F1VisaNewsItem)
        .order_by(
            models.F1VisaNewsItem.ingested_at.desc(),
            models.F1VisaNewsItem.id.desc(),
        )
        .limit(50)
        .all()
    )

    last_ingested_at = (
        items[0].ingested_at.isoformat() if items and items[0].ingested_at else None
    )

    return {
        "items": [
            {
                "title": item.title,
                "summary": item.summary,
                "why_it_matters": item.why_it_matters or "",
                "source_name": item.source_name,
                "source_url": item.source_url or "",
                "published_date": item.published_date or "unknown",
            }
            for item in items
        ],
        "fetched_at": last_ingested_at,
        "source": "stored",
        "count": len(items),
    }


@router.get("/f1-interview-experiences")
def get_f1_interview_experiences(
    country: str = Query(default="India"),
    consulates: Optional[List[str]] = Query(default=None),
    refresh: bool = Query(default=False),
    current_user: models.User = Depends(get_current_active_user),
):
    del current_user  # endpoint is protected; user object is not needed further.
    now_utc = datetime.now(timezone.utc)

    selected_country, selected_consulates = _normalize_filter_inputs(country, consulates)
    cache_key = _build_interview_cache_key(selected_country, selected_consulates)

    with _interview_lock:
        cache_entry = _interview_cache.get(cache_key)
        if cache_entry and not refresh and _cache_entry_is_fresh(cache_entry, now_utc, INTERVIEW_CACHE_TTL):
            return {
                "country": selected_country,
                "consulates": selected_consulates,
                "items": cache_entry["items"],
                "cached": True,
                "fetched_at": cache_entry["fetched_at"].isoformat(),
                "model_used": cache_entry.get("model_used"),
                "auth_mode": cache_entry.get("auth_mode"),
                "grounded": cache_entry.get("grounded"),
                "grounding_method": cache_entry.get("grounding_method"),
            }

    generated = _generate_f1_interview_experiences_with_gemini(selected_country, selected_consulates)
    cache_entry = {
        "country": selected_country,
        "consulates": selected_consulates,
        "items": generated["items"],
        "fetched_at": now_utc,
        "model_used": generated["model_used"],
        "auth_mode": generated.get("auth_mode"),
        "grounded": generated.get("grounded"),
        "grounding_method": generated.get("grounding_method"),
    }

    with _interview_lock:
        _interview_cache[cache_key] = cache_entry

    return {
        "country": selected_country,
        "consulates": selected_consulates,
        "items": generated["items"],
        "cached": False,
        "fetched_at": now_utc.isoformat(),
        "model_used": generated["model_used"],
        "auth_mode": generated.get("auth_mode"),
        "grounded": generated.get("grounded"),
        "grounding_method": generated.get("grounding_method"),
    }
