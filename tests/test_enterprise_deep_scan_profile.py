"""Regression guards: Deep Scan audits documents against the WHOLE client profile.

Same 2026-08-22 gap as the assistant and the Copilot: _deep_scan_client_block claimed to
send "EVERY staff-entered profile field" but predated the intake block, so an IELTS
certificate contradicting the profile's score, a transcript contradicting the year of
passing, or a sponsor letter naming someone other than the guardian could not be flagged.
Now the block appends the shared intake lines, the per-document extraction pulls the
like-for-like facts (test scores, qualifications, addresses, sponsor/guardian names), the
audit checklist names the comparison, and the per-document facts cache is versioned so
already-scanned documents are re-extracted once under the new schema.

Run: cd web_app && python3 -m pytest tests/test_enterprise_deep_scan_profile.py
"""

import hashlib
import json
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import enterprise_ai
from app import enterprise_client_fields as client_fields
from app import models
from app.database import Base
from app.routers import enterprise as router


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    owner = models.User(email="owner@example.com", hashed_password="x", full_name="Org Owner")
    db.add(owner); db.commit()
    org = models.EnterpriseOrganization(company_name="Acme Overseas", created_by_user_id=owner.id)
    db.add(org); db.commit()
    row = models.EnterpriseClient(
        organization_id=org.id, created_by_user_id=owner.id, full_name="Dev Malhotra",
        email="dev@example.com", phone="+91 98765 43210", current_city="Mumbai", nationality="Indian",
        date_of_birth=date(2002, 5, 14), passport_number="N1234567", guardian_name="Rakesh Malhotra",
        guardian_relation="father", visa_category="student", destination_country_code="AE",
        destination_country_name="United Arab Emirates", visa_type="Student Visa", intake="Sep 2026",
        study_level="masters", highest_qualification="bachelors_4yr", qualification_score="8.1",
        qualification_scale="cgpa_10", year_of_passing=2024, english_test_status="score_available",
        english_test_type="ielts_academic", english_test_score="7.5", budget_band="15_25l",
        funding_source="loan_sanctioned", lead_source="google_ads", status="documents", priority="high",
    )
    db.add(row); db.commit()
    try:
        yield row
    finally:
        db.close()


def test_deep_scan_profile_block_carries_the_intake_fields(client):
    block = enterprise_ai._deep_scan_client_block(client)
    for needle in (
        "Full name: Dev Malhotra", "Passport number: N1234567",          # core fields unchanged
        "Current city: Mumbai", "Guardian name: Rakesh Malhotra",
        f"Guardian relation: {client_fields.choice_label('guardian_relation', 'father')}",
        "English test score: 7.5", "Year of passing: 2024", "Qualification score: 8.1",
        f"Funding source: {client_fields.choice_label('funding_source', 'loan_sanctioned')}",
        f"Budget band: {client_fields.choice_label('budget_band', '15_25l')}",
        f"Lead source (staff): {client_fields.choice_label('lead_source', 'google_ads')}",
    ):
        assert needle in block, needle


def test_every_intake_field_the_client_screen_tracks_reaches_deep_scan(client):
    expected = set(router._CLIENT_INTAKE_TEXT_FIELDS) | set(router._CLIENT_INTAKE_CHOICE_FIELDS)
    expected |= {f for f, _l in router._CLIENT_INTAKE_DATE_FIELDS}
    expected |= {f for f, _l, _lo, _hi in router._CLIENT_INTAKE_INT_FIELDS}
    expected.discard("branch_name")
    keys = {k for k, _line in enterprise_ai._intake_profile_lines(client)}
    missing = sorted(expected - keys)
    assert not missing, f"intake fields on the client screen but invisible to Deep Scan: {missing}"
    # blanks are rendered, as '—', never dropped (the auditor is told '—' = not filled in)
    client.current_city = None
    block = enterprise_ai._deep_scan_client_block(client)
    assert "Current city: —" in block
    # an unticked consent box is "not recorded", never "no" (which read as a refusal)
    assert "Consent to share with institutions: not recorded" in block
    import inspect
    assert "not a refusal and never critical" in inspect.getsource(enterprise_ai.run_deep_scan_audit)


def test_extraction_schema_pulls_like_for_like_facts():
    schema = enterprise_ai._DEEP_SCAN_FACTS_SCHEMA
    for key in ('"test_scores"', '"qualifications"', '"addresses"', '"sponsor_or_guardian_names"'):
        assert key in schema, key
    # and the audit is told to compare them against the profile's intake fields
    import inspect
    src = inspect.getsource(enterprise_ai.run_deep_scan_audit)
    assert "Academic & background consistency" in src
    assert "test_scores" in src and "sponsor_or_guardian_names" in src


def test_facts_cache_is_versioned_so_old_extractions_are_redone_once(monkeypatch):
    """A document extracted under the old schema (hash of text only) must be re-extracted;
    one extracted under the current version is reused."""
    calls = []
    monkeypatch.setattr(enterprise_ai, "_extract_document_facts",
                        lambda doc, model_state: calls.append(doc) or {"document_type": "x", "test_scores": []})
    text = "IELTS Test Report Form — Overall Band 6.5"
    old_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    stale = SimpleNamespace(extracted_text=text, deep_scan_facts_hash=old_hash,
                            deep_scan_facts=json.dumps({"document_type": "old"}), document_type="IELTS")
    facts, status = enterprise_ai._facts_for_document(stale, {})
    assert status == "extracted" and facts["document_type"] == "x" and len(calls) == 1
    assert stale.deep_scan_facts_hash != old_hash                      # re-keyed under the new version
    # second pass: same text, current-version hash -> cached, no extraction call
    facts, status = enterprise_ai._facts_for_document(stale, {})
    assert status == "cached" and len(calls) == 1
    # the version is part of the key, so bumping it would invalidate again
    assert enterprise_ai._DEEP_SCAN_FACTS_VERSION in ("2",) or enterprise_ai._DEEP_SCAN_FACTS_VERSION.isdigit()
