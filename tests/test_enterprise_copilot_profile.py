"""Regression guards: the Copilot (Chrome extension + client invite link) must see the
WHOLE client profile, with the invite-link surface withholding staff-internal data.

Same 2026-08-22 gap as the dashboard assistant: build_client_profile_block sent only the
core case fields, so the Copilot — whose job is to help fill applications from the CRM
record — could not see current city, guardian, academics, test scores, budget/funding or
prior refusals. The block is now built from the client API's own intake serializer (via
enterprise_ai._client_intake_profile), so a field added to the client screen reaches the
Copilot without a second edit.

Run: cd web_app && python3 -m pytest tests/test_enterprise_copilot_profile.py
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import enterprise_copilot as copilot
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
        organization_id=org.id, created_by_user_id=owner.id,
        full_name="Dev Malhotra", email="dev@example.com", phone="+91 98765 43210",
        whatsapp_number="+91 98765 43210", current_city="Mumbai", gender="male", nationality="Indian",
        date_of_birth=date(2002, 5, 14), passport_number="N1234567", passport_expiry=date(2031, 1, 1),
        guardian_name="Rakesh Malhotra", guardian_relation="father", guardian_phone="+91 91234 56789",
        visa_category="student", destination_country_code="AE", destination_country_name="United Arab Emirates",
        visa_type="Student Visa", intake="Sep 2026", study_level="masters", field_of_study="Computer Science",
        highest_qualification="bachelors_4yr", qualification_score="8.1", qualification_scale="cgpa_10",
        year_of_passing=2024, backlogs_count=0, english_test_status="score_available",
        english_test_type="ielts_academic", english_test_score="7.5", budget_band="15_25l",
        funding_source="loan_planning", prior_refusal_history="none", prior_refusal_notes="internal: refused in 2019",
        lead_source="google_ads", lead_source_detail="Spring campaign", branch_name="Head Office",
        next_followup_date=date(2026, 9, 3), status="shortlisting", priority="high",
        marketing_consent_channels="whatsapp,email",
    )
    db.add(row); db.commit()
    try:
        yield row
    finally:
        db.close()


def test_staff_block_carries_the_full_profile(client):
    block = copilot.build_client_profile_block(client, allow_sensitive=True)
    for needle in (
        "Current city: Mumbai", "WhatsApp number: +91 98765 43210", "Guardian name: Rakesh Malhotra",
        f"Guardian relation: {client_fields.choice_label('guardian_relation', 'father')}",
        f"Study level: {client_fields.choice_label('study_level', 'masters')}",
        "Field of study: Computer Science", "English test score: 7.5",
        f"English test: {client_fields.choice_label('english_test_type', 'ielts_academic')}",
        f"Funding source: {client_fields.choice_label('funding_source', 'loan_planning')}",
        f"Lead source (staff): {client_fields.choice_label('lead_source', 'google_ads')}",
        "Prior refusal notes (staff): internal: refused in 2019",
        "Next follow-up date (staff): 2026-09-03", "Office / branch: Head Office",
        "Passport number: N1234567", "Priority: high",
    ):
        assert needle in block, needle
    # choice fields are labels, not stored keys
    assert "ielts_academic" not in block and "loan_planning" not in block


def test_client_link_block_has_own_profile_but_not_staff_internals(client):
    block = copilot.build_client_profile_block(client, for_client=True)
    for needle in ("Current city: Mumbai", "Guardian name: Rakesh Malhotra", "English test score: 7.5",
                   "Field of study: Computer Science", "Passport number (masked for security): •••• 567"):
        assert needle in block, needle
    for withheld in ("Lead source", "Spring campaign", "refused in 2019", "Next follow-up", "Priority",
                     "consent", "Office / branch", "N1234567"):
        assert withheld not in block, withheld


def test_staff_without_sensitive_capability_still_gets_the_profile(client):
    block = copilot.build_client_profile_block(client, allow_sensitive=False)
    assert "N1234567" not in block and "withheld" in block
    assert "Current city: Mumbai" in block and "Guardian name: Rakesh Malhotra" in block


def test_every_intake_field_the_client_screen_tracks_reaches_the_copilot(client):
    """Drift guard tied to the UI field lists, same as the assistant's."""
    expected = set(router._CLIENT_INTAKE_TEXT_FIELDS) | set(router._CLIENT_INTAKE_CHOICE_FIELDS)
    expected |= {f for f, _l in router._CLIENT_INTAKE_DATE_FIELDS}
    expected |= {f for f, _l, _lo, _hi in router._CLIENT_INTAKE_INT_FIELDS}
    expected.discard("branch_name")  # rendered as "Office / branch" from the core block (staff only)
    staff_keys = {k for k, _line in copilot._intake_profile_lines(client, for_client=False)}
    missing = sorted(expected - staff_keys)
    assert not missing, f"intake fields on the client screen but invisible to the Copilot: {missing}"
    client_keys = {k for k, _line in copilot._intake_profile_lines(client, for_client=True)}
    assert client_keys == staff_keys - copilot._STAFF_ONLY_PROFILE_FIELDS


def test_blank_fields_render_as_dash_and_prompts_explain_it(client):
    client.current_city = None
    block = copilot.build_client_profile_block(client)
    assert "Current city: —" in block
    org = models.EnterpriseOrganization(company_name="Acme Overseas", created_by_user_id=1)
    staff = models.User(email="s@example.com", hashed_password="x", full_name="Staff")
    staff_prompt = copilot.build_system_prompt(organization=org, staff_user=staff, role="admin", client=client,
                                               profile_block=block, documents_block="", journey_block="")
    client_prompt = copilot.build_client_system_prompt(organization=org, client=client, profile_block=block,
                                                       documents_block="", journey_block="")
    assert 'shown as "—"' in staff_prompt and 'shown as "—"' in client_prompt
    assert "Current city: —" in staff_prompt
