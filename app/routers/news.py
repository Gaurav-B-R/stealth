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
_news_cache: Dict[str, Dict[str, Any]] = {}
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


def _generate_content_with_grounding(model: Any, prompt: str, model_name: str, label: str) -> Any:
    """
    Generate content with Google Search grounding enabled.
    Falls back to regular generation if grounded call path is unavailable.
    This helper is intentionally used only by News/Interview endpoints.
    """
    grounding_errors: List[str] = []
    _log_gemini_prompt(label, model_name, prompt, extra="grounding=enabled")

    # Vertex AI grounding path
    if gemini_utils.USE_VERTEX_AI and gemini_utils.VERTEX_AI_AVAILABLE:
        try:
            from vertexai.generative_models import Tool
            from vertexai.generative_models import grounding
            tool = Tool.from_google_search_retrieval(
                grounding.GoogleSearchRetrieval()
            )
            response = model.generate_content(prompt, tools=[tool])
            _log_gemini_response(label, model_name, response, extra="grounding_method=vertex_google_search_retrieval")
            return response
        except Exception as exc:
            grounding_errors.append(f"vertex_grounding_error={str(exc)}")
    else:
        # google.generativeai grounding path
        if gemini_utils.GENAI_AVAILABLE and gemini_utils.genai:
            try:
                tool = gemini_utils.genai.protos.Tool(
                    google_search_retrieval=gemini_utils.genai.protos.GoogleSearchRetrieval()
                )
                response = model.generate_content(prompt, tools=[tool])
                _log_gemini_response(label, model_name, response, extra="grounding_method=genai_protos_tool")
                return response
            except Exception as exc:
                grounding_errors.append(f"genai_proto_grounding_error={str(exc)}")

            # Alternate dict-style tool format for compatibility with some SDK builds.
            try:
                response = model.generate_content(prompt, tools=[{"google_search_retrieval": {}}])
                _log_gemini_response(label, model_name, response, extra="grounding_method=genai_dict_tool")
                return response
            except Exception as exc:
                grounding_errors.append(f"genai_dict_grounding_error={str(exc)}")

    # Fallback to non-grounded generation if grounding tool failed.
    try:
        response = model.generate_content(prompt)
        _log_gemini_response(
            label,
            model_name,
            response,
            extra=f"grounding_method=fallback_non_grounded; errors={' | '.join(grounding_errors) if grounding_errors else 'none'}"
        )
        return response
    except Exception as exc:
        details = "; ".join(grounding_errors) if grounding_errors else "grounding_unavailable"
        raise RuntimeError(f"generation_failed_after_grounding_attempts: {details}; base_error={str(exc)}")


def _generate_f1_news_with_gemini(user_country: str) -> Dict[str, Any]:
    has_service_account = os.path.exists(gemini_utils.SERVICE_ACCOUNT_PATH)
    has_valid_api_key = gemini_utils.GEMINI_API_KEY and gemini_utils.GEMINI_API_KEY.startswith("AIza")
    if not has_service_account and not has_valid_api_key:
        raise HTTPException(
            status_code=503,
            detail="Gemini is not configured on the server"
        )

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
- Include source links for each update
- Keep summaries clear and concise
- If uncertain, prefer official sources and major publications
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

            response = _generate_content_with_grounding(model, prompt, model_name=model_name, label="news.f1_latest")
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

            response = _generate_content_with_grounding(
                model,
                prompt,
                model_name=model_name,
                label="news.f1_interview_experiences"
            )
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
    user_country = _resolve_user_residence_country(current_user)
    now_utc = datetime.now(timezone.utc)
    country_cache_key = user_country.lower()

    with _news_lock:
        cache_entry = _news_cache.get(country_cache_key)
        if cache_entry and not refresh and _cache_entry_is_fresh(cache_entry, now_utc, NEWS_CACHE_TTL):
            return {
                "country_context": user_country,
                "items": cache_entry["items"],
                "cached": True,
                "fetched_at": cache_entry["fetched_at"].isoformat() if cache_entry.get("fetched_at") else None,
                "model_used": cache_entry.get("model_used"),
            }

        generated = _generate_f1_news_with_gemini(user_country)
        _news_cache[country_cache_key] = {
            "country_context": user_country,
            "items": generated["items"],
            "fetched_at": now_utc,
            "model_used": generated["model_used"],
        }

        return {
            "country_context": user_country,
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
