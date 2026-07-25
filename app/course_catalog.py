"""Course Finder catalog: shared universities/courses data + the AI that maintains it.

Three jobs live here:

1. **Discovery** — one grounded Gemini call per country that lists the top-N
   universities for international students; inserted as stub rows awaiting enrichment.
2. **Enrichment/refresh** — per-university grounded Gemini call returning the full
   profile (ranks, tuition band, scholarships) plus its flagship international
   programs (fees, intakes, deadlines, IELTS/TOEFL/GRE cutoffs), upserted into
   `course_catalog_universities` / `course_catalog_courses` with `last_verified_at`.
   Called only by the background agent (app/services/course_catalog_refresh.py).
3. **Recommendation** — the enterprise Course Finder's billed AI action: Rilono AI
   ranks best-fit courses for a consultancy client using OUR verified catalog rows
   as ground truth (no web-search fee on this path). When the catalog is still thin
   for a query it transparently falls back to Google-Search-grounded generation so
   consultants get value from day one while the agent seeds data.

Grounded calls follow app/university_shortlist.py (google-genai SDK — the legacy
google-generativeai package only ships GoogleSearchRetrieval, which Gemini 2.x+
rejects); ungrounded fallback uses gemini_service._generate_content_with_fallback
so a single retired model id never kills the feature.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app import models
from app.utils import gemini_service

logger = logging.getLogger(__name__)

# Destination countries the catalog covers (same launch set as the rest of the app).
def catalog_countries() -> list[dict]:
    """[{code, name, flag_emoji, student_intakes}] for every catalog country."""
    from app import enterprise_catalog
    from app.visa_catalog import LAUNCH_COUNTRY_CODES
    out = []
    for code in LAUNCH_COUNTRY_CODES:
        meta = enterprise_catalog.COUNTRY_MAP.get(code)
        if meta:
            out.append({
                "code": code,
                "name": meta["name"],
                "flag_emoji": meta.get("flag_emoji", ""),
                "student_intakes": meta.get("student_intakes", []),
            })
    return out


def country_name(code: str) -> Optional[str]:
    for c in catalog_countries():
        if c["code"] == (code or "").upper():
            return c["name"]
    return None


# Canonical discipline buckets — the enrichment prompt forces every course into one,
# so the browse filter works without free-text chaos.
DISCIPLINES = [
    "Business & Management",
    "Computer Science & IT",
    "Data Science & AI",
    "Engineering",
    "Health & Medicine",
    "Nursing",
    "Natural Sciences",
    "Mathematics & Statistics",
    "Social Sciences",
    "Psychology",
    "Law",
    "Economics & Finance",
    "Arts & Design",
    "Architecture",
    "Education",
    "Media & Communications",
    "Hospitality & Tourism",
    "Environmental Science & Sustainability",
    "Agriculture & Food Science",
    "Other",
]
_DISCIPLINE_SET = {d.lower(): d for d in DISCIPLINES}

DEGREE_LEVELS = [
    {"key": "bachelors", "label": "Bachelor's"},
    {"key": "masters", "label": "Master's"},
    {"key": "phd", "label": "PhD / Doctorate"},
    {"key": "diploma", "label": "Diploma / Certificate"},
    {"key": "other", "label": "Other"},
]
_LEVEL_KEYS = {l["key"] for l in DEGREE_LEVELS}

_FIT_LEVELS = {"reach", "match", "safety"}

# Recommendation context sizing: how many catalog courses we hand the model, and the
# minimum catalog matches under which we fall back to grounded live search.
RECOMMEND_CONTEXT_COURSES = int(os.getenv("COURSE_FINDER_CONTEXT_COURSES", "40"))
RECOMMEND_MIN_CATALOG_ROWS = int(os.getenv("COURSE_FINDER_MIN_CATALOG_ROWS", "5"))
RECOMMEND_MAX_RESULTS = 8

GROUNDING_ENABLED = os.getenv("COURSE_CATALOG_GROUNDING_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}

# Re-verification cadence (same env var as the refresh agent) — a course not
# re-confirmed across ~2 cycles is treated as renamed/discontinued and pruned.
_REVERIFY_DAYS = max(1, int(os.getenv("COURSE_CATALOG_REVERIFY_DAYS", "30") or "30"))


def ai_available() -> bool:
    has_service_account = os.path.exists(gemini_service.SERVICE_ACCOUNT_PATH)
    has_valid_api_key = bool(
        gemini_service.GEMINI_API_KEY and gemini_service.GEMINI_API_KEY.startswith("AIza")
    )
    return has_service_account or has_valid_api_key


def _model_candidates() -> list[str]:
    try:
        candidates = gemini_service.get_model_candidates(
            primary_env="COURSE_CATALOG_MODEL",
            candidates_env="COURSE_CATALOG_MODEL_CANDIDATES",
        )
    except Exception:
        candidates = []
    return candidates or [os.getenv("GEMINI_MODEL", "gemini-3.1-pro")]


def normalize_key(name: str) -> str:
    """Dedup key: lowercase, strip punctuation, collapse spaces, drop a leading 'the '.
    Makes "The University of Melbourne" == "University of Melbourne."."""
    s = re.sub(r"[^a-z0-9 ]+", " ", str(name or "").lower())
    s = re.sub(r"\s+", " ", s).strip()
    if s.startswith("the "):
        s = s[4:]
    return s[:200]


# ---------------------------------------------------------------------------
# Gemini helpers (grounded-first with ungrounded fallback)
# ---------------------------------------------------------------------------

def _extract_grounding_urls(response: Any, limit: int = 8) -> list[str]:
    """Real source URLs from grounding metadata (mirrors routers/news.py)."""
    urls: list[str] = []
    try:
        for candidate in (getattr(response, "candidates", None) or []):
            meta = getattr(candidate, "grounding_metadata", None)
            for chunk in (getattr(meta, "grounding_chunks", None) or []):
                web = getattr(chunk, "web", None)
                uri = str(getattr(web, "uri", "") or "").strip()
                if uri.startswith("http") and uri not in urls:
                    urls.append(uri[:400])
                if len(urls) >= limit:
                    return urls
    except Exception:
        pass
    return urls


# Second-level public suffixes common for university domains, so eTLD+1 extraction
# doesn't collapse "unimelb.edu.au" to "edu.au".
_SECOND_LEVEL_SUFFIXES = {
    "ac.uk", "co.uk", "org.uk", "gov.uk", "ac.ie",
    "edu.au", "com.au", "org.au", "ac.nz", "co.nz",
    "edu.in", "ac.in", "co.in", "edu.pk", "edu.bd", "edu.np", "edu.lk",
    "edu.sg", "com.sg", "edu.my", "edu.hk", "com.hk", "edu.cn", "com.cn",
    "ac.jp", "co.jp", "ac.kr", "co.kr", "edu.tw",
    "ac.za", "co.za", "edu.br", "com.br", "edu.mx", "com.mx",
    "ac.at", "ac.ir", "edu.tr", "edu.sa", "edu.eg", "ac.ae",
}


def _registrable_domain(url) -> Optional[str]:
    """eTLD+1-ish domain of a URL ("https://www.study.unimelb.edu.au/x" → "unimelb.edu.au").
    Heuristic suffix list, not the full PSL — plenty for comparing university domains."""
    try:
        host = (urlparse(str(url or "")).hostname or "").lower().strip(".")
    except Exception:
        return None
    if not host or "." not in host:
        return None
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _SECOND_LEVEL_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _extract_grounding_domains(response: Any, limit: int = 24) -> set[str]:
    """Registrable domains of the pages Google Search grounding actually consulted.
    Used to corroborate model-returned website URLs — grounded output is untrusted
    web-derived content, so a URL the sources never mentioned must not persist.
    chunk.web.uri is usually a vertexaisearch redirect; chunk.web.domain has the
    real host, so both are tried (Google's own hosts filtered out)."""
    domains: set[str] = set()
    try:
        for candidate in (getattr(response, "candidates", None) or []):
            meta = getattr(candidate, "grounding_metadata", None)
            for chunk in (getattr(meta, "grounding_chunks", None) or []):
                web = getattr(chunk, "web", None)
                for raw in (getattr(web, "domain", None), getattr(web, "uri", None)):
                    raw = str(raw or "").strip()
                    if not raw:
                        continue
                    if not raw.startswith("http"):
                        raw = f"https://{raw}"
                    d = _registrable_domain(raw)
                    if d and "google" not in d:
                        domains.add(d)
                if len(domains) >= limit:
                    return domains
    except Exception:
        pass
    return domains


def _grounded_generate(prompt: str, model_name: str, usage_source: str):
    """Google-Search-grounded JSON generation (google-genai SDK, API-key auth).

    Returns (text, source_urls, source_domains) or None so the caller falls back to
    the ungrounded model — catalog runs must survive grounding being unavailable.
    """
    if not GROUNDING_ENABLED:
        return None
    api_key = (getattr(gemini_service, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")).strip()
    if not api_key or not api_key.startswith("AIza"):
        return None
    try:
        from google import genai as _genai
        from google.genai import types as _types

        client = _genai.Client(api_key=api_key)
        config = _types.GenerateContentConfig(
            tools=[_types.Tool(google_search=_types.GoogleSearch())],
            temperature=0.3,
        )
        response = client.models.generate_content(model=model_name, contents=prompt, config=config)
        text = (getattr(response, "text", "") or "").strip()
        if not text:
            return None
        try:
            from app import ai_usage
            ai_usage.record_gemini_usage(usage_source, model_name, response)
        except Exception:
            pass
        return text, _extract_grounding_urls(response), _extract_grounding_domains(response)
    except Exception as exc:
        logger.warning("Course catalog grounding unavailable (%s); using ungrounded model.", exc)
        return None


def _generate_json(prompt: str, usage_source: str, *, prefer_grounded: bool) -> tuple[Optional[dict], bool, list[str], set[str], str]:
    """Run the prompt and parse a JSON object.
    Returns (data, grounded, source_urls, source_domains, model)."""
    candidates = _model_candidates()
    model_name = candidates[0]
    text: str = ""
    grounded = False
    source_urls: list[str] = []
    source_domains: set[str] = set()
    if prefer_grounded:
        grounded_result = _grounded_generate(prompt, model_name, usage_source)
        if grounded_result is not None:
            text, source_urls, source_domains = grounded_result
            grounded = True
    if not text:
        response = gemini_service._generate_content_with_fallback(candidates, prompt, usage_source=usage_source)
        text = (getattr(response, "text", "") or "")
        # The fallback chain may have served from a later candidate — report the
        # model that actually answered when the response exposes it.
        model_name = str(getattr(response, "model_version", "") or "").strip() or model_name
    return _parse_json_object(text), grounded, source_urls, source_domains, model_name


def _parse_json_object(raw: str) -> Optional[dict]:
    raw = (raw or "").strip()
    if raw.startswith("```json"):
        raw = raw[7:].strip()
    elif raw.startswith("```"):
        raw = raw[3:].strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    fb, lb = raw.find("{"), raw.rfind("}")
    if fb == -1 or lb == -1 or lb <= fb:
        return None
    try:
        data = json.loads(raw[fb:lb + 1])
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _clean_text(value, limit: int) -> Optional[str]:
    s = str(value or "").strip()
    if not s or s.lower() in {"n/a", "na", "none", "null", "unknown", "-", ""}:
        return None
    return s[:limit]


def _clean_url(value) -> Optional[str]:
    """Only absolute http(s) URLs survive — model output is rendered as hrefs, so a
    javascript:/data: value must never persist (stored-XSS vector)."""
    s = str(value or "").strip()
    if not s or s.lower() in {"n/a", "na", "none", "null", "unknown", "-"}:
        return None
    if not re.match(r"^https?://[^\s/$.?#].[^\s]*$", s, re.I):
        return None
    return s[:400]


def _clean_rank(value) -> Optional[str]:
    s = str(value or "").strip().lstrip("#").strip()
    if not s or s.lower() in {"n/a", "na", "none", "null", "unknown", "unranked", "-"}:
        return None
    return s[:20]


def _clean_level(value) -> str:
    s = str(value or "").strip().lower()
    if s in _LEVEL_KEYS:
        return s
    if "bachelor" in s or "undergrad" in s or s in {"ug", "bs", "ba"}:
        return "bachelors"
    if "master" in s or "msc" in s or "postgrad" in s or s in {"pg", "ms", "mba"}:
        return "masters"
    if "phd" in s or "doctor" in s:
        return "phd"
    if "diploma" in s or "certificate" in s:
        return "diploma"
    return "other"


def _clean_discipline(value) -> Optional[str]:
    s = str(value or "").strip()
    if not s:
        return None
    canonical = _DISCIPLINE_SET.get(s.lower())
    if canonical:
        return canonical
    lowered = s.lower()
    for key, label in _DISCIPLINE_SET.items():
        if key != "other" and (key in lowered or lowered in key):
            return label
    return "Other"


def _clean_int(value) -> Optional[int]:
    try:
        n = int(round(float(re.sub(r"[^0-9.]", "", str(value)) or "nan")))
        return n if 0 < n < 10_000_000 else None
    except Exception:
        return None


def _clean_intakes(value) -> Optional[str]:
    if isinstance(value, list):
        items = [str(v).strip()[:30] for v in value if str(v).strip()][:6]
        return json.dumps(items) if items else None
    s = _clean_text(value, 120)
    if not s:
        return None
    return json.dumps([p.strip()[:30] for p in re.split(r"[,;/]+", s) if p.strip()][:6])


# ---------------------------------------------------------------------------
# 1) Discovery — top-N universities per country (stub rows)
# ---------------------------------------------------------------------------

def discover_universities(db: Session, country_code: str, target: int, usage_source: str = "course_catalog_refresh") -> int:
    """Ask grounded Gemini for the top universities for international students in a
    country; insert missing ones as stub rows (enriched later). Returns rows added."""
    code = (country_code or "").upper()
    cname = country_name(code)
    if not cname:
        return 0
    existing = (
        db.query(models.CourseCatalogUniversity)
        .filter(models.CourseCatalogUniversity.country_code == code)
        .all()
    )
    existing_keys = {u.name_key for u in existing}
    want = max(0, int(target) - len([u for u in existing if u.is_active]))
    if want <= 0:
        return 0

    prompt = (
        "You are Rilono AI, a study-abroad data researcher building a verified university database.\n"
        f"List the TOP {int(target)} universities in {cname} for INTERNATIONAL students, ranked by a blend of "
        "QS World University Ranking, national reputation and popularity with international applicants.\n\n"
        'Return STRICTLY a JSON object: {"universities":[{'
        '"name":"Official university name",'
        '"city":"City, Region",'
        '"qs_world_rank":"Most recent QS World rank as a plain number or range, e.g. \\"34\\" or \\"301-350\\". \\"N/A\\" if unranked.",'
        '"national_rank":"Rank within the country as a plain number. \\"N/A\\" if unsure.",'
        '"university_type":"public | private",'
        '"website":"Absolute https:// official website URL. \\"N/A\\" if unsure."'
        "}]}\n\n"
        "Rules:\n"
        f"- Only real, currently operating universities in {cname}.\n"
        "- Order the list best-ranked first.\n"
        "- Use up-to-date ranking sources; use \"N/A\" rather than guessing.\n"
        "- URLs must be the university's real official domain — never invent one.\n"
        "- Output ONLY the JSON object, no prose and no ``` fences."
    )
    data, grounded, _urls, source_domains, _model = _generate_json(prompt, usage_source, prefer_grounded=True)
    items = (data or {}).get("universities")
    if not isinstance(items, list):
        logger.warning("Course catalog discovery for %s returned no usable list.", code)
        return 0

    added = 0
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        name = _clean_text(item.get("name"), 200)
        if not name:
            continue
        key = normalize_key(name)
        if not key or key in existing_keys:
            continue
        existing_keys.add(key)
        # This catalog is shared across every tenant, so a model-invented (or
        # search-poisoned) domain must never persist: only keep a website the
        # grounded sources corroborate — enrichment gets another shot later.
        site = _clean_url(item.get("website"))
        if site and _registrable_domain(site) not in source_domains:
            site = None
        db.add(models.CourseCatalogUniversity(
            country_code=code,
            name=name,
            name_key=key,
            city=_clean_text(item.get("city"), 160),
            qs_world_rank=_clean_rank(item.get("qs_world_rank")),
            national_rank=_clean_rank(item.get("national_rank")),
            university_type=_clean_text(item.get("university_type"), 20),
            website_url=site,
            seed_rank=idx + 1,
            is_active=True,
        ))
        added += 1
        if added >= want:
            break
    db.commit()
    logger.info("Course catalog discovery %s: +%d universities (grounded=%s)", code, added, grounded)
    return added


# ---------------------------------------------------------------------------
# 2) Enrichment — full profile + courses for one university
# ---------------------------------------------------------------------------

def refresh_university(db: Session, uni: models.CourseCatalogUniversity, usage_source: str = "course_catalog_refresh") -> dict:
    """Grounded refresh of one university's profile + flagship international courses.
    Upserts courses (update-by-key or insert) and stamps last_verified_at. Returns
    {"courses_upserted": int, "grounded": bool}. Raises on total AI failure so the
    caller can decide (a failed refresh must NOT stamp last_verified_at)."""
    cname = country_name(uni.country_code) or uni.country_code
    prompt = (
        "You are Rilono AI, a study-abroad data researcher keeping a university database current.\n"
        f"Research {uni.name} ({cname}) and return its CURRENT profile and its most popular degree "
        "programs for INTERNATIONAL students.\n\n"
        'Return STRICTLY a JSON object:\n{'
        '"profile":{'
        '"city":"City, Region",'
        '"qs_world_rank":"Most recent QS World rank, plain number or range. \\"N/A\\" if unranked.",'
        '"national_rank":"Rank within the country, plain number. \\"N/A\\" if unsure.",'
        '"university_type":"public | private",'
        '"website":"Absolute https:// official website URL",'
        '"tuition_note":"Typical annual tuition band for international students with currency, e.g. \\"USD 45,000 - 62,000/year\\"",'
        '"summary":"1-2 sentences on what this university is known for",'
        '"scholarships_note":"1 sentence on the main scholarships international students actually get, or \\"N/A\\""'
        "},"
        '"courses":[{'
        '"course_name":"Official program name, e.g. \\"MSc Computer Science\\"",'
        '"degree_level":"bachelors | masters | phd | diploma",'
        f'"discipline":"EXACTLY one of: {", ".join(DISCIPLINES)}",'
        '"duration":"e.g. \\"2 years\\"",'
        '"annual_tuition":"Annual international tuition with currency, e.g. \\"USD 58,000/year\\"",'
        '"tuition_amount":"Annual tuition as a plain integer in the local currency, e.g. 58000. null if unsure.",'
        '"tuition_currency":"3-letter code, e.g. USD",'
        '"intakes":["Fall","Spring"],'
        '"application_deadline":"Next main intake deadline, e.g. \\"Dec 15, 2026 (Fall 2027)\\". \\"N/A\\" if unsure.",'
        '"application_fee":"With currency, e.g. \\"USD 90\\", or \\"No application fee\\"",'
        '"ielts_requirement":"e.g. \\"6.5 overall (6.0 in each band)\\". \\"N/A\\" if not published.",'
        '"toefl_requirement":"e.g. \\"90 iBT\\". \\"N/A\\" if not published.",'
        '"gre_gmat_requirement":"e.g. \\"GRE optional\\" or \\"Not required\\"",'
        '"entry_requirements":"Short academic requirement summary (GPA/percentage, prerequisite degree)",'
        '"course_url":"Absolute https:// official program page URL. \\"N/A\\" if unsure."'
        "}]}\n\n"
        "Rules:\n"
        "- Return 8 to 14 courses spread across the university's strongest disciplines "
        "(not 14 variants of one department), prioritizing programs international students actually enroll in.\n"
        "- Fees, deadlines and score cutoffs must reflect the university's CURRENT published figures — "
        "use up-to-date sources; use \"N/A\" rather than guessing.\n"
        "- URLs must be on the university's real official domain — never invent one; \"N/A\" instead.\n"
        "- The application fee is the one-off fee to APPLY, which is different from tuition.\n"
        "- Output ONLY the JSON object, no prose and no ``` fences."
    )
    data, grounded, source_urls, source_domains, _model = _generate_json(prompt, usage_source, prefer_grounded=True)
    if not data:
        raise RuntimeError(f"Catalog refresh for {uni.name}: model returned no usable JSON")

    # URL trust policy (this table is cross-tenant and its links render as "official"):
    # the university's website domain may only be SET or CHANGED to a domain the
    # grounded sources corroborate (or kept as-is), and every course_url must live on
    # that same registrable domain — a prompt-injected/hallucinated off-domain link
    # is dropped rather than served to every consultancy as verified data.
    established_domain = _registrable_domain(uni.website_url)
    profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
    if profile:
        uni.city = _clean_text(profile.get("city"), 160) or uni.city
        uni.qs_world_rank = _clean_rank(profile.get("qs_world_rank")) or uni.qs_world_rank
        uni.national_rank = _clean_rank(profile.get("national_rank")) or uni.national_rank
        uni.university_type = _clean_text(profile.get("university_type"), 20) or uni.university_type
        new_site = _clean_url(profile.get("website"))
        if new_site:
            new_domain = _registrable_domain(new_site)
            if new_domain and (new_domain == established_domain or new_domain in source_domains):
                uni.website_url = new_site
            elif not established_domain:
                logger.info(
                    "Catalog refresh %s: uncorroborated website domain %r dropped", uni.name, new_domain
                )
        uni.tuition_note = _clean_text(profile.get("tuition_note"), 160) or uni.tuition_note
        uni.summary = _clean_text(profile.get("summary"), 500) or uni.summary
        uni.scholarships_note = _clean_text(profile.get("scholarships_note"), 400) or uni.scholarships_note
    if source_urls:
        uni.source_urls = json.dumps(source_urls)
    site_domain = _registrable_domain(uni.website_url)

    existing_courses = {
        (c.name_key, c.degree_level): c
        for c in db.query(models.CourseCatalogCourse).filter(models.CourseCatalogCourse.university_id == uni.id).all()
    }
    now = datetime.now(timezone.utc)
    upserted = 0
    items = data.get("courses")
    for item in (items if isinstance(items, list) else [])[:16]:
        if not isinstance(item, dict):
            continue
        cname_course = _clean_text(item.get("course_name"), 200)
        if not cname_course:
            continue
        level = _clean_level(item.get("degree_level"))
        key = normalize_key(cname_course)
        if not key:
            continue
        row = existing_courses.get((key, level))
        if row is None:
            row = models.CourseCatalogCourse(
                university_id=uni.id, country_code=uni.country_code,
                course_name=cname_course, name_key=key, degree_level=level,
            )
            db.add(row)
            existing_courses[(key, level)] = row
        row.course_name = cname_course
        row.discipline = _clean_discipline(item.get("discipline")) or row.discipline
        row.duration = _clean_text(item.get("duration"), 60) or row.duration
        row.annual_tuition = _clean_text(item.get("annual_tuition"), 80) or row.annual_tuition
        row.tuition_amount = _clean_int(item.get("tuition_amount")) or row.tuition_amount
        row.tuition_currency = (_clean_text(item.get("tuition_currency"), 8) or row.tuition_currency or "").upper() or None
        row.intakes = _clean_intakes(item.get("intakes")) or row.intakes
        # Deadline is the one field that ROTS: unlike the keep-old pattern above, an
        # "N/A" here must CLEAR the stored value — re-stamping an expired deadline as
        # freshly verified is worse than showing none.
        row.application_deadline = _clean_text(item.get("application_deadline"), 120)
        row.application_fee = _clean_text(item.get("application_fee"), 60) or row.application_fee
        row.ielts_requirement = _clean_text(item.get("ielts_requirement"), 80) or row.ielts_requirement
        row.toefl_requirement = _clean_text(item.get("toefl_requirement"), 80) or row.toefl_requirement
        row.gre_gmat_requirement = _clean_text(item.get("gre_gmat_requirement"), 80) or row.gre_gmat_requirement
        row.entry_requirements = _clean_text(item.get("entry_requirements"), 400) or row.entry_requirements
        course_url = _clean_url(item.get("course_url"))
        # Strict same-domain rule (also scrubs any pre-validation legacy value).
        row.course_url = (
            course_url
            if course_url and site_domain and _registrable_domain(course_url) == site_domain
            else None
        )
        row.is_active = True
        row.last_verified_at = now
        upserted += 1

    if upserted == 0:
        # Profile-only responses shouldn't count as a verified refresh of the courses.
        raise RuntimeError(f"Catalog refresh for {uni.name}: no usable courses in response")

    # Prune drift: a course the model hasn't re-confirmed across ~2 re-verification
    # cycles is likely renamed/discontinued — deactivate it (the upsert path revives
    # it automatically if it ever reappears).
    prune_cutoff = now - timedelta(days=2 * _REVERIFY_DAYS + 7)
    for stale in existing_courses.values():
        ts = stale.last_verified_at
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts is None or ts < prune_cutoff:
            stale.is_active = False

    uni.is_active = True
    uni.consecutive_failures = 0
    uni.last_verified_at = now
    db.commit()
    return {"courses_upserted": upserted, "grounded": grounded}


# ---------------------------------------------------------------------------
# Catalog queries + serializers (free browse path)
# ---------------------------------------------------------------------------

def serialize_course(row: models.CourseCatalogCourse) -> dict:
    try:
        intakes = json.loads(row.intakes) if row.intakes else []
        if not isinstance(intakes, list):
            intakes = []
    except Exception:
        intakes = []
    return {
        "id": int(row.id),
        "course_name": row.course_name,
        "degree_level": row.degree_level,
        "discipline": row.discipline,
        "duration": row.duration,
        "annual_tuition": row.annual_tuition,
        "tuition_amount": row.tuition_amount,
        "tuition_currency": row.tuition_currency,
        "intakes": [str(x)[:30] for x in intakes][:6],
        "application_deadline": row.application_deadline,
        "application_fee": row.application_fee,
        "ielts_requirement": row.ielts_requirement,
        "toefl_requirement": row.toefl_requirement,
        "gre_gmat_requirement": row.gre_gmat_requirement,
        "entry_requirements": row.entry_requirements,
        "course_url": row.course_url,
        "last_verified_at": row.last_verified_at.isoformat() if row.last_verified_at else None,
    }


def serialize_university(uni: models.CourseCatalogUniversity, courses: Optional[list] = None) -> dict:
    return {
        "id": int(uni.id),
        "country_code": uni.country_code,
        "name": uni.name,
        "city": uni.city,
        "qs_world_rank": uni.qs_world_rank,
        "national_rank": uni.national_rank,
        "university_type": uni.university_type,
        "website_url": uni.website_url,
        "tuition_note": uni.tuition_note,
        "summary": uni.summary,
        "scholarships_note": uni.scholarships_note,
        "seed_rank": uni.seed_rank,
        "last_verified_at": uni.last_verified_at.isoformat() if uni.last_verified_at else None,
        "courses": [serialize_course(c) for c in (courses or [])],
    }


def query_catalog(
    db: Session,
    *,
    country_code: str,
    degree_level: Optional[str] = None,
    discipline: Optional[str] = None,
    q: Optional[str] = None,
    max_tuition: Optional[int] = None,
    limit_universities: int = 30,
) -> list[tuple[models.CourseCatalogUniversity, list[models.CourseCatalogCourse]]]:
    """Universities (with their matching courses) for the browse view, best-ranked first.

    Course-level filters (level/discipline/q/max_tuition) narrow WHICH courses show
    AND which universities appear (a university with zero matching courses is
    dropped — unless there are no course filters at all, when stub universities
    awaiting enrichment still show with an empty course list).
    """
    from sqlalchemy import or_

    code = (country_code or "").upper()
    uq = (
        db.query(models.CourseCatalogUniversity)
        .filter(
            models.CourseCatalogUniversity.country_code == code,
            models.CourseCatalogUniversity.is_active.is_(True),
        )
    )
    has_course_filters = bool(degree_level or discipline or q or max_tuition)
    unis = uq.all()

    # Sort: seeded rank first (it encodes the discovery ordering), then name.
    unis.sort(key=lambda u: (u.seed_rank if u.seed_rank is not None else 10_000, u.name or ""))

    cq = db.query(models.CourseCatalogCourse).filter(
        models.CourseCatalogCourse.country_code == code,
        models.CourseCatalogCourse.is_active.is_(True),
    )
    if degree_level and degree_level in _LEVEL_KEYS:
        cq = cq.filter(models.CourseCatalogCourse.degree_level == degree_level)
    if discipline:
        cq = cq.filter(models.CourseCatalogCourse.discipline == discipline)
    if max_tuition:
        cq = cq.filter(
            models.CourseCatalogCourse.tuition_amount.isnot(None),
            models.CourseCatalogCourse.tuition_amount <= int(max_tuition),
        )
    if q:
        needle = f"%{str(q).strip()[:80]}%"
        cq = cq.filter(or_(
            models.CourseCatalogCourse.course_name.ilike(needle),
            models.CourseCatalogCourse.discipline.ilike(needle),
        ))
    by_uni: dict[int, list[models.CourseCatalogCourse]] = {}
    for course in cq.all():
        by_uni.setdefault(course.university_id, []).append(course)
    for course_list in by_uni.values():
        course_list.sort(key=lambda c: (c.degree_level or "", c.course_name or ""))

    # A name search should also surface universities matched BY NAME even when no
    # course matches (consultants search "melbourne" as often as "data science").
    name_needle = str(q).strip().lower() if q else ""

    out = []
    for uni in unis:
        matched = by_uni.get(uni.id, [])
        if has_course_filters and not matched:
            if not (name_needle and name_needle in (uni.name or "").lower()):
                continue
        out.append((uni, matched))
        if len(out) >= max(1, int(limit_universities)):
            break
    return out


def catalog_stats(db: Session) -> dict:
    """Per-country row counts + freshness for the meta endpoint / admin console."""
    from sqlalchemy import func as sqlfunc

    uni_counts = dict(
        db.query(models.CourseCatalogUniversity.country_code, sqlfunc.count(models.CourseCatalogUniversity.id))
        .filter(models.CourseCatalogUniversity.is_active.is_(True))
        .group_by(models.CourseCatalogUniversity.country_code).all()
    )
    enriched_counts = dict(
        db.query(models.CourseCatalogUniversity.country_code, sqlfunc.count(models.CourseCatalogUniversity.id))
        .filter(
            models.CourseCatalogUniversity.is_active.is_(True),
            models.CourseCatalogUniversity.last_verified_at.isnot(None),
        )
        .group_by(models.CourseCatalogUniversity.country_code).all()
    )
    course_counts = dict(
        db.query(models.CourseCatalogCourse.country_code, sqlfunc.count(models.CourseCatalogCourse.id))
        .filter(models.CourseCatalogCourse.is_active.is_(True))
        .group_by(models.CourseCatalogCourse.country_code).all()
    )
    latest = dict(
        db.query(models.CourseCatalogUniversity.country_code, sqlfunc.max(models.CourseCatalogUniversity.last_verified_at))
        .group_by(models.CourseCatalogUniversity.country_code).all()
    )
    countries = []
    for c in catalog_countries():
        code = c["code"]
        latest_ts = latest.get(code)
        countries.append({
            **c,
            "universities": int(uni_counts.get(code, 0)),
            "universities_enriched": int(enriched_counts.get(code, 0)),
            "courses": int(course_counts.get(code, 0)),
            "last_verified_at": latest_ts.isoformat() if latest_ts else None,
        })
    return {"countries": countries}


# ---------------------------------------------------------------------------
# 3) Recommendation — the billed Course Finder AI action
# ---------------------------------------------------------------------------

def _client_profile_block(client) -> str:
    """Compact dossier facts for personalization. Includes scalar stage_data fields
    (that's where consultants record academics/budget — there are no typed columns)."""
    lines = [
        f"- Name: {client.full_name}",
        f"- Nationality / home country: {client.nationality or 'Not recorded'}",
        f"- Destination: {client.destination_country_name or client.destination_country_code or 'Not recorded'}",
        f"- Visa type: {client.visa_type or 'Student'}",
        f"- Target intake: {client.intake or 'Not recorded'}",
    ]
    if getattr(client, "target_date", None):
        lines.append(f"- Target date: {client.target_date}")
    try:
        stage_data = json.loads(client.stage_data) if client.stage_data else {}
    except Exception:
        stage_data = {}
    added = 0
    if isinstance(stage_data, dict):
        for _stage, fields in stage_data.items():
            if not isinstance(fields, dict):
                continue
            for field_key, value in fields.items():
                if added >= 18:
                    break
                if isinstance(value, (str, int, float)) and str(value).strip():
                    text_value = str(value).strip()
                    if len(text_value) > 160:
                        text_value = text_value[:160] + "…"
                    label = str(field_key).replace("_", " ").strip()[:60]
                    lines.append(f"- {label}: {text_value}")
                    added += 1
    return "\n".join(lines)


def _catalog_context_block(rows: list[tuple[Any, list]]) -> tuple[str, int]:
    """Compact JSON-lines context of catalog courses for the recommendation prompt."""
    lines: list[str] = []
    count = 0
    for uni, courses in rows:
        for course in courses:
            if count >= RECOMMEND_CONTEXT_COURSES:
                break
            entry = {
                "university": uni.name,
                "city": uni.city,
                "qs_world_rank": uni.qs_world_rank,
                "course": course.course_name,
                "level": course.degree_level,
                "discipline": course.discipline,
                "duration": course.duration,
                "annual_tuition": course.annual_tuition,
                "intakes": course.intakes,
                "deadline": course.application_deadline,
                "application_fee": course.application_fee,
                "ielts": course.ielts_requirement,
                "toefl": course.toefl_requirement,
                "gre_gmat": course.gre_gmat_requirement,
                "entry_requirements": course.entry_requirements,
                # URLs deliberately excluded: catalog hits get their (domain-validated)
                # URLs snapped from the DB after parsing, never echoed via the model.
            }
            lines.append(json.dumps({k: v for k, v in entry.items() if v}, ensure_ascii=False))
            count += 1
    return "\n".join(lines), count


def recommend_courses(
    *,
    destination_country: str,
    catalog_rows: list,
    client=None,
    field_of_study: Optional[str] = None,
    degree_level: Optional[str] = None,
    discipline: Optional[str] = None,
    budget: Optional[str] = None,
    notes: Optional[str] = None,
    max_results: int = 6,
    usage_source: str = "enterprise_course_finder",
) -> dict:
    """Rilono AI course recommendations. Never raises.

    Catalog-first: when we have enough verified rows, the model ranks OUR data
    (cheap — no live search). Thin catalog → grounded live search so the feature
    still delivers while the background agent seeds. Returns
    {available, summary, recommendations, grounded, catalog_based, model}.
    """
    max_results = max(1, min(int(max_results or 6), RECOMMEND_MAX_RESULTS))
    if not ai_available():
        return {"available": False, "recommendations": [], "message": "AI recommendations are not configured."}

    catalog_block, catalog_count = _catalog_context_block(catalog_rows)
    catalog_based = catalog_count >= RECOMMEND_MIN_CATALOG_ROWS

    profile_lines = []
    if client is not None:
        profile_lines.append("STUDENT PROFILE (from the consultancy's case record):\n" + _client_profile_block(client))
    request_lines = [
        f"- Destination country: {destination_country}",
        f"- Field of study: {field_of_study or discipline or 'Not specified'}",
        f"- Degree level: {degree_level or 'Not specified'}",
        f"- Approximate annual budget: {budget or 'Not specified'}",
        f"- Consultant notes/preferences: {notes or 'None'}",
    ]

    schema = (
        '{"summary":"2-3 sentence overview of the strategy behind this shortlist",'
        '"recommendations":[{'
        '"university_name":"University name",'
        '"course_name":"Program name",'
        '"degree_level":"bachelors | masters | phd | diploma",'
        '"location":"City, Region",'
        '"fit_level":"reach | match | safety",'
        '"why_recommended":"2-3 sentences tied to THIS student/request",'
        '"annual_tuition":"With currency, e.g. \\"USD 52,000/year\\"",'
        '"intakes":"e.g. \\"Fall, Spring\\"",'
        '"application_deadline":"e.g. \\"Dec 15, 2026\\" or \\"N/A\\"",'
        '"application_fee":"e.g. \\"USD 90\\" or \\"N/A\\"",'
        '"key_requirements":["short requirement 1","short requirement 2"],'
        '"course_url":"Absolute https:// URL or \\"N/A\\"",'
        '"website_url":"Absolute https:// URL or \\"N/A\\"",'
        '"qs_world_rank":"Plain number/range or \\"N/A\\"",'
        '"in_catalog":true'
        "}]}"
    )

    if catalog_based:
        source_rules = (
            "COURSE DATABASE (verified by Rilono — treat as ground truth for fees/requirements):\n"
            f"{catalog_block}\n\n"
            "Rules:\n"
            "- Recommend from the COURSE DATABASE above; copy its fees, deadlines and requirements exactly (set in_catalog=true).\n"
            "- If (and only if) the database lacks a genuinely better fit for this request, you may add up to 2 well-known "
            "alternatives from your own knowledge — set in_catalog=false for those and keep their figures conservative.\n"
        )
    else:
        source_rules = (
            (f"COURSE DATABASE (partial — our researcher agent is still filling this destination):\n{catalog_block}\n\n" if catalog_block else "")
            + "Rules:\n"
            "- Our database has too few matches for this request, so recommend real, currently offered programs "
            "using up-to-date sources; set in_catalog=false for anything not in the database above.\n"
            "- Be accurate about current tuition, deadlines and score requirements; use \"N/A\" rather than guessing.\n"
        )

    prompt = (
        "You are Rilono AI, a study-abroad admissions strategist working for a visa consultancy. "
        f"Build the best-fit course shortlist for this request.\n\n"
        + ("\n".join(profile_lines) + "\n\n" if profile_lines else "")
        + "REQUEST:\n" + "\n".join(request_lines) + "\n\n"
        + source_rules
        + f"- Return up to {max_results} recommendations ranked best-fit first, mixing reach/match/safety when possible.\n"
        "- Only programs in the destination country.\n"
        "- URLs must be real official university domains, starting with https:// — never invent one; \"N/A\" instead.\n"
        f"- Return STRICTLY this JSON object, no prose, no ``` fences:\n{schema}\n"
        "- Identity guardrail: never mention Gemini, Google, or internal model names; you are Rilono AI."
    )

    # "✓ Verified" in the UI hangs off in_catalog, so it is computed HERE by matching
    # against the rows we actually handed the model — never trusted from model output.
    # Catalog hits also get their URLs from our domain-validated rows, not the model.
    catalog_keys: set[tuple[str, str]] = set()
    catalog_course_urls: dict[tuple[str, str], Optional[str]] = {}
    catalog_site_urls: dict[str, Optional[str]] = {}
    for cat_uni, cat_courses in (catalog_rows or []):
        uk = normalize_key(cat_uni.name)
        catalog_site_urls.setdefault(uk, cat_uni.website_url)
        for cat_course in cat_courses:
            ck = (uk, normalize_key(cat_course.course_name))
            catalog_keys.add(ck)
            catalog_course_urls.setdefault(ck, cat_course.course_url)

    try:
        data, grounded, _urls, _domains, model_name = _generate_json(prompt, usage_source, prefer_grounded=not catalog_based)
        items = (data or {}).get("recommendations")
        recommendations = []
        for item in (items if isinstance(items, list) else [])[:max_results]:
            if not isinstance(item, dict):
                continue
            uni_name = _clean_text(item.get("university_name"), 200)
            course_name_value = _clean_text(item.get("course_name"), 200)
            if not uni_name or not course_name_value:
                continue
            fit = str(item.get("fit_level") or "match").strip().lower()
            reqs = item.get("key_requirements")
            requirements = [str(r).strip()[:140] for r in reqs if str(r).strip()][:6] if isinstance(reqs, list) else []
            rec_key = (normalize_key(uni_name), normalize_key(course_name_value))
            in_catalog = rec_key in catalog_keys
            if in_catalog:
                course_url = catalog_course_urls.get(rec_key)
                website_url = catalog_site_urls.get(rec_key[0])
            else:
                course_url = _clean_url(item.get("course_url"))
                website_url = _clean_url(item.get("website_url"))
            recommendations.append({
                "university_name": uni_name,
                "course_name": course_name_value,
                "degree_level": _clean_level(item.get("degree_level")),
                "location": _clean_text(item.get("location"), 160),
                "fit_level": fit if fit in _FIT_LEVELS else "match",
                "why_recommended": _clean_text(item.get("why_recommended"), 600),
                "annual_tuition": _clean_text(item.get("annual_tuition"), 80),
                "intakes": _clean_text(item.get("intakes"), 120),
                "application_deadline": _clean_text(item.get("application_deadline"), 120),
                "application_fee": _clean_text(item.get("application_fee"), 60),
                "key_requirements": requirements,
                "course_url": course_url,
                "website_url": website_url,
                "qs_world_rank": _clean_rank(item.get("qs_world_rank")),
                "in_catalog": in_catalog,
            })
        return {
            "available": True,
            "summary": _clean_text((data or {}).get("summary"), 800),
            "recommendations": recommendations,
            "grounded": grounded,
            "catalog_based": catalog_based,
            "model": model_name,
        }
    except Exception as exc:
        logger.warning("Course Finder recommendation failed: %s", exc)
        return {"available": False, "recommendations": [], "message": "Could not generate recommendations right now."}
