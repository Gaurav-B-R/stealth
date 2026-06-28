"""B2C student-visa catalog: countries -> visa types -> journey stages + documents.

Single source of truth for the personalized student dashboard. The B2C product used
to be hard-wired to US F-1; this module generalizes it to multiple destination
countries and visa types while keeping the **US F-1 content byte-for-byte identical**
to the original `app/document_catalog.py` definitions (which now import from here).

Country display metadata (name, flag, gradient, landmark, intakes) is reused from
`app/enterprise_catalog.py` so the two products stay consistent. This module adds the
per-(country, visa_type) **journey stages** and **document checklist** that the
enterprise side never had.

Per-country content for UK / Canada / Australia is a best-effort first draft and is
stored as editable data (seeded into `document_type_catalog`), so corrections need no
code change.
"""
from __future__ import annotations

from typing import Any, Optional

from app import enterprise_catalog

# Destination countries enabled for B2C in this build (subset of the enterprise catalog).
LAUNCH_COUNTRY_CODES = ["US", "UK", "CA", "AU"]

DEFAULT_COUNTRY_CODE = "US"
DEFAULT_VISA_TYPE_KEY = "us_f1"


# ===========================================================================
# US F-1 — copied VERBATIM from the original app/document_catalog.py so existing
# behaviour is unchanged. Do not edit without a matching golden-output check.
# ===========================================================================

US_F1_STAGES: list[dict[str, Any]] = [
    {
        "stage": 1,
        "name": "Getting Started",
        "emoji": "📝",
        "description": "Build your profile with core academic and test documents.",
        "next_step": "Upload and validate your starter document set",
    },
    {
        "stage": 2,
        "name": "Admission Received",
        "emoji": "🎓",
        "description": "University admission confirmed!",
        "next_step": "Upload admission proof and one financial proof document",
    },
    {
        "stage": 3,
        "name": "I-20 Received",
        "emoji": "📘",
        "description": "Upload and validate your signed Form I-20.",
        "next_step": "Complete your DS-160 application online",
    },
    {
        "stage": 4,
        "name": "DS-160 Filed",
        "emoji": "📋",
        "description": "Upload and validate your full DS-160 application and 2x2 photograph.",
        "next_step": "Pay your SEVIS I-901 fee and visa fee",
    },
    {
        "stage": 5,
        "name": "Fees Paid",
        "emoji": "💳",
        "description": "SEVIS payment is mandatory. Other fee/appointment confirmations are optional.",
        "next_step": "Book interview slot and upload interview documents",
    },
    {
        "stage": 6,
        "name": "Visa",
        "emoji": "🛂",
        "description": "Prepare your visa interview packet and supporting documents.",
        "next_step": "Review final interview checklist and confidence prep",
    },
    {
        "stage": 7,
        "name": "Ready to Fly!",
        "emoji": "✈️",
        "description": "Visa approved. Complete final pre-departure documents and travel readiness.",
        "next_step": "Upload remaining arrival documents (for example vaccination records) and finalize travel plans.",
    },
]


