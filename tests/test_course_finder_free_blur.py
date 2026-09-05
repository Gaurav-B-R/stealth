"""Course Finder free tier: only the first picks of an AI shortlist are delivered in full.

2026-09-03: free accounts see the first FREE_COURSE_FINDER_VISIBLE_RESULTS picks and a
blurred card + Visa-Pass CTA for each later one. The blur is cosmetic; the gate is
server-side — a hidden pick's name, fees, requirements and URLs never leave the API, and
the save-to-shortlist route refuses hidden indexes — so devtools cannot lift it. Masking
is applied at read time, so buying the pass unlocks a student's earlier shortlists.

Run: cd web_app && python3 -m pytest tests/test_course_finder_free_blur.py
"""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import subscriptions as subs
from app import visa_pass
from app.auth import get_current_active_user
from app.database import get_db
from app.routers import courses


def _pick(i):
    return {
        "fit_level": ["match", "safety", "reach"][i % 3],
        "course_name": f"Course {i}", "university_name": f"University {i}", "location": f"City {i}",
        "annual_tuition": f"AUD {40000 + i}", "why_recommended": f"secret rationale {i}",
        "key_requirements": [f"secret requirement {i}"], "website_url": f"https://u{i}.example",
        "course_url": f"https://u{i}.example/course", "qs_world_rank": 10 + i, "in_catalog": True,
    }


def _row(n=6):
    return SimpleNamespace(
        id=7, user_id=1, country_code="AU", degree_level="masters", discipline="Data Science & AI",
        query=json.dumps({"field_of_study": "Data Science"}), summary="overview",
        recommendations=json.dumps([_pick(i) for i in range(n)]),
        catalog_based=True, grounded=False, created_at=datetime(2026, 9, 3),
    )


FREE_SUB = SimpleNamespace(plan="free", status=subs.STATUS_ACTIVE, ends_at=None, course_finder_runs_used=1)
PERPETUAL_SUB = SimpleNamespace(plan=subs.PLAN_PRO, status=subs.STATUS_ACTIVE, ends_at=None, course_finder_runs_used=0)
PASS_SUB = SimpleNamespace(plan=subs.PLAN_PRO, status=subs.STATUS_ACTIVE,
                           ends_at=datetime.utcnow() + timedelta(days=10), course_finder_runs_used=1)
EXPIRED_SUB = SimpleNamespace(plan=subs.PLAN_PRO, status=subs.STATUS_ACTIVE,
                              ends_at=datetime.utcnow() - timedelta(days=1), course_finder_runs_used=1)


class _Query:
    def __init__(self, rows): self.rows = rows
    def filter(self, *a, **k): return self
    def order_by(self, *a, **k): return self
    def limit(self, n): return self
    def first(self): return self.rows[0] if self.rows else None
    def all(self): return list(self.rows)


class _DB:
    """Only the Course Finder rows are real; everything else queries empty."""
    def __init__(self, rows): self.rows = rows
    def query(self, model):
        from app import models
        return _Query(self.rows if model is models.UserCourseFinderRec else [])
    def add(self, *a): pass
    def commit(self): pass
    def refresh(self, *a): pass
    def rollback(self): pass


def _client(monkeypatch, sub, rows):
    app = FastAPI()
    app.include_router(courses.router)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(
        id=1, email="s@example.com", destination_country_code="AU", current_residence_country="India")
    app.dependency_overrides[get_db] = lambda: _DB(rows)
    monkeypatch.setattr(courses, "get_or_create_user_subscription", lambda db, uid: sub)
    return TestClient(app, raise_server_exceptions=False)


def _hidden_fields_absent(item):
    assert item == {"locked": True, "fit_level": item["fit_level"]}, item
    assert item["fit_level"] in {"reach", "match", "safety", None}


def test_free_tier_gets_only_the_visible_window_in_full():
    visible = visa_pass.FREE_COURSE_FINDER_VISIBLE_RESULTS
    assert visible == 2                                            # the product dial as shipped
    data = courses._serialize_rec(_row(6), reveal_all=False)
    items = data["recommendations"]
    assert len(items) == 6 and data["count"] == 6 and data["locked_count"] == 4
    for i, it in enumerate(items):
        if i < visible:
            assert it["university_name"] == f"University {i}"      # real pick, untouched
        else:
            _hidden_fields_absent(it)                              # nothing to un-blur
    # Nothing identifying about a hidden pick survives serialisation.
    dumped = json.dumps(items[visible:])
    for i in range(visible, 6):
        for leak in (f"University {i}", f"Course {i}", f"secret rationale {i}", f"secret requirement {i}", f"u{i}.example"):
            assert leak not in dumped, leak


def test_pass_holders_and_history_rows_are_untouched():
    full = courses._serialize_rec(_row(6), reveal_all=True)
    assert full["locked_count"] == 0 and all("locked" not in it for it in full["recommendations"])
    summary = courses._serialize_rec(_row(6), include_items=False, reveal_all=False)
    assert "recommendations" not in summary and summary["count"] == 6 and summary["locked_count"] == 4


