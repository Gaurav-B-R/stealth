"""Regression guards: the enterprise AI Assistant must see the WHOLE client profile.

2026-08-22 incident: asked "What is the current city of Dev Malhotra?", the assistant
answered "I don't have information about their current city in the client details" —
even though `EnterpriseClient.current_city` exists and the client screen shows it. The
assistant only sees what its tools return, and `get_client_details` returned a hand-typed
subset written before the intake block (~25 columns: WhatsApp, city, gender, guardian,
academics, test scores, budget, lead source, follow-up…) was added to the model. The UI
serializer was extended; the AI tool was not. Nothing tested the tool payload, so it
drifted silently.

These tests pin the fix in app/enterprise_ai.py:

1. `get_client_details` returns every intake field the client screen tracks (derived from
   the router's own `_serialize_client_intake` field lists, so UI and AI cannot drift again),
   plus date of birth / visa category, with choice fields as human labels.
2. Every column on EnterpriseClient is either exposed by `get_client_details` or listed here
   as deliberately internal — a new column fails the build until it is classified.
3. Passport stays gated on `clients.view_sensitive` (the profile must not widen that).
4. `count_clients` and `search_clients` accept the SAME filter set (a parameter only one
   accepted used to raise TypeError mid-turn), and the new profile filters actually filter.
5. The full-profile payload fits under the tool-result cap, so it is never truncated.

Run: cd web_app && python3 -m pytest tests/test_enterprise_ai_client_profile.py
"""

import inspect
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import enterprise_access as access
from app import enterprise_ai
from app import enterprise_catalog as catalog
from app import enterprise_client_fields as client_fields
from app import models
from app.database import Base
from app.routers import enterprise as router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def org(db):
    owner = models.User(email="owner@example.com", hashed_password="x", full_name="Org Owner")
    db.add(owner)
    db.commit()
    organization = models.EnterpriseOrganization(company_name="Acme Overseas", created_by_user_id=owner.id)
    db.add(organization)
    db.commit()
    return organization


def _client(db, org, **overrides) -> models.EnterpriseClient:
    fields = dict(
        organization_id=org.id,
        created_by_user_id=org.created_by_user_id,
        full_name="Dev Malhotra",
        email="dev@example.com",
        phone="+91 98765 43210",
        whatsapp_number="+91 98765 43210",
        current_city="Mumbai",
        gender="male",
        nationality="Indian",
        date_of_birth=date(2002, 5, 14),
        passport_number="N1234567",
        passport_expiry=date(2031, 1, 1),
        guardian_name="Rakesh Malhotra",
        guardian_relation="father",
        guardian_phone="+91 91234 56789",
        visa_category="student",
        destination_country_code="AE",
        destination_country_name="United Arab Emirates",
        visa_type="Student Visa",
        intake="Sep 2026",
        application_reference="APP-001",
        study_level="masters",
        field_of_study="Computer Science",
        admission_stage="shortlisting",
        prior_refusal_history="none",
        highest_qualification="bachelors_4yr",
        qualification_score="8.1",
        qualification_scale="cgpa_10",
        year_of_passing=2024,
        backlogs_count=0,
        work_experience_band="1_2",
        english_test_status="score_available",
        english_test_type="ielts_academic",
        english_test_score="7.5",
        english_test_date=date(2026, 3, 2),
        aptitude_test_type="gre",
        aptitude_test_score="318",
        budget_band="15_25l",
        funding_source="loan_planning",
        lead_source="google_ads",
        lead_source_detail="Spring campaign",
        branch_name="Head Office",
        next_followup_date=date.today() - timedelta(days=2),
        status="shortlisting",
        priority="high",
        target_date=date(2026, 9, 1),
        marketing_consent_channels="whatsapp,email",
    )
    fields.update(overrides)
    row = models.EnterpriseClient(**fields)
    db.add(row)
    db.commit()
    return row


def _ctx(org, *, capabilities, scope_kind, branch_ids=frozenset(), user_id=None, role_key="custom") -> access.AccessContext:
    """A minimal non-owner AccessContext. user_id defaults to the org owner — the user the
    fixture clients are created by — so ASSIGNED scope sees them; pass another id to test
    out-of-scope behaviour."""
    caps = frozenset(capabilities)
    return access.AccessContext(
        organization_id=org.id, user_id=user_id or org.created_by_user_id, member_id=1,
        role_key=role_key, role_label=role_key, custom_role_id=None,
        is_owner=False, is_admin_like=False,
        capabilities=caps, scope_kind=scope_kind, branch_ids=frozenset(branch_ids),
        primary_branch_id=None, status="active",
        preset_capabilities=caps, granted_capabilities=frozenset(), denied_capabilities=frozenset(),
    )


