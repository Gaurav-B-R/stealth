from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Dict, List
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Query

from app import models
from app.auth import get_current_active_user
from app.utils import gemini_service as gemini_utils

router = APIRouter(prefix="/api/news", tags=["news"])

NEWS_CACHE_TTL = timedelta(hours=6)
_news_lock = Lock()
_news_cache: Dict[str, Any] = {
    "items": [],
    "fetched_at": None,
    "model_used": None,
}


def _cache_is_fresh(now_utc: datetime) -> bool:
    if not _news_cache["fetched_at"] or not _news_cache["items"]:
        return False
    return (now_utc - _news_cache["fetched_at"]) < NEWS_CACHE_TTL


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
