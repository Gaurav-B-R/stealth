from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app import models
from app import visa_catalog

# Back-compat aliases: the US F-1 catalog now lives in app/visa_catalog.py (single
# source of truth). These names are kept because other modules import them.
DEFAULT_JOURNEY_STAGES: list[dict[str, Any]] = visa_catalog.US_F1_STAGES
DEFAULT_DOCUMENT_TYPES: list[dict[str, Any]] = visa_catalog.US_F1_DOCUMENTS

REMOVED_DOCUMENT_TYPES = {
    "degree-certificates",
    "transcripts-marksheets",
    "offer-letters",
}

# The US F-1 scope owns the legacy rows (existing prod data is backfilled to this).
_US_COUNTRY = visa_catalog.DEFAULT_COUNTRY_CODE   # "US"
_US_VISA = visa_catalog.DEFAULT_VISA_TYPE_KEY     # "us_f1"


def _scoped_query(db: Session, country_code: str, visa_type_key: str, active_only: bool):
    query = db.query(models.DocumentTypeCatalog).filter(
        models.DocumentTypeCatalog.country_code == country_code,
        models.DocumentTypeCatalog.visa_type_key == visa_type_key,
    )
    if active_only:
        query = query.filter(models.DocumentTypeCatalog.is_active.is_(True))
    return query


def ensure_default_document_type_catalog(db: Session) -> None:
    """Seed/repair every (country, visa) document catalog scope."""
    _ensure_us_f1_catalog(db)
    _ensure_additional_scope_catalogs(db)
    ensure_enterprise_document_catalog(db)


def ensure_enterprise_document_catalog(db: Session) -> None:
    """Seed/sync the per-country ENTERPRISE document catalogs (visa_type_key='enterprise').

    The detailed destination-specific lists live in
    enterprise_catalog.ENTERPRISE_DOCUMENT_CATALOG; this mirrors them into the
    document_type_catalog table so the CRM pickers are DB-driven. Idempotent:
    inserts missing rows and keeps label/hint/required/sort in step with the code
    defaults, but never touches is_active (so rows can be disabled in the DB).
    """
    from app import enterprise_catalog

    has_changes = False
    for country_code, items in enterprise_catalog.ENTERPRISE_DOCUMENT_CATALOG.items():
        existing_by_type = {
            row.document_type: row
            for row in _scoped_query(db, country_code, "enterprise", active_only=False).all()
        }
        for sort_order, item in enumerate(items, start=1):
            existing = existing_by_type.get(item["key"])
            if not existing:
                db.add(models.DocumentTypeCatalog(
                    document_type=item["key"],
                    country_code=country_code,
                    visa_type_key="enterprise",
                    label=item["label"],
                    description=item.get("hint") or None,
                    sort_order=sort_order,
                    is_required=bool(item.get("required")),
                ))
                has_changes = True
                continue
            if (existing.label != item["label"] or (existing.description or "") != (item.get("hint") or "")
                    or existing.sort_order != sort_order or bool(existing.is_required) != bool(item.get("required"))):
                existing.label = item["label"]
                existing.description = item.get("hint") or None
                existing.sort_order = sort_order
                existing.is_required = bool(item.get("required"))
                has_changes = True
    if has_changes:
        db.commit()


def _ensure_us_f1_catalog(db: Session) -> None:
    """US F-1 seeding + one-time legacy migrations. Behaviour is unchanged from the
    original single-scope implementation; queries/inserts are scoped to US/us_f1."""
    existing_rows = _scoped_query(db, _US_COUNTRY, _US_VISA, active_only=False).all()
    existing_by_type = {row.document_type: row for row in existing_rows}
    has_changes = False

    for row in DEFAULT_DOCUMENT_TYPES:
        existing = existing_by_type.get(row["document_type"])
        if not existing:
            db.add(models.DocumentTypeCatalog(**row, country_code=_US_COUNTRY, visa_type_key=_US_VISA))
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
    for existing in _scoped_query(db, _US_COUNTRY, _US_VISA, active_only=False).all():
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


def _ensure_additional_scope_catalogs(db: Session) -> None:
    """Additively seed the non-US (country, visa) catalogs from visa_catalog. Existing
    rows are left untouched so admin customizations survive. Each scope commits on its
    own and rolls back on failure, so a legacy DB (e.g. a pre-migration single-unique
    document_type) degrades gracefully to US-only instead of crashing startup."""
    scoped_default_label_repairs: dict[tuple[str, str], dict[str, set[str]]] = {
        ("UK", "uk_student"): {
            "english-language-test": {"Approved English Test (IELTS UKVI / PTE)"},
            "entry-vignette": {"Entry Vignette / Decision Letter"},
            "brp": {"Biometric Residence Permit (BRP)"},
        },
    }
    for country_code, journey_key in visa_catalog.catalog_scopes():
        if (country_code, journey_key) == (_US_COUNTRY, _US_VISA):
            continue
        try:
            existing_by_type = {
                row.document_type: row
                for row in _scoped_query(db, country_code, journey_key, active_only=False).all()
            }
            changed = False
            default_label_repairs = scoped_default_label_repairs.get((country_code, journey_key), {})
            for row in visa_catalog.documents_for(country_code, journey_key):
                existing = existing_by_type.get(row["document_type"])
                if existing:
                    stale_default_labels = default_label_repairs.get(existing.document_type)
                    if stale_default_labels and existing.label in stale_default_labels:
                        for field in (
                            "label",
                            "sort_order",
                            "is_required",
                            "journey_stage",
                            "stage_gate_required",
                            "stage_gate_requires_validation",
                            "stage_gate_group",
                        ):
                            value = row.get(field)
                            if getattr(existing, field) != value:
                                setattr(existing, field, value)
                                changed = True
                    continue
                db.add(models.DocumentTypeCatalog(**row, country_code=country_code, visa_type_key=journey_key))
                changed = True
            if changed:
                db.commit()
        except Exception:
            db.rollback()


def get_document_type_catalog(
    db: Session,
    active_only: bool = True,
    country_code: str | None = None,
    visa_type_key: str | None = None,
) -> list[models.DocumentTypeCatalog]:
    code, journey = visa_catalog.catalog_scope(country_code, visa_type_key)
    return (
        _scoped_query(db, code, journey, active_only)
        .order_by(models.DocumentTypeCatalog.sort_order.asc(), models.DocumentTypeCatalog.id.asc())
        .all()
    )


def get_document_type_payload(
    db: Session,
    active_only: bool = True,
    country_code: str | None = None,
    visa_type_key: str | None = None,
) -> list[dict[str, Any]]:
    rows = get_document_type_catalog(db, active_only=active_only, country_code=country_code, visa_type_key=visa_type_key)
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


def build_journey_stages(
    document_types: list[dict[str, Any]],
    stages: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    base_stages = stages if stages is not None else DEFAULT_JOURNEY_STAGES
    stage_map: dict[int, dict[str, Any]] = {}
    for stage in base_stages:
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


def build_document_catalog_response(
    db: Session,
    country_code: str | None = None,
    visa_type_key: str | None = None,
) -> dict[str, Any]:
    code, journey = visa_catalog.catalog_scope(country_code, visa_type_key)
    document_types = get_document_type_payload(db, active_only=True, country_code=code, visa_type_key=journey)
    required_document_types = [row["value"] for row in document_types if row.get("is_required")]
    stages = visa_catalog.journey_stages_for(code, journey)
    journey_stages = build_journey_stages(document_types, stages)
    return {
        "document_types": document_types,
        "required_document_types": required_document_types,
        "journey_stages": journey_stages,
    }