def _viewer_ctx(org) -> access.AccessContext:
    """Viewer preset: holds clients.view but NOT clients.view_sensitive; ASSIGNED scope (the
    fixture clients are created by the org owner, which _ctx uses as the viewer's user_id)."""
    preset = access.ROLE_PRESETS[access.ROLE_VIEWER]
    return _ctx(org, capabilities=preset["capabilities"], scope_kind=preset["data_scope"], role_key=access.ROLE_VIEWER)


def _tool(db, org, name, ctx=None):
    tools = {t.__name__: t for t in enterprise_ai.build_org_tools(db, org.id, ctx=ctx, viewer_user_id=1)}
    assert name in tools, f"{name} not registered: {sorted(tools)}"
    return tools[name]


# ---------------------------------------------------------------------------
# 1. The full profile reaches the assistant
# ---------------------------------------------------------------------------

def test_get_client_details_returns_the_intake_block(db, org):
    _client(db, org)
    detail = _tool(db, org, "get_client_details")(name="Dev Malhotra")
    assert "error" not in detail and "multiple_matches" not in detail

    # The exact question from the incident.
    assert detail["current_city"] == "Mumbai"
    # Contact / personal / guardian.
    assert detail["whatsapp_number"] == "+91 98765 43210"
    assert detail["nationality"] == "Indian"
    assert detail["date_of_birth"] == "2002-05-14"
    assert detail["guardian_name"] == "Rakesh Malhotra"
    assert detail["guardian_phone"] == "+91 91234 56789"
    # Choice fields come back as the human label, not the stored key.
    assert detail["gender"] == client_fields.choice_label("gender", "male")
    assert detail["guardian_relation"] == client_fields.choice_label("guardian_relation", "father")
    assert detail["study_level"] == client_fields.choice_label("study_level", "masters")
    assert detail["study_level"] != "masters"  # label, not key
    assert detail["english_test_status"] != "score_available"
    assert "score" in detail["english_test_status"].lower()
    assert detail["english_test_type"].upper().startswith("IELTS")
    assert detail["visa_category"] == catalog.VISA_CATEGORY_MAP["student"]["label"]
    # Academics, tests, money, source, follow-up.
    assert detail["field_of_study"] == "Computer Science"
    assert detail["qualification_score"] == "8.1"
    assert detail["year_of_passing"] == 2024
    assert detail["backlogs_count"] == 0
    assert detail["english_test_score"] == "7.5"
    assert detail["english_test_date"] == "2026-03-02"
    assert detail["aptitude_test_score"] == "318"
    assert detail["lead_source_detail"] == "Spring campaign"
    assert detail["next_followup_date"] == (date.today() - timedelta(days=2)).isoformat()
    assert detail["marketing_consent_channels"] == client_fields.marketing_channel_labels("whatsapp,email")
    assert "whatsapp" not in detail["marketing_consent_channels"]  # labels, not keys
    # The pre-existing keys are still there and unchanged in shape.
    assert detail["name"] == "Dev Malhotra"
    assert detail["destination"] == "United Arab Emirates"
    assert detail["office"] == "Head Office"
    assert detail["status"] == enterprise_ai._stage_label("shortlisting")
    assert isinstance(detail["recent_notes"], list)


def test_blank_intake_fields_are_present_as_null_not_missing(db, org):
    """A blank field must still be a key (null) so the model says 'not filled in yet'
    instead of 'I can't see that' — the exact wording that confused staff."""
    _client(db, org, current_city=None, guardian_name=None, english_test_score=None)
    detail = _tool(db, org, "get_client_details")(name="Dev")
    for key in ("current_city", "guardian_name", "english_test_score"):
        assert key in detail, f"{key} missing from payload"
        assert detail[key] is None