US_F1_DOCUMENTS: list[dict[str, Any]] = [
    {
        "document_type": "passport",
        "label": "Passport",
        "sort_order": 10,
        "is_required": True,
        "journey_stage": 1,
        "stage_gate_required": True,
        "stage_gate_requires_validation": True,
    },
    {
        "document_type": "high-school-transcripts",
        "label": "High School Transcripts",
        "sort_order": 20,
        "is_required": False,
        "journey_stage": 1,
        "stage_gate_required": False,
        "stage_gate_requires_validation": False,
    },
    {
        "document_type": "bachelors-transcript",
        "label": "Bachelors Transcript (Optional)",
        "sort_order": 30,
        "is_required": False,
        "journey_stage": 1,
        "stage_gate_required": False,
        "stage_gate_requires_validation": False,
    },
    {
        "document_type": "masters-transcript",
        "label": "Master's Transcript (Optional)",
        "sort_order": 40,
        "is_required": False,
        "journey_stage": 1,
        "stage_gate_required": False,
        "stage_gate_requires_validation": False,
    },
    {
        "document_type": "other-school-college-degree-certificates",
        "label": "Other School/College/Degree Certificates",
        "sort_order": 50,
        "is_required": False,
        "journey_stage": 1,
        "stage_gate_required": False,
        "stage_gate_requires_validation": False,
    },
    {
        "document_type": "standardized-test-scores",
        "label": "Standardized Test Scores (TOEFL/IELTS/Duolingo)",
        "sort_order": 60,
        "is_required": True,
        "journey_stage": 1,
        "stage_gate_required": True,
        "stage_gate_requires_validation": True,
    },
    {
        "document_type": "standardized-test-scores-gre-gmat",
        "label": "Standardized Test Scores (GRE/GMAT)",
        "sort_order": 70,
        "is_required": False,
        "journey_stage": 1,
        "stage_gate_required": False,
        "stage_gate_requires_validation": False,
    },
    {
        "document_type": "statement-of-purpose-lors",
        "label": "Statement of Purpose (SOP) & LORs",
        "description": "Copies of the SOP and LORs submitted to university applications.",
        "sort_order": 80,
        "is_required": False,
        "journey_stage": 1,
        "stage_gate_required": False,
        "stage_gate_requires_validation": False,
    },
    {
        "document_type": "resume",
        "label": "Resume/CV",
        "sort_order": 90,
        "is_required": True,
        "journey_stage": 1,
        "stage_gate_required": True,
        "stage_gate_requires_validation": True,
    },
    {
        "document_type": "ds-160-confirmation",
        "label": "DS-160 Confirmation Page",
        "sort_order": 160,
        "is_required": False,
        "journey_stage": 4,
        "stage_gate_required": False,
        "stage_gate_requires_validation": False,
    },
    {
        "document_type": "ds-160-application",
        "label": "DS-160 Application (Full Application)",
        "sort_order": 170,
        "is_required": True,
        "journey_stage": 4,
        "stage_gate_required": True,
        "stage_gate_requires_validation": True,
    },
    {
        "document_type": "travel-history-documents",
        "label": "Travel History Documents",
        "sort_order": 175,
        "is_required": False,
        "journey_stage": 4,
        "stage_gate_required": False,
        "stage_gate_requires_validation": False,
    },
    {
        "document_type": "us-visa-appointment-letter",
        "label": "US Visa Appointment Letter",
        "sort_order": 240,
        "is_required": True,
        "journey_stage": 6,
        "stage_gate_required": True,
        "stage_gate_requires_validation": True,
    },
    {
        "document_type": "stamped-f1-visa",
        "label": "Stamped F-1 Visa",
        "sort_order": 245,
        "is_required": True,
        "journey_stage": 6,
        "stage_gate_required": True,
        "stage_gate_requires_validation": True,
    },
    {
        "document_type": "immunization-vaccination-records",
        "label": "Immunization/Vaccination Records",
        "sort_order": 290,
        "is_required": True,
        "journey_stage": 7,
        "stage_gate_required": True,
        "stage_gate_requires_validation": True,
    },
    {
        "document_type": "visa-fee-receipt",
        "label": "Visa Application (MRV) Fee Receipts",
        "sort_order": 190,
        "is_required": False,
        "journey_stage": 5,
        "stage_gate_required": False,
        "stage_gate_requires_validation": False,
    },
    {
        "document_type": "biometric-appointment-confirmation",
        "label": "Biometric Appointment Confirmation",
        "sort_order": 191,
        "is_required": False,
        "journey_stage": 5,
        "stage_gate_required": False,
        "stage_gate_requires_validation": False,
    },
    {
        "document_type": "consular-interview-confirmation",
        "label": "Consular Interview Confirmation",
        "sort_order": 192,
        "is_required": False,
        "journey_stage": 5,
        "stage_gate_required": False,
        "stage_gate_requires_validation": False,
    },
    {
        "document_type": "photograph-2x2",
        "label": "Photograph (2x2 Inches)",
        "sort_order": 250,
        "is_required": True,
        "journey_stage": 4,
        "stage_gate_required": True,
        "stage_gate_requires_validation": True,
    },
    {
        "document_type": "form-i20-signed",
        "label": "Form I-20 (Signed)",
        "sort_order": 140,
        "is_required": True,
        "journey_stage": 3,
        "stage_gate_required": True,
        "stage_gate_requires_validation": True,
    },
    {
        "document_type": "previous-i20s",
        "label": "Previous I-20's",
        "sort_order": 150,
        "is_required": False,
        "journey_stage": 3,
        "stage_gate_required": False,
        "stage_gate_requires_validation": False,
    },
    {
        "document_type": "university-admission-letter",
        "label": "University Admission Letter",
        "sort_order": 100,
        "is_required": True,
        "journey_stage": 2,
        "stage_gate_required": True,
        "stage_gate_requires_validation": True,
        "stage_gate_group": "admission_proof",
    },
    {
        "document_type": "university-offer-letter",
        "label": "University Offer Letter",
        "sort_order": 101,
        "is_required": False,
        "journey_stage": 2,
        "stage_gate_required": True,
        "stage_gate_requires_validation": True,
        "stage_gate_group": "admission_proof",
    },
    {
        "document_type": "bank-statement",
        "label": "Bank Statement",
        "sort_order": 102,
        "is_required": True,
        "journey_stage": 2,
        "stage_gate_required": True,
        "stage_gate_requires_validation": True,
        "stage_gate_group": "financial_proof",
    },
    {
        "document_type": "bank-balance-certificate",
        "label": "Bank balance certificate",
        "sort_order": 103,
        "is_required": False,
        "journey_stage": 2,
        "stage_gate_required": True,
        "stage_gate_requires_validation": True,
        "stage_gate_group": "financial_proof",
    },
    {
        "document_type": "loan-approval-letter",
        "label": "Loan approval letter (if applicable)",
        "sort_order": 104,
        "is_required": False,
        "journey_stage": 2,
        "stage_gate_required": True,
        "stage_gate_requires_validation": True,
        "stage_gate_group": "financial_proof",
    },
    {
        "document_type": "loan-sanction-letter",
        "label": "Loan Sanction Letter",
        "sort_order": 105,
        "is_required": False,
        "journey_stage": 2,
        "stage_gate_required": True,
        "stage_gate_requires_validation": True,
        "stage_gate_group": "financial_proof",
    },
    {
        "document_type": "affidavit-of-support",
        "label": "Affidavit of Support (from parents/sponsors)",
        "sort_order": 210,
        "is_required": False,
        "journey_stage": 6,
        "stage_gate_required": False,
        "stage_gate_requires_validation": False,
    },
    {
        "document_type": "ca-statement",
        "label": "CA Statement (summary of assets)",
        "sort_order": 225,
        "is_required": False,
        "journey_stage": 6,
        "stage_gate_required": False,
        "stage_gate_requires_validation": False,
    },
    {
        "document_type": "sponsor-income-proof",
        "label": "Sponsor's income proof (salary slips, IT returns)",
        "sort_order": 220,
        "is_required": False,
        "journey_stage": 6,
        "stage_gate_required": False,
        "stage_gate_requires_validation": False,
    },
    {
        "document_type": "provisional-certificates",
        "label": "Provisional certificates",
        "sort_order": 130,
        "is_required": False,
        "journey_stage": 3,
        "stage_gate_required": False,
        "stage_gate_requires_validation": False,
    },
    {
        "document_type": "experience-letters",
        "label": "Work Experience Letters",
        "sort_order": 280,
        "is_required": False,
        "journey_stage": 6,
        "stage_gate_required": False,
        "stage_gate_requires_validation": False,
    },
    {
        "document_type": "salary-slips",
        "label": "Salary slips (last 3-6 months)",
        "sort_order": 230,
        "is_required": False,
        "journey_stage": 6,
        "stage_gate_required": False,
        "stage_gate_requires_validation": False,
    },
    {
        "document_type": "i901-sevis-fee-confirmation",
        "label": "SEVIS I-901 Fee Receipt",
        "sort_order": 180,
        "is_required": True,
        "journey_stage": 5,
        "stage_gate_required": True,
        "stage_gate_requires_validation": True,
    },
]


