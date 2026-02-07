from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Query

from app import models
from app.auth import get_current_active_user
from app.utils import gemini_service as gemini_utils

router = APIRouter(prefix="/api/news", tags=["news"])

NEWS_CACHE_TTL = timedelta(hours=6)
INTERVIEW_CACHE_TTL = timedelta(hours=6)
_news_lock = Lock()
_news_cache: Dict[str, Any] = {
    "items": [],
    "fetched_at": None,
    "model_used": None,
}
_interview_lock = Lock()
_interview_cache: Dict[str, Dict[str, Any]] = {}

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


def _cache_is_fresh(now_utc: datetime) -> bool:
    if not _news_cache["fetched_at"] or not _news_cache["items"]:
        return False
    return (now_utc - _news_cache["fetched_at"]) < NEWS_CACHE_TTL


def _cache_entry_is_fresh(entry: Dict[str, Any], now_utc: datetime, ttl: timedelta) -> bool:
    fetched_at = entry.get("fetched_at")
    items = entry.get("items")
    if not fetched_at or not items:
        return False
    return (now_utc - fetched_at) < ttl


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


def _generate_f1_news_with_gemini() -> Dict[str, Any]:
    has_service_account = os.path.exists(gemini_utils.SERVICE_ACCOUNT_PATH)
    has_valid_api_key = gemini_utils.GEMINI_API_KEY and gemini_utils.GEMINI_API_KEY.startswith("AIza")
    if not has_service_account and not has_valid_api_key:
        raise HTTPException(
            status_code=503,
            detail="Gemini is not configured on the server"
        )

    prompt = f"""You are a research assistant for F1 student visa applicants.
Task: Provide the latest important updates on US F1 visa news.

Requirements:
- Focus on recent and relevant updates for F1 student visa applicants
- Include source links for each update
- Keep summaries clear and concise
- If uncertain, prefer official sources and major publications
- Return ONLY valid JSON

Output JSON format:
{{
  "generated_at_utc": "{datetime.now(timezone.utc).isoformat()}",
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

Provide 4 to 8 items."""

    model_candidates = [
        "gemini-2.0-flash-exp",
        "gemini-1.5-flash",
        "gemini-3-pro-preview",
    ]
    last_error = None

    for model_name in model_candidates:
        try:
            if gemini_utils.USE_VERTEX_AI and gemini_utils.VERTEX_AI_AVAILABLE:
                from vertexai.generative_models import GenerativeModel
                model = GenerativeModel(model_name)
            elif gemini_utils.GENAI_AVAILABLE and gemini_utils.genai:
                model = gemini_utils.genai.GenerativeModel(model_name)
            else:
                raise HTTPException(status_code=503, detail="Gemini library is not available")

            response = model.generate_content(prompt)
            data = _clean_and_parse_json(getattr(response, "text", ""))
            items = _normalize_items(data.get("items", []))
            if not items:
                raise ValueError("Gemini returned no usable news items")
            return {"items": items, "model_used": model_name}
        except Exception as exc:
            last_error = exc
            continue

    raise HTTPException(
        status_code=502,
        detail=f"Failed to generate news from Gemini: {str(last_error)}"
    )


def _generate_f1_interview_experiences_with_gemini(country: str, consulates: List[str]) -> Dict[str, Any]:
    has_service_account = os.path.exists(gemini_utils.SERVICE_ACCOUNT_PATH)
    has_valid_api_key = gemini_utils.GEMINI_API_KEY and gemini_utils.GEMINI_API_KEY.startswith("AIza")
    if not has_service_account and not has_valid_api_key:
        raise HTTPException(
            status_code=503,
            detail="Gemini is not configured on the server"
        )

    consulate_text = ", ".join(consulates)
    prompt = f"""You are a research assistant helping F1 visa students.
Task: Find recent F-1 visa interview experiences posted by real users online.

Filters:
- Country where interview happened: {country}
- Target consulates: {consulate_text}

Sources to prioritize:
- Reddit
- X (Twitter)
- Telegram communities
- Yocket
- Other active student communities/forums

Strict output requirements:
- Include only experiences relevant to the selected country and consulates.
- Prefer very recent posts.
- Include a direct source link for each item when available.
- Keep each summary short and practical for a student.
- Return ONLY valid JSON. No markdown.

Output JSON format:
{{
  "generated_at_utc": "{datetime.now(timezone.utc).isoformat()}",
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
        "gemini-2.0-flash-exp",
        "gemini-1.5-flash",
        "gemini-3-pro-preview",
    ]
    last_error = None

    for model_name in model_candidates:
        try:
            if gemini_utils.USE_VERTEX_AI and gemini_utils.VERTEX_AI_AVAILABLE:
                from vertexai.generative_models import GenerativeModel
                model = GenerativeModel(model_name)
            elif gemini_utils.GENAI_AVAILABLE and gemini_utils.genai:
                model = gemini_utils.genai.GenerativeModel(model_name)
            else:
                raise HTTPException(status_code=503, detail="Gemini library is not available")

            response = model.generate_content(prompt)
            data = _clean_and_parse_json(getattr(response, "text", ""))
            items = _normalize_interview_items(data.get("items", []), consulates)
            if not items:
                raise ValueError("Gemini returned no usable interview experiences")
            return {"items": items, "model_used": model_name}
        except Exception as exc:
            last_error = exc
            continue

    raise HTTPException(
        status_code=502,
        detail=f"Failed to generate interview experiences from Gemini: {str(last_error)}"
    )


@router.get("/f1-latest")
def get_f1_latest_news(
    refresh: bool = Query(default=False),
    current_user: models.User = Depends(get_current_active_user),
):
    del current_user  # endpoint is protected; user object is not needed further.
    now_utc = datetime.now(timezone.utc)

    with _news_lock:
        if not refresh and _cache_is_fresh(now_utc):
            return {
                "items": _news_cache["items"],
                "cached": True,
                "fetched_at": _news_cache["fetched_at"].isoformat() if _news_cache["fetched_at"] else None,
                "model_used": _news_cache["model_used"],
            }

        generated = _generate_f1_news_with_gemini()
        _news_cache["items"] = generated["items"]
        _news_cache["fetched_at"] = now_utc
        _news_cache["model_used"] = generated["model_used"]

        return {
            "items": generated["items"],
            "cached": False,
            "fetched_at": now_utc.isoformat(),
            "model_used": generated["model_used"],
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
            }

    generated = _generate_f1_interview_experiences_with_gemini(selected_country, selected_consulates)
    cache_entry = {
        "country": selected_country,
        "consulates": selected_consulates,
        "items": generated["items"],
        "fetched_at": now_utc,
        "model_used": generated["model_used"],
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
    }
