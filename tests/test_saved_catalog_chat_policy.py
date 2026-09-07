"""Keep catalog recommendations on the saved-data path without changing interviews."""
from types import SimpleNamespace

import pytest

from app import enterprise_ai, enterprise_copilot
from app.routers import ai_chat


def student_prompt(source):
    return ai_chat.build_system_prompt(source=source, student_profile_context="Saved profile",
        documents_context="Saved documents", attached_docs_text="", navigation_guide_text="",
        visa_summary="Canada Study Permit")


@pytest.mark.parametrize("source", ["rilono_ai_chat", "rilono_ai_copilot"])
def test_b2c_chat_redirects_new_recommendations_but_keeps_existing_record_help(source):
    prompt = student_prompt(source)
    assert "This chat has no catalog lookup" in prompt
    assert "Course Finder's saved database" in prompt
    assert "You may discuss institutions and courses already in the attached profile or documents" in prompt


@pytest.mark.parametrize("source", ["mock_interview", "visa_prep"])
def test_interview_modes_do_not_receive_the_chat_redirect(source):
    prompt = student_prompt(source)
    assert "This chat has no catalog lookup" not in prompt
    assert "Ground EVERY question in the ATTACHED RAW STUDENT PROFILE FILE" in prompt


def test_crm_assistant_keeps_catalog_tools_and_no_memory_fallback():
    prompt = enterprise_ai._system_instruction("Test consultancy", "Test staff", "admin")
    assert "New university or course recommendations must use only saved catalog tool results from this turn" in prompt
    assert "If no saved results match" in prompt
    assert "never add alternatives from memory" in prompt
    assert "You may still discuss choices already recorded" in prompt


def test_both_copilots_redirect_new_shortlists_while_allowing_existing_records():
    organization = SimpleNamespace(company_name="Test consultancy")
    client = SimpleNamespace(full_name="Test client", destination_country_name="Canada",
                             destination_country_code="CA", visa_type="Study Permit")
    staff = SimpleNamespace(full_name="Test staff", email="staff@example.invalid")
    common = dict(organization=organization, client=client, profile_block="Saved profile",
                  documents_block="Saved documents", journey_block="")
    prompts = [enterprise_copilot.build_system_prompt(**common, staff_user=staff, role="admin"),
               enterprise_copilot.build_client_system_prompt(**common)]
    for prompt in prompts:
        assert "This Copilot has no catalog lookup" in prompt
        assert "Course Finder's saved database" in prompt
        assert "You may discuss choices already in the client's profile or documents" in prompt
    assert "have their consultancy use Course Finder" in prompts[1]
