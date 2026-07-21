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
        "label": "Biometrics / Appointment",
        "description": "Biometrics or VFS appointment booked — plus a visa interview where the destination requires one.",
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
    "Visa Fee Receipt",
    "Medical / Health Insurance",
    "Other",
]
DEFAULT_DOCUMENT_TYPE = "Other"

# ---------------------------------------------------------------------------
# Per-country document catalogs (detailed, destination-specific)
# ---------------------------------------------------------------------------
# The generic STUDENT_DOCUMENT_TYPES above is the legacy/fallback list. Each entry:
#   key       — stable identifier (also used when seeding the DB catalog)
#   label     — what staff see & what is stored on EnterpriseClientDocument.document_type
#   required  — part of the standard checklist for that destination
#   hint      — one-line guidance shown in the picker
# Ordering is the recommended collection order for that destination.

ENTERPRISE_DOCUMENT_CATALOG: dict[str, list[dict]] = {
    "US": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "Valid at least 6 months beyond intended stay."},
        {"key": "photo", "label": "Passport Photo (2×2 inch, US spec)", "required": True, "hint": "White background, taken within 6 months."},
        {"key": "admission-letter", "label": "University Admission / Offer Letter", "required": True, "hint": "From the SEVP-certified school."},
        {"key": "form-i20", "label": "Form I-20 (signed)", "required": True, "hint": "Signed by the DSO and the student."},
        {"key": "ds160-confirmation", "label": "DS-160 Confirmation Page", "required": True, "hint": "Barcode page after submitting the DS-160 online."},
        {"key": "sevis-receipt", "label": "SEVIS I-901 Fee Receipt", "required": True, "hint": "Paid on fmjfee.com against the I-20 SEVIS ID."},
        {"key": "mrv-fee-receipt", "label": "Visa (MRV) Fee Receipt", "required": True, "hint": "Machine-readable visa application fee."},
        {"key": "interview-appointment", "label": "Interview Appointment Confirmation", "required": True, "hint": "OFC/biometrics + consular interview slots."},
        {"key": "bank-statements", "label": "Bank Statements / Balance Certificate", "required": True, "hint": "Liquid funds covering I-20 first-year cost."},
        {"key": "loan-sanction", "label": "Education Loan Sanction Letter", "required": False, "hint": "If part of funding — sanctioned, not applied."},
        {"key": "scholarship-letter", "label": "Scholarship / Assistantship Letter", "required": False, "hint": "University or external funding award."},
        {"key": "sponsor-affidavit", "label": "Sponsor Affidavit of Support", "required": False, "hint": "With sponsor's bank proof & income evidence."},
        {"key": "ca-statement", "label": "CA Statement / Asset Valuation", "required": False, "hint": "Chartered-accountant net-worth summary."},
        {"key": "transcripts", "label": "Academic Transcripts & Marksheets", "required": True, "hint": "All semesters, university-attested."},
        {"key": "degree-certificates", "label": "Degree / Provisional Certificates", "required": False, "hint": "Completed programs only."},
        {"key": "english-test", "label": "English Test Score (TOEFL / IELTS / Duolingo)", "required": True, "hint": "As required by the admitting school."},
        {"key": "aptitude-test", "label": "GRE / GMAT / SAT Score Report", "required": False, "hint": "If used in the admission."},
        {"key": "resume", "label": "Resume / CV", "required": False, "hint": "Useful for interview & OPT-related questions."},
        {"key": "work-experience", "label": "Work Experience Letters", "required": False, "hint": "For applicants with employment history."},
        {"key": "gap-justification", "label": "Gap / Study-Break Justification", "required": False, "hint": "Explains gaps after prior education."},
        {"key": "prior-visa-refusal", "label": "Previous US Visa / Refusal Documents (221g)", "required": False, "hint": "Any earlier US travel or refusals."},
        {"key": "ds2019", "label": "Form DS-2019 (J-1 only)", "required": False, "hint": "Exchange-visitor program form."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "UK": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "With at least one blank page."},
        {"key": "cas", "label": "CAS Statement", "required": True, "hint": "Confirmation of Acceptance for Studies with CAS number."},
        {"key": "offer-letter", "label": "Unconditional Offer Letter", "required": True, "hint": "From the licensed student sponsor."},
        {"key": "financial-evidence", "label": "28-Day Bank Statement / Financial Evidence", "required": True, "hint": "Funds held 28 consecutive days, ending ≤31 days before applying."},
        {"key": "ihs-confirmation", "label": "IHS Payment Confirmation", "required": True, "hint": "Immigration Health Surcharge reference."},
        {"key": "visa-application", "label": "Visa Application Confirmation (GOV.UK)", "required": True, "hint": "Submitted online application summary."},
        {"key": "tb-certificate", "label": "TB Test Certificate", "required": True, "hint": "From an approved clinic (required for many countries incl. India)."},
        {"key": "atas", "label": "ATAS Certificate", "required": False, "hint": "Only for certain sensitive subjects."},
        {"key": "selt", "label": "SELT / IELTS-for-UKVI Result", "required": False, "hint": "Or degree-taught-in-English exemption evidence."},
        {"key": "transcripts", "label": "Academic Transcripts", "required": True, "hint": "Documents used to obtain the CAS."},
        {"key": "degree-certificates", "label": "Degree Certificates", "required": False, "hint": "As listed on the CAS."},
        {"key": "sponsor-consent", "label": "Parental / Sponsor Consent + Relationship Proof", "required": False, "hint": "If funds are in a parent's or sponsor's name."},
        {"key": "loan-letter", "label": "Education Loan Letter", "required": False, "hint": "Regulated financial institution letterhead."},
        {"key": "scholarship-letter", "label": "Scholarship / Official Sponsorship Letter", "required": False, "hint": "Government or international scholarship agency."},
        {"key": "photo", "label": "Passport-size Photograph", "required": False, "hint": "Only if a VAC requests physical photos."},
        {"key": "prior-refusals", "label": "Previous UK Visa / Refusal Documents", "required": False, "hint": "Any earlier UK immigration history."},
        {"key": "cv", "label": "CV / Resume", "required": False, "hint": "Occasionally requested for credibility interviews."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "CA": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "Valid for the full study period."},
        {"key": "loa", "label": "Letter of Acceptance (LOA)", "required": True, "hint": "From a Designated Learning Institution (DLI)."},
        {"key": "pal", "label": "Provincial / Territorial Attestation Letter (PAL/TAL)", "required": True, "hint": "Required for most study-permit applications."},
        {"key": "gic", "label": "GIC Certificate", "required": True, "hint": "Guaranteed Investment Certificate for living costs."},
        {"key": "tuition-receipt", "label": "First-Year Tuition Payment Receipt", "required": True, "hint": "Proof of tuition paid to the DLI."},
        {"key": "proof-of-funds", "label": "Proof of Funds / Bank Statements (4 months)", "required": True, "hint": "Beyond the GIC where applicable."},
        {"key": "loan-sanction", "label": "Education Loan Sanction Letter", "required": False, "hint": "If loan-funded."},
        {"key": "imm1294", "label": "Study Permit Application (IMM 1294)", "required": True, "hint": "Or the IRCC online equivalent summary."},
        {"key": "sop-study-plan", "label": "Statement of Purpose / Study Plan", "required": True, "hint": "Why this program, why Canada, ties to home country."},
        {"key": "language-test", "label": "Language Test (IELTS / PTE / CELPIP / TEF)", "required": True, "hint": "Per DLI and stream requirements."},
        {"key": "transcripts", "label": "Academic Transcripts", "required": True, "hint": "All completed education."},
        {"key": "degree-certificates", "label": "Degree / Diploma Certificates", "required": False, "hint": "Completed programs only."},
        {"key": "medical-exam", "label": "Medical Exam (eMedical) Confirmation", "required": False, "hint": "Upfront medical from a panel physician."},
        {"key": "biometrics", "label": "Biometrics Confirmation", "required": False, "hint": "Biometric Instruction Letter / completion slip."},
        {"key": "custodianship", "label": "Custodianship Declaration (minors)", "required": False, "hint": "IMM 5646 for students under 17."},
        {"key": "family-forms", "label": "Family Information Form (IMM 5645/5707)", "required": False, "hint": "As requested by IRCC."},
        {"key": "caq", "label": "Quebec Acceptance Certificate (CAQ)", "required": False, "hint": "Only for study in Quebec."},
        {"key": "prior-refusals", "label": "Previous Refusal Letter(s)", "required": False, "hint": "Any earlier Canadian refusals — address them in the SOP."},
        {"key": "digital-photo", "label": "Digital Photo (IRCC spec)", "required": False, "hint": "Per IRCC photo specifications."},
        {"key": "work-experience", "label": "Work Experience Letters", "required": False, "hint": "If employment history supports the study plan."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "AU": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "Valid for the intended stay."},
        {"key": "coe", "label": "Confirmation of Enrolment (CoE)", "required": True, "hint": "One per course being packaged."},
        {"key": "offer-letter", "label": "Offer Letter", "required": True, "hint": "From the Australian provider."},
        {"key": "gs-statement", "label": "Genuine Student (GS) Statement & Answers", "required": True, "hint": "Responses to the GS questions — decisive for 500s."},
        {"key": "oshc", "label": "OSHC Policy Certificate", "required": True, "hint": "Health cover spanning the entire stay."},
        {"key": "financial-capacity", "label": "Financial Capacity Evidence", "required": True, "hint": "Bank funds / loan / sponsor income per Home Affairs settings."},
        {"key": "english-test", "label": "English Test (IELTS / PTE / TOEFL)", "required": True, "hint": "Unless exempt."},
        {"key": "transcripts", "label": "Academic Transcripts", "required": True, "hint": "All prior study."},
        {"key": "degree-certificates", "label": "Degree / Award Certificates", "required": False, "hint": "Completed qualifications."},
        {"key": "health-exam", "label": "Health Examination (HAP ID / eMedical)", "required": False, "hint": "Panel clinic examination reference."},
        {"key": "photo", "label": "Passport-size Photograph", "required": False, "hint": "Recent, per specifications."},
        {"key": "form-956a", "label": "Form 956A (Agent Appointment)", "required": False, "hint": "If your agency lodges on the student's behalf."},
        {"key": "guardian-forms", "label": "Guardianship / U-18 Welfare Forms (157N / CAAW)", "required": False, "hint": "For minors and subclass 590 guardians."},
        {"key": "relationship-docs", "label": "Marriage / Relationship Certificates (dependents)", "required": False, "hint": "If including family members."},
        {"key": "employment-evidence", "label": "Employment Evidence / CV", "required": False, "hint": "Supports GS circumstances."},
        {"key": "prior-refusals", "label": "Previous Visa / Refusal Documents", "required": False, "hint": "Australian or other-country refusals."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "DE": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "Issued within 10 years, 2 blank pages."},
        {"key": "biometric-photos", "label": "Biometric Photos (35×45 mm)", "required": True, "hint": "German biometric specification."},
        {"key": "admission", "label": "Admission Letter (Zulassungsbescheid) / Conditional Admission", "required": True, "hint": "Or uni-assist / applicant confirmation."},
        {"key": "aps", "label": "APS Certificate", "required": True, "hint": "Mandatory for India, China, Vietnam applicants."},
        {"key": "sperrkonto", "label": "Blocked Account (Sperrkonto) Confirmation", "required": True, "hint": "Funded to the current annual minimum."},
        {"key": "scholarship-letter", "label": "Scholarship Award Letter", "required": False, "hint": "DAAD or equivalent — alternative to blocked account."},
        {"key": "verpflichtung", "label": "Formal Obligation Letter (Verpflichtungserklärung)", "required": False, "hint": "Sponsor-based financing alternative."},
        {"key": "videx", "label": "VIDEX National Visa Form", "required": True, "hint": "Completed and signed VIDEX printout."},
        {"key": "declaration", "label": "Declaration of Accuracy of Information", "required": True, "hint": "Signed declarations required by the mission."},
        {"key": "health-insurance", "label": "Health / Travel Insurance Proof", "required": True, "hint": "Coverage from entry until enrolment insurance starts."},
        {"key": "language-cert", "label": "Language Certificate (TestDaF / DSH / Goethe or IELTS/TOEFL)", "required": True, "hint": "Per the program's language of instruction."},
        {"key": "transcripts", "label": "Academic Transcripts", "required": True, "hint": "All prior study records."},
        {"key": "degree-certificates", "label": "Degree Certificates", "required": False, "hint": "Bachelor's certificate for Master's applicants."},
        {"key": "cv", "label": "CV (Tabular / Lebenslauf)", "required": True, "hint": "German-style tabular CV."},
        {"key": "motivation-letter", "label": "Motivation Letter (Motivationsschreiben)", "required": True, "hint": "Program-specific reasoning."},
        {"key": "appointment", "label": "Visa Appointment Confirmation", "required": False, "hint": "Embassy / consulate booking."},
        {"key": "fee-receipt", "label": "Visa Fee Receipt", "required": False, "hint": "National visa fee payment."},
        {"key": "accommodation", "label": "Accommodation Proof", "required": False, "hint": "If already arranged in Germany."},
        {"key": "prior-refusals", "label": "Previous Refusal Documents", "required": False, "hint": "Any Schengen/German refusals."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "IE": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "Valid 12+ months beyond arrival."},
        {"key": "acceptance-letter", "label": "Letter of Acceptance", "required": True, "hint": "From the Irish college confirming the full-time course."},
        {"key": "fee-receipt", "label": "Tuition Fee Payment Receipt", "required": True, "hint": "Proof fees are paid (or ILEP escrow evidence)."},
        {"key": "proof-of-funds", "label": "Proof of Funds / 6-Month Bank Statements", "required": True, "hint": "Access to required maintenance funds."},
        {"key": "education-bond", "label": "Education Bond / Official Sponsorship", "required": False, "hint": "If using a bond or sponsor arrangement."},
        {"key": "medical-insurance", "label": "Medical / Travel Insurance", "required": True, "hint": "Private medical insurance covering the stay."},
        {"key": "english-test", "label": "English Test (IELTS / TOEFL / Duolingo)", "required": True, "hint": "Meeting the course's English requirement."},
        {"key": "transcripts", "label": "Academic Transcripts", "required": True, "hint": "Previous exam results & study history."},
        {"key": "degree-certificates", "label": "Degree Certificates", "required": False, "hint": "Completed qualifications."},
        {"key": "avats-summary", "label": "AVATS Application Summary", "required": True, "hint": "Online visa application summary sheet."},
        {"key": "photos", "label": "Passport Photographs", "required": True, "hint": "Two recent colour photos."},
        {"key": "application-letter", "label": "Letter of Application / SOP", "required": True, "hint": "Explains study plan and immigration history."},
        {"key": "sponsor-docs", "label": "Sponsor Documents + Relationship Proof", "required": False, "hint": "If financially sponsored."},
        {"key": "work-experience", "label": "Work Experience / Gap Evidence", "required": False, "hint": "Accounts for time since last study."},
        {"key": "prior-refusals", "label": "Previous Visa Refusals (any country)", "required": False, "hint": "Must be declared with details."},
        {"key": "accommodation", "label": "Accommodation Details", "required": False, "hint": "If already arranged in Ireland."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
}


