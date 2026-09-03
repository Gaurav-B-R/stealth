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
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from sqlalchemy import text as sqltext
from sqlalchemy.orm import Session, object_session

from app import models
from app.utils import gemini_service

logger = logging.getLogger(__name__)

# Destination countries the catalog covers: every CRM destination. Deliberately
# broader than visa_catalog.LAUNCH_COUNTRY_CODES (the B2C visa-journey launch set) —
# a CRM client can be bound for any COUNTRIES entry, so the Course Finder must be too.
# Adding a country to enterprise_catalog.COUNTRIES automatically brings it here, and
# the nightly refresh agent starts seeding it on its next run (one discovery call,
# then enrichment paced by COURSE_CATALOG_DAILY_BATCH).
def catalog_countries() -> list[dict]:
    """[{code, name, flag_emoji, student_intakes}] for every catalog country."""
    from app import enterprise_catalog
    return [
        {
            "code": meta["code"],
            "name": meta["name"],
            "flag_emoji": meta.get("flag_emoji", ""),
            "student_intakes": meta.get("student_intakes", []),
        }
        for meta in enterprise_catalog.COUNTRIES
    ]


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

# ---------------------------------------------------------------------------
# Advanced browse filters
#
# One vocabulary, served to the UI by /course-catalog/meta AND used to validate the
# incoming query — so a value the dropdown offers is always a value the query accepts.
# ---------------------------------------------------------------------------

INTAKE_BUCKETS = [
    {"key": "fall", "label": "Fall / Autumn (Aug–Oct)"},
    {"key": "spring", "label": "Spring (Jan–Mar)"},
    {"key": "summer", "label": "Summer (May–Jul)"},
    {"key": "winter", "label": "Winter (Nov–Dec)"},
]
# Substrings matched (case-insensitively) against the stored intakes JSON. Universities
# publish intakes as seasons OR months ("Fall" vs "September"), so a season bucket has to
# cover both spellings or half the catalog would look like it has no intake at all.
_INTAKE_MATCH = {
    "fall": ["fall", "autumn", "aug", "sep", "oct"],
    "spring": ["spring", "jan", "feb", "mar"],
    "summer": ["summer", "may", "jun", "jul"],
    "winter": ["winter", "nov", "dec"],
}
_INTAKE_KEYS = {b["key"] for b in INTAKE_BUCKETS}

CATALOG_SORTS = [
    {"key": "rank", "label": "Best ranked first"},
    {"key": "qs", "label": "QS world rank"},
    {"key": "tuition_asc", "label": "Tuition: low → high"},
    {"key": "tuition_desc", "label": "Tuition: high → low"},
    {"key": "name", "label": "University name (A–Z)"},
    {"key": "verified", "label": "Recently verified"},
]
_SORT_KEYS = {s["key"] for s in CATALOG_SORTS}

UNIVERSITY_TYPES = [
    {"key": "public", "label": "Public"},
    {"key": "private", "label": "Private"},
]
_UNIVERSITY_TYPE_KEYS = {t["key"] for t in UNIVERSITY_TYPES}

GRE_FILTERS = [
    # "unstated" counts as not-required on purpose: outside the US the field is simply
    # never published, so excluding NULLs would return nothing for UK/CA/AU/EU programs.
    {"key": "not_required", "label": "Not required / optional"},
    {"key": "required", "label": "Required"},
]
_GRE_FILTER_KEYS = {g["key"] for g in GRE_FILTERS}

# Course-level advanced keys — these narrow WHICH courses match, so they also decide
# whether a university survives the browse query (see query_catalog).
_COURSE_LEVEL_ADVANCED = (
    "min_tuition", "require_tuition", "max_ielts", "max_toefl", "gre",
    "intake", "max_duration_months", "no_app_fee", "has_deadline",
)

_FIT_LEVELS = {"reach", "match", "safety"}

# Recommendation context sizing: how many catalog courses we hand the model, and the
# minimum catalog matches under which we fall back to grounded live search.
RECOMMEND_CONTEXT_COURSES = int(os.getenv("COURSE_FINDER_CONTEXT_COURSES", "40"))
RECOMMEND_MIN_CATALOG_ROWS = int(os.getenv("COURSE_FINDER_MIN_CATALOG_ROWS", "5"))
RECOMMEND_MAX_RESULTS = 8

