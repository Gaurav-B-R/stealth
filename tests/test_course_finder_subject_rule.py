"""AI shortlists: a subject area (catalog discipline bucket) is required — every surface.

2026-08-22: "House Wife" typed into the free-text Field of study produced a polished,
meaningless 5-credit shortlist. Both forms now make Subject area the required primary
input (pre-filled from the client's profile) and demote the text box to "Specific course
or specialisation (optional)"; this pins the matching server-side rule in
course_catalog.resolve_subject, applied by the enterprise Course Finder and the B2C Course
Finder (/api/courses/recommend), so API callers can't bypass what the forms enforce.

Run: cd web_app && python3 -m pytest tests/test_course_finder_subject_rule.py
"""

import pytest
from fastapi import HTTPException

from app import course_catalog
from app.routers.enterprise import _course_finder_subject_or_400 as rule


def test_a_picked_subject_area_is_accepted_with_or_without_free_text():
    assert rule("Computer Science & IT", "") == ("Computer Science & IT", "")
    assert rule("Computer Science & IT", "Machine Learning") == ("Computer Science & IT", "Machine Learning")
    assert rule("Other", "Circus studies") == ("Other", "Circus studies")       # explicit Other + the specific course
    with pytest.raises(HTTPException) as e:
        rule("Other", "")                                                        # "Other" alone tells the model nothing
    assert "Other" in e.value.detail
    assert rule("psychology", "") == ("Psychology", "")                          # case-insensitive label
    for bucket in course_catalog.DISCIPLINES:
        if bucket == "Other":
            continue                                                             # needs the specific course (below)
        assert rule(bucket, "")[0] == bucket


def test_free_text_alone_is_rejected_unless_it_maps_to_a_real_bucket():
    assert rule("", "Psychology") == ("Psychology", "Psychology")                # maps cleanly
    assert rule("", "engineering") == ("Engineering", "engineering")
    with pytest.raises(HTTPException) as e:
        rule("", "House Wife")                                                   # the incident
    assert e.value.status_code == 400 and "subject area" in e.value.detail
    with pytest.raises(HTTPException):
        rule("", "Machine Learning")                                             # legit, but no bucket given
    with pytest.raises(HTTPException):
        rule("", "")
    with pytest.raises(HTTPException):
        rule(None, None)


def test_unknown_subject_area_is_rejected_not_silently_bucketed_as_other():
    with pytest.raises(HTTPException) as e:
        rule("Astrology & Tarot", "")
    assert e.value.status_code == 400 and "Astrology & Tarot" in e.value.detail


def test_every_surface_applies_the_same_rule():
    """One resolver, two routers: the B2C Course Finder must reject the same inputs the
    enterprise endpoint rejects, with a 400 (not a silent shortlist)."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.routers import courses
    from app.auth import get_current_active_user
    from app.database import get_db
    from types import SimpleNamespace

    with pytest.raises(ValueError):
        course_catalog.resolve_subject("", "House Wife")
    assert course_catalog.resolve_subject("Engineering", "Robotics") == ("Engineering", "Robotics")

    app = FastAPI()
    app.include_router(courses.router)
    fake_user = SimpleNamespace(id=1, email="s@example.com", destination_country_code="AU", current_residence_country="India")
    app.dependency_overrides[get_current_active_user] = lambda: fake_user
    app.dependency_overrides[get_db] = lambda: None
    client = TestClient(app)
    # The endpoint hits the rule before any model call / quota / rate-limit state is
    # needed — the rejection must come back as a clean 400 with the shared message.
    for path in ("/api/courses/recommend",):
        r = client.post(path, json={"field_of_study": "House Wife", "country_code": "AU"})
        assert r.status_code == 400, (path, r.status_code, r.text)
        assert "subject area" in r.json()["detail"], (path, r.text)


def test_budget_must_be_a_positive_amount_but_real_formats_pass():
    nb = course_catalog.normalize_budget
    assert nb("") is None and nb(None) is None and nb("   ") is None
    for ok in ("30000", "£22,000", "USD 40k", "USD 40,000", "₹15–25 L / year", "2 lakh", "A$35,000", "€12,000 per year", "15-25 lakhs"):
        assert nb(ok) == " ".join(ok.split()), ok
    for bad in ("-10000", "−5000", "abc", "ten thousand", "30000abc", "0", "£0", "999999999999", "e.g. 30000", "30000; drop table"):
        with pytest.raises(ValueError, match="budget|Budget"):
            nb(bad)


def test_budget_rule_is_enforced_by_the_b2c_endpoint_before_any_spend():
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.routers import courses
    from app.auth import get_current_active_user
    from app.database import get_db
    from types import SimpleNamespace
    app = FastAPI(); app.include_router(courses.router)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id=1, email="s@example.com", destination_country_code="UK", current_residence_country="India")
    app.dependency_overrides[get_db] = lambda: None
    r = TestClient(app).post("/api/courses/recommend", json={"discipline": "Engineering", "budget": "-10000", "country_code": "UK"})
    assert r.status_code == 400 and "negative" in r.json()["detail"]


def test_catalog_filters_drop_nonsense_numbers_instead_of_clamping_them():
    nf = course_catalog.normalize_catalog_filters
    out = nf({"min_tuition": "-10000", "max_tuition": "-5", "max_toefl": "-5", "max_qs_rank": "0", "max_duration_months": "-1"})
    for key in ("min_tuition", "max_tuition", "max_toefl", "max_qs_rank", "max_duration_months"):
        assert key not in out, key                                    # nonsense is ignored, never applied
    out = nf({"max_tuition": "99999999999", "max_toefl": "250", "min_tuition": "5000"})
    assert out["max_tuition"] == 10_000_000 and out["max_toefl"] == 120 and out["min_tuition"] == 5000
    assert nf({"max_toefl": "95", "max_ielts": "6.5"}) == {"max_toefl": 95, "max_ielts": 6.5}
    assert "max_ielts" not in nf({"max_ielts": "-6.5"}) and "max_ielts" not in nf({"max_ielts": "12"})