# ===========================================================================
# UK — Student Visa (Tier 4). First-draft content; editable.
# ===========================================================================

UK_STUDENT_STAGES: list[dict[str, Any]] = [
    {"stage": 1, "name": "Getting Started", "emoji": "📝",
     "description": "Build your profile with academics and an approved English test.",
     "next_step": "Upload your passport, transcripts and English test score"},
    {"stage": 2, "name": "Offer Received", "emoji": "🎓",
     "description": "Conditional or unconditional offer from your university.",
     "next_step": "Upload your university offer letter"},
    {"stage": 3, "name": "CAS Issued", "emoji": "📄",
     "description": "Confirmation of Acceptance for Studies (CAS) issued by your university.",
     "next_step": "Upload your CAS statement"},
    {"stage": 4, "name": "Finances & Healthcare", "emoji": "💷",
     "description": "Show 28-day maintenance funds and pay the Immigration Health Surcharge.",
     "next_step": "Upload financial evidence and your IHS payment confirmation"},
    {"stage": 5, "name": "Visa Application", "emoji": "🛂",
     "description": "Submit the online application, give biometrics, and ATAS if required.",
     "next_step": "Upload your application confirmation and biometric appointment"},
    {"stage": 6, "name": "Decision & Vignette", "emoji": "📘",
     "description": "Visa decision and 90-day entry vignette / BRP collection.",
     "next_step": "Upload your entry vignette or decision letter"},
    {"stage": 7, "name": "Ready to Fly!", "emoji": "✈️",
     "description": "Finalize accommodation, travel and pre-departure documents.",
     "next_step": "Upload remaining arrival documents and finalize travel plans"},
]

