from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app import models

DEFAULT_JOURNEY_STAGES: list[dict[str, Any]] = [
    {
        "stage": 1,
        "name": "Getting Started",
        "emoji": "📝",
        "description": "Welcome! Start your F1 visa journey.",
        "next_step": "Upload your university offer/admission letter",
    },
    {
        "stage": 2,
        "name": "Admission Received",
        "emoji": "🎓",
        "description": "University admission confirmed!",
        "next_step": "Upload your passport and academic documents",
    },
    {
        "stage": 3,
        "name": "Documents Ready",
        "emoji": "📄",
        "description": "Essential documents collected.",
        "next_step": "Get your signed I-20 from your university",
    },
    {
        "stage": 4,
        "name": "I-20 Received",
        "emoji": "📘",
        "description": "Great! You have your I-20 from the university.",
        "next_step": "Complete your DS-160 application online",
    },
    {
        "stage": 5,
        "name": "DS-160 Filed",
        "emoji": "📋",
        "description": "DS-160 application submitted successfully.",
        "next_step": "Pay your SEVIS I-901 fee and visa fee",
    },
    {
        "stage": 6,
        "name": "Fees Paid",
        "emoji": "💳",
        "description": "SEVIS and visa fees payment confirmed.",
        "next_step": "Schedule your visa interview appointment",
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
        "journey_stage": 3,
        "stage_gate_required": True,
    },
    {
        "document_type": "ds-160-confirmation",
        "label": "DS-160 Confirmation Page",
        "sort_order": 20,
        "is_required": True,
        "journey_stage": 5,
        "stage_gate_required": True,
    },
    {
        "document_type": "ds-160-application",
        "label": "DS-160 Application",
        "sort_order": 30,
        "is_required": True,
        "journey_stage": 5,
        "stage_gate_required": False,
    },
    {
        "document_type": "us-visa-appointment-letter",
        "label": "US Visa Appointment Letter",
        "sort_order": 40,
        "is_required": True,
        "journey_stage": 7,
        "stage_gate_required": True,
    },
    {
        "document_type": "visa-fee-receipt",
        "label": "Visa Fee Receipt",
        "sort_order": 50,
        "is_required": True,
        "journey_stage": 6,
        "stage_gate_required": False,
    },
    {
        "document_type": "photograph-2x2",
        "label": "Photograph (2x2 Inches)",
        "sort_order": 60,
        "is_required": True,
        "journey_stage": 7,
        "stage_gate_required": True,
    },
    {
        "document_type": "form-i20-signed",
        "label": "Form I-20 (Signed)",
        "sort_order": 70,
        "is_required": True,
        "journey_stage": 4,
        "stage_gate_required": True,
    },
    {
        "document_type": "previous-i20s",
        "label": "Previous I-20's",
        "sort_order": 80,
        "is_required": False,
        "journey_stage": 4,
        "stage_gate_required": False,
    },
    {
        "document_type": "university-admission-letter",
        "label": "University Admission Letter",
        "sort_order": 90,
        "is_required": True,
        "journey_stage": 2,
        "stage_gate_required": True,
    },
    {
        "document_type": "bank-balance-certificate",
        "label": "Bank balance certificate",
        "sort_order": 100,
        "is_required": True,
        "journey_stage": 7,
        "stage_gate_required": True,
    },
    {
        "document_type": "loan-approval-letter",
        "label": "Loan approval letter (if applicable)",
        "sort_order": 110,
        "is_required": False,
        "journey_stage": 6,
        "stage_gate_required": False,
    },
    {
        "document_type": "affidavit-of-support",
        "label": "Affidavit of Support (if sponsored)",
        "sort_order": 120,
        "is_required": False,
        "journey_stage": 6,
        "stage_gate_required": False,
    },
    {
        "document_type": "sponsor-income-proof",
        "label": "Sponsor's income proof (salary slips, IT returns)",
        "sort_order": 130,
        "is_required": False,
        "journey_stage": 6,
        "stage_gate_required": False,
    },
    {
        "document_type": "degree-certificates",
        "label": "Degree certificates",
        "sort_order": 140,
        "is_required": True,
        "journey_stage": 3,
        "stage_gate_required": True,
        "stage_gate_group": "academics_one_of",
    },
    {
        "document_type": "provisional-certificates",
        "label": "Provisional certificates",
        "sort_order": 150,
        "is_required": False,
        "journey_stage": 3,
        "stage_gate_required": False,
    },
    {
        "document_type": "transcripts-marksheets",
        "label": "Transcripts / mark sheets (all semesters)",
        "sort_order": 160,
        "is_required": True,
        "journey_stage": 3,
        "stage_gate_required": True,
        "stage_gate_group": "academics_one_of",
    },
    {
        "document_type": "standardized-test-scores",
        "label": "Standardized test scores (GRE, TOEFL, IELTS, Duolingo)",
        "sort_order": 170,
        "is_required": False,
        "journey_stage": 3,
        "stage_gate_required": False,
    },
    {
        "document_type": "experience-letters",
        "label": "Experience letters",
        "sort_order": 180,
        "is_required": False,
        "journey_stage": 3,
        "stage_gate_required": False,
    },
    {
        "document_type": "offer-letters",
        "label": "Offer letters",
        "sort_order": 190,
        "is_required": False,
        "journey_stage": 3,
        "stage_gate_required": False,
    },
    {
        "document_type": "salary-slips",
        "label": "Salary slips (last 3-6 months)",
        "sort_order": 200,
        "is_required": False,
        "journey_stage": 6,
        "stage_gate_required": False,
    },
    {
        "document_type": "resume",
        "label": "Resume (updated)",
        "sort_order": 210,
        "is_required": False,
        "journey_stage": 3,
        "stage_gate_required": False,
    },
    {
        "document_type": "i901-sevis-fee-confirmation",
        "label": "I-901 SEVIS fee payment confirmation",
        "sort_order": 220,
        "is_required": True,
        "journey_stage": 6,
        "stage_gate_required": True,
    },
]


def ensure_default_document_type_catalog(db: Session) -> None:
    existing_rows = db.query(models.DocumentTypeCatalog.document_type).all()
    existing_types = {row[0] for row in existing_rows}

    to_insert = [row for row in DEFAULT_DOCUMENT_TYPES if row["document_type"] not in existing_types]
    if not to_insert:
        return

    for row in to_insert:
        db.add(models.DocumentTypeCatalog(**row))
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