def document_types_for_country(country_code: str | None) -> list[dict]:
    """Detailed picker list for one destination (falls back to the generic list)."""
    items = ENTERPRISE_DOCUMENT_CATALOG.get(str(country_code or "").strip().upper())
    if items:
        return [dict(item) for item in items]
    return [{"key": t.lower().replace(" ", "-")[:40], "label": t, "required": False, "hint": ""}
            for t in STUDENT_DOCUMENT_TYPES]


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

def _document_types_by_country_from_db(db) -> dict[str, list[dict]]:
    """Load the enterprise document catalog from the DB (scope visa_type_key='enterprise').

    The DB is the runtime source of truth (seeded from ENTERPRISE_DOCUMENT_CATALOG at
    startup, editable later without a deploy); any country with no rows falls back to
    the in-code list so the picker never comes up empty."""
    from app import models  # local import — this module is imported by models-adjacent code
    out: dict[str, list[dict]] = {}
    try:
        rows = (
            db.query(models.DocumentTypeCatalog)
            .filter(
                models.DocumentTypeCatalog.visa_type_key == "enterprise",
                models.DocumentTypeCatalog.is_active.is_(True),
            )
            .order_by(models.DocumentTypeCatalog.country_code.asc(), models.DocumentTypeCatalog.sort_order.asc())
            .all()
        )
        for row in rows:
            out.setdefault(row.country_code, []).append({
                "key": row.document_type,
                "label": row.label,
                "required": bool(row.is_required),
                "hint": row.description or "",
            })
    except Exception:
        out = {}
    for code in ENTERPRISE_DOCUMENT_CATALOG:
        if not out.get(code):
            out[code] = document_types_for_country(code)
    return out