UK_STUDENT_DOCUMENTS: list[dict[str, Any]] = [
    {"document_type": "passport", "label": "Passport", "sort_order": 10,
     "is_required": True, "journey_stage": 1, "stage_gate_required": True, "stage_gate_requires_validation": True},
    {"document_type": "english-language-test", "label": "Approved English Test (IELTS UKVI / PTE)", "sort_order": 20,
     "is_required": True, "journey_stage": 1, "stage_gate_required": True, "stage_gate_requires_validation": True},
    {"document_type": "academic-transcripts", "label": "Academic Transcripts & Certificates", "sort_order": 30,
     "is_required": False, "journey_stage": 1, "stage_gate_required": False, "stage_gate_requires_validation": False},
    {"document_type": "university-offer-letter", "label": "University Offer Letter", "sort_order": 100,
     "is_required": True, "journey_stage": 2, "stage_gate_required": True, "stage_gate_requires_validation": True,
     "stage_gate_group": "admission_proof"},
    {"document_type": "cas-statement", "label": "CAS Statement", "sort_order": 120,
     "is_required": True, "journey_stage": 3, "stage_gate_required": True, "stage_gate_requires_validation": True},
    {"document_type": "financial-evidence", "label": "28-Day Financial Evidence / Bank Statement", "sort_order": 140,
     "is_required": True, "journey_stage": 4, "stage_gate_required": True, "stage_gate_requires_validation": True,
     "stage_gate_group": "financial_proof"},
    {"document_type": "ihs-payment-confirmation", "label": "IHS Payment Confirmation", "sort_order": 150,
     "is_required": True, "journey_stage": 4, "stage_gate_required": True, "stage_gate_requires_validation": True},
    {"document_type": "tb-test-certificate", "label": "TB Test Certificate (if applicable)", "sort_order": 160,
     "is_required": False, "journey_stage": 4, "stage_gate_required": False, "stage_gate_requires_validation": False},
    {"document_type": "tuition-deposit-receipt", "label": "Tuition Deposit Receipt", "sort_order": 165,
     "is_required": False, "journey_stage": 4, "stage_gate_required": False, "stage_gate_requires_validation": False},
    {"document_type": "atas-certificate", "label": "ATAS Certificate (if required)", "sort_order": 180,
     "is_required": False, "journey_stage": 5, "stage_gate_required": False, "stage_gate_requires_validation": False},
    {"document_type": "visa-application-form", "label": "Online Visa Application Confirmation", "sort_order": 190,
     "is_required": True, "journey_stage": 5, "stage_gate_required": True, "stage_gate_requires_validation": True},
    {"document_type": "biometric-appointment-confirmation", "label": "Biometric Appointment Confirmation", "sort_order": 195,
     "is_required": False, "journey_stage": 5, "stage_gate_required": False, "stage_gate_requires_validation": False},
    {"document_type": "entry-vignette", "label": "Entry Vignette / Decision Letter", "sort_order": 240,
     "is_required": True, "journey_stage": 6, "stage_gate_required": True, "stage_gate_requires_validation": True},
    {"document_type": "brp", "label": "Biometric Residence Permit (BRP)", "sort_order": 245,
     "is_required": False, "journey_stage": 6, "stage_gate_required": False, "stage_gate_requires_validation": False},
    {"document_type": "accommodation-proof", "label": "Accommodation Confirmation", "sort_order": 280,
     "is_required": False, "journey_stage": 7, "stage_gate_required": False, "stage_gate_requires_validation": False},
]


