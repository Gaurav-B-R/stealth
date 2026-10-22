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
from app import enterprise_catalog as catalog
from app import enterprise_coupons as coupons
from app import enterprise_credits as credits
from app import enterprise_help as help_mod
from app import money

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

def _plan_line(text: str, key: str) -> str:
    """The rendered plans-list bullet for one plan (`(key)` is unique to it)."""
    line = next((ln for ln in text.splitlines() if f"(`{key}`)" in ln), None)
    assert line, f"plan {key} has no line in the plans list"
    return line


def test_every_plan_is_documented(full_text):
    for key in billing.PLAN_ORDER:
        plan = billing.PLANS[key]
        line = _plan_line(full_text, key)
        assert plan["label"] in line, f"plan {plan['label']!r} missing from help"
        assert f"{plan['included_credits']:,} AI credits" in line, f"plan {key} credits missing"
        assert f"{plan['max_seats']:,} staff seat" in line, f"plan {key} seats missing"
        assert f"{plan['max_clients']:,} open student files" in line, f"plan {key} open files missing"
        assert f"{plan['max_reads']:,} AI document reads" in line, f"plan {key} reads missing"
        if key in billing.PAID_PLAN_KEYS:
            price = money.format_money(billing.plan_price_minor(key, "INR"), "INR")
            assert f"{price}/month" in line, f"plan {key} INR price missing"


def test_plans_follow_env_overrides(monkeypatch):
    """The plans list is rendered from PLANS at request time, never cached copy: an env
    override (here simulated on the registry) must show up in the very next answer."""
    monkeypatch.setitem(billing.PLANS["starter"], "max_reads", 777)
    monkeypatch.setitem(billing.PLANS["starter"], "max_clients", 4321)
    line = _plan_line(help_mod.full_guide_text(), "starter")
    assert "777 AI document reads" in line
    assert "4,321 open student files" in line


def test_old_client_limit_wording_is_gone(full_text):
    """Plans are sized by OPEN student files since 2026-10-22; "active clients" taught the
    assistant the old rule (every client counts)."""
    assert not re.search(r"active[- ]clients?", full_text, re.I)
    assert "open student files" in full_text


def test_every_credit_action_is_documented(full_text):
    for action in credits.actions_payload():
        assert action["label"] in full_text, f"credit action {action['label']!r} missing"
        # The price is quoted with its UNIT ("4 credits per 15 pages"), never as a bare
        # number that reads as a flat price.
        assert f"**{action['label']}** — {action['price_label']}." in full_text, (
            f"credit action {action['key']} must be priced with its price_label"
        )
    assert not re.search(r"\d+ credit\(s\)", full_text), "bare credit counts are back"


def test_every_topup_pack_is_documented(full_text):
    for pack in credits.packages_payload("INR"):
        assert pack["label"] in full_text, f"pack {pack['label']!r} missing from help"
        assert f"{pack['amount_display']} for {pack['total_credits']:,} credits" in full_text


def test_free_allowances_are_documented(full_text):
    copilot = next(a for a in credits.actions_payload() if a["key"] == credits.COPILOT_ACTION_KEY)
    assert f"{credits.COPILOT_FREE_DAILY} AI assistant messages" in full_text
    assert f"then {copilot['price_label']}" in full_text
    assert f"{credits.INTERVIEW_FREE_STAFF_PREVIEWS} free staff mock-interview previews" in full_text


def test_free_deep_scans_only_when_configured(monkeypatch):
    """No free Deep Scans by default (2026-10-22). The free-scan sentence must exist only
    while ENTERPRISE_DEEP_SCAN_FREE_SCANS_PER_CLIENT > 0 — and come back if a promotion
    turns it on, so the help never contradicts the scan screen either way."""
    monkeypatch.setattr(credits, "DEEP_SCAN_FREE_SCANS_PER_CLIENT", 0)
    text = help_mod.full_guide_text()
    assert "free Deep Scans" not in text
    assert not re.search(r"first (?:Deep )?scans? (?:is |are )?free", text, re.I)
    assert "no free scans" in text

    monkeypatch.setattr(credits, "DEEP_SCAN_FREE_SCANS_PER_CLIENT", 1)
    text = help_mod.full_guide_text()
    assert "each client's first 1 Deep Scan" in text
    assert f"{credits.DEEP_SCAN_FREE_MONTHLY_ORG_CAP} free Deep Scans" in text
    assert "no free scans" not in text