GROUNDING_ENABLED = os.getenv("COURSE_CATALOG_GROUNDING_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
# Hard per-request ceiling for a grounded call (ms). A grounded research call measures
# 45-95s, so 240s is generous; without it a hung request has no upper bound and the
# run-level deadline (checked only between universities) can never fire.
GROUNDED_REQUEST_TIMEOUT_MS = max(30_000, int(os.getenv("COURSE_CATALOG_REQUEST_TIMEOUT_MS", "240000") or "240000"))

# Re-verification cadence (same env var as the refresh agent) — a course not
# re-confirmed across ~2 cycles is treated as renamed/discontinued and pruned.
_REVERIFY_DAYS = max(1, int(os.getenv("COURSE_CATALOG_REVERIFY_DAYS", "30") or "30"))

# Link liveness. The same-domain rule below validates the HOST of a course_url and
# nothing else, so a model-composed path on a real university domain
# ("eecs.mit.edu/academics/undergraduate-programs/course-6-3-.../") stored clean and
# rendered as an official "Page ↗" — measured at 23.5% hard 404 across a 200-row
# sample of live rows. Every candidate URL is now fetched before it is stored.
COURSE_URL_CHECK_ENABLED = os.getenv("COURSE_CATALOG_URL_CHECK_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
COURSE_URL_CHECK_TIMEOUT = max(3, int(os.getenv("COURSE_CATALOG_URL_CHECK_TIMEOUT", "12") or "12"))
COURSE_URL_CHECK_WORKERS = max(1, min(16, int(os.getenv("COURSE_CATALOG_URL_CHECK_WORKERS", "8") or "8")))


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
    return candidates or [os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview")]


def normalize_key(name: str) -> str:
    """Dedup key: lowercase, strip punctuation, collapse spaces, drop a leading 'the '.
    Makes "The University of Melbourne" == "University of Melbourne."

    Also strips the alias forms the model alternates between across runs, which are
    the ones that actually created duplicate rows: a parenthetical acronym
    ("Australian Catholic University (ACU)") and a trailing country qualifier
    ("The University of Newcastle, Australia"). Without this they hash differently
    from the plain name and both insert whenever no corroborated domain is available
    to dedupe on.
    """
    s = str(name or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)                      # drop "(ACU)", "(UNSW Sydney)"
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if s.startswith("the "):
        s = s[4:]
    for suffix in (" australia", " usa", " uk", " canada", " germany", " ireland"):
        if s.endswith(suffix) and len(s) > len(suffix) + 4:
            s = s[: -len(suffix)].strip()
    return s[:200]


# A parenthetical whose content is ONE token (no internal space): an acronym or
# abbreviated form — "(LLM)", "(MFin)", "(M.Arch)", "(MME-PS)", "(Informatik)".
_SINGLE_TOKEN_PAREN = re.compile(r"\(\s*[^)\s]+\s*\)")


def normalize_course_key(name: str) -> str:
    """Dedup key for COURSE names — deliberately gentler than normalize_key.

    Universities use parentheses for aliases ("Australian Catholic University (ACU)"),
    so normalize_key strips every parenthetical. Courses use them for BOTH acronyms
    ("Master of Laws (LLM)") and SPECIALIZATIONS ("MBA (Finance)", "Bachelor of
    Engineering Honours (Software Engineering)") — and a key that strips the latter
    collapses distinct degrees into one row: measured on live data, one university's
    five MBA specializations would have upserted into a single course. So only a
    single-token parenthetical (acronym-shaped) is dropped; multi-word ones keep their
    words in the key.
    """
    s = _SINGLE_TOKEN_PAREN.sub(" ", str(name or "")).lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)   # multi-word parentheticals lose brackets, keep words
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
    "edu.au", "com.au", "org.au", "ac.nz", "co.nz", "org.nz", "govt.nz",
    "edu.in", "ac.in", "co.in", "edu.pk", "edu.bd", "edu.np", "edu.lk",
    "edu.sg", "com.sg", "org.sg", "gov.sg", "edu.my", "edu.hk", "com.hk", "edu.cn", "com.cn",
    "ac.jp", "co.jp", "ac.kr", "co.kr", "edu.tw",
    "ac.za", "co.za", "edu.br", "com.br", "edu.mx", "com.mx",
    "ac.at", "ac.ir", "edu.tr", "edu.sa", "edu.eg", "ac.ae",
    # Poland: most universities live under edu.pl or a regional city suffix
    # (sgh.waw.pl, put.poznan.pl, p.lodz.pl, ue.wroc.pl…) — without these, every
    # such university collapses to the same registrable domain and the per-country
    # unique domain_key index rejects the whole discovery batch.
    "edu.pl", "com.pl", "org.pl", "net.pl", "gov.pl",
    "waw.pl", "wroc.pl", "krakow.pl", "poznan.pl", "lodz.pl", "gda.pl",
    "szczecin.pl", "lublin.pl", "katowice.pl", "torun.pl", "olsztyn.pl",
    "rzeszow.pl", "bialystok.pl", "opole.pl",
}

# Australian state education suffixes are THIRD-level ("wa.edu.au"): TAFE and state
# providers sit one label deeper (northmetrotafe.wa.edu.au, gotafe.vic.edu.au), so
# eTLD+1 extraction must keep four labels — otherwise every provider in a state
# collapses to the same key (North and South Metropolitan TAFE became one catalog
# row with a fabricated https://www.wa.edu.au website). Same failure mode the
# Polish regional suffixes above fix one level up.
_THIRD_LEVEL_SUFFIXES = {
    "wa.edu.au", "vic.edu.au", "nsw.edu.au", "qld.edu.au",
    "sa.edu.au", "tas.edu.au", "act.edu.au", "nt.edu.au",
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
    if len(parts) >= 4 and ".".join(parts[-3:]) in _THIRD_LEVEL_SUFFIXES:
        return ".".join(parts[-4:])
    if len(parts) >= 3 and ".".join(parts[-2:]) in _SECOND_LEVEL_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _extract_grounding_domains(response: Any, limit: int = 24) -> set[str]:
    """Registrable domains of the pages Google Search grounding actually consulted.
    Used to corroborate model-returned website URLs — grounded output is untrusted
    web-derived content, so a URL the sources never mentioned must not persist.
    chunk.web.uri is a vertexaisearch redirect (its own domain is Google's, so it is
    useless here). `.domain` exists only on some SDK versions — on google-genai as
    shipped the real host is in `.title` (e.g. "monash.edu"). All three are tried and
    Google's own hosts filtered out; without the title fallback this returns an empty
    set, which would strip EVERY corroborated website and course URL."""
    domains: set[str] = set()
    try:
        for candidate in (getattr(response, "candidates", None) or []):
            meta = getattr(candidate, "grounding_metadata", None)
            for chunk in (getattr(meta, "grounding_chunks", None) or []):
                web = getattr(chunk, "web", None)
                for raw in (
                    getattr(web, "domain", None),
                    getattr(web, "title", None),
                    getattr(web, "uri", None),
                ):
                    raw = str(raw or "").strip()
                    # A title is only a host when it looks like one — real page
                    # titles ("Fees | Monash") must never be read as domains.
                    if not raw or (not raw.startswith("http") and (" " in raw or "." not in raw)):
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


def _grounded_generate(prompt: str, model_names: list[str] | str, usage_source: str):
    """Google-Search-grounded JSON generation (google-genai SDK, API-key auth).

    Tries EVERY configured model candidate before giving up: a dead primary id
    (e.g. `gemini-3.1-pro` 404s while only `-preview` exists) must not silently
    demote the whole catalog to ungrounded model recall — that is exactly how the
    catalog ended up with zero verified source URLs.

    Returns (text, source_urls, source_domains) or None so the caller falls back to
    the ungrounded model — catalog runs must survive grounding being unavailable.
    """
    if not GROUNDING_ENABLED:
        return None
    api_key = (getattr(gemini_service, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")).strip()
    if not api_key or not api_key.startswith("AIza"):
        return None
    candidates = [model_names] if isinstance(model_names, str) else list(model_names or [])
    try:
        from google import genai as _genai
        from google.genai import types as _types
    except Exception as exc:
        logger.warning("Course catalog grounding SDK unavailable (%s); using ungrounded model.", exc)
        return None

    last_exc: Optional[Exception] = None
    for model_name in candidates:
        try:
            # Hard request timeout. The run-level soft deadline is only evaluated
            # BETWEEN universities, so without this a single hung call blocks the
            # daily run indefinitely — long enough for the stale-run takeover to
            # fire and start a second, concurrent run.
            client = _genai.Client(
                api_key=api_key,
                http_options=_types.HttpOptions(timeout=GROUNDED_REQUEST_TIMEOUT_MS),
            )
            config = _types.GenerateContentConfig(
                tools=[_types.Tool(google_search=_types.GoogleSearch())],
                temperature=0.3,
            )
            response = client.models.generate_content(model=model_name, contents=prompt, config=config)
            text = (getattr(response, "text", "") or "").strip()
            # Meter BEFORE the empty-text guard. Google has already billed this call —
            # tokens plus every search the model ran — and a grounded response that comes
            # back empty is the expensive case, not the free one. Recording after the
            # `continue` below is how those calls used to vanish from the ledger.
            try:
                from app import ai_usage
                ai_usage.record_gemini_usage(
                    usage_source, model_name, response, status="ok" if text else "empty",
                )
            except Exception:
                pass
            if not text:
                continue
            return text, _extract_grounding_urls(response), _extract_grounding_domains(response)
        except Exception as exc:  # noqa: BLE001 — try the next candidate (404/quota/etc.)
            last_exc = exc
            logger.info("Course catalog grounding candidate '%s' failed (%s); trying next.", model_name, str(exc)[:160])
    logger.warning("Course catalog grounding unavailable on all candidates (%s); using ungrounded model.", last_exc)
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
        grounded_result = _grounded_generate(prompt, candidates, usage_source)
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
    """Pull the JSON object out of a model reply.

    Grounded research replies are prose FOLLOWED by the JSON (a bare "return only
    JSON" prompt makes the model skip the search tool entirely), so a naive
    first-brace/last-brace slice breaks on any '{' in the prose.

    Strategy: brace-match EVERY '{' into a balanced candidate, then keep the one that
    ENDS last, tie-breaking on the widest span. Picking by start position instead
    silently returns the last *nested* object — for these schemas (`courses[]`,
    `universities[]`, `recommendations[]` all end in a nested object) that means the
    final array element rather than the payload, which reads as "no usable courses",
    burns the grounded call, and after repeated failures deactivates a real university.
    """
    raw = (raw or "").strip()
    if not raw:
        return None

    def _loads(candidate: str) -> Optional[dict]:
        try:
            data = json.loads(candidate)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    # Fast path: the whole reply is the object (strict-JSON prompts).
    parsed = _loads(raw)
    if parsed is not None:
        return parsed

    best_key: Optional[tuple[int, int]] = None
    best_val: Optional[dict] = None
    for start, ch0 in enumerate(raw):
        if ch0 != "{":
            continue
        depth, in_str, esc = 0, False, False
        for i in range(start, len(raw)):
            ch = raw[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = _loads(raw[start:i + 1])
                    if candidate is not None:
                        # Latest end wins (the trailing deliverable); on a tie the
                        # earlier start wins (the outermost enclosing object).
                        key = (i, -start)
                        if best_key is None or key > best_key:
                            best_key, best_val = key, candidate
                    break
    return best_val


def _clean_text(value, limit: int) -> Optional[str]:
    s = str(value or "").strip()
    if not s or s.lower() in {"n/a", "na", "none", "null", "unknown", "-", ""}:
        return None
    return s[:limit]


def _clean_url(value) -> Optional[str]:
    """Only absolute http(s) URLs survive — model output is rendered as hrefs, so a
    javascript:/data: value must never persist (stored-XSS vector). Quotes/angle-
    brackets/backticks are rejected too: a quote inside a double-quoted href breaks
    out of the attribute even when the scheme is a legitimate https."""
    s = str(value or "").strip()
    if not s or s.lower() in {"n/a", "na", "none", "null", "unknown", "-"}:
        return None
    if any(c in s for c in "\"'<>`"):
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


def resolve_subject(discipline, field_of_study) -> tuple:
    """The one rule every AI-shortlist form enforces (enterprise Course Finder, the
    per-client Universities tab, the B2C Course Finder and the B2C Universities page),
    applied server-side too: a shortlist is always built WITHIN a catalog subject area
    (discipline bucket); the free-text field of study only refines it. Free text alone —
    "House Wife", "Machine Learning" — is accepted only when it maps cleanly onto a real
    bucket, and "Other" must come with the specific course, so the model is never handed
    free text alone (or just "Other") and billed for inventing a shortlist around it.
    Returns (discipline, field_of_study); raises ValueError with the user-facing message."""
    field = str(field_of_study or "").strip()
    subject = str(discipline or "").strip()
    if subject:
        canonical = _clean_discipline(subject)
        if canonical == "Other" and subject.lower() != "other":
            raise ValueError(f"'{subject}' isn't a subject area Course Finder knows — pick one from the list.")
        if canonical == "Other" and not field:
            raise ValueError("For 'Other', add the specific course or specialisation you mean.")
        return canonical, field
    mapped = _clean_discipline(field) if field else None
    if field and mapped and mapped != "Other":
        return mapped, field
    raise ValueError(
        "Pick a subject area first — Rilono AI shortlists within it (add a specific "
        "course or specialisation if you have one)."
    )


_BUDGET_ALLOWED_WORDS = frozenset({
    "per", "year", "yr", "annual", "annually", "approx", "approximately", "about", "around", "upto", "up",
    "to", "max", "maximum", "min", "minimum", "lakh", "lakhs", "lac", "lacs", "crore", "crores", "cr", "k",
    "l", "m", "mn", "million", "thousand", "usd", "gbp", "cad", "aud", "eur", "inr", "nzd", "sgd", "aed",
    "pln", "sek", "chf", "jpy", "rs", "dollars", "pounds", "euros", "rupees",
    # currency prefixes as typed: A$35,000, C$25,000, NZ$, S$, US$, HK$, Dh/Dhs, RM
    "a", "c", "s", "nz", "us", "hk", "ca", "au", "uk", "dh", "dhs", "rm",
})
_BUDGET_ALLOWED_CHARS = re.compile(r"[^0-9A-Za-z\s,.\-–/()$£€₹¥₩₪₱₫฿]")
_BUDGET_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def normalize_budget(raw) -> Optional[str]:
    """Sanity rule for the free-text annual budget every AI-shortlist form sends (mirrored
    client-side as cfBudgetProblem). Budgets legitimately arrive as "£22,000", "USD 40k"
    or "₹15–25 L / year" (the enterprise pre-fill from the client's budget band), so the
    text is kept as written for the model — but it must contain a positive amount:
    "-10000" and "abc" used to reach the model (and be billed) untouched. Returns the
    trimmed text, None when blank; raises ValueError with the user-facing message."""
    text = " ".join(str(raw or "").split())
    if not text:
        return None
    if text[0] in "-−–":
        raise ValueError("Budget can't be negative — enter the annual amount, e.g. 30000 or £22,000.")
    numbers = _BUDGET_NUMBER.findall(text)
    if not numbers:
        raise ValueError("Enter the annual budget as an amount, e.g. 30000 or £22,000.")
    for token in numbers:
        try:
            value = float(token.replace(",", ""))
        except ValueError:
            value = 0.0
        if value <= 0:
            raise ValueError("Budget must be more than zero — enter the annual amount, e.g. 30000.")
        if value > 100_000_000:
            raise ValueError("That budget looks wrong — enter the annual amount, e.g. 30000.")
    words = re.findall(r"[A-Za-z]+", text)
    if any(w.lower() not in _BUDGET_ALLOWED_WORDS for w in words) or _BUDGET_ALLOWED_CHARS.search(text):
        raise ValueError("Enter the annual budget as an amount (optionally with a currency), e.g. 30000, £22,000 or USD 40k.")
    return text[:60]


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
# Link liveness
#
# A course_url is model-authored free text. The same-domain rule proves only that the
# host belongs to the university — the path is a guess, and university sites re-slug
# program pages every admissions cycle, so even a URL that was correct when written
# rots. Verdicts are deliberately three-valued: a link is dropped only when the server
# positively says the page is gone. Oxford, Melbourne and QUT all 403 a bot while
# serving fine in a browser, so treating "not 200" as "dead" would delete good links.
# ---------------------------------------------------------------------------

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
# Soft 404s: a 200 whose <title> announces the miss. Matched against the TITLE ONLY —
# a body-wide search hits the "404" in nav/footer/search widgets on live pages.
_SOFT_404_TITLE_MARKERS = (
    "not found", "404", "page unavailable", "page no longer available",
    "seite nicht gefunden", "410 gone",
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def probe_url(url: str) -> str:
    """One link verdict: "live" | "dead" | "unknown".

    "dead" means the server answered and the page is not there (404/410, a soft 404,
    or a deep path bounced to the site root). Blocks, throttling, TLS failures, 5xx
    and timeouts are "unknown" — we keep those links rather than delete a working
    page because a bot was refused.
    """
    try:
        import requests
    except Exception:  # noqa: BLE001 — checking is best-effort, never fatal
        return "unknown"
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _BROWSER_UA, "Accept": "text/html,application/xhtml+xml"},
            timeout=COURSE_URL_CHECK_TIMEOUT,
            allow_redirects=True,
            stream=True,
        )
    except Exception:  # noqa: BLE001 — DNS/TLS/timeout: unproven, so not "dead"
        return "unknown"
    try:
        if resp.status_code in (404, 410):
            return "dead"
        if resp.status_code >= 400:
            return "unknown"
        # Bounced to the homepage: a deep program path that lands on "/" is the other
        # way sites say "no such page" (they 302 to root instead of serving a 404).
        try:
            asked = (urlparse(url).path or "/").rstrip("/")
            landed = (urlparse(resp.url).path or "/").rstrip("/")
            if asked and not landed:
                return "dead"
        except Exception:
            pass
        head = b""
        for chunk in resp.iter_content(8192):
            head += chunk
            if len(head) >= 32_768:
                break
        title_match = _TITLE_RE.search(head.decode("utf-8", "ignore"))
        if title_match:
            title = re.sub(r"\s+", " ", title_match.group(1)).strip().lower()
            if any(marker in title for marker in _SOFT_404_TITLE_MARKERS):
                return "dead"
        return "live"
    finally:
        try:
            resp.close()
        except Exception:
            pass


def probe_urls(urls) -> dict[str, str]:
    """{url: verdict} for a batch, checked concurrently. Empty when checking is off,
    which makes every caller fall back to its pre-check behaviour."""
    unique = [u for u in dict.fromkeys(u for u in urls if u)]
    if not unique or not COURSE_URL_CHECK_ENABLED:
        return {}
    if len(unique) == 1:
        return {unique[0]: probe_url(unique[0])}
    from concurrent.futures import ThreadPoolExecutor
    workers = min(COURSE_URL_CHECK_WORKERS, len(unique))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(zip(unique, pool.map(probe_url, unique)))


def pick_live_url(candidates, verdicts: dict[str, str]) -> Optional[str]:
    """First candidate the probe confirmed live; else the first merely-unproven one;
    else None. Ordering the candidates [new guess, previously stored] is what keeps a
    known-good link when the model's fresh guess for the same course is broken."""
    unproven = None
    for url in candidates:
        if not url:
            continue
        verdict = verdicts.get(url, "unknown")
        if verdict == "live":
            return url
        if verdict == "unknown" and unproven is None:
            unproven = url
    return unproven


# ---------------------------------------------------------------------------
# Derived numeric fields
#
# The advanced browse filters (IELTS/TOEFL/GRE/duration/QS rank) have to run in SQL —
# the catalog is paged with LIMIT/OFFSET, so a Python-side pass could only ever filter
# the page it already fetched. The agent stores those figures as published free text
# ("6.5 overall (6.0 in each band)", "301-350"), so each one is parsed once at write
# time into a numeric column that SQL can compare.
# ---------------------------------------------------------------------------

def parse_ielts_band(value) -> Optional[float]:
    """Overall IELTS band a program asks for, snapped to a half band.

    The overall requirement always leads the published phrasing ("6.5 overall (6.0 in
    each band)", "IELTS 7.0 minimum"), so the first number inside the band range wins.
    """
    for match in re.finditer(r"\d+(?:\.\d+)?", str(value or "")):
        try:
            n = float(match.group())
        except Exception:
            continue
        if 4.0 <= n <= 9.0:
            return round(n * 2) / 2
    return None


def parse_toefl_score(value) -> Optional[int]:
    """Total TOEFL iBT a program asks for. Skips per-section minimums ("20 in each
    section, 90 total") by only accepting numbers inside the plausible total range."""
    for match in re.finditer(r"\d+(?:\.\d+)?", str(value or "")):
        try:
            n = int(float(match.group()))
        except Exception:
            continue
        if 40 <= n <= 120:
            return n
    return None


def parse_gre_requirement(value) -> Optional[int]:
    """0 = not required, 1 = optional, 2 = required, None = nothing published.

    Order matters: "GRE not required" also contains "requir", so the negative
    phrasings are tested first.
    """
    s = str(value or "").strip().lower()
    if not s:
        return None
    if any(k in s for k in (
        "not required", "no gre", "no gmat", "not needed", "waive", "not accepted",
        "not applicable", "none", "no test",
    )):
        return 0
    if "optional" in s or "recommended" in s or "not mandatory" in s:
        return 1
    if "requir" in s or re.search(r"\bgre\b|\bgmat\b", s):
        return 2
    return None


def parse_duration_months(value) -> Optional[int]:
    """Program length in months. A range or a full-time/part-time pair takes the LOWER
    bound ("3-4 years" -> 36), which is the figure a "finishes within X" filter means."""
    s = str(value or "").strip().lower()
    match = re.search(r"\d+(?:\.\d+)?", s)
    if not match:
        return None
    try:
        n = float(match.group())
    except Exception:
        return None
    if "month" in s or re.search(r"\bmos?\b", s):
        months = n
    elif "year" in s or re.search(r"\byrs?\b", s):
        months = n * 12
    elif "semester" in s or "term" in s or "trimester" in s:
        months = n * 6
    else:
        return None
    months = int(round(months))
    return months if 1 <= months <= 120 else None


def parse_rank_number(value) -> Optional[int]:
    """Sortable/filterable rank from a display rank. A band takes its best end
    ("301-350" -> 301) — that is how "within the top 500" is read in practice."""
    match = re.search(r"\d+", str(value or ""))
    if not match:
        return None
    try:
        n = int(match.group())
    except Exception:
        return None
    return n if 1 <= n <= 5000 else None


_MONTHS = {m.lower(): i for i, m in enumerate(
    ("January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"), start=1)}
_MONTHS.update({m[:3]: n for m, n in list(_MONTHS.items())})
_MONTHS["sept"] = 9

# "Jan 4, 2025" / "January 4 2025" — month first
_DEADLINE_MDY = re.compile(r"\b([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s+(\d{4})\b")
# "15 January 2027" / "15 Jan, 2027" — day first
_DEADLINE_DMY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?\s*,?\s+(\d{4})\b")
# ISO "2026-01-15" (also matches 2026/01/15)
_DEADLINE_ISO = re.compile(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b")
# Month + year only: "December 2026" — treated as the 1st (conservative: hides earlier)
_DEADLINE_MY = re.compile(r"\b([a-z]{3,9})\.?\s+(\d{4})\b")


def parse_deadline_date(value) -> Optional[date]:
    """The first parseable calendar date in a published deadline string, else None.

    The model publishes deadlines as prose ("Jan 4, 2025 (Fall 2025)", "15 January 2027",
    "Rolling admissions"), and this is the only course field whose truth DECAYS — a date
    that was correct when written silently becomes wrong the day it passes. Parsing it
    into a real date is what lets every read path ask "is this still ahead of today?".
    Returns None for rolling/unparseable text, which read paths treat as "show as-is"
    (no date is not the same claim as a past date).
    """
    s = str(value or "").strip().lower()
    if not s:
        return None

    def _mk(y: int, m: int, d: int) -> Optional[date]:
        try:
            return date(y, m, d)
        except ValueError:
            return None

    m = _DEADLINE_MDY.search(s)
    if m and m.group(1) in _MONTHS:
        parsed = _mk(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2)))
        if parsed:
            return parsed
    m = _DEADLINE_DMY.search(s)
    if m and m.group(2) in _MONTHS:
        parsed = _mk(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
        if parsed:
            return parsed
    m = _DEADLINE_ISO.search(s)
    if m:
        parsed = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if parsed:
            return parsed
    m = _DEADLINE_MY.search(s)
    if m and m.group(1) in _MONTHS:
        parsed = _mk(int(m.group(2)), _MONTHS[m.group(1)], 1)
        if parsed:
            return parsed
    return None


def drop_past_deadline_text(value: Optional[str]) -> Optional[str]:
    """A deadline string, or None when the date inside it has already passed.
    For text from outside the catalog tables (e.g. model output) that never gets a
    parsed-date column of its own."""
    parsed = parse_deadline_date(value)
    if parsed is not None and parsed < datetime.now(timezone.utc).date():
        return None
    return value


def deadline_is_past(row: models.CourseCatalogCourse) -> bool:
    """Whether this course's parsed deadline is strictly before today (UTC).

    Evaluated at READ time on purpose: rows are only re-verified every ~30 days, so a
    deadline must be able to expire between writes. No parsed date -> False (rolling
    or unparseable text is displayed as published, not suppressed)."""
    d = getattr(row, "application_deadline_date", None)
    return d is not None and d < datetime.now(timezone.utc).date()


def apply_course_derived_fields(row: models.CourseCatalogCourse) -> None:
    """Re-derive a course's numeric filter columns from the text fields they come from.
    Called on every upsert — the advanced filters run in SQL, so they can only ever see
    what these columns hold."""
    row.ielts_score = parse_ielts_band(row.ielts_requirement)
    row.toefl_score = parse_toefl_score(row.toefl_requirement)
    row.gre_gmat_required = parse_gre_requirement(row.gre_gmat_requirement)
    row.duration_months = parse_duration_months(row.duration)
    row.application_deadline_date = parse_deadline_date(row.application_deadline)


def normalize_catalog_filters(raw: Optional[dict]) -> dict:
    """Validate + clamp the advanced browse filters.

    Single gate for every caller (browse endpoint today, AI shortlist context tomorrow):
    unknown keys are dropped, enums must be in the served vocabulary, numbers are clamped
    to sane ranges, and anything unusable is simply omitted rather than 400-ing — a stale
    bookmark should degrade to a broader search, not an error page.
    """
    src = raw if isinstance(raw, dict) else {}
    out: dict = {}

    def _int(key: str, lo: int, hi: int):
        """Below the floor the value is nonsense (a negative tuition, a TOEFL of -5): DROP it
        rather than clamp it up — clamping -5 to a TOEFL ceiling of 40 used to turn a typo
        into a filter that hid almost every course. Above the ceiling it is just "a lot":
        clamp. Both forms reject these client-side first; this is the API's safety net."""
        v = src.get(key)
        if v is None or v == "":
            return
        try:
            n = int(float(v))
        except Exception:
            return
        if n < lo:
            return
        n = min(n, hi)
        if n > 0:
            out[key] = n

    def _flag(key: str):
        v = src.get(key)
        if v is True or str(v).strip().lower() in {"1", "true", "yes", "on"}:
            out[key] = True

    def _enum(key: str, allowed: set):
        v = str(src.get(key) or "").strip().lower()
        if v in allowed:
            out[key] = v

    _int("min_tuition", 0, 10_000_000)
    _int("max_tuition", 0, 10_000_000)
    _int("max_toefl", 40, 120)
    _int("max_duration_months", 1, 120)
    _int("max_qs_rank", 1, 5000)
    _flag("require_tuition")
    _flag("tests_include_unknown")
    _flag("no_app_fee")
    _flag("has_deadline")
    _flag("verified_only")
    _flag("scholarships_only")
    _enum("gre", _GRE_FILTER_KEYS)
    _enum("intake", _INTAKE_KEYS)
    _enum("university_type", _UNIVERSITY_TYPE_KEYS)
    _enum("sort", _SORT_KEYS)

    try:
        band = float(src.get("max_ielts") or 0)
    except Exception:
        band = 0.0
    if 4.0 <= band <= 9.0:
        out["max_ielts"] = round(band * 2) / 2

    city = str(src.get("city") or "").strip()
    if city:
        out["city"] = city[:60]

    # A min above the max would silently return nothing — treat the pair as a range and
    # keep the wider intent instead of a dead result set.
    if out.get("min_tuition") and out.get("max_tuition") and out["min_tuition"] > out["max_tuition"]:
        out["min_tuition"], out["max_tuition"] = out["max_tuition"], out["min_tuition"]
    return out


def active_filter_count(filters: Optional[dict]) -> int:
    """How many advanced filters are actually narrowing the result (sort isn't one)."""
    return len([k for k, v in (filters or {}).items() if k != "sort" and v not in (None, "", False)])


# ---------------------------------------------------------------------------
# 0) Registry seeding — real universities from the curated domain registry
# ---------------------------------------------------------------------------

def domain_key_for(url_or_domain) -> Optional[str]:
    """Stable identity for a university: the registrable domain of its official site.
    Accepts a full URL or a bare host."""
    raw = str(url_or_domain or "").strip().lower()
    if not raw:
        return None
    if not raw.startswith("http"):
        raw = f"https://{raw}"
    return _registrable_domain(raw)


def registry_universities(db: Session, country_code: str) -> list[dict]:
    """Curated real universities for a country from the `us_universities` registry
    (legacy table name — it is the all-country email-domain map, one row per domain).

    The registry is the trustworthy seed source: real institutions with their OFFICIAL
    domain, so seeding costs no AI call and cannot hallucinate. Rows are collapsed to
    one entry per registrable domain, preferring the shortest host (`monash.edu` over
    `student.monash.edu`) and the shortest display name for that domain.
    """
    code = (country_code or "").upper()
    try:
        rows = db.execute(
            sqltext(
                "SELECT university_name, email_domain, location FROM us_universities "
                "WHERE upper(coalesce(country_code,'US')) = :cc"
            ),
            {"cc": code},
        ).fetchall()
    except Exception:
        # Postgres leaves the session in an aborted transaction after a failed
        # statement — without the rollback every later query in this run fails too.
        try:
            db.rollback()
        except Exception:
            pass
        logger.exception("Course catalog: university registry unavailable for %s", code)
        return []

    best: dict[str, dict] = {}
    for name, domain, location in rows:
        name = _clean_text(name, 200)
        dkey = domain_key_for(domain)
        if not name or not dkey:
            continue
        host = str(domain or "").strip().lower()
        current = best.get(dkey)
        if current is None or len(host) < len(current["_host"]) or (
            len(host) == len(current["_host"]) and len(name) < len(current["name"])
        ):
            best[dkey] = {
                "name": name,
                "domain_key": dkey,
                "_host": host,
                "city": _clean_text(location, 160),
                "website_url": f"https://www.{dkey}",
            }
    out = sorted(best.values(), key=lambda d: d["name"].lower())
    for item in out:
        item.pop("_host", None)
    return out


def _repair_state_suffix_rows(db: Session, code: str, registry: list[dict]) -> int:
    """Repair rows created before _THIRD_LEVEL_SUFFIXES existed: a row whose domain_key
    IS a bare state suffix ("wa.edu.au") carries a fabricated website URL and blocks the
    real provider's registry row from seeding. Re-key it from the registry when the name
    matches (and the corrected key is free); deactivate it otherwise so fabricated data
    stops being served. Returns rows touched."""
    suffix_rows = (
        db.query(models.CourseCatalogUniversity)
        .filter(
            models.CourseCatalogUniversity.country_code == code,
            models.CourseCatalogUniversity.domain_key.in_(sorted(_THIRD_LEVEL_SUFFIXES)),
        )
        .all()
    )
    if not suffix_rows:
        return 0
    taken_keys = {
        u.domain_key
        for u in db.query(models.CourseCatalogUniversity)
        .filter(models.CourseCatalogUniversity.country_code == code)
        .all()
        if u.domain_key
    }
    by_name = {normalize_key(item["name"]): item for item in registry}
    touched = 0
    for row in suffix_rows:
        match = by_name.get(row.name_key)
        if match and match["domain_key"] not in taken_keys:
            taken_keys.discard(row.domain_key)
            row.domain_key = match["domain_key"]
            row.website_url = match["website_url"]
            taken_keys.add(match["domain_key"])
        else:
            row.is_active = False
        touched += 1
    if touched:
        db.commit()
        logger.info("Course catalog %s: repaired %d state-suffix domain rows", code, touched)
    return touched


def seed_universities_from_registry(db: Session, country_code: str, limit: Optional[int] = None) -> int:
    """Insert stub rows for every curated registry university not already in the
    catalog. Free (no AI call) and hallucination-proof; enrichment fills courses and
    rankings later. Dedupes on domain first, then name. Returns rows added."""
    code = (country_code or "").upper()
    if not country_name(code):
        return 0
    registry = registry_universities(db, code)
    _repair_state_suffix_rows(db, code, registry)
    existing = (
        db.query(models.CourseCatalogUniversity)
        .filter(models.CourseCatalogUniversity.country_code == code)
        .all()
    )
    have_domains = {u.domain_key for u in existing if u.domain_key}
    have_names = {u.name_key for u in existing}

    added = 0
    for item in registry:
        if limit is not None and added >= int(limit):
            break
        dkey = item["domain_key"]
        nkey = normalize_key(item["name"])
        if not nkey or dkey in have_domains or nkey in have_names:
            continue
        have_domains.add(dkey)
        have_names.add(nkey)
        db.add(models.CourseCatalogUniversity(
            country_code=code,
            name=item["name"],
            name_key=nkey,
            domain_key=dkey,
            city=item["city"],
            website_url=item["website_url"],
            seed_rank=None,  # unranked tail; enrichment fills qs_world_rank
            is_active=True,
        ))
        added += 1
    if added:
        db.commit()
    logger.info("Course catalog registry seed %s: +%d universities", code, added)
    return added


# ---------------------------------------------------------------------------
# 1) Discovery — top-N universities per country (stub rows)
# ---------------------------------------------------------------------------

def discover_universities(db: Session, country_code: str, target: int, usage_source: str = "course_catalog_refresh") -> int:
    """Establish the ranked TOP-N head of a country's catalog.

    Since the registry seed provides the full roster, discovery's job is no longer
    "add rows" but "rank them": a returned university that already exists gets its
    seed_rank (browse ordering) and rankings filled in, and only genuinely unknown
    ones are inserted. Gating on the count of ACTIVE rows instead of RANKED rows
    would make want = 50 - 1119 = 0 for ever, so nothing would ever be ranked and
    "best-ranked first" browse ordering would never exist.

    Returns the number of rows added or newly ranked.
    """
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
    existing_domains = {u.domain_key for u in existing if u.domain_key}
    by_name = {u.name_key: u for u in existing}
    by_domain = {u.domain_key: u for u in existing if u.domain_key}
    # Registry fallback identity: when the model returns no corroborated website we
    # have no domain to dedupe on, and an alias spelling would insert a second row.
    # The curated registry maps the real name -> official domain, recovering identity.
    registry_domain_by_name = {
        normalize_key(r["name"]): r["domain_key"] for r in registry_universities(db, code)
    }
    ranked_active = len([u for u in existing if u.is_active and u.seed_rank is not None])
    want = max(0, int(target) - ranked_active)
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
        if not key:
            continue
        # This catalog is shared across every tenant, so a model-invented (or
        # search-poisoned) domain must never persist: only keep a website the
        # grounded sources corroborate — enrichment gets another shot later.
        site = _clean_url(item.get("website"))
        if site and _registrable_domain(site) not in source_domains:
            site = None
        # Domain is the real identity: the model returns the same university under
        # different names across runs ("UNSW Sydney" vs "The University of New South
        # Wales"), and name_key alone let both insert as separate rows.
        dkey = domain_key_for(site) if site else None
        if not dkey:
            dkey = registry_domain_by_name.get(key)

        # Already in the catalog (almost always, post registry-seed): rank it in
        # place rather than skipping, so the seeded roster gains a ranked head.
        current = by_domain.get(dkey) if dkey else None
        if current is None:
            current = by_name.get(key)
        if current is not None:
            if current.seed_rank is None:
                current.seed_rank = idx + 1
                added += 1
            current.qs_world_rank = current.qs_world_rank or _clean_rank(item.get("qs_world_rank"))
            current.qs_rank_numeric = parse_rank_number(current.qs_world_rank)
            current.national_rank = current.national_rank or _clean_rank(item.get("national_rank"))
            current.university_type = current.university_type or _clean_text(item.get("university_type"), 20)
            current.city = current.city or _clean_text(item.get("city"), 160)
            if site and not current.website_url:
                current.website_url = site
            if dkey and not current.domain_key and dkey not in existing_domains:
                current.domain_key = dkey
                existing_domains.add(dkey)
            if added >= want:
                break
            continue

        # A dkey already claimed this run (by an earlier insert or an in-place
        # update) means this item is the same institution under another name —
        # inserting it would violate the per-country unique domain_key index and
        # roll back the entire discovery batch.
        if dkey and dkey in existing_domains:
            continue
        existing_keys.add(key)
        if dkey:
            existing_domains.add(dkey)
        db.add(models.CourseCatalogUniversity(
            country_code=code,
            name=name,
            name_key=key,
            domain_key=dkey,
            city=_clean_text(item.get("city"), 160),
            qs_world_rank=_clean_rank(item.get("qs_world_rank")),
            qs_rank_numeric=parse_rank_number(item.get("qs_world_rank")),
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
    site_hint = f" (official site: {uni.website_url})" if uni.website_url else ""
    # The date anchor is load-bearing: without it "next intake deadline" is relative to
    # the model's training data or whichever archived cycle page grounding lands on —
    # measured before the anchor existed, 60-81% of a day's written deadlines were
    # already in the past. The example date is derived from today for the same reason.
    today = datetime.now(timezone.utc).date()
    example_deadline = f"Dec 15, {today.year} (Fall {today.year + 1})"
    prompt = (
        "You are Rilono AI, a study-abroad data researcher keeping a university database current.\n\n"
        f"Today's date is {today.strftime('%B %d, %Y')}.\n\n"
        # ORDER MATTERS. A prompt that opens with "return STRICTLY a JSON object" makes
        # the model treat this as pure formatting and it never invokes the Search tool —
        # measured: 0 grounding chunks for every JSON-first phrasing, vs 8-20 when the
        # research task leads and the JSON is the closing deliverable. Tuition, deadlines
        # and score cutoffs change yearly and consultants quote them to students, so this
        # must come off live official pages, not model memory. Do not reorder this.
        f"STEP 1 — RESEARCH. Use Google Search to read the OFFICIAL pages of {uni.name} "
        f"({cname}){site_hint}: international tuition fees, course catalogue, entry "
        "requirements and application deadlines. Quote the key current figures you find "
        "and note which official page each came from. Do not answer from memory.\n\n"
        "STEP 2 — REPORT. After the research, output the findings as a JSON object.\n\n"
        'JSON shape:\n{'
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
        f'"application_deadline":"Next UPCOMING intake deadline — a date AFTER today, e.g. \\"{example_deadline}\\". If only a past cycle\'s deadline is published, \\"N/A\\".",'
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
        f"- application_deadline MUST be a date after today ({today.strftime('%B %d, %Y')}). "
        "A deadline that has already passed is wrong even if it is the one on the page — "
        "give the next cycle's date or \"N/A\".\n"
        "- URLs must be on the university's real official domain — never invent one; \"N/A\" instead.\n"
        "- The application fee is the one-off fee to APPLY, which is different from tuition.\n"
        "- End your reply with the JSON object (a ```json fence is fine). Keep the STEP 1 "
        "research notes brief — the JSON is the deliverable."
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
        uni.qs_rank_numeric = parse_rank_number(uni.qs_world_rank)
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
    # Backfill the identity key once a website is known, so later runs can dedupe on
    # domain instead of the unreliable display name. Never overwrite a known key, and
    # skip if another row in this country already owns it (the partial unique index
    # would reject the flush and abort the whole enrichment).
    if site_domain and not uni.domain_key:
        clash = (
            db.query(models.CourseCatalogUniversity.id)
            .filter(
                models.CourseCatalogUniversity.country_code == uni.country_code,
                models.CourseCatalogUniversity.domain_key == site_domain,
                models.CourseCatalogUniversity.id != uni.id,
            )
            .first()
        )
        if not clash:
            uni.domain_key = site_domain

    existing_courses = {
        (c.name_key, c.degree_level): c
        for c in db.query(models.CourseCatalogCourse).filter(models.CourseCatalogCourse.university_id == uni.id).all()
    }
    now = datetime.now(timezone.utc)
    upserted = 0

    def _on_site(candidate: Optional[str]) -> Optional[str]:
        """Host check only — proves the link belongs to this university, not that the
        page exists. Also scrubs any pre-validation legacy value off a stored row."""
        return candidate if candidate and site_domain and _registrable_domain(candidate) == site_domain else None

    # (row, [new guess, previously stored]) — resolved in one batched liveness pass
    # after the loop so a university's ~10 links are fetched concurrently, not serially.
    pending_urls: list[tuple[models.CourseCatalogCourse, list[Optional[str]]]] = []
    items = data.get("courses")
    for item in (items if isinstance(items, list) else [])[:16]:
        if not isinstance(item, dict):
            continue
        cname_course = _clean_text(item.get("course_name"), 200)
        if not cname_course:
            continue
        level = _clean_level(item.get("degree_level"))
        key = normalize_course_key(cname_course)
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
        # row.course_url is still the PREVIOUS value here — kept as the fallback
        # candidate so a link we already confirmed survives a broken fresh guess.
        pending_urls.append((row, [_on_site(_clean_url(item.get("course_url"))), _on_site(row.course_url)]))
        # Keep the SQL-filterable numerics in step with the text they're parsed from.
        apply_course_derived_fields(row)
        row.is_active = True
        row.last_verified_at = now
        upserted += 1

    if upserted == 0:
        # Profile-only responses shouldn't count as a verified refresh of the courses.
        raise RuntimeError(f"Catalog refresh for {uni.name}: no usable courses in response")

    # Resolve every course link against the live server in one concurrent batch: a
    # confirmed-404 path is dropped rather than published as an official program page.
    # ~10-14 fetches adds a couple of seconds to a call that already takes 45-95s.
    verdicts = probe_urls([u for _row, cands in pending_urls for u in cands if u])
    dropped = 0
    for row, candidates in pending_urls:
        chosen = pick_live_url(candidates, verdicts)
        if any(candidates) and not chosen:
            dropped += 1
        row.course_url = chosen
    if dropped:
        logger.info("Catalog refresh %s: dropped %d dead course link(s)", uni.name, dropped)

    # Prune drift: a course the model hasn't re-confirmed across ~2 re-verification
    # cycles is likely renamed/discontinued — deactivate it (the upsert path revives
    # it automatically if it ever reappears). 3× the nominal cadence, because the
    # real cadence stretches past _REVERIFY_DAYS whenever the roster outgrows the
    # daily batch — at 2× a single missed confirmation could prune a live course.
    prune_cutoff = now - timedelta(days=3 * _REVERIFY_DAYS + 7)
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
        # Read-time expiry: a deadline that has passed since the last refresh is
        # suppressed, not displayed — quoting "Jan 4, 2025" as a live deadline is the
        # one mistake a consultant can't recover from in front of a student.
        "application_deadline": None if deadline_is_past(row) else row.application_deadline,
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
    advanced: Optional[dict] = None,
    limit_universities: int = 30,
    offset_universities: int = 0,
) -> tuple[list[tuple[models.CourseCatalogUniversity, list[models.CourseCatalogCourse]]], int]:
    """Universities (with their matching courses) for the browse view, best-ranked first.

    Course-level filters (level/discipline/q/max_tuition plus the course half of
    `advanced`) narrow WHICH courses show AND which universities appear (a university
    with zero matching courses is dropped — unless there are no course filters at all,
    when stub universities awaiting enrichment still show with an empty course list).
    University-level advanced filters (rank/type/city/verified/scholarships) narrow the
    universities directly and never hide a course.

    `advanced` must come from normalize_catalog_filters() — it is trusted here to hold
    validated, clamped values only.

    Returns (page_rows, total_matching) — the catalog runs to ~1.5k universities, far
    past one screen, so the caller pages through with offset_universities and shows
    the true total rather than silently truncating the tail.
    """
    from sqlalchemy import and_, func as sqlfunc, or_

    code = (country_code or "").upper()
    U, C = models.CourseCatalogUniversity, models.CourseCatalogCourse
    adv = advanced if isinstance(advanced, dict) else {}
    max_tuition = max_tuition or adv.get("max_tuition")
    has_course_filters = bool(
        degree_level or discipline or q or max_tuition
        or any(adv.get(k) for k in _COURSE_LEVEL_ADVANCED)
    )
    sort = adv.get("sort") or "rank"
    start = max(0, int(offset_universities or 0))
    limit = max(1, int(limit_universities))

    def _course_filters(cq):
        if degree_level and degree_level in _LEVEL_KEYS:
            cq = cq.filter(C.degree_level == degree_level)
        if discipline:
            cq = cq.filter(C.discipline == discipline)
        if max_tuition:
            cq = cq.filter(C.tuition_amount.isnot(None), C.tuition_amount <= int(max_tuition))
        if q:
            needle = f"%{str(q).strip()[:80]}%"
            cq = cq.filter(or_(C.course_name.ilike(needle), C.discipline.ilike(needle)))
        if adv.get("min_tuition"):
            cq = cq.filter(C.tuition_amount.isnot(None), C.tuition_amount >= int(adv["min_tuition"]))
        if adv.get("require_tuition"):
            cq = cq.filter(C.tuition_amount.isnot(None))
        # Test scores: a program qualifies if the student clears EITHER published
        # requirement — someone with both scores applies with whichever one is accepted.
        score_clauses = []
        if adv.get("max_ielts") is not None:
            score_clauses.append(C.ielts_score <= float(adv["max_ielts"]))
        if adv.get("max_toefl") is not None:
            score_clauses.append(C.toefl_score <= int(adv["max_toefl"]))
        if score_clauses:
            condition = or_(*score_clauses)
            if adv.get("tests_include_unknown"):
                condition = or_(condition, and_(C.ielts_score.is_(None), C.toefl_score.is_(None)))
            cq = cq.filter(condition)
        if adv.get("gre") == "not_required":
            cq = cq.filter(or_(C.gre_gmat_required.in_((0, 1)), C.gre_gmat_required.is_(None)))
        elif adv.get("gre") == "required":
            cq = cq.filter(C.gre_gmat_required == 2)
        if adv.get("intake"):
            patterns = _INTAKE_MATCH.get(adv["intake"]) or []
            if patterns:
                cq = cq.filter(or_(*[C.intakes.ilike(f"%{p}%") for p in patterns]))
        if adv.get("max_duration_months"):
            cq = cq.filter(
                C.duration_months.isnot(None),
                C.duration_months <= int(adv["max_duration_months"]),
            )
        if adv.get("no_app_fee"):
            # The fee is stored as the university publishes it, so "free to apply" has to
            # be matched by phrasing rather than by a number.
            cq = cq.filter(or_(*[
                C.application_fee.ilike(p) for p in
                ("%no application fee%", "%no fee%", "%free%", "%waive%", "%nil%", "0", "%none%")
            ]))
        if adv.get("has_deadline"):
            # "Published" must mean STILL AHEAD: an expired date is worse than none.
            # Unparseable text (rolling admissions etc.) keeps counting as published —
            # absence of a parsed date is not evidence the deadline passed.
            cq = cq.filter(
                C.application_deadline.isnot(None), C.application_deadline != "",
                or_(C.application_deadline_date.is_(None),
                    C.application_deadline_date >= datetime.now(timezone.utc).date()),
            )
        return cq

    # Order: ranked head first, then rank-less rows by name. Done in SQL so paging is
    # a real LIMIT/OFFSET — hydrating every university and every course of a country
    # on each request does not scale now that a country holds ~1.1k universities.
    order_by = (U.seed_rank.is_(None), U.seed_rank.asc(), U.name.asc(), U.id.asc())

    uq = db.query(U).filter(U.country_code == code, U.is_active.is_(True))
    if adv.get("max_qs_rank"):
        uq = uq.filter(U.qs_rank_numeric.isnot(None), U.qs_rank_numeric <= int(adv["max_qs_rank"]))
    if adv.get("university_type"):
        # Stored as the free text the model returned ("public", "Public research"), so
        # this is a contains-match rather than an equality test.
        uq = uq.filter(U.university_type.ilike(f"%{adv['university_type']}%"))
    if adv.get("city"):
        uq = uq.filter(U.city.ilike(f"%{adv['city']}%"))
    if adv.get("verified_only"):
        uq = uq.filter(U.last_verified_at.isnot(None))
    if adv.get("scholarships_only"):
        uq = uq.filter(U.scholarships_note.isnot(None), U.scholarships_note != "")
    if has_course_filters:
        matching_uni_ids = _course_filters(
            db.query(C.university_id).filter(C.country_code == code, C.is_active.is_(True))
        ).distinct()
        # A name search should also surface universities matched BY NAME even when no
        # course matches (consultants search "melbourne" as often as "data science").
        if q:
            name_needle = f"%{str(q).strip()[:80]}%"
            uq = uq.filter(or_(U.id.in_(matching_uni_ids), U.name.ilike(name_needle)))
        else:
            uq = uq.filter(U.id.in_(matching_uni_ids))

    total = uq.count()

    # Sort. Ties always fall back to name so paging can never repeat or skip a row.
    # NULLs are ordered with an explicit `is_(None)` key rather than NULLS LAST, which
    # older SQLite builds reject.
    if sort in ("tuition_asc", "tuition_desc"):
        # Universities are ordered by the cheapest course that MATCHES the current
        # filters, so "cheapest first" answers the question actually on screen.
        cheapest = (
            _course_filters(
                db.query(C.university_id.label("uid"), sqlfunc.min(C.tuition_amount).label("min_tuition"))
                .filter(C.country_code == code, C.is_active.is_(True))
            )
            .group_by(C.university_id)
            .subquery()
        )
        uq = uq.outerjoin(cheapest, U.id == cheapest.c.uid)
        price = cheapest.c.min_tuition
        order_by = (
            price.is_(None),
            price.asc() if sort == "tuition_asc" else price.desc(),
            U.name.asc(), U.id.asc(),
        )
    elif sort == "qs":
        order_by = (U.qs_rank_numeric.is_(None), U.qs_rank_numeric.asc(), U.name.asc(), U.id.asc())
    elif sort == "name":
        order_by = (U.name.asc(), U.id.asc())
    elif sort == "verified":
        order_by = (U.last_verified_at.is_(None), U.last_verified_at.desc(), U.name.asc(), U.id.asc())

    page = uq.order_by(*order_by).offset(start).limit(limit).all()
    if not page:
        return [], total

    # Courses only for the universities actually on this page.
    page_ids = [u.id for u in page]
    cq = _course_filters(
        db.query(C).filter(C.university_id.in_(page_ids), C.is_active.is_(True))
    )
    by_uni: dict[int, list] = {}
    for course in cq.all():
        by_uni.setdefault(course.university_id, []).append(course)
    if sort in ("tuition_asc", "tuition_desc"):
        # Match the card order inside the card: sorting universities by price and then
        # listing their courses alphabetically hides the row that won them the position.
        descending = sort == "tuition_desc"
        for course_list in by_uni.values():
            # Negate rather than reverse=True: a plain reverse would also flip the
            # is-None key and float the courses with no published fee to the top.
            course_list.sort(key=lambda c: (
                c.tuition_amount is None,
                -(c.tuition_amount or 0) if descending else (c.tuition_amount or 0),
            ))
    else:
        for course_list in by_uni.values():
            course_list.sort(key=lambda c: (c.degree_level or "", c.course_name or ""))

    return [(u, by_uni.get(u.id, [])) for u in page], total


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
    from app import enterprise_catalog

    stage = enterprise_catalog.stage_brief(
        getattr(client, "destination_country_code", None), getattr(client, "status", None)
    ) or {}
    stage_text = str(stage.get("label") or "").strip() or "Not recorded"
    stage_note = str(stage.get("description") or "").strip()
    lines = [
        f"- Name: {client.full_name}",
        f"- Nationality / home country: {client.nationality or 'Not recorded'}",
        f"- Destination: {client.destination_country_name or client.destination_country_code or 'Not recorded'}",
        f"- Visa type: {client.visa_type or 'Student'}",
        f"- Target intake: {client.intake or 'Not recorded'}",
        f"- Current case stage: {stage_text}" + (f" ({stage_note})" if stage_note else ""),
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


SHORTLIST_CONTEXT_ROWS = 40

_SHORTLIST_STATUS_TEXT = {
    "considering": "on the shortlist, not applied yet",
    "applied": "applied — awaiting the university's decision",
    "admitted": "ADMITTED — the student already holds this offer",
    "rejected": "REJECTED the student's application",
}


def _client_shortlist_block(client) -> str:
    """Universities already on this client's shortlist, with each row's outcome.

    Course Finder is billed per run and staff re-run it deep into a case, so without this
    the paid shortlist re-suggests a university that already admitted — or already
    rejected — this exact student.
    """
    try:
        session = object_session(client)
        if session is None:
            return ""
        rows = (
            session.query(models.EnterpriseClientUniversity)
            .filter(
                models.EnterpriseClientUniversity.organization_id == client.organization_id,
                models.EnterpriseClientUniversity.client_id == client.id,
            )
            .order_by(models.EnterpriseClientUniversity.created_at.desc())
            .limit(SHORTLIST_CONTEXT_ROWS)
            .all()
        )
    except Exception:
        # recommend_courses is documented never to raise — a shortlist we cannot read
        # degrades the prompt, it must not fail the paid call.
        logger.warning("Course Finder: could not read the client's shortlist", exc_info=True)
        return ""
    lines = []
    for row in rows:
        name = (row.university_name or "").strip()
        if not name:
            continue
        program = (row.program or "").strip()
        status = (row.status or "considering").strip().lower()
        outcome = _SHORTLIST_STATUS_TEXT.get(status, status or "on the shortlist")
        lines.append(f"- {name}" + (f" — {program}" if program else "") + f" [{outcome}]")
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
                # An expired deadline handed to the model as fact comes back in the paid
                # shortlist as a recommendation the student can no longer act on.
                "deadline": None if deadline_is_past(course) else course.application_deadline,
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
    for_student: bool = False,
    student_profile: Optional[str] = None,
    student_history: Optional[str] = None,
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

    Personalization comes from exactly one of two callers: the enterprise router
    passes `client` (profile + shortlist read from the CRM tables here), while the
    B2C router passes pre-built `student_profile` / `student_history` text blocks
    (its data lives on User/UniversityShortlistEntry, which this module doesn't
    know about). `student_history` must follow the same "- Name — Program [outcome]"
    line format as _client_shortlist_block, because the never-re-suggest prompt
    rule reads those outcome tags.
    """
    max_results = max(1, min(int(max_results or 6), RECOMMEND_MAX_RESULTS))
    if not ai_available():
        return {"available": False, "recommendations": [], "message": "AI recommendations are not configured."}

    catalog_block, catalog_count = _catalog_context_block(catalog_rows)
    catalog_based = catalog_count >= RECOMMEND_MIN_CATALOG_ROWS

    profile_lines = []
    shortlist_block = ""
    if client is not None:
        profile_lines.append("STUDENT PROFILE (from the consultancy's case record):\n" + _client_profile_block(client))
        shortlist_block = _client_shortlist_block(client)
        if shortlist_block:
            profile_lines.append(
                "UNIVERSITIES ALREADY ON THIS STUDENT'S SHORTLIST (with their outcomes):\n"
                + shortlist_block
            )
    else:
        if (student_profile or "").strip():
            profile_lines.append("STUDENT PROFILE:\n" + student_profile.strip())
        shortlist_block = (student_history or "").strip()
        if shortlist_block:
            profile_lines.append(
                "UNIVERSITIES ALREADY ON THIS STUDENT'S SHORTLIST (with their outcomes):\n"
                + shortlist_block
            )
    # The audience changes the voice, not the data: consultants read the enterprise
    # answer to a client, students read the B2C answer about themselves. Keyed on the
    # explicit for_student flag (set only by the B2C router) rather than `client is
    # None` — enterprise runs a legitimate client-less flow that must keep the
    # consultancy persona.
    notes_label = "Student notes/preferences" if for_student else "Consultant notes/preferences"
    request_lines = [
        f"- Destination country: {destination_country}",
        f"- Field of study: {field_of_study or discipline or 'Not specified'}",
        f"- Degree level: {degree_level or 'Not specified'}",
        f"- Approximate annual budget: {budget or 'Not specified'}",
        f"- {notes_label}: {notes or 'None'}",
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

    # Same date anchor as the refresh agent: this is a PAID answer consultants read to
    # students, and an unanchored "deadline" comes from whatever admissions cycle the
    # model remembers.
    rec_today = datetime.now(timezone.utc).date()
    persona = (
        "You are Rilono AI, a study-abroad admissions strategist advising this student directly. "
        if for_student else
        "You are Rilono AI, a study-abroad admissions strategist working for a study-abroad consultancy. "
    )
    prompt = (
        persona
        + "Build the best-fit course shortlist for this request.\n\n"
        f"Today's date is {rec_today.strftime('%B %d, %Y')}.\n\n"
        + ("\n".join(profile_lines) + "\n\n" if profile_lines else "")
        + "REQUEST:\n" + "\n".join(request_lines) + "\n\n"
        + source_rules
        + f"- Return up to {max_results} recommendations ranked best-fit first, mixing reach/match/safety when possible.\n"
        + ("- In `summary` and `why_recommended` prose, never use the words reach, match or safety as "
           "labels — the student's UI shows these as a high, medium or low chance of admission. Keep "
           "emitting the fit_level enum exactly as specified in the schema.\n"
           if for_student else "")
        + "- Only programs in the destination country.\n"
        + ("- NEVER recommend a university already listed on the student's shortlist above — one that "
           "already admitted or already rejected this student must not come back as a suggestion. "
           "Shortlist around them and say in the summary how this set complements what they hold.\n"
           if shortlist_block else "")
        + ("- Respect the student's current case stage above: if they are already past choosing "
           "universities, treat this as an additional or backup shortlist and say so in the summary "
           "rather than presenting it as their first set of options.\n"
           if client is not None else "")
        + f"- Any application_deadline you state MUST be after today ({rec_today.strftime('%B %d, %Y')}) — "
        "a student cannot apply to a closed cycle. If the next cycle's date isn't known, use \"N/A\".\n"
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
            ck = (uk, normalize_course_key(cat_course.course_name))
            catalog_keys.add(ck)
            catalog_course_urls.setdefault(ck, cat_course.course_url)

    try:
        data, grounded, _urls, _domains, model_name = _generate_json(prompt, usage_source, prefer_grounded=not catalog_based)
        items = (data or {}).get("recommendations")
        recommendations = []
        unverified_urls: list[str] = []
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
            rec_key = (normalize_key(uni_name), normalize_course_key(course_name_value))
            in_catalog = rec_key in catalog_keys
            if in_catalog:
                # Already domain-checked AND liveness-checked at write time.
                course_url = catalog_course_urls.get(rec_key)
                website_url = catalog_site_urls.get(rec_key[0])
            else:
                # Off-catalog rows are pure model output — they used to be published
                # with nothing but a scheme check, so they could be dead AND on some
                # other party's domain. Same host rule as the catalog writer; the
                # liveness pass runs below, batched across the whole shortlist.
                website_url = _clean_url(item.get("website_url"))
                course_url = _clean_url(item.get("course_url"))
                site_dom = _registrable_domain(website_url)
                if course_url and site_dom and _registrable_domain(course_url) != site_dom:
                    course_url = None
                unverified_urls.extend(u for u in (course_url, website_url) if u)
            recommendations.append({
                "university_name": uni_name,
                "course_name": course_name_value,
                "degree_level": _clean_level(item.get("degree_level")),
                "location": _clean_text(item.get("location"), 160),
                "fit_level": fit if fit in _FIT_LEVELS else "match",
                "why_recommended": _clean_text(item.get("why_recommended"), 600),
                "annual_tuition": _clean_text(item.get("annual_tuition"), 80),
                "intakes": _clean_text(item.get("intakes"), 120),
                # Output-side guard for the same prompt rule: if the model still returns
                # a date that is already past, store nothing rather than a dead deadline.
                "application_deadline": drop_past_deadline_text(
                    _clean_text(item.get("application_deadline"), 120)),
                "application_fee": _clean_text(item.get("application_fee"), 60),
                "key_requirements": requirements,
                "course_url": course_url,
                "website_url": website_url,
                "qs_world_rank": _clean_rank(item.get("qs_world_rank")),
                "in_catalog": in_catalog,
            })
        # One batched liveness pass over the off-catalog links only — catalog links
        # were already proven at write time, and this is a latency-sensitive paid call.
        if unverified_urls:
            verdicts = probe_urls(unverified_urls)
            for rec in recommendations:
                if rec["in_catalog"]:
                    continue
                for field in ("course_url", "website_url"):
                    if rec[field] and verdicts.get(rec[field]) == "dead":
                        rec[field] = None
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