# ===========================================================================
# Canada — Study Permit. First-draft content; editable.
# ===========================================================================

CA_STUDY_STAGES: list[dict[str, Any]] = [
    {"stage": 1, "name": "Getting Started", "emoji": "📝",
     "description": "Build your profile with academics and an approved language test.",
     "next_step": "Upload your passport, transcripts and language test score"},
    {"stage": 2, "name": "Letter of Acceptance", "emoji": "🎓",
     "description": "Letter of Acceptance (LOA) from a Designated Learning Institution.",
     "next_step": "Upload your Letter of Acceptance"},
    {"stage": 3, "name": "Provincial Attestation", "emoji": "🍁",
     "description": "Provincial/Territorial Attestation Letter (PAL/TAL).",
     "next_step": "Upload your PAL/TAL"},
    {"stage": 4, "name": "Finances", "emoji": "💰",
     "description": "GIC, tuition payment and proof of funds.",
     "next_step": "Upload your GIC certificate and tuition payment receipt"},
    {"stage": 5, "name": "Study Permit Application", "emoji": "🛂",
     "description": "Submit the application, give biometrics and complete a medical exam.",
     "next_step": "Upload your application and biometrics confirmation"},
    {"stage": 6, "name": "Approval & POE Letter", "emoji": "📘",
     "description": "Approval and Port of Entry Letter of Introduction.",
     "next_step": "Upload your POE Letter of Introduction"},
    {"stage": 7, "name": "Ready to Fly!", "emoji": "✈️",
     "description": "Finalize accommodation, travel and pre-departure documents.",
     "next_step": "Upload remaining arrival documents and finalize travel plans"},
]

CA_STUDY_DOCUMENTS: list[dict[str, Any]] = [
    {"document_type": "passport", "label": "Passport", "sort_order": 10,
     "is_required": True, "journey_stage": 1, "stage_gate_required": True, "stage_gate_requires_validation": True},
    {"document_type": "english-language-test", "label": "Language Test (IELTS / PTE / TOEFL)", "sort_order": 20,
     "is_required": True, "journey_stage": 1, "stage_gate_required": True, "stage_gate_requires_validation": True},
    {"document_type": "academic-transcripts", "label": "Academic Transcripts & Certificates", "sort_order": 30,
     "is_required": False, "journey_stage": 1, "stage_gate_required": False, "stage_gate_requires_validation": False},
    {"document_type": "letter-of-acceptance", "label": "Letter of Acceptance (LOA)", "sort_order": 100,
     "is_required": True, "journey_stage": 2, "stage_gate_required": True, "stage_gate_requires_validation": True,
     "stage_gate_group": "admission_proof"},
    {"document_type": "provincial-attestation-letter", "label": "Provincial Attestation Letter (PAL/TAL)", "sort_order": 120,
     "is_required": True, "journey_stage": 3, "stage_gate_required": True, "stage_gate_requires_validation": True},
    {"document_type": "gic-certificate", "label": "GIC Certificate", "sort_order": 140,
     "is_required": True, "journey_stage": 4, "stage_gate_required": True, "stage_gate_requires_validation": True,
     "stage_gate_group": "financial_proof"},
    {"document_type": "tuition-payment-receipt", "label": "Tuition Payment Receipt", "sort_order": 145,
     "is_required": True, "journey_stage": 4, "stage_gate_required": True, "stage_gate_requires_validation": True,
     "stage_gate_group": "financial_proof"},
    {"document_type": "proof-of-funds", "label": "Proof of Funds / Bank Statements", "sort_order": 150,
     "is_required": False, "journey_stage": 4, "stage_gate_required": False, "stage_gate_requires_validation": False,
     "stage_gate_group": "financial_proof"},
    {"document_type": "study-permit-application", "label": "Study Permit Application (IMM forms)", "sort_order": 190,
     "is_required": True, "journey_stage": 5, "stage_gate_required": True, "stage_gate_requires_validation": True},
    {"document_type": "medical-exam-confirmation", "label": "Upfront Medical Exam (IME) Confirmation", "sort_order": 195,
     "is_required": False, "journey_stage": 5, "stage_gate_required": False, "stage_gate_requires_validation": False},
    {"document_type": "biometrics-confirmation", "label": "Biometrics Confirmation", "sort_order": 196,
     "is_required": False, "journey_stage": 5, "stage_gate_required": False, "stage_gate_requires_validation": False},
    {"document_type": "poe-letter", "label": "Port of Entry Letter of Introduction", "sort_order": 240,
     "is_required": True, "journey_stage": 6, "stage_gate_required": True, "stage_gate_requires_validation": True},
    {"document_type": "accommodation-proof", "label": "Accommodation Confirmation", "sort_order": 280,
     "is_required": False, "journey_stage": 7, "stage_gate_required": False, "stage_gate_requires_validation": False},
]