# ---------------------------------------------------------------------------
# Registry drift — tax, yearly, currency (each printed only while it is true)
# ---------------------------------------------------------------------------

def test_gst_wording_follows_the_tax_rate(monkeypatch):
    """ENTERPRISE_GST_PERCENT=0 is a supported configuration (GST registration deferred):
    then nothing in the help may say GST, exactly like the price cards and checkout."""
    monkeypatch.setattr(money, "GST_PERCENT", money.Decimal(0))
    assert money.tax_note("INR") == ""
    text = help_mod.full_guide_text()
    assert "GST" not in text
    assert "No tax is added at checkout" in text
    starter_price = money.format_money(billing.plan_price_minor("starter", "INR"), "INR")
    assert f"{starter_price}/month." in _plan_line(text, "starter")

    monkeypatch.setattr(money, "GST_PERCENT", money.Decimal(18))
    text = help_mod.full_guide_text()
    assert f"{starter_price}/month + GST." in _plan_line(text, "starter")
    assert "18% GST is added at checkout" in text


def test_yearly_only_when_enabled(monkeypatch):
    monkeypatch.setattr(billing, "YEARLY_ENABLED", False)
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)
    text = help_mod.full_guide_text()
    assert "yearly" not in text.lower()
    assert "months free" not in text

    monkeypatch.setattr(billing, "YEARLY_ENABLED", True)
    text = help_mod.full_guide_text()
    yearly = money.format_money(billing.plan_price_minor("starter", "INR", "yearly"), "INR")
    assert "billed monthly or yearly" in text
    assert f"{billing.PLANS['starter']['label']} {yearly}" in text
    assert f"{12 - money.YEARLY_PRICE_MONTHS} months free" in text


def test_currency_region_rule_is_documented(full_text):
    assert "billed in INR only" in full_text
    assert "can't be billed in INR" in full_text
    for code in money.supported_charge_currencies():
        if code != "INR":
            assert code in full_text, f"charge currency {code} missing from the region rule"
    for code in billing.INR_REGION_COUNTRIES - {"IN"}:
        name = help_mod._COUNTRY_NAMES.get(code, code)
        assert name in full_text, f"INR-region country {code} missing"


def test_coupon_cap_is_documented(full_text):
    assert f"at most {help_mod._percent(coupons.max_percent_off())}% off" in full_text


# ---------------------------------------------------------------------------
# Registry drift — open files, trial / AI pause, reads, Team features, client links
# ---------------------------------------------------------------------------

def test_open_file_rule_is_documented(full_text):
    for stage in catalog.CLIENT_STAGES:
        assert stage["label"] in full_text, f"stage {stage['label']!r} missing from the open-file rule"
    closed = catalog.CLIENT_STAGE_MAP[catalog.STAGE_CLOSED]
    assert f"move it to \"{closed['label']}\"" in full_text
    assert closed["description"] in full_text
    assert f"{billing.FILE_LIMIT_GRACE_DAYS} days from the first add" in full_text
    assert "Reopening a file" in full_text


def test_file_grace_zero_reads_as_hard_limit(monkeypatch):
    monkeypatch.setattr(billing, "FILE_LIMIT_GRACE_DAYS", 0)
    text = help_mod.full_guide_text()
    assert "The open-file limit is a hard limit" in text
    assert "keep adding for" not in text
    assert "adding past the open-file limit is allowed" not in text


def test_trial_and_ai_pause_are_documented(full_text):
    trial = billing.trial_facts()
    assert f"starts on the {trial['label']}" in full_text
    assert f"{trial['reads']:,} AI document reads for the whole trial" in full_text
    assert f"+{trial['demo_bonus_credits']:,} more, once, after a demo call" in full_text
    assert billing.AI_PAUSED_TRIAL_MESSAGE in full_text
    assert billing.AI_PAUSED_CLIENT_MESSAGE in full_text
    assert billing.AI_PAUSED_LAPSED_MESSAGE.format(plan=billing.PLANS["starter"]["label"]) in full_text
    assert "One free trial per company" in full_text
    # Top-ups are add-ons to a live plan or trial (POST /credits/topup/checkout 402s while paused).
    assert "can't be bought while AI is paused" in full_text


