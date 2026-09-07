"""Catalog recommendations may rank saved rows but cannot research or invent facts."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import ai_usage, course_catalog as catalog, models
from app.utils import gemini_service


def saved_rows():
    university = models.CourseCatalogUniversity(
        id=7, name="Saved University", country_code="US", city="Saved City", qs_world_rank="101",
        website_url="https://saved.example.edu", is_active=True,
    )
    course = models.CourseCatalogCourse(
        id=12, university_id=7, course_name="Saved Computing MSc", degree_level="masters",
        discipline="engineering_technology", annual_tuition="USD 20,000", tuition_amount=20000,
        tuition_currency="USD", duration="24 months", intakes='["Fall"]', application_fee="USD 50",
        ielts_requirement="6.5", toefl_requirement="90", gre_gmat_requirement="Not required",
        entry_requirements="Recorded bachelor's degree requirement",
        course_url="https://saved.example.edu/computing", is_active=True,
    )
    return [(university, [course])]


@pytest.fixture
def no_research(monkeypatch):
    network = Mock(side_effect=AssertionError("Recommendation must not access the internet"))
    monkeypatch.setattr(catalog, "ai_available", lambda: True)
    monkeypatch.setattr(catalog, "probe_urls", network)
    monkeypatch.setattr(catalog, "_grounded_generate", network)
    monkeypatch.setattr(gemini_service, "get_genai_client", network)
    return network


def reply(monkeypatch, items, **extra):
    generate = Mock(return_value=({"recommendations": items, **extra}, False, [], set(), "gemini-2.5-pro"))
    monkeypatch.setattr(catalog, "_generate_json", generate)
    return generate


def test_empty_saved_catalog_never_calls_ai_even_if_configured(no_research, monkeypatch):
    generate = reply(monkeypatch, [])
    result = catalog.recommend_courses(destination_country="United States", catalog_rows=[])
    assert result["available"] and result["no_matches"]
    assert result["recommendations"] == [] and result["grounded"] is False
    generate.assert_not_called()
    no_research.assert_not_called()


def test_thin_catalog_only_ranks_saved_ids_and_copies_all_facts(no_research, monkeypatch):
    rows = saved_rows()
    generate = reply(monkeypatch, [{
        "catalog_course_id": "12", "fit_level": "safety", "university_name": "Invented University",
        "course_name": "Invented Course", "annual_tuition": "FREE", "application_fee": "FREE",
        "key_requirements": ["No qualifications"], "intakes": "Every month", "location": "Invented City",
        "course_url": "https://invented.example", "website_url": "https://invented.example",
        "why_recommended": "An invented guarantee", "qs_world_rank": "1",
    }], summary="Invented fee and scholarship claims")
    monkeypatch.setattr(catalog, "RECOMMEND_MIN_CATALOG_ROWS", 500)
    result = catalog.recommend_courses(destination_country="United States", catalog_rows=rows, for_student=True)
    selected, = result["recommendations"]
    assert result["grounded"] is False and result["catalog_based"] is True
    assert selected["university_name"] == "Saved University"
    assert selected["course_name"] == "Saved Computing MSc"
    assert selected["annual_tuition"] == "USD 20,000"
    assert selected["application_fee"] == "USD 50"
    assert selected["intakes"] == "Fall" and selected["location"] == "Saved City"
    assert selected["qs_world_rank"] == "101"
    assert selected["course_url"] == "https://saved.example.edu/computing"
    assert selected["website_url"] == "https://saved.example.edu"
    assert selected["key_requirements"] == ["IELTS: 6.5", "TOEFL: 90", "GRE / GMAT: Not required", "Recorded bachelor's degree requirement"]
    assert "Invented" not in json.dumps(result) and "guarantee" not in json.dumps(result)
    assert generate.call_args.kwargs["prefer_grounded"] is False
    no_research.assert_not_called()


def test_outside_catalog_and_duplicate_ids_are_rejected(no_research, monkeypatch):
    reply(monkeypatch, [{"catalog_course_id": "999", "university_name": "Invented"},
                       {"catalog_course_id": True}, {"catalog_course_id": 12}, {"catalog_course_id": "12"}])
    result = catalog.recommend_courses(destination_country="US", catalog_rows=saved_rows())
    assert [row["catalog_course_id"] for row in result["recommendations"]] == [12]
    no_research.assert_not_called()


def test_selection_outside_prompted_context_is_rejected(no_research, monkeypatch):
    rows = saved_rows()
    later = models.CourseCatalogCourse(id=13, university_id=7, course_name="Another saved course", is_active=True)
    rows[0][1].append(later)
    monkeypatch.setattr(catalog, "RECOMMEND_CONTEXT_COURSES", 1)
    reply(monkeypatch, [{"catalog_course_id": "13"}])
    result = catalog.recommend_courses(destination_country="US", catalog_rows=rows)
    assert result["available"] is False and not result["recommendations"]


def test_inactive_rows_never_become_recommendations(no_research, monkeypatch):
    rows = saved_rows()
    rows[0][1][0].is_active = False
    generate = reply(monkeypatch, [{"catalog_course_id": "12"}])
    result = catalog.recommend_courses(destination_country="US", catalog_rows=rows)
    assert result["no_matches"] and not result["recommendations"]
    generate.assert_not_called()


def test_missing_database_values_stay_missing(no_research, monkeypatch):
    rows = saved_rows()
    rows[0][1][0].annual_tuition = None
    rows[0][1][0].application_fee = None
    rows[0][1][0].entry_requirements = None
    reply(monkeypatch, [{"catalog_course_id": "12", "annual_tuition": "USD 1000", "application_fee": "USD 1"}])
    selected, = catalog.recommend_courses(destination_country="US", catalog_rows=rows)["recommendations"]
    assert selected["annual_tuition"] is None and selected["application_fee"] is None


@pytest.mark.parametrize("account,source", [
    ({"user_id": 42, "product": "b2c", "trigger": "user"}, "course_finder"),
    ({"organization_id": 6, "product": "b2b", "trigger": "user"}, "enterprise_course_finder"),
])
def test_tool_free_ranking_preserves_actual_usage_attribution(monkeypatch, account, source):
    events = []
    response = SimpleNamespace(text='{"recommendations":[{"catalog_course_id":"12"}]}',
                               model_version="gemini-2.5-pro", usage_metadata={
                                   "promptTokenCount": 10, "candidatesTokenCount": 2,
                                   "totalTokenCount": 12})
    generate = Mock(return_value=response)
    monkeypatch.setattr(gemini_service, "USE_VERTEX_AI", False)
    monkeypatch.setattr(gemini_service, "GENAI_AVAILABLE", True)
    monkeypatch.setattr(gemini_service, "genai", SimpleNamespace(GenerativeModel=lambda name: SimpleNamespace(generate_content=generate)))
    monkeypatch.setattr(catalog, "_model_candidates", lambda: ["gemini-2.5-pro"])
    monkeypatch.setattr(ai_usage, "_write_event", lambda event: events.append(dict(event)) or True)
    token = ai_usage.set_usage_account(**account)
    try:
        data, grounded, urls, domains, model = catalog._generate_json("Offline catalog", source, prefer_grounded=True)
    finally:
        ai_usage.reset_usage_account(token)
    assert data["recommendations"] and not grounded and not urls and not domains
    assert model == "gemini-2.5-pro"
    assert events[-1]["source"] == source and events[-1]["product"] == account["product"]
    assert events[-1]["user_id"] == account.get("user_id")
    assert events[-1]["organization_id"] == account.get("organization_id")
    assert events[-1]["total_tokens"] == 12
    assert "tools" not in generate.call_args.kwargs


def test_catalog_discovery_and_refresh_do_not_touch_ai_network_or_database(monkeypatch):
    database, university = Mock(), Mock()
    generate = Mock(side_effect=AssertionError("Automatic AI updates must remain disabled"))
    monkeypatch.setattr(catalog, "_generate_json", generate)
    monkeypatch.setattr(catalog, "GROUNDING_ENABLED", True)
    assert catalog.discover_universities(database, "US", 100) == 0
    with pytest.raises(RuntimeError, match="disabled"):
        catalog.refresh_university(database, university)
    assert not database.mock_calls and not university.mock_calls
    generate.assert_not_called()


def test_explicit_no_fit_response_is_honest_empty_result(no_research, monkeypatch):
    reply(monkeypatch, [])
    result = catalog.recommend_courses(destination_country="US", catalog_rows=saved_rows())
    assert result["available"] and result["no_matches"]
    assert result["recommendations"] == []


def test_invalid_model_response_is_failure_not_a_claim_of_no_catalog_matches(no_research, monkeypatch):
    monkeypatch.setattr(catalog, "_generate_json", lambda *args, **kwargs: (None, False, [], set(), "test"))
    result = catalog.recommend_courses(destination_country="US", catalog_rows=saved_rows())
    assert result["available"] is False and not result["recommendations"]
