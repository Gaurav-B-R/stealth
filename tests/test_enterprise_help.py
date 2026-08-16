"""Drift guards for the assistant's product-help knowledge base.

The help guide (app/prompts/ENTERPRISE_HELP_GUIDE.md + app/enterprise_help.py) promises
to describe the CURRENT product. These tests make that promise enforceable: they fail
when the guide and the code's own registries (capabilities, roles, scopes, plans, credit
actions) or the portal's navigation drift apart — so a feature change that forgets the
help content breaks the build instead of silently teaching the assistant stale answers.

Run: python -m pytest tests/test_enterprise_help.py
"""

import re
from pathlib import Path

import pytest

from app import enterprise_access as access
from app import enterprise_billing as billing
from app import enterprise_credits as credits
from app import enterprise_help as help_mod

WEB_APP = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def full_text() -> str:
    text = help_mod.full_guide_text()
    assert text, "help guide rendered empty"
    return text


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def test_guide_parses_into_topics():
    keys = help_mod.topic_keys()
    assert len(keys) >= 10, f"expected a real topic set, got {keys}"
    assert "team-access" in keys, "the teammate-access topic is the KB's anchor use case"
    for entry in help_mod.topics_index():
        assert entry["title"], f"topic {entry['key']} has no title"
        assert entry["summary"], f"topic {entry['key']} is missing its first-line summary"


def test_every_topic_renders_within_tool_budget():
    from app import enterprise_ai
    for key in help_mod.topic_keys():
        rendered = help_mod.render_topic(key)
        assert rendered and rendered["content"], f"topic {key} rendered empty"
        assert "{{" not in rendered["content"], f"topic {key} left a placeholder unexpanded"
        assert len(rendered["content"]) <= help_mod.TOPIC_CHAR_CAP
        # A topic must fit an assistant tool result — truncation there would hand the
        # model a partial guide with an in-band "tell the user it's partial" note.
        assert len(rendered["content"]) < enterprise_ai.TOOL_RESULT_CHAR_CAP, (
            f"topic {key} exceeds the assistant tool-result cap"
        )


def test_unknown_topic_returns_none_and_index_survives():
    assert help_mod.render_topic("no-such-topic") is None
    assert help_mod.render_topic("") is None
    assert help_mod.render_topic(None) is None


def test_guide_keeps_its_generated_placeholders():
    """Deleting a {{PLACEHOLDER}} line would silently swap live registry facts for
    whatever prose was last hand-written. Every generator must stay referenced."""
    raw = help_mod.GUIDE_PATH.read_text(encoding="utf-8")
    for name in help_mod._GENERATORS:
        assert f"{{{{{name}}}}}" in raw, f"guide no longer uses {{{{{name}}}}}"


# ---------------------------------------------------------------------------
# Registry drift — permissions, roles, scopes
# ---------------------------------------------------------------------------

def test_every_capability_is_documented(full_text):
    for cap in access.ALL_CAPABILITIES:
        assert cap["key"] in full_text, f"capability {cap['key']} missing from help"
        assert cap["label"] in full_text, f"capability label {cap['label']!r} missing from help"


def test_every_role_preset_is_documented(full_text):
    for key, preset in access.ROLE_PRESETS.items():
        if key == access.ROLE_CUSTOM:
            continue
        assert preset["label"] in full_text, f"role {preset['label']!r} missing from help"
        assert preset["description"] in full_text, f"role description for {key} missing"


def test_every_data_scope_is_documented(full_text):
    for scope in access.SCOPES:
        assert scope["label"] in full_text, f"scope {scope['label']!r} missing from help"
        assert scope["desc"] in full_text, f"scope desc for {scope['key']} missing"


# ---------------------------------------------------------------------------
# Registry drift — plans, credit actions, packs
# ---------------------------------------------------------------------------

def test_every_plan_is_documented(full_text):
    for key in billing.PLAN_ORDER:
        plan = billing.PLANS[key]
        assert plan["label"] in full_text, f"plan {plan['label']!r} missing from help"
        assert f"{plan['included_credits']:,}" in full_text, (
            f"plan {key} credit allowance missing from help"
        )


def test_every_credit_action_is_documented(full_text):
    for action in credits.ACTIONS.values():
        assert action["label"] in full_text, f"credit action {action['label']!r} missing"


def test_every_topup_pack_is_documented(full_text):
    for key in credits.PACKAGE_ORDER:
        pack = credits.PACKAGES[key]
        assert pack["label"] in full_text, f"pack {pack['label']!r} missing from help"