def test_ai_pause_text_follows_its_switch(monkeypatch):
    monkeypatch.setattr(billing, "AI_PAUSE_ON_EXPIRY", False)
    text = help_mod.full_guide_text()
    assert billing.AI_PAUSED_TRIAL_MESSAGE not in text
    assert "can't be bought while AI is paused" not in text
    assert "AI features keep working" in text


def test_reads_allowance_is_documented(full_text):
    for key in billing.PLAN_ORDER:
        plan = billing.PLANS[key]
        assert f"{plan['label']} {plan['max_reads']:,}" in full_text, f"reads for {key} missing"
    assert f"One read covers up to {credits.DOCUMENT_BLOCK_PAGES} pages" in full_text
    assert "\"Not read yet\"" in full_text and "\"Read now\"" in full_text
    assert "never uses reads" in full_text


def test_team_features_are_documented(full_text):
    team = [billing.PLANS[k]["label"] for k in billing.PLAN_ORDER
            if k in billing.PAID_PLAN_KEYS and billing.PLANS[k]["features_tier"] == "team"]
    starter_like = [billing.PLANS[k]["label"] for k in billing.PLAN_ORDER
                    if k in billing.PAID_PLAN_KEYS and billing.PLANS[k]["features_tier"] != "team"]
    assert team and starter_like, "expected both tiers in the catalog"
    assert f"are part of the {help_mod._join(team)} plans and the free trial while it runs" in full_text
    assert f"On {help_mod._join(starter_like)}: one office" in full_text
    assert "Nothing is taken away on a lower plan" in full_text


def test_client_link_terms_are_documented(full_text):
    by_key = {a["key"]: a for a in credits.actions_payload()}
    assert f"Client Copilot link: {by_key['copilot_client']['price_label']}" in full_text
    assert f"up to {credits.COPILOT_CLIENT_MESSAGES} messages over {credits.COPILOT_CLIENT_DAYS} days" in full_text
    assert f"up to {credits.INTERVIEW_MAX_QUESTIONS} officer questions and one feedback report" in full_text


def test_hand_written_guide_states_no_billing_numbers():
    """The curated prose must not restate anything a registry owns — prices, "+ GST",
    seat/file/credit/read/message counts, the trial length, free allowances. Those come only
    from {{PLACEHOLDER}} blocks, which is what keeps them true after an env override, a
    re-price or GST going to 0. (The old guide hand-wrote "up to 100 messages" and "18% GST"
    and both went stale on the 2026-10-22 re-price.)"""
    topics = help_mod._parse_guide(help_mod.GUIDE_PATH.read_text(encoding="utf-8"))
    banned = [
        r"\b\d[\d,]*\s+(?:AI\s+)?credits?\b",
        r"\b\d[\d,]*\s+(?:AI\s+)?(?:document\s+)?reads?\b",
        r"\b\d[\d,]*\s+(?:free\s+)?(?:assistant\s+)?messages?\b",
        r"\b\d[\d,]*\s+open(?:\s+student)?\s+files?\b",
        r"\b\d[\d,]*\s+(?:team\s+|staff\s+)?seats?\b",
        r"\b\d[\d,]*\s+(?:officer\s+)?questions\b",
        r"\bGST\b",
        r"\b\d+-day\s+(?:free\s+)?(?:trial|sandbox|grace)\b",
        r"\bfirst\s+(?:Deep\s+)?scan\s+(?:is\s+)?free\b",
        r"\bactive[- ]clients?\b",
        r"\bmonths free\b",
    ]
    prices = [
        money.format_money(billing.plan_price_minor(k, "INR"), "INR")
        for k in billing.PAID_PLAN_KEYS
    ] + [p["amount_display"] for p in credits.packages_payload("INR")]
    for key, topic in topics.items():
        body = topic["body"]
        for pattern in banned:
            hit = re.search(pattern, body, re.I)
            assert not hit, (
                f"topic {key} hand-writes {hit.group(0)!r} — use a generated block "
                "(app/enterprise_help.py) instead"
            )
        for price in prices:
            assert price not in body, f"topic {key} hand-writes the price {price}"


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