def build_catalog_payload(db=None) -> dict:
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
    doc_types_by_country = (
        _document_types_by_country_from_db(db) if db is not None
        else {code: document_types_for_country(code) for code in ENTERPRISE_DOCUMENT_CATALOG}
    )
    return {
        "categories": [dict(item) for item in VISA_CATEGORIES],
        "stages": [dict(item) for item in CLIENT_STAGES],
        "priorities": [dict(item) for item in CLIENT_PRIORITIES],
        # Legacy flat list (kept for back-compat); the per-country map below is what
        # the client-profile pickers use.
        "document_types": list(STUDENT_DOCUMENT_TYPES),
        "document_types_by_country": doc_types_by_country,
        # Case-record fields to capture at each pipeline stage, resolved per destination.
        "stage_fields_by_country": stage_fields_by_country(),
        "countries": countries_payload,
    }


# ---------------------------------------------------------------------------
# Per-stage CASE RECORD fields (destination-aware)
# ---------------------------------------------------------------------------
# What a counselor RECORDS on the client at each pipeline stage — the numbers, dates and
# references that make up the case file. Documents themselves are handled separately by
# ENTERPRISE_DOCUMENT_CATALOG; these are the data points, and they differ per destination
# (US SEVIS/DS-160 vs UK CAS/IHS vs Canada IRCC/GIC …).
#
# Each field: key (stable, unique within a destination), label, type
# (text | date | number | select | textarea), hint, required — plus options for select.
#
# SHARED fields apply to every destination. The per-country map ADDS destination-specific
# fields; a country field reusing a shared key overrides it.
# The field data lives in its own module (it is large); this file owns the resolution rules.
from app.enterprise_stage_fields import (  # noqa: E402
    ENTERPRISE_STAGE_SHARED_FIELDS,
    ENTERPRISE_STAGE_FIELD_CATALOG,
)