def test_masking_is_decided_at_read_time_by_the_current_pass(monkeypatch):
    rows = [_row(6)]
    free = _client(monkeypatch, FREE_SUB, rows).get("/api/courses/recs/7").json()["rec"]
    assert free["locked_count"] == 4 and free["recommendations"][5] == {"locked": True, "fit_level": "reach"}
    unlocked = _client(monkeypatch, PASS_SUB, rows).get("/api/courses/recs/7").json()["rec"]
    assert unlocked["locked_count"] == 0 and unlocked["recommendations"][5]["university_name"] == "University 5"
    perpetual = _client(monkeypatch, PERPETUAL_SUB, rows).get("/api/courses/recs/7").json()["rec"]
    assert perpetual["locked_count"] == 0 and perpetual["summary"] == "overview"
    # The same stored row locks again once the pass lapses.
    relocked = _client(monkeypatch, EXPIRED_SUB, rows).get("/api/courses/recs/7").json()["rec"]
    assert relocked["locked_count"] == 4 and "university_name" not in relocked["recommendations"][2]
    listing = _client(monkeypatch, FREE_SUB, rows).get("/api/courses/recs").json()["recs"][0]
    assert listing["locked_count"] == 4 and "recommendations" not in listing


def test_save_route_refuses_a_hidden_index_on_the_free_plan(monkeypatch):
    rows = [_row(6)]
    r = _client(monkeypatch, FREE_SUB, rows).post("/api/courses/recs/7/save", json={"index": 2})
    assert r.status_code == 402 and "Visa Success Pass" in r.json()["detail"]
    r = _client(monkeypatch, FREE_SUB, rows).post("/api/courses/recs/7/save", json={"index": 5})
    assert r.status_code == 402
    # A visible pick is still saveable on the free plan; a pass holder can save any pick.
    assert _client(monkeypatch, FREE_SUB, rows).post("/api/courses/recs/7/save", json={"index": 1}).status_code != 402
    assert _client(monkeypatch, PASS_SUB, rows).post("/api/courses/recs/7/save", json={"index": 5}).status_code != 402
    # Out-of-range stays a 400 for everyone — the gate never turns a bad index into a paywall.
    assert _client(monkeypatch, FREE_SUB, rows).post("/api/courses/recs/7/save", json={"index": 9}).status_code == 400


def test_summary_and_visible_prose_cannot_name_hidden_picks():
    """The overview and a visible pick's reasoning are written in the same model call as
    the hidden picks and can name them — and the student's notes reach that prompt
    verbatim, so "compare every university in pick 1" is a one-run bypass. Free tier
    therefore gets no summary while picks are hidden, and hidden university names are
    scrubbed from the picks it does get."""
    row = _row(6)
    row.summary = "We paired University 0 with University 4 and The University 5 as ambitious picks."
    items = json.loads(row.recommendations)
    items[0]["why_recommended"] = "Cheaper than University 3 and university 5; the same course as University 1."
    items[0]["key_requirements"] = ["Similar bar to The University 4", "IELTS 6.5"]
    row.recommendations = json.dumps(items)

    data = courses._serialize_rec(row, reveal_all=False)
    assert data["summary"] is None
    dumped = json.dumps(data)
    for i in range(2, 6):
        assert f"University {i}" not in dumped and f"university {i}" not in dumped, i
    pick0 = data["recommendations"][0]
    assert pick0["why_recommended"] == "Cheaper than another university and another university; the same course as University 1."
    assert pick0["key_requirements"] == ["Similar bar to another university", "IELTS 6.5"]
    assert pick0["course_name"] == "Course 0"                          # the pick's own fields are untouched

    full = courses._serialize_rec(row, reveal_all=True)                # pass holders: verbatim
    assert full["summary"].startswith("We paired") and "University 3" in full["recommendations"][0]["why_recommended"]
    # With nothing hidden there is nothing to withhold — a 2-pick run keeps its summary.
    assert courses._serialize_rec(_row(2), reveal_all=False)["summary"] == "overview"


def test_edge_rows_and_the_fail_closed_signature():
    for n, locked in ((0, 0), (1, 0), (2, 0), (3, 1), (8, 6)):
        d = courses._serialize_rec(_row(n), reveal_all=False)
        assert (d["count"], d["locked_count"]) == (n, locked), n
    bad = _row(6); bad.recommendations = "{not json"
    d = courses._serialize_rec(bad, reveal_all=False)
    assert (d["count"], d["locked_count"], d["recommendations"]) == (0, 0, [])
    with pytest.raises(TypeError):
        courses._serialize_rec(_row(6))                                # reveal_all is deliberately required


def test_clients_can_disclose_the_partial_reveal_before_a_run():
    ent = visa_pass.feature_entitlement(FREE_SUB, "course_finder")
    assert ent["free_visible_results"] == visa_pass.FREE_COURSE_FINDER_VISIBLE_RESULTS
    assert "free_visible_results" not in visa_pass.feature_entitlement(FREE_SUB, "sop_generator")


def test_assistant_guide_matches_the_dial():
    """USER_NAVIGATION_GUIDE.md is injected verbatim into the B2C assistant; pin its number
    to the constant so an env change can't leave the AI teaching a stale limit."""
    from pathlib import Path
    guide = (Path(courses.__file__).resolve().parents[1] / "prompts" / "USER_NAVIGATION_GUIDE.md").read_text()
    assert f"first {visa_pass.FREE_COURSE_FINDER_VISIBLE_RESULTS} picks" in guide