# ===========================================================================
# Australia — Subclass 500 Student Visa. First-draft content; editable.
# ===========================================================================

AU_STUDENT_STAGES: list[dict[str, Any]] = [
    {"stage": 1, "name": "Getting Started", "emoji": "📝",
     "description": "Build your profile with academics and an approved English test.",
     "next_step": "Upload your passport, transcripts and English test score"},
    {"stage": 2, "name": "Offer & CoE", "emoji": "🎓",
     "description": "Offer letter and Confirmation of Enrolment (CoE).",
     "next_step": "Upload your offer letter and CoE"},
    {"stage": 3, "name": "GTE & OSHC", "emoji": "🌏",
     "description": "Genuine Temporary Entrant statement and Overseas Student Health Cover.",
     "next_step": "Upload your GTE statement and OSHC certificate"},
    {"stage": 4, "name": "Finances", "emoji": "💰",
     "description": "Evidence of financial capacity for tuition and living costs.",
     "next_step": "Upload your financial capacity evidence"},
    {"stage": 5, "name": "Visa Application", "emoji": "🛂",
     "description": "Apply via ImmiAccount, complete health exam and biometrics.",
     "next_step": "Upload your application confirmation and health exam"},
    {"stage": 6, "name": "Decision", "emoji": "📘",
     "description": "Visa grant notice from the Department of Home Affairs.",
     "next_step": "Upload your visa grant notice"},
    {"stage": 7, "name": "Ready to Fly!", "emoji": "✈️",
     "description": "Finalize accommodation, travel and pre-departure documents.",
     "next_step": "Upload remaining arrival documents and finalize travel plans"},
]