def stage_fields_for(country_code: str | None, stage_key: str | None) -> list[dict]:
    """Fields to record at `stage_key` for `country_code`: the shared set plus that
    destination's own fields (a country field reusing a shared key overrides it)."""
    stage = str(stage_key or "").strip().lower()
    if stage not in CLIENT_STAGE_KEYS:
        return []
    merged: dict[str, dict] = {f["key"]: dict(f) for f in ENTERPRISE_STAGE_SHARED_FIELDS.get(stage, [])}
    country = (ENTERPRISE_STAGE_FIELD_CATALOG.get(str(country_code or "").strip().upper()) or {}).get(stage, [])
    for field in country:
        # applicable=False means "this shared field doesn't exist for this destination"
        # (e.g. the UK issues an eVisa, so there is no passport sticker number to record).
        if field.get("applicable") is False:
            merged.pop(field["key"], None)
            continue
        merged[field["key"]] = {k: v for k, v in field.items() if k != "applicable"}
    return list(merged.values())


def stage_fields_by_country() -> dict:
    """Resolved catalog for the frontend: {COUNTRY_CODE: {stage_key: [field, …]}}."""
    stage_keys = [item["key"] for item in CLIENT_STAGES]
    return {
        code: {stage: stage_fields_for(code, stage) for stage in stage_keys}
        for code in COUNTRY_MAP
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