def test_free_allowances_are_documented(full_text):
    assert f"{credits.COPILOT_FREE_DAILY} AI assistant messages" in full_text
    assert f"{credits.DEEP_SCAN_FREE_MONTHLY_ORG_CAP} free Deep Scans" in full_text
    assert f"{credits.INTERVIEW_FREE_STAFF_PREVIEWS} free staff mock-interview previews" in full_text


# ---------------------------------------------------------------------------
# UI drift — the sidebar the guide walks users through
# ---------------------------------------------------------------------------

def test_every_portal_screen_is_mentioned():
    """The SPA's own view-title map is the ground truth for screen names. A renamed or
    added screen must show up in the help guide, or its help answers point nowhere."""
    js = (WEB_APP / "static" / "enterprise.js").read_text(encoding="utf-8")
    match = re.search(r"const titles = \{(?P<body>[^}]+)\}", js)
    assert match, "could not find the view-title map in enterprise.js"
    titles = re.findall(r'"([^"]+)"', match.group("body"))
    assert len(titles) >= 10, f"title map parsed suspiciously small: {titles}"
    full = help_mod.full_guide_text()
    for title in titles:
        assert title in full, (
            f"portal screen {title!r} (enterprise.js view-title map) is not mentioned "
            "in the help guide — update app/prompts/ENTERPRISE_HELP_GUIDE.md"
        )


# ---------------------------------------------------------------------------
# Assistant wiring
# ---------------------------------------------------------------------------

def _viewer_ctx():
    """A minimal non-owner AccessContext (Viewer preset, no offices)."""
    preset = access.ROLE_PRESETS[access.ROLE_VIEWER]
    return access.AccessContext(
        organization_id=1, user_id=1, member_id=1,
        role_key=access.ROLE_VIEWER, role_label=preset["label"], custom_role_id=None,
        is_owner=False, is_admin_like=False,
        capabilities=preset["capabilities"],
        scope_kind=preset["data_scope"], branch_ids=frozenset(),
        primary_branch_id=None, status="active",
        preset_capabilities=preset["capabilities"],
        granted_capabilities=frozenset(), denied_capabilities=frozenset(),
    )


def test_assistant_exposes_help_tools_to_every_role():
    from app import enterprise_ai
    # db=None is safe here: neither tool touches the session at build time, and
    # get_my_access only queries when the ctx actually has offices.
    tools = enterprise_ai.build_org_tools(None, 1, ctx=_viewer_ctx(), viewer_user_id=1)
    names = {t.__name__ for t in tools}
    assert "get_product_help" in names
    assert "get_my_access" in names


def test_get_my_access_reports_missing_permissions():
    from app import enterprise_ai
    tools = enterprise_ai.build_org_tools(None, 1, ctx=_viewer_ctx(), viewer_user_id=1)
    my_access = next(t for t in tools if t.__name__ == "get_my_access")()
    assert my_access["role"] == "Viewer"
    assert my_access["is_owner"] is False
    held = set(my_access["permissions_held"])
    missing = {m["permission"] for m in my_access["permissions_not_held"]}
    assert "Manage team" in missing, "a Viewer must be told they can't manage the team"
    assert "View clients" in held
    assert held.isdisjoint(missing)
    assert len(held) + len(missing) == len(access.ALL_CAPABILITIES)
    # JSON-safe through the assistant's own result boundary.
    payload = enterprise_ai._capped_tool_result("get_my_access", my_access)
    assert "truncated" not in payload


def test_get_product_help_tool_round_trip():
    from app import enterprise_ai
    tools = enterprise_ai.build_org_tools(None, 1, ctx=_viewer_ctx(), viewer_user_id=1)
    help_tool = next(t for t in tools if t.__name__ == "get_product_help")
    index = help_tool()
    assert {t["key"] for t in index["topics"]} == set(help_mod.topic_keys())
    topic = help_tool("team-access")
    assert "Invite member" in topic["content"]
    payload = enterprise_ai._capped_tool_result("get_product_help", topic)
    assert "truncated" not in payload


def test_system_instruction_advertises_every_topic():
    from app import enterprise_ai
    system = enterprise_ai._system_instruction("Test Org", "Test User", "admin")
    assert "get_product_help" in system
    assert "get_my_access" in system
    for key in help_mod.topic_keys():
        assert key in system, f"topic {key} not advertised in the system instruction"
