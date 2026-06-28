"""AI university shortlisting / recommendation engine (B2C).

Given a student's destination country, field of study, budget and academic profile, asks
Gemini for a ranked list of universities with rationale, estimated cost and entry
requirements. Mirrors the structured-JSON Gemini pattern used by
`gemini_service.scan_document_red_flags`; usage is logged under the
"university_shortlist" source for cost tracking.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from app.utils import gemini_service

VALID_STATUSES = ("considering", "applied", "admitted", "rejected")
DEFAULT_STATUS = "considering"
MAX_RESULTS = 8
_DIFFICULTY = {"reach", "match", "safety"}


def ai_available() -> bool:
    has_service_account = os.path.exists(gemini_service.SERVICE_ACCOUNT_PATH)
    has_valid_api_key = bool(
        gemini_service.GEMINI_API_KEY and gemini_service.GEMINI_API_KEY.startswith("AIza")
    )
    return has_service_account or has_valid_api_key


# Google Search grounding makes rankings reflect current web data (vs the model's
# stale training knowledge). Done via the google-genai SDK because the legacy
# google-generativeai package only ships the old GoogleSearchRetrieval tool, which
# Gemini 2.x rejects.
GROUNDING_ENABLED = os.getenv("UNIVERSITY_GROUNDING_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def _model_name() -> str:
    try:
        return gemini_service.get_model_candidates(
            primary_env="UNIVERSITY_SHORTLIST_MODEL",
            candidates_env="UNIVERSITY_SHORTLIST_MODEL_CANDIDATES",
        )[0]
    except Exception:
        return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def _model_and_name():
    model_name = _model_name()
    return gemini_service.build_generative_model(model_name), model_name


def _grounded_generate(prompt: str, model_name: str):
    """Generate with Google Search grounding (google-genai SDK, API-key auth).

    Returns (text, response) on success, or None to signal the caller to fall back
    to the ungrounded model — so recommendations never break if grounding is
    unavailable in this environment.
    """
    if not GROUNDING_ENABLED:
        return None
    api_key = (getattr(gemini_service, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")).strip()
    # Grounding here uses the Gemini API key. Vertex/service-account setups fall back.
    if not api_key or not api_key.startswith("AIza"):
        return None
    try:
        from google import genai as _genai
        from google.genai import types as _types

        client = _genai.Client(api_key=api_key)
        config = _types.GenerateContentConfig(
            tools=[_types.Tool(google_search=_types.GoogleSearch())],
            temperature=0.4,
        )
        response = client.models.generate_content(
            model=model_name, contents=prompt, config=config
        )
        text = (getattr(response, "text", "") or "").strip()
        if not text:
            return None
        return text, response
    except Exception as exc:
        print(f"University grounding unavailable ({exc}); using ungrounded model.")
        return None


def _build_prompt(
    *,
    destination_country: str,
    field_of_study: str,
    level: Optional[str],
    budget: Optional[str],
    gpa: Optional[str],
    test_scores: Optional[str],
    home_country: Optional[str],
    preferences: Optional[str],
    max_results: int,
) -> str:
    facts = [
        f"- Destination country: {destination_country}",
        f"- Field of study: {field_of_study}",
        f"- Study level: {level or 'Not specified'}",
        f"- Approximate annual budget: {budget or 'Not specified'}",
        f"- Academic profile (GPA/grades): {gpa or 'Not specified'}",
        f"- Test scores (IELTS/TOEFL/GRE/GMAT etc.): {test_scores or 'Not specified'}",
        f"- Student's home country: {home_country or 'Not specified'}",
        f"- Other preferences: {preferences or 'None'}",
    ]
    return (
        "You are Rilono AI, a study-abroad university advisor. Recommend real universities in the "
        f"student's destination country that fit this profile.\n\n"
        "STUDENT PROFILE:\n" + "\n".join(facts) + "\n\n"
        f"Return STRICTLY a JSON object with up to {max_results} universities, ranked best-fit first:\n"
        '{"universities":[{'
        '"name":"University name",'
        '"location":"City, Region",'
        '"program":"Most relevant matching program",'
        '"why_recommended":"1-2 sentence rationale tied to the student profile",'
        '"estimated_annual_tuition":"e.g. \\"$25,000 - $35,000\\"",'
        '"qs_world_rank":"Most recent QS World University Ranking as a plain number or range, e.g. \\"34\\" or \\"301-350\\". Use \\"N/A\\" if unsure.",'
        '"country_rank":"National rank within the destination country as a plain number, e.g. \\"3\\". Use \\"N/A\\" if unsure.",'
        '"admission_difficulty":"reach | match | safety",'
        '"key_requirements":["short requirement 1","short requirement 2"]'
        "}]}\n\n"
        "Rules:\n"
        f"- Only universities in {destination_country}.\n"
        "- Mix reach, match and safety options when the profile allows.\n"
        "- Be realistic about tuition ranges and requirements.\n"
        f"- Use up-to-date sources for the most recent QS World University Ranking and the national rank within {destination_country}. "
        "If a reliable figure is not available, use \"N/A\" rather than guessing.\n"
        "- Output ONLY the JSON object. Do NOT include ```json or ``` markers or any prose.\n"
        "- Identity guardrail: never mention Gemini, Google, or internal model names; you are Rilono AI."
    )


def _parse_universities(raw: str, max_results: int) -> list[dict]:
    raw = (raw or "").strip()
    if raw.startswith("```json"):
        raw = raw[7:].strip()
    elif raw.startswith("```"):
        raw = raw[3:].strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    fb, lb = raw.find("{"), raw.rfind("}")
    if fb != -1 and lb != -1 and lb > fb:
        raw = raw[fb:lb + 1]
    data = json.loads(raw)
    items = data.get("universities") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for item in items[:max_results]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        difficulty = str(item.get("admission_difficulty") or "match").strip().lower()
        if difficulty not in _DIFFICULTY:
            difficulty = "match"
        reqs = item.get("key_requirements")
        if isinstance(reqs, list):
            requirements = [str(r).strip()[:140] for r in reqs if str(r).strip()][:6]
        else:
            requirements = []
        out.append({
            "name": name[:200],
            "location": str(item.get("location") or "").strip()[:160],
            "program": str(item.get("program") or "").strip()[:200],
            "why_recommended": str(item.get("why_recommended") or "").strip()[:600],
            "estimated_annual_tuition": str(item.get("estimated_annual_tuition") or "").strip()[:80],
            "qs_world_rank": _clean_rank(item.get("qs_world_rank")),
            "country_rank": _clean_rank(item.get("country_rank")),
            "admission_difficulty": difficulty,
            "key_requirements": requirements,
        })
    return out


def _clean_rank(value) -> Optional[str]:
    """Normalize a ranking value to a short display string, or None when unknown."""
    s = str(value or "").strip().lstrip("#").strip()
    if not s or s.lower() in {"n/a", "na", "none", "null", "unknown", "unranked", "-"}:
        return None
    return s[:20]


def recommend_universities(
    *,
    destination_country: str,
    field_of_study: str,
    level: Optional[str] = None,
    budget: Optional[str] = None,
    gpa: Optional[str] = None,
    test_scores: Optional[str] = None,
    home_country: Optional[str] = None,
    preferences: Optional[str] = None,
    max_results: int = 6,
) -> dict:
    """Return {"available": bool, "universities": [...], "model": str}. Never raises."""
    max_results = max(1, min(int(max_results or 6), MAX_RESULTS))
    if not ai_available():
        return {"available": False, "universities": [], "message": "AI recommendations are not configured."}
    try:
        prompt = _build_prompt(
            destination_country=destination_country,
            field_of_study=field_of_study,
            level=level,
            budget=budget,
            gpa=gpa,
            test_scores=test_scores,
            home_country=home_country,
            preferences=preferences,
            max_results=max_results,
        )
        model_name = _model_name()
        grounded = False
        # Preferred path: Google-Search-grounded so QS / national rankings are current.
        grounded_result = _grounded_generate(prompt, model_name)
        if grounded_result is not None:
            text, response = grounded_result
            grounded = True
        else:
            model, model_name = _model_and_name()
            if model is None:
                return {"available": False, "universities": [], "message": "AI recommendation model is unavailable."}
            response = model.generate_content(prompt)
            text = response.text or ""

        try:
            from app import ai_usage
            ai_usage.record_gemini_usage("university_shortlist", model_name, response)
        except Exception:
            pass
        universities = _parse_universities(text, max_results)
        return {"available": True, "universities": universities, "model": model_name, "grounded": grounded}
    except Exception as exc:
        print(f"Error generating university recommendations: {exc}")
        return {"available": False, "universities": [], "message": "Could not generate recommendations right now."}


def serialize_entry(entry) -> dict:
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
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def normalize_status(raw: str | None) -> str:
    value = str(raw or "").strip().lower()
    return value if value in VALID_STATUSES else DEFAULT_STATUS
