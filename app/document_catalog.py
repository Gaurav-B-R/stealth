from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app import models

DEFAULT_JOURNEY_STAGES: list[dict[str, Any]] = [
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
        "name": "Visa Stage",
        "emoji": "🛂",
        "description": "Prepare your visa interview packet and supporting documents.",
        "next_step": "Review final interview checklist and confidence prep",
    },
    {
        "stage": 7,
        "name": "Ready to Fly!",
        "emoji": "✈️",
        "description": "Interview scheduled! All documents ready.",
        "next_step": "You're all set! Good luck with your visa interview!",
    },
]


DEFAULT_DOCUMENT_TYPES: list[dict[str, Any]] = [
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

REMOVED_DOCUMENT_TYPES = {
    "degree-certificates",
    "transcripts-marksheets",
    "offer-letters",
}


def ensure_default_document_type_catalog(db: Session) -> None:
    existing_rows = db.query(models.DocumentTypeCatalog).all()
    existing_by_type = {row.document_type: row for row in existing_rows}
    has_changes = False

    for row in DEFAULT_DOCUMENT_TYPES:
        existing = existing_by_type.get(row["document_type"])
        if not existing:
            db.add(models.DocumentTypeCatalog(**row))
            has_changes = True
            continue

        # One-time migration of legacy stage-1 mappings without overriding user customizations.
        legacy_shift_rules = {
            "passport": {"legacy_stage": 3, "new_stage": 1, "new_label": "Passport"},
            "standardized-test-scores": {
                "legacy_stage": 3,
                "new_stage": 1,
                "new_label": "Standardized Test Scores (TOEFL/IELTS/Duolingo)",
            },
            "resume": {"legacy_stage": 3, "new_stage": 1, "new_label": "Resume/CV"},
        }
        rule = legacy_shift_rules.get(existing.document_type)
        if rule and existing.journey_stage == rule["legacy_stage"]:
            existing.journey_stage = rule["new_stage"]
            existing.stage_gate_required = True
            existing.stage_gate_requires_validation = True
            if existing.label in {"Passport", "Standardized test scores (GRE, TOEFL, IELTS, Duolingo)", "Resume (updated)"}:
                existing.label = rule["new_label"]
            has_changes = True

    # Ensure validation requirement exists for mandatory stage-1 starter documents.
    stage_one_required = {
        "passport",
        "standardized-test-scores",
        "resume",
    }
    stage_one_optional = {
        "high-school-transcripts",
        "other-school-college-degree-certificates",
        "standardized-test-scores-gre-gmat",
        "statement-of-purpose-lors",
    }
    admission_stage_rules: dict[str, dict[str, Any]] = {
        "university-admission-letter": {
            "journey_stage": 2,
            "is_required": True,
            "stage_gate_required": True,
            "stage_gate_requires_validation": True,
            "stage_gate_group": "admission_proof",
            "sort_order": 100,
        },
        "university-offer-letter": {
            "journey_stage": 2,
            "is_required": False,
            "stage_gate_required": True,
            "stage_gate_requires_validation": True,
            "stage_gate_group": "admission_proof",
            "sort_order": 101,
        },
        "bank-statement": {
            "journey_stage": 2,
            "is_required": True,
            "stage_gate_required": True,
            "stage_gate_requires_validation": True,
            "stage_gate_group": "financial_proof",
            "sort_order": 102,
        },
        "bank-balance-certificate": {
            "journey_stage": 2,
            "is_required": False,
            "stage_gate_required": True,
            "stage_gate_requires_validation": True,
            "stage_gate_group": "financial_proof",
            "sort_order": 103,
        },
        "loan-approval-letter": {
            "journey_stage": 2,
            "is_required": False,
            "stage_gate_required": True,
            "stage_gate_requires_validation": True,
            "stage_gate_group": "financial_proof",
            "sort_order": 104,
        },
        "loan-sanction-letter": {
            "journey_stage": 2,
            "is_required": False,
            "stage_gate_required": True,
            "stage_gate_requires_validation": True,
            "stage_gate_group": "financial_proof",
            "sort_order": 105,
        },
    }
    stage_flow_rules: dict[str, dict[str, Any]] = {
        "form-i20-signed": {
            "journey_stage": 3,
            "is_required": True,
            "stage_gate_required": True,
            "stage_gate_requires_validation": True,
        },
        "previous-i20s": {
            "journey_stage": 3,
            "is_required": False,
            "stage_gate_required": False,
            "stage_gate_requires_validation": False,
        },
        "ds-160-confirmation": {
            "journey_stage": 4,
            "is_required": False,
            "stage_gate_required": False,
            "stage_gate_requires_validation": False,
        },
        "ds-160-application": {
            "label": "DS-160 Application (Full Application)",
            "journey_stage": 4,
            "is_required": True,
            "stage_gate_required": True,
            "stage_gate_requires_validation": True,
        },
        "travel-history-documents": {
            "journey_stage": 4,
            "is_required": False,
            "stage_gate_required": False,
            "stage_gate_requires_validation": False,
            "sort_order": 175,
        },
        "i901-sevis-fee-confirmation": {
            "label": "SEVIS I-901 Fee Receipt",
            "journey_stage": 5,
            "is_required": True,
            "stage_gate_required": True,
            "stage_gate_requires_validation": True,
        },
        "visa-fee-receipt": {
            "label": "Visa Application (MRV) Fee Receipts",
            "journey_stage": 5,
            "is_required": False,
            "stage_gate_required": False,
            "stage_gate_requires_validation": False,
        },
        "biometric-appointment-confirmation": {
            "journey_stage": 5,
            "is_required": False,
            "stage_gate_required": False,
            "stage_gate_requires_validation": False,
            "sort_order": 191,
        },
        "consular-interview-confirmation": {
            "journey_stage": 5,
            "is_required": False,
            "stage_gate_required": False,
            "stage_gate_requires_validation": False,
            "sort_order": 192,
        },
        "us-visa-appointment-letter": {
            "journey_stage": 6,
            "is_required": True,
            "stage_gate_required": True,
            "stage_gate_requires_validation": True,
        },
        "stamped-f1-visa": {
            "label": "Stamped F-1 Visa",
            "journey_stage": 6,
            "is_required": True,
            "stage_gate_required": True,
            "stage_gate_requires_validation": True,
            "sort_order": 245,
        },
        "immunization-vaccination-records": {
            "label": "Immunization/Vaccination Records",
            "journey_stage": 7,
            "is_required": True,
            "stage_gate_required": True,
            "stage_gate_requires_validation": True,
            "sort_order": 290,
        },
        "affidavit-of-support": {
            "label": "Affidavit of Support (from parents/sponsors)",
            "journey_stage": 6,
            "is_required": False,
            "stage_gate_required": False,
            "stage_gate_requires_validation": False,
            "sort_order": 210,
        },
        "ca-statement": {
            "label": "CA Statement (summary of assets)",
            "journey_stage": 6,
            "is_required": False,
            "stage_gate_required": False,
            "stage_gate_requires_validation": False,
            "sort_order": 225,
        },
        "experience-letters": {
            "label": "Work Experience Letters",
            "journey_stage": 6,
            "is_required": False,
            "stage_gate_required": False,
            "stage_gate_requires_validation": False,
            "sort_order": 280,
        },
        "photograph-2x2": {
            "journey_stage": 4,
            "is_required": True,
            "stage_gate_required": True,
            "stage_gate_requires_validation": True,
        },
    }
    for existing in db.query(models.DocumentTypeCatalog).all():
        if existing.document_type in REMOVED_DOCUMENT_TYPES:
            if existing.is_active:
                existing.is_active = False
                has_changes = True
            if existing.is_required:
                existing.is_required = False
                has_changes = True
            if existing.stage_gate_required:
                existing.stage_gate_required = False
                has_changes = True
            if existing.stage_gate_requires_validation:
                existing.stage_gate_requires_validation = False
                has_changes = True
        admission_rule = admission_stage_rules.get(existing.document_type)
        if admission_rule:
            for field, value in admission_rule.items():
                if getattr(existing, field) != value:
                    setattr(existing, field, value)
                    has_changes = True
        stage_flow_rule = stage_flow_rules.get(existing.document_type)
        if stage_flow_rule:
            for field, value in stage_flow_rule.items():
                if getattr(existing, field) != value:
                    setattr(existing, field, value)
                    has_changes = True
        if existing.document_type in stage_one_required and existing.journey_stage == 1:
            if not existing.is_required:
                existing.is_required = True
                has_changes = True
            if not existing.stage_gate_required:
                existing.stage_gate_required = True
                has_changes = True
            if not existing.stage_gate_requires_validation:
                existing.stage_gate_requires_validation = True
                has_changes = True
        if existing.document_type in stage_one_optional and existing.journey_stage == 1:
            if existing.is_required:
                existing.is_required = False
                has_changes = True
            if existing.stage_gate_required:
                existing.stage_gate_required = False
                has_changes = True
            if existing.stage_gate_requires_validation:
                existing.stage_gate_requires_validation = False
                has_changes = True
        # Mandatory docs must gate stage progression.
        if existing.is_required and not existing.stage_gate_required:
            existing.stage_gate_required = True
            has_changes = True
        # Any stage-gating document must be validated successfully before progression.
        if existing.stage_gate_required and not existing.stage_gate_requires_validation:
            existing.stage_gate_requires_validation = True
            has_changes = True
        if not existing.stage_gate_required and existing.stage_gate_requires_validation:
            existing.stage_gate_requires_validation = False
            has_changes = True

    if has_changes:
        db.commit()


def get_document_type_catalog(
    db: Session,
    active_only: bool = True,
) -> list[models.DocumentTypeCatalog]:
    query = db.query(models.DocumentTypeCatalog)
    if active_only:
        query = query.filter(models.DocumentTypeCatalog.is_active.is_(True))
    return query.order_by(models.DocumentTypeCatalog.sort_order.asc(), models.DocumentTypeCatalog.id.asc()).all()


def get_document_type_payload(
    db: Session,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    rows = get_document_type_catalog(db, active_only=active_only)
    return [
        {
            "value": row.document_type,
            "label": row.label,
            "description": row.description,
            "sort_order": row.sort_order,
            "is_active": row.is_active,
            "is_required": row.is_required,
            "journey_stage": row.journey_stage,
            "stage_gate_required": row.stage_gate_required,
            "stage_gate_requires_validation": row.stage_gate_requires_validation,
            "stage_gate_group": row.stage_gate_group,
        }
        for row in rows
    ]


def build_journey_stages(document_types: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stage_map: dict[int, dict[str, Any]] = {}
    for stage in DEFAULT_JOURNEY_STAGES:
        stage_map[stage["stage"]] = {
            **stage,
            "required_docs": [],
        }

    for doc_type in document_types:
        stage_number = doc_type.get("journey_stage")
        if not isinstance(stage_number, int):
            continue
        stage_obj = stage_map.get(stage_number)
        if not stage_obj:
            continue
        if doc_type.get("is_required"):
            stage_obj["required_docs"].append(doc_type["value"])

    return [stage_map[key] for key in sorted(stage_map.keys())]


def build_document_catalog_response(db: Session) -> dict[str, Any]:
    document_types = get_document_type_payload(db, active_only=True)
    required_document_types = [row["value"] for row in document_types if row.get("is_required")]
    journey_stages = build_journey_stages(document_types)
    return {
        "document_types": document_types,
        "required_document_types": required_document_types,
        "journey_stages": journey_stages,
    }