def test_every_intake_field_the_client_screen_tracks_reaches_the_assistant(db, org):
    """Drift guard tied to the UI: every field in the router's intake lists must be a key in
    the assistant's payload. Adding a field to the client screen without it reaching the AI
    fails here."""
    _client(db, org)
    detail = _tool(db, org, "get_client_details")(name="Dev Malhotra")
    expected = set(router._CLIENT_INTAKE_TEXT_FIELDS) | set(router._CLIENT_INTAKE_CHOICE_FIELDS)
    expected |= {f for f, _label in router._CLIENT_INTAKE_DATE_FIELDS}
    expected |= {f for f, _label, _lo, _hi in router._CLIENT_INTAKE_INT_FIELDS}
    expected.discard("branch_name")  # the brief already carries it as "office"
    missing = sorted(f for f in expected if f not in detail)
    assert not missing, f"intake fields shown on the client screen but invisible to the AI: {missing}"


# Columns the assistant deliberately does NOT echo as profile facts. Everything else on
# EnterpriseClient must appear in get_client_details (possibly under a friendlier key).
_RENAMED = {
    "full_name": "name",
    "destination_country_name": "destination",
    "destination_country_code": "destination",
    "target_date": "key_date",
    "assigned_to_user_id": "assigned_to",
    "branch_name": "office",
    "created_at": "added_on",
    "updated_at": "last_updated",
    "held_from_status": "on_hold_from_stage",
    "marketing_consent_at": "marketing_consent_at",
    "institution_share_consent_at": "institution_share_consent",
}
_INTERNAL = {
    "organization_id",              # tenancy filter only
    "branch_id",                    # record-scope filter only; office name is exposed
    "created_by_user_id",           # record-scope filter only
    "client_consent_confirmed_by_user_id",
    "client_consent_confirmed_at",  # staff-side attestation, not a profile fact
    "stage_data",                   # separate tool: get_client_stage_records
    "stage_visits",                 # journey timestamps; not profile data
    "version",                      # optimistic-concurrency token
    "sop_draft_payload", "sop_draft_updated_at",  # tolerated if present on some branches
}


def test_every_client_column_is_exposed_or_explicitly_internal(db, org):
    _client(db, org)
    detail = _tool(db, org, "get_client_details")(name="Dev Malhotra")
    unclassified = []
    for column in models.EnterpriseClient.__table__.columns:
        name = column.name
        if name in _INTERNAL:
            continue
        key = _RENAMED.get(name, name)
        if key not in detail:
            unclassified.append(name)
    assert not unclassified, (
        "EnterpriseClient columns the assistant can't see and that aren't listed as internal "
        f"in this test: {unclassified}. Either expose them in get_client_details or add them "
        "to _INTERNAL with a reason."
    )


# ---------------------------------------------------------------------------
# 2. Sensitive-data rule is unchanged
# ---------------------------------------------------------------------------

def test_passport_stays_gated_but_profile_is_not(db, org):
    _client(db, org)
    detail = _tool(db, org, "get_client_details", ctx=_viewer_ctx(org))(name="Dev Malhotra")
    # Same rule as the client API: the key is OMITTED and a flag set — never a null that the
    # prompt would (rightly) read as "not filled in yet".
    assert "passport_number" not in detail and detail["passport_hidden"] is True
    assert detail["current_city"] == "Mumbai", "the rest of the profile is not sensitive"
    assert detail["guardian_name"] == "Rakesh Malhotra"
    # And the owner-ish path (no ctx) still returns it, with no hidden flag.
    full = _tool(db, org, "get_client_details")(name="Dev Malhotra")
    assert full["passport_number"] == "N1234567" and "passport_hidden" not in full


def test_client_record_tools_require_clients_view(db, org):
    """A custom role holding ai.assistant but not clients.view cannot open the client screen,
    so it must not be able to read client records (now the whole profile) via the assistant.
    Aggregates stay, minus the profile breakdowns."""
    _client(db, org)
    no_clients = _ctx(org, capabilities={"ai.assistant", "credits.spend", "dashboard.view"}, scope_kind=access.SCOPE_ALL)
    names = {t.__name__ for t in enterprise_ai.build_org_tools(db, org.id, ctx=no_clients, viewer_user_id=1)}
    for hidden in ("get_client_details", "search_clients", "count_clients", "clients_needing_attention", "list_recent_activity"):
        assert hidden not in names, hidden
    assert {"get_portal_overview", "get_product_help", "get_my_access"} <= names
    overview = _tool(db, org, "get_portal_overview", ctx=no_clients)()
    assert overview["total_clients"] == 1 and "by_current_city" not in overview
    # …and every built-in role that holds ai.assistant also holds clients.view, so no preset
    # loses the client tools.
    for key, preset in access.ROLE_PRESETS.items():
        if "ai.assistant" in preset["capabilities"]:
            assert "clients.view" in preset["capabilities"], key


