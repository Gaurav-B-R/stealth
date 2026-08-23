"""Course Finder AI shortlist: a subject area (catalog discipline bucket) is required.

2026-08-22: "House Wife" typed into the free-text Field of study produced a polished,
meaningless 5-credit shortlist. Both forms now make Subject area the required primary
input (pre-filled from the client's profile) and demote the text box to "Specific course
or specialisation (optional)"; this pins the matching server-side rule in
app/routers/enterprise.py::_course_finder_subject_or_400 so API callers can't bypass it.

Run: cd web_app && python3 -m pytest tests/test_course_finder_subject_rule.py
"""

import pytest
from fastapi import HTTPException

from app import course_catalog
from app.routers.enterprise import _course_finder_subject_or_400 as rule


def test_a_picked_subject_area_is_accepted_with_or_without_free_text():
    assert rule("Computer Science & IT", "") == ("Computer Science & IT", "")
    assert rule("Computer Science & IT", "Machine Learning") == ("Computer Science & IT", "Machine Learning")
    assert rule("Other", "Circus studies") == ("Other", "Circus studies")       # explicit Other is a choice
    assert rule("psychology", "") == ("Psychology", "")                          # case-insensitive label
    for bucket in course_catalog.DISCIPLINES:
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
