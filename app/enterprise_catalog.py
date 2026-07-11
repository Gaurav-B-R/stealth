"""
Student-visa & destination-country catalog for the Rilono enterprise platform.

Rilono Enterprise is focused exclusively on STUDENT / education visas for the six
most popular study destinations. This module is the single source of truth for:
  * The (single) visa category — student
  * Destination countries, their iconic landmark, flag and brand gradient
  * The student visa types available for each country
  * The visa-case pipeline stages a client moves through

The frontend renders bundled SVG landmark art keyed by the country `code`, using
the `gradient_from` / `gradient_to` / `accent` colors supplied here so the look is
fully on-brand and never depends on an external image/CDN.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Visa category (student only)
# ---------------------------------------------------------------------------

VISA_CATEGORY_STUDENT = "student"

VISA_CATEGORIES = [
    {
        "key": VISA_CATEGORY_STUDENT,
        "label": "Student",
        "short_label": "Student",
        "description": "Study permits and student visas for universities & colleges.",
        "icon": "graduation",
        "accent": "#6366f1",
        "uses_intake": True,
    },
]

VISA_CATEGORY_MAP = {item["key"]: item for item in VISA_CATEGORIES}
VISA_CATEGORY_KEYS = {item["key"] for item in VISA_CATEGORIES}


# ---------------------------------------------------------------------------
# Visa-case pipeline stages
# ---------------------------------------------------------------------------

STAGE_NEW_LEAD = "new_lead"
STAGE_DOCUMENTS = "documents"
STAGE_SUBMITTED = "submitted"
STAGE_APPOINTMENT = "appointment"
STAGE_DECISION = "decision"
STAGE_APPROVED = "approved"
STAGE_REJECTED = "rejected"
STAGE_ON_HOLD = "on_hold"

CLIENT_STAGES = [
    {
        "key": STAGE_NEW_LEAD,
        "label": "New Lead",
        "description": "Enquiry received, not yet started.",
        "order": 1,
        "color": "#64748b",
        "is_open": True,
        "is_terminal": False,
    },
    {
        "key": STAGE_DOCUMENTS,
        "label": "Collecting Documents",
        "description": "Gathering and preparing the applicant's documents.",
        "order": 2,
        "color": "#6366f1",
        "is_open": True,
        "is_terminal": False,
    },
    {
        "key": STAGE_SUBMITTED,
        "label": "Application Submitted",
        "description": "Application filed with the consulate / authority.",
        "order": 3,
        "color": "#0ea5e9",
        "is_open": True,
        "is_terminal": False,
    },
    {
        "key": STAGE_APPOINTMENT,
        "label": "Biometrics / Interview",
        "description": "Biometrics, VFS or visa interview scheduled.",
        "order": 4,
        "color": "#8b5cf6",
        "is_open": True,
        "is_terminal": False,
    },
    {
        "key": STAGE_DECISION,
        "label": "Awaiting Decision",
        "description": "Application under review by the authority.",
        "order": 5,
        "color": "#f59e0b",
        "is_open": True,
        "is_terminal": False,
    },
    {
        "key": STAGE_APPROVED,
        "label": "Approved",
        "description": "Visa granted. 🎉",
        "order": 6,
        "color": "#10b981",
        "is_open": False,
        "is_terminal": True,
    },
    {
        "key": STAGE_REJECTED,
        "label": "Rejected",
        "description": "Application refused.",
        "order": 7,
        "color": "#ef4444",
        "is_open": False,
        "is_terminal": True,
    },
    {
        "key": STAGE_ON_HOLD,
        "label": "On Hold",
        "description": "Paused — waiting on the client or external factors.",
        "order": 8,
        "color": "#9ca3af",
        "is_open": False,
        "is_terminal": False,
    },
]

CLIENT_STAGE_MAP = {item["key"]: item for item in CLIENT_STAGES}
CLIENT_STAGE_KEYS = {item["key"] for item in CLIENT_STAGES}
DEFAULT_CLIENT_STAGE = STAGE_NEW_LEAD

CLIENT_PRIORITIES = [
    {"key": "low", "label": "Low", "color": "#94a3b8"},
    {"key": "normal", "label": "Normal", "color": "#6366f1"},
    {"key": "high", "label": "High", "color": "#f97316"},
    {"key": "urgent", "label": "Urgent", "color": "#ef4444"},
]
CLIENT_PRIORITY_KEYS = {item["key"] for item in CLIENT_PRIORITIES}
DEFAULT_CLIENT_PRIORITY = "normal"


# ---------------------------------------------------------------------------
# Student document types (for per-client document uploads)
# ---------------------------------------------------------------------------

STUDENT_DOCUMENT_TYPES = [
    "Passport",
    "Passport-size Photograph",
    "Offer / Admission Letter",
    "I-20 / CAS / Confirmation of Enrolment",
    "Financial Proof / Bank Statement",
    "Academic Transcripts & Certificates",
    "English Test Score (IELTS / TOEFL / PTE)",
    "Statement of Purpose (SOP)",
    "Letters of Recommendation",
    "Visa Application Form",
    "Visa Fee / SEVIS Receipt",
    "Medical / Health Insurance",
    "Other",
]
DEFAULT_DOCUMENT_TYPE = "Other"


def normalize_document_type(raw: str | None) -> str:
    value = str(raw or "").strip()
    if not value:
        return DEFAULT_DOCUMENT_TYPE
    for option in STUDENT_DOCUMENT_TYPES:
        if option.lower() == value.lower():
            return option
    # Accept a free-form custom type (trimmed) so staff aren't boxed in.
    return value[:80]


# ---------------------------------------------------------------------------
# Destination countries (student visas only)
# ---------------------------------------------------------------------------
# Six most popular study destinations. The `gradient_*` and `accent` colors feed
# the bundled SVG landmark art on the frontend.

COUNTRIES = [
    {
        "code": "US",
        "name": "United States",
        "flag_emoji": "🇺🇸",
        "landmark": "Statue of Liberty",
        "gradient_from": "#1d4ed8",
        "gradient_to": "#0ea5e9",
        "accent": "#f8fafc",
        "student_intakes": ["Spring", "Summer", "Fall"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["F-1 Student Visa", "J-1 Exchange Visitor", "M-1 Vocational Student"],
        },
    },
    {
        "code": "CA",
        "name": "Canada",
        "flag_emoji": "🇨🇦",
        "landmark": "Niagara Falls",
        "gradient_from": "#dc2626",
        "gradient_to": "#f87171",
        "accent": "#fff5f5",
        "student_intakes": ["January", "May", "September"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["Study Permit"],
        },
    },
    {
        "code": "UK",
        "name": "United Kingdom",
        "flag_emoji": "🇬🇧",
        "landmark": "Big Ben",
        "gradient_from": "#1e3a8a",
        "gradient_to": "#7c3aed",
        "accent": "#eef2ff",
        "student_intakes": ["January", "September"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["Student Visa", "Child Student Visa", "Short-Term Study Visa"],
        },
    },
    {
        "code": "AU",
        "name": "Australia",
        "flag_emoji": "🇦🇺",
        "landmark": "Sydney Opera House",
        "gradient_from": "#0e7490",
        "gradient_to": "#14b8a6",
        "accent": "#ecfeff",
        "student_intakes": ["February", "July", "November"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["Subclass 500 Student Visa", "Subclass 590 Student Guardian"],
        },
    },
    {
        "code": "DE",
        "name": "Germany",
        "flag_emoji": "🇩🇪",
        "landmark": "Brandenburg Gate",
        "gradient_from": "#111827",
        "gradient_to": "#b91c1c",
        "accent": "#fef3c7",
        "student_intakes": ["Summer Semester", "Winter Semester"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["National Visa (Type D) – Study", "Student Applicant Visa", "Language Course Visa"],
        },
    },
    {
        "code": "IE",
        "name": "Ireland",
        "flag_emoji": "🇮🇪",
        "landmark": "Cliffs of Moher",
        "gradient_from": "#15803d",
        "gradient_to": "#65a30d",
        "accent": "#f0fdf4",
        "student_intakes": ["January", "September"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["D Study Visa", "Short Stay 'C' Study Visa"],
        },
    },
]

COUNTRY_MAP = {item["code"]: item for item in COUNTRIES}
COUNTRY_CODES = {item["code"] for item in COUNTRIES}


# ---------------------------------------------------------------------------
# Intake helpers (for student cases)
# ---------------------------------------------------------------------------

_INTAKE_START_MONTH_HINTS = {
    "spring": 1, "summer": 5, "fall": 8, "autumn": 8, "winter": 11,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "summer semester": 4, "winter semester": 10,
}


def _resolve_intake_start_month(intake_label: str) -> int:
    normalized = str(intake_label or "").strip().lower()
    if not normalized:
        return 9
    if normalized in _INTAKE_START_MONTH_HINTS:
        return int(_INTAKE_START_MONTH_HINTS[normalized])
    for key, month in _INTAKE_START_MONTH_HINTS.items():
        if key in normalized:
            return int(month)
    return 9


def materialize_future_intakes(intake_labels: list[str]) -> list[str]:
    """Turn base intake labels (e.g. "Fall") into the next upcoming dated intakes."""
    now_utc = datetime.utcnow()
    current_month = int(now_utc.month)
    current_year = int(now_utc.year)
    sortable: list[tuple[int, int, str, str]] = []
    seen: set[str] = set()
    for raw_label in intake_labels:
        base_label = str(raw_label or "").strip()
        if not base_label:
            continue
        start_month = _resolve_intake_start_month(base_label)
        year = current_year if start_month >= current_month else (current_year + 1)
        future_label = f"{base_label} {year}"
        key = future_label.lower()
        if key in seen:
            continue
        seen.add(key)
        sortable.append((year, start_month, base_label.lower(), future_label))
    sortable.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in sortable]


# ---------------------------------------------------------------------------
# Public payloads & validation
# ---------------------------------------------------------------------------

def build_catalog_payload() -> dict:
    """Full catalog the frontend uses to drive dropdowns and graphics."""
    countries_payload = []
    for country in COUNTRIES:
        visa_types_by_category = {
            category: list(country["visa_types"].get(category, []))
            for category in VISA_CATEGORY_KEYS
        }
        countries_payload.append({
            "code": country["code"],
            "name": country["name"],
            "flag_emoji": country["flag_emoji"],
            "landmark": country["landmark"],
            "gradient_from": country["gradient_from"],
            "gradient_to": country["gradient_to"],
            "accent": country["accent"],
            "student_intakes": materialize_future_intakes(country.get("student_intakes", [])),
            "visa_types": visa_types_by_category,
        })
    return {
        "categories": [dict(item) for item in VISA_CATEGORIES],
        "stages": [dict(item) for item in CLIENT_STAGES],
        "priorities": [dict(item) for item in CLIENT_PRIORITIES],
        "document_types": list(STUDENT_DOCUMENT_TYPES),
        "countries": countries_payload,
    }


def normalize_category(raw_category: str | None) -> Optional[str]:
    """Student-only catalog: everything resolves to student (or None if clearly invalid)."""
    value = str(raw_category or "").strip().lower()
    if not value:
        return VISA_CATEGORY_STUDENT
    if value in VISA_CATEGORY_KEYS:
        return value
    if value in {"students", "study", "education", "educational", "student visa"}:
        return VISA_CATEGORY_STUDENT
    return None


def normalize_stage(raw_stage: str | None) -> str:
    value = str(raw_stage or "").strip().lower()
    if value in CLIENT_STAGE_KEYS:
        return value
    return DEFAULT_CLIENT_STAGE


def normalize_priority(raw_priority: str | None) -> str:
    value = str(raw_priority or "").strip().lower()
    if value in CLIENT_PRIORITY_KEYS:
        return value
    return DEFAULT_CLIENT_PRIORITY


def get_country(country_code: str | None) -> Optional[dict]:
    return COUNTRY_MAP.get(str(country_code or "").strip().upper())


def resolve_visa_case(
    *,
    category: str | None,
    country_code: str | None,
    visa_type: str | None,
    intake: str | None = None,
) -> dict:
    """
    Validate & canonicalize a (country, visa type, intake) selection. The category
    is always student in this catalog.

    Returns a dict with canonical values, or raises ValueError with a friendly
    message describing the first problem encountered.
    """
    canonical_category = normalize_category(category) or VISA_CATEGORY_STUDENT

    country = get_country(country_code)
    if not country:
        raise ValueError("Please choose a valid study destination country.")

    available_visa_types = country["visa_types"].get(canonical_category, [])
    if not available_visa_types:
        raise ValueError(f"{country['name']} does not have student visas configured.")

    visa_input = str(visa_type or "").strip()
    canonical_visa_type = ""
    for option in available_visa_types:
        if str(option).strip().lower() == visa_input.lower():
            canonical_visa_type = str(option).strip()
            break
    if not canonical_visa_type:
        raise ValueError("The selected visa type is not valid for that country.")

    canonical_intake: Optional[str] = None
    intake_input = str(intake or "").strip()
    if intake_input:
        allowed = materialize_future_intakes(country.get("student_intakes", []))
        for option in allowed:
            if option.strip().lower() == intake_input.lower():
                canonical_intake = option.strip()
                break
        if canonical_intake is None:
            # Accept a free-form intake the user typed, just trim it.
            canonical_intake = intake_input[:120]

    return {
        "category": canonical_category,
        "country_code": country["code"],
        "country_name": country["name"],
        "visa_type": canonical_visa_type,
        "intake": canonical_intake,
    }