# ---------------------------------------------------------------------------
# 3. count_clients / search_clients: one filter set, and it filters
# ---------------------------------------------------------------------------

def test_count_and_search_accept_the_same_filters(db, org):
    count = _tool(db, org, "count_clients")
    search = _tool(db, org, "search_clients")
    count_params = set(inspect.signature(count).parameters)
    search_params = set(inspect.signature(search).parameters)
    assert count_params <= search_params, f"search_clients lacks: {count_params - search_params}"
    assert search_params - count_params == {"query", "limit"}
    for f in enterprise_ai._PROFILE_TEXT_FILTERS + enterprise_ai._PROFILE_CHOICE_FILTERS + ("followup",):
        assert f in count_params, f"count_clients missing profile filter {f}"
    # Both tools document the shared profile filters (compactly — the declarations are re-sent
    # every round, and a long option list here made gemini-2.5-flash return empty candidates).
    for tool in (count, search):
        for f in enterprise_ai._PROFILE_TEXT_FILTERS + enterprise_ai._PROFILE_CHOICE_FILTERS + ("followup",):
            assert f in tool.__doc__, f"{tool.__name__} docstring doesn't mention {f}"
        assert len(tool.__doc__) < 2000, f"{tool.__name__} docstring grew to {len(tool.__doc__)} chars"


def test_profile_filters_actually_filter(db, org):
    _client(db, org)  # Dev: Mumbai, Indian, masters, google_ads, IELTS score available, overdue follow-up
    _client(db, org, full_name="Priya Nair", email="priya@example.com", current_city="Kochi",
            nationality="Indian", study_level="bachelors", lead_source="referral",
            english_test_status="booked", gender="female", funding_source="self_family",
            budget_band="under_10l", next_followup_date=date.today() + timedelta(days=3))
    _client(db, org, full_name="Ahmed Khan", email="ahmed@example.com", current_city="Dubai",
            nationality="Emirati", study_level="mba", lead_source="walk_in",
            english_test_status="not_taken", next_followup_date=None)
    count = _tool(db, org, "count_clients")
    search = _tool(db, org, "search_clients")

    assert count()["count"] == 3
    assert count(current_city="mumbai")["count"] == 1                     # substring, case-insensitive
    assert count(nationality="Indian")["count"] == 2
    assert count(study_level="masters")["count"] == 1                     # stored key
    assert count(study_level="Bachelors")["count"] == 1                   # human label
    assert count(study_level="bachelor")["count"] == 1                    # prefix
    assert count(lead_source="google")["count"] == 1
    assert count(lead_source="ref")["count"] == 1                         # prefix of 'referral' only
    assert count(english_test_status="Score available")["count"] == 1
    assert count(nationality="Indian", status="shortlisting")["count"] == 2
    # gender / budget / funding / field_of_study are deliberately NOT list filters (see the
    # _PROFILE_*_FILTERS comment in enterprise_ai.py) — they must be rejected loudly, not
    # silently ignored, so the model never believes it filtered.
    import pytest as _pytest
    with _pytest.raises(TypeError):
        count(gender="female")
    assert count(followup="overdue")["count"] == 1
    assert count(followup="this_week")["count"] == 1
    assert count(followup="none")["count"] == 1
    assert count(followup="any")["count"] == 2

    who = search(current_city="Kochi")
    assert who["count"] == 1 and who["clients"][0]["name"] == "Priya Nair"
    assert who["clients"][0]["current_city"] == "Kochi"                  # brief carries it
    assert who["filters_applied"]["current_city"] == "Kochi"
    who = search(lead_source="walk_in", followup="none")
    assert [c["name"] for c in who["clients"]] == ["Ahmed Khan"]

    # query composes with the shared filters (LIKE is applied on top of the filtered query).
    who = search(query="nair", nationality="Indian")
    assert [c["name"] for c in who["clients"]] == ["Priya Nair"]
    assert who["filters_applied"]["nationality"] == "Indian"
    who = search(query="Dev", current_city="Kochi")
    assert who["count"] == 0 and who["filters_applied"]["current_city"] == "Kochi"
    who = search(query="dev@example.com")
    assert [c["name"] for c in who["clients"]] == ["Dev Malhotra"] and who["filters_applied"] == "none"

    # An unknown choice value is an error listing the options — never an unfiltered list.
    bad = count(study_level="nonsense")
    assert "error" in bad and "masters" in bad["error"]
    bad = search(followup="someday")
    assert "error" in bad and "clients" not in bad