AU_STUDENT_DOCUMENTS: list[dict[str, Any]] = [
    {"document_type": "passport", "label": "Passport", "sort_order": 10,
     "is_required": True, "journey_stage": 1, "stage_gate_required": True, "stage_gate_requires_validation": True},
    {"document_type": "english-language-test", "label": "English Test (IELTS / PTE / TOEFL)", "sort_order": 20,
     "is_required": True, "journey_stage": 1, "stage_gate_required": True, "stage_gate_requires_validation": True},
    {"document_type": "academic-transcripts", "label": "Academic Transcripts & Certificates", "sort_order": 30,
     "is_required": False, "journey_stage": 1, "stage_gate_required": False, "stage_gate_requires_validation": False},
    {"document_type": "university-offer-letter", "label": "University Offer Letter", "sort_order": 100,
     "is_required": True, "journey_stage": 2, "stage_gate_required": True, "stage_gate_requires_validation": True,
     "stage_gate_group": "admission_proof"},
    {"document_type": "confirmation-of-enrolment", "label": "Confirmation of Enrolment (CoE)", "sort_order": 110,
     "is_required": True, "journey_stage": 2, "stage_gate_required": True, "stage_gate_requires_validation": True,
     "stage_gate_group": "admission_proof"},
    {"document_type": "gte-statement", "label": "Genuine Temporary Entrant (GTE) Statement", "sort_order": 120,
     "is_required": True, "journey_stage": 3, "stage_gate_required": True, "stage_gate_requires_validation": True},
    {"document_type": "oshc-certificate", "label": "Overseas Student Health Cover (OSHC)", "sort_order": 130,
     "is_required": True, "journey_stage": 3, "stage_gate_required": True, "stage_gate_requires_validation": True},
    {"document_type": "financial-capacity-evidence", "label": "Financial Capacity Evidence", "sort_order": 140,
     "is_required": True, "journey_stage": 4, "stage_gate_required": True, "stage_gate_requires_validation": True,
     "stage_gate_group": "financial_proof"},
    {"document_type": "visa-application-form", "label": "ImmiAccount Visa Application Confirmation", "sort_order": 190,
     "is_required": True, "journey_stage": 5, "stage_gate_required": True, "stage_gate_requires_validation": True},
    {"document_type": "health-exam-confirmation", "label": "Health Examination Confirmation", "sort_order": 195,
     "is_required": False, "journey_stage": 5, "stage_gate_required": False, "stage_gate_requires_validation": False},
    {"document_type": "biometrics-confirmation", "label": "Biometrics Confirmation", "sort_order": 196,
     "is_required": False, "journey_stage": 5, "stage_gate_required": False, "stage_gate_requires_validation": False},
    {"document_type": "visa-grant-notice", "label": "Visa Grant Notice", "sort_order": 240,
     "is_required": True, "journey_stage": 6, "stage_gate_required": True, "stage_gate_requires_validation": True},
    {"document_type": "accommodation-proof", "label": "Accommodation Confirmation", "sort_order": 280,
     "is_required": False, "journey_stage": 7, "stage_gate_required": False, "stage_gate_requires_validation": False},
]


# ===========================================================================
# Registries
# ===========================================================================

# Visa types per country. The first entry is the default. `journey` points at the
# JOURNEYS key that supplies stages + documents (aliases let secondary visa types
# reuse the primary journey until dedicated content is authored).
VISA_TYPES: dict[str, list[dict[str, Any]]] = {
    "US": [
        {"key": "us_f1", "label": "F-1 Student Visa", "journey": "us_f1"},
        {"key": "us_j1", "label": "J-1 Exchange Visitor", "journey": "us_f1"},
        {"key": "us_m1", "label": "M-1 Vocational Student", "journey": "us_f1"},
    ],
    "UK": [
        {"key": "uk_student", "label": "Student Visa (Tier 4)", "journey": "uk_student"},
        {"key": "uk_short_study", "label": "Short-Term Study Visa", "journey": "uk_student"},
    ],
    "CA": [
        {"key": "ca_study_permit", "label": "Study Permit", "journey": "ca_study_permit"},
        {"key": "ca_sds", "label": "Student Direct Stream (SDS)", "journey": "ca_study_permit"},
    ],
    "AU": [
        {"key": "au_subclass500", "label": "Subclass 500 Student Visa", "journey": "au_subclass500"},
    ],
}

# journey_key -> {"stages": [...], "documents": [...]}
JOURNEYS: dict[str, dict[str, list[dict[str, Any]]]] = {
    "us_f1": {"stages": US_F1_STAGES, "documents": US_F1_DOCUMENTS},
    "uk_student": {"stages": UK_STUDENT_STAGES, "documents": UK_STUDENT_DOCUMENTS},
    "ca_study_permit": {"stages": CA_STUDY_STAGES, "documents": CA_STUDY_DOCUMENTS},
    "au_subclass500": {"stages": AU_STUDENT_STAGES, "documents": AU_STUDENT_DOCUMENTS},
}

# Flat (country_code, visa_type_key) -> visa-type dict, for quick lookup/validation.
_VISA_TYPE_INDEX: dict[tuple[str, str], dict[str, Any]] = {
    (code, vt["key"]): vt for code, items in VISA_TYPES.items() for vt in items
}


# ===========================================================================
# Accessors
# ===========================================================================