def test_choice_prefix_widens_to_a_union_and_never_substring_matches(db, org):
    """'exempt' means every exempt status (union, every label echoed); 'taken' must NOT hit
    not_taken (prefix, never substring) — it is an error listing the options instead of a
    confident inverted count."""
    _client(db, org, english_test_status="exempt_moi")
    _client(db, org, full_name="Priya Nair", email="p@example.com", english_test_status="exempt_provider")
    _client(db, org, full_name="Ahmed Khan", email="a@example.com", english_test_status="not_taken")
    count = _tool(db, org, "count_clients")
    res = count(english_test_status="exempt")
    assert res["count"] == 2
    assert " or " in res["filters_applied"]["english_test_status"]
    assert enterprise_ai._choice_keys("english_test_status", "exempt") == ["exempt_moi", "exempt_provider"]
    bad = count(english_test_status="taken")
    assert "error" in bad and "not_taken" in bad["error"]
    assert enterprise_ai._choice_keys("english_test_status", "taken") == []
    assert enterprise_ai._choice_keys("lead_source", "client") == []          # not 'Referral (client / friend)'
    assert enterprise_ai._choice_keys("english_test_status", "Score available") == ["score_available"]
    assert enterprise_ai._choice_keys("english_test_status", "not taken") == ["not_taken"]


def test_followup_windows_today_and_this_month(db, org):
    """Uses the same UTC clock as the code (datetime.utcnow) so it can't flake at midnight."""
    today = datetime.utcnow().date()
    _client(db, org, next_followup_date=today)
    _client(db, org, full_name="Priya Nair", email="p@example.com", next_followup_date=today + timedelta(days=20))
    _client(db, org, full_name="Ahmed Khan", email="a@example.com", next_followup_date=today + timedelta(days=40))
    count = _tool(db, org, "count_clients")
    assert count(followup="today")["count"] == 1
    assert count(followup="this_month")["count"] == 2
    assert count(followup="any")["count"] == 3


def test_profile_filters_respect_branch_scope(db, org):
    """A branch-scoped member must not count, list, break down or look up another office's
    clients through the new filters — scope is applied to the base query, before any filter."""
    b1 = models.EnterpriseBranch(organization_id=org.id, name="Mumbai office")
    b2 = models.EnterpriseBranch(organization_id=org.id, name="Delhi office")
    db.add_all([b1, b2]); db.commit()
    _client(db, org, branch_id=b1.id)                                                     # Dev, Mumbai, b1
    _client(db, org, full_name="Rohan Das", email="r@example.com", branch_id=b2.id)       # Mumbai too, b2
    preset = access.ROLE_PRESETS[access.ROLE_BRANCH_MANAGER]
    scoped = _ctx(org, capabilities=preset["capabilities"], scope_kind=access.SCOPE_BRANCH, branch_ids={b1.id})
    count = _tool(db, org, "count_clients", ctx=scoped)
    search = _tool(db, org, "search_clients", ctx=scoped)
    assert count(current_city="Mumbai")["count"] == 1
    assert count(followup="any")["count"] == 1
    assert [c["name"] for c in search(current_city="Mumbai")["clients"]] == ["Dev Malhotra"]
    assert _tool(db, org, "get_portal_overview", ctx=scoped)()["by_current_city"] == {"Mumbai": 1}
    assert "error" in _tool(db, org, "get_client_details", ctx=scoped)(name="Rohan Das")


def test_calendar_surfaces_next_followup_dates(db, org):
    """The calendar tool must see the profile's next follow-up date (the calendar screen does),
    so 'who is due a follow-up' gets the same answer from either route; decided cases skip."""
    today = datetime.utcnow().date()
    _client(db, org, next_followup_date=today + timedelta(days=2))
    _client(db, org, full_name="Done Deal", email="d@example.com", status="approved",
            next_followup_date=today + timedelta(days=2))
    events = _tool(db, org, "list_upcoming_calendar_events")(within_days=7)["events"]
    followups = [e for e in events if e["type"] == "client_followup"]
    assert [e["client"] for e in followups] == ["Dev Malhotra"]
    assert followups[0]["date"] == (today + timedelta(days=2)).isoformat() and followups[0]["overdue"] is False


def test_portal_overview_has_profile_breakdowns(db, org):
    _client(db, org)
    _client(db, org, full_name="Priya Nair", email="p@example.com", current_city="Kochi",
            lead_source="referral", study_level="bachelors")
    overview = _tool(db, org, "get_portal_overview")()
    assert overview["by_nationality"] == {"Indian": 2}
    assert overview["by_current_city"] == {"Mumbai": 1, "Kochi": 1}
    label = client_fields.choice_label
    assert overview["by_lead_source"] == {label("lead_source", "google_ads"): 1, label("lead_source", "referral"): 1}
    assert overview["by_study_level"] == {label("study_level", "masters"): 1, label("study_level", "bachelors"): 1}


# ---------------------------------------------------------------------------
# 4. Payload size + prompt
# ---------------------------------------------------------------------------

def test_full_profile_fits_under_the_tool_result_cap(db, org):
    _client(db, org, prior_refusal_notes="x" * 5000)  # long free text is clipped, not dropped
    detail = _tool(db, org, "get_client_details")(name="Dev Malhotra")
    capped = enterprise_ai._capped_tool_result("get_client_details", detail)
    assert "truncated" not in capped
    assert len(detail["prior_refusal_notes"]) <= 601


def test_system_prompt_tells_the_model_the_profile_is_complete():
    prompt = enterprise_ai._system_instruction("Test Org", "Test User", "admin")
    assert "get_client_details" in prompt and "current city" in prompt
    assert "passport_hidden" in prompt          # the one legitimate "no access" case is named
    assert "next follow-up" in prompt           # calendar bullet reconciled with the data
    assert "MUST come from a tool result" in prompt  # grounding: no invented clients/IDs


# ---------------------------------------------------------------------------
# 5. Empty-candidate safety net in the tool loop
# ---------------------------------------------------------------------------

class _Part:
    def __init__(self, text=None):
        self.text = text
        self.function_call = None

    def __contains__(self, item):  # mimics proto "function_call" in part
        return item == "function_call" and self.function_call is not None


class _Content:
    def __init__(self, parts):
        self.parts = parts


class _Candidate:
    def __init__(self, parts):
        self.content = _Content(parts)


class _Response:
    def __init__(self, parts):
        self.candidates = [_Candidate(parts)]
        self.text = "".join(p.text or "" for p in parts) if parts else ""


def test_empty_candidate_is_re_asked_once(monkeypatch):
    """gemini-2.5-flash sometimes returns finish_reason=STOP with zero parts (no text, no
    call). The loop must re-ask (up to twice) instead of surfacing the canned 'couldn't
    find an answer' — and must not loop forever if the model keeps returning nothing."""
    from app.utils import gemini_service as gu

    class FakeModel:
        scripted = []
        calls = 0

        def __init__(self, *a, **k):
            pass

        def generate_content(self, *a, **k):
            FakeModel.calls += 1
            return FakeModel.scripted.pop(0)

    monkeypatch.setattr(gu.genai, "GenerativeModel", FakeModel)
    monkeypatch.setattr(enterprise_ai, "_meter_round", lambda *a, **k: None)

    def noop_tool() -> dict:
        """A tool."""
        return {}

    def run(scripted):
        FakeModel.scripted = list(scripted)
        FakeModel.calls = 0
        usage = enterprise_ai.TurnUsage()
        text = enterprise_ai._run_metered_tool_loop(
            model_name="fake", system="sys", tools=[noop_tool], history=None, message="hi",
            source="test", organization_id=1, user_id=1, usage=usage)
        return text, usage, FakeModel.calls

    # empty → re-ask → text: the user gets the answer, one retry recorded.
    text, usage, calls = run([_Response([]), _Response([_Part("Mumbai")])])
    assert text == "Mumbai" and usage.empty_retries == 1 and calls == 2
    # empty twice → second re-ask still recovers.
    text, usage, calls = run([_Response([]), _Response([]), _Response([_Part("Mumbai")])])
    assert text == "Mumbai" and usage.empty_retries == 2 and calls == 3
    # empty three times: exactly two re-asks, then give up (never a runaway loop).
    text, usage, calls = run([_Response([]), _Response([]), _Response([]), _Response([_Part("never")])])
    assert text == "" and usage.empty_retries == 2 and calls == 3
    # a normal text answer is untouched.
    text, usage, calls = run([_Response([_Part("hello")])])
    assert text == "hello" and usage.empty_retries == 0 and calls == 1