def normalize_country(code: str | None) -> str | None:
    value = str(code or "").strip().upper()
    return value if value in VISA_TYPES else None


def default_visa_type(country_code: str) -> str | None:
    items = VISA_TYPES.get(str(country_code or "").strip().upper())
    return items[0]["key"] if items else None


def normalize_visa_type(country_code: str | None, visa_type_key: str | None) -> str | None:
    code = normalize_country(country_code)
    if not code:
        return None
    key = str(visa_type_key or "").strip().lower()
    if (code, key) in _VISA_TYPE_INDEX:
        return key
    return None


def resolve_selection(country_code: str | None, visa_type_key: str | None) -> tuple[str, str]:
    """Best-effort (country, visa_type) resolution with US/F-1 fallback."""
    code = normalize_country(country_code) or DEFAULT_COUNTRY_CODE
    visa = normalize_visa_type(code, visa_type_key) or default_visa_type(code) or DEFAULT_VISA_TYPE_KEY
    return code, visa


def country_meta(country_code: str) -> Optional[dict]:
    """Display metadata (name, flag, gradient, landmark, intakes) from the enterprise catalog."""
    return enterprise_catalog.get_country(country_code)


def get_journey(country_code: str | None, visa_type_key: str | None) -> dict[str, list[dict[str, Any]]]:
    """Return {'stages': [...], 'documents': [...]} for a (country, visa) selection."""
    code, visa = resolve_selection(country_code, visa_type_key)
    journey_key = _VISA_TYPE_INDEX.get((code, visa), {}).get("journey", visa)
    return JOURNEYS.get(journey_key) or JOURNEYS[DEFAULT_VISA_TYPE_KEY]


def journey_stages_for(country_code: str | None, visa_type_key: str | None) -> list[dict[str, Any]]:
    return get_journey(country_code, visa_type_key)["stages"]


def documents_for(country_code: str | None, visa_type_key: str | None) -> list[dict[str, Any]]:
    return get_journey(country_code, visa_type_key)["documents"]


def visa_type_label(country_code: str | None, visa_type_key: str | None) -> str:
    vt = _VISA_TYPE_INDEX.get((normalize_country(country_code) or "", str(visa_type_key or "").strip().lower()))
    return vt["label"] if vt else ""


def all_scopes() -> list[tuple[str, str]]:
    """Every (country_code, visa_type_key) pair enabled in this build."""
    return list(_VISA_TYPE_INDEX.keys())


def catalog_scope(country_code: str | None, visa_type_key: str | None) -> tuple[str, str]:
    """Map a (country, visa) selection to the (country, journey_key) under which its
    document-catalog rows are stored. Secondary/aliased visa types collapse onto their
    primary journey so the catalog isn't duplicated per alias."""
    code, visa = resolve_selection(country_code, visa_type_key)
    journey_key = _VISA_TYPE_INDEX.get((code, visa), {}).get("journey", visa)
    return code, journey_key


def catalog_scopes() -> list[tuple[str, str]]:
    """Distinct (country_code, journey_key) scopes that own a document catalog."""
    seen: list[tuple[str, str]] = []
    for code in LAUNCH_COUNTRY_CODES:
        for vt in VISA_TYPES.get(code, []):
            scope = (code, vt["journey"])
            if scope not in seen:
                seen.append(scope)
    return seen


def onboarding_catalog_payload() -> dict[str, Any]:
    """Countries + visa types + intakes for the onboarding wizard."""
    countries = []
    for code in LAUNCH_COUNTRY_CODES:
        meta = enterprise_catalog.get_country(code) or {}
        countries.append({
            "code": code,
            "name": meta.get("name", code),
            "flag_emoji": meta.get("flag_emoji", ""),
            "gradient_from": meta.get("gradient_from"),
            "gradient_to": meta.get("gradient_to"),
            "accent": meta.get("accent"),
            "intakes": enterprise_catalog.materialize_future_intakes(meta.get("student_intakes", [])),
            "visa_types": [
                {"key": vt["key"], "label": vt["label"], "default": idx == 0}
                for idx, vt in enumerate(VISA_TYPES.get(code, []))
            ],
        })
    return {"countries": countries}
