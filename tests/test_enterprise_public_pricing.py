"""Server-rendered Enterprise prices on the public pages (app/enterprise_public_pricing.py).

Marketing pages carry {{ENT_*}} tokens that app/main.py fills from the live catalog at serve
time. These tests pin:

  * every static page renders with NO token left over and every JSON-LD block still parses —
    an unknown token is a test failure, never a blank on the page;
  * token values are the catalog's own numbers (billing / credits / money), and are safe in
    HTML text, double-quoted attributes and JSON-LD strings alike;
  * "+ GST" exists only while GST is charged, and yearly copy only while yearly is on sale;
  * the owned pages carry no hand-typed plan price, no stale catalog, and don't promote the
    interim-priced client Copilot link or "priority support";
  * the routes (and the raw /static/*.html mount) serve rendered pages, a renderer failure
    costs the price lines rather than the page, and the public price list keeps its own
    Cache-Control / Vary through the security-headers middleware.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.responses import JSONResponse

from app import enterprise_billing as billing
from app import enterprise_credits as credits
from app import enterprise_public_pricing as epp
from app import money

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

# The pages this package owns that quote Enterprise prices/limits. Every one must contain at
# least one token (otherwise it is quoting prices by hand, or not at all).
PRICED_PAGES = (
    "for_enterprise.html",
    "enterprise_demo.html",
    "index.html",
    "enterprise.html",
    "blog-enterprise-visa-management-guide.html",
    "us_f1_visa.html",
    "blog-copilot-guide.html",
)
# Marketing pages that must not promote the interim client Copilot link.
MARKETING_PAGES = (
    "for_enterprise.html",
    "enterprise_demo.html",
    "index.html",
    "enterprise.html",
    "blog-enterprise-visa-management-guide.html",
    "blog.html",
)

# Route → page for every page that carries tokens. A NEW tokenised page must be added here
# (test_every_tokenised_page_has_a_rendering_route fails otherwise), because a page served
# by a plain FileResponse would ship its raw "{{ENT_…}}" text.
ROUTES = {
    "/": "index.html",
    "/some/unknown/spa/path": "index.html",
    "/for-enterprise": "for_enterprise.html",
    "/enterprise": "enterprise.html",
    "/enterprise/clients/42": "enterprise.html",
    "/enterprise/demo": "enterprise_demo.html",
    "/book-a-demo": "enterprise_demo.html",
    "/blog": "blog.html",
    "/blog/student-visa-crm-for-consultancies": "blog-enterprise-visa-management-guide.html",
    "/blog/how-to-use-rilono-ai-copilot": "blog-copilot-guide.html",
    "/pricing": "us_f1_visa.html",
    "/us-f1-visa": "us_f1_visa.html",
}


def _all_pages() -> list[Path]:
    return sorted(STATIC.glob("*.html")) + sorted((STATIC / "partials").glob("*.html"))


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _cards() -> dict:
    return {c["key"]: c for c in billing.public_plans_payload("INR")}


def _jsonld_blocks(page: str) -> list[str]:
    return re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)


def _published_text(page: str) -> str:
    """What a visitor or crawler reads: the page minus comments, styles and scripts — but
    keeping JSON-LD, which search engines show. (Developer comments may name env vars.)"""
    page = re.sub(r"<!--.*?-->", "", page, flags=re.S)
    page = re.sub(r"<style.*?</style>", "", page, flags=re.S)
    return re.sub(r'<script(?![^>]*application/ld\+json).*?</script>', "", page, flags=re.S)


@pytest.fixture
def gst_zero(monkeypatch):
    monkeypatch.setattr(money, "GST_PERCENT", Decimal(0))


@pytest.fixture
def yearly_on(monkeypatch):
    monkeypatch.setattr(billing, "YEARLY_ENABLED", True)
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)


# ---------------------------------------------------------------------------
# Every page renders; unknown tokens fail loudly
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("page_path", _all_pages(), ids=lambda p: p.name)
def test_every_static_page_renders_strictly_with_nothing_left_over(page_path):
    raw = page_path.read_text(encoding="utf-8")
    rendered = epp.render(raw, strict=True)
    assert epp.leftover_tokens(rendered) == []
    assert "{{ENT_" not in rendered
    # Tokens land inside JSON-LD answers: the structured data must still parse.
    for block in _jsonld_blocks(rendered):
        json.loads(block)


@pytest.mark.parametrize("state", ["default", "gst_zero", "yearly_on", "both"])
def test_pages_render_in_every_tax_and_yearly_state(state, monkeypatch):
    if state in {"gst_zero", "both"}:
        monkeypatch.setattr(money, "GST_PERCENT", Decimal(0))
    if state in {"yearly_on", "both"}:
        monkeypatch.setattr(billing, "YEARLY_ENABLED", True)
    for page_path in _all_pages():
        rendered = epp.render(page_path.read_text(encoding="utf-8"), strict=True)
        assert "{{ENT_" not in rendered, page_path.name
        for block in _jsonld_blocks(rendered):
            json.loads(block)


@pytest.mark.parametrize("name", PRICED_PAGES)
def test_priced_pages_actually_use_tokens(name):
    assert epp.tokens_in(_read(name)), f"{name} quotes Enterprise prices without tokens"


def test_unknown_token_raises_in_strict_mode_and_stays_visible_otherwise(caplog):
    page = "<p>Starter {{ENT_STARTER_PRICE_INR}} and {{ENT_NO_SUCH_THING}}</p>"
    with pytest.raises(epp.UnknownPriceToken, match="ENT_NO_SUCH_THING"):
        epp.render(page, strict=True)
    with caplog.at_level("ERROR"):
        out = epp.render(page)
    # Known token still expands; the unknown one is left in place (never silently "").
    assert _cards()["starter"]["monthly_display"] in out
    assert "{{ENT_NO_SUCH_THING}}" in out
    assert "ENT_NO_SUCH_THING" in caplog.text


@pytest.mark.parametrize("page", [
    "{{ENT_IF_NOPE}}x{{ENT_END_IF_NOPE}}",          # unknown flag
    "{{ENT_IF_YEARLY}}never closed",                # unclosed block
    "a{{ENT_END_IF_TAX}}",                          # stray close
])
def test_bad_blocks_raise_in_strict_mode(page):
    with pytest.raises(epp.UnknownPriceToken):
        epp.render(page, strict=True)


def test_blocks_follow_their_flags_and_nest_across_flags():
    page = "[{{ENT_IF_TAX}}T{{ENT_IF_YEARLY}}Y{{ENT_END_IF_YEARLY}}{{ENT_END_IF_TAX}}|{{ENT_IF_NO_TAX}}N{{ENT_END_IF_NO_TAX}}]"
    flags = {"TAX": True, "NO_TAX": False, "YEARLY": False}
    assert epp.render(page, strict=True, tokens={}, flags=flags) == "[T|]"
    flags = {"TAX": True, "NO_TAX": False, "YEARLY": True}
    assert epp.render(page, strict=True, tokens={}, flags=flags) == "[TY|]"
    flags = {"TAX": False, "NO_TAX": True, "YEARLY": True}
    assert epp.render(page, strict=True, tokens={}, flags=flags) == "[|N]"


def test_page_without_tokens_is_returned_untouched():
    page = "<p>No prices here {{ something_else }}</p>"
    assert epp.render(page, strict=True) is page


# ---------------------------------------------------------------------------
# Values come from the catalog and are safe everywhere
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("state", ["default", "gst_zero", "yearly_on"])
def test_token_values_are_safe_in_text_attributes_and_json(state, monkeypatch):
    if state == "gst_zero":
        monkeypatch.setattr(money, "GST_PERCENT", Decimal(0))
    if state == "yearly_on":
        monkeypatch.setattr(billing, "YEARLY_ENABLED", True)
    for name, value in epp.build_tokens().items():
        assert isinstance(value, str), name
        bad = set(value) & epp.UNSAFE_VALUE_CHARS
        assert not bad, f"{name}={value!r} contains {bad}"
        assert not epp.TOKEN_RE.search(value), name


def test_plan_tokens_are_the_live_catalog_numbers():
    tokens = epp.build_tokens()
    cards = _cards()
    for key, prefix in epp.PLAN_TOKEN_PREFIX.items():
        card = cards[key]
        assert tokens[f"ENT_{prefix}_LABEL"] == card["label"]
        assert tokens[f"ENT_{prefix}_PRICE_INR"] == card["monthly_display"]
        assert tokens[f"ENT_{prefix}_SEATS"] == f"{card['max_seats']:,}"
        assert tokens[f"ENT_{prefix}_OPEN_FILES"] == f"{card['max_open_files']:,}"
        assert tokens[f"ENT_{prefix}_CREDITS"] == f"{card['included_credits']:,}"
        assert tokens[f"ENT_{prefix}_READS"] == f"{card['max_reads']:,}"
        assert tokens[f"ENT_{prefix}_YEARLY_PRICE_INR"] == card["yearly_display"]
        for option in card["price_options"]:
            assert tokens[f"ENT_{prefix}_PRICE_{option['currency']}"] == option["display"]
    # The owner-approved 2026-10-22 card, end to end through the token map.
    assert (tokens["ENT_STARTER_LABEL"], tokens["ENT_TEAM_LABEL"], tokens["ENT_MULTI_BRANCH_LABEL"]) == (
        "Starter", "Team", "Multi-branch")
    assert (tokens["ENT_STARTER_PRICE_INR"], tokens["ENT_TEAM_PRICE_INR"], tokens["ENT_MULTI_BRANCH_PRICE_INR"]) == (
        "₹1,499", "₹3,999", "₹9,999")
    assert tokens["ENT_STARTER_INTL_PRICES"] == "$39 / £29 / A$59"
    assert tokens["ENT_FROM_PRICE_INR"] == "₹1,499"


def test_trial_action_pack_and_branch_tokens_follow_their_sources():
    tokens = epp.build_tokens()
    trial = billing.trial_facts()
    assert tokens["ENT_TRIAL_LABEL"] == trial["label"]
    assert tokens["ENT_TRIAL_DAYS"] == str(trial["days"])
    assert tokens["ENT_TRIAL_SEATS"] == str(trial["max_seats"])
    assert tokens["ENT_TRIAL_OPEN_FILES"] == str(trial["max_open_files"])
    assert tokens["ENT_TRIAL_CREDITS"] == str(trial["included_credits"])
    assert tokens["ENT_TRIAL_READS"] == str(trial["reads"])
    assert tokens["ENT_TRIAL_CREDITS_NOTE"] == (
        f"{trial['included_credits']} AI credits at signup, +{trial['demo_bonus_credits']} after a demo call")

    actions = {a["key"]: a for a in credits.actions_payload()}
    assert tokens["ENT_DOC_CHECK_PRICE"] == actions["document_scan"]["price_label"] == "4 credits per 15 pages"
    assert tokens["ENT_WRITING_COST"] == "5 credits"
    assert tokens["ENT_INTERVIEW_COST"] == "20 credits"
    assert tokens["ENT_INTERVIEW_MAX_QUESTIONS"] == str(actions["mock_interview"]["max_questions"])
    assert tokens["ENT_DEEP_SCAN_COST"] == "40 credits"
    assert tokens["ENT_DEEP_SCAN_MAX_DOCS"] == str(actions["deep_scan"]["max_documents"])
    assert tokens["ENT_ASSISTANT_PRICE"] == actions["ai_copilot"]["price_label"]
    assert tokens["ENT_COPILOT_LINK_COST"] == "30 credits"
    assert tokens["ENT_COPILOT_LINK_MESSAGES"] == str(actions["copilot_client"]["messages_included"])

    packs = credits.packages_payload("INR")
    assert tokens["ENT_TOPUP_FROM_INR"] == min(packs, key=lambda p: p["amount_minor"])["amount_display"] == "₹999"
    assert tokens["ENT_TOPUP_PACKS_INR"] == "₹999 for 100 credits, ₹2,999 for 350 and ₹4,999 for 650"

    pack = billing.branch_pack_facts()
    assert tokens["ENT_BRANCH_PACK_FILES"] == str(pack["open_files"])
    assert tokens["ENT_BRANCH_PACK_SEATS"] == str(pack["seats"])
    assert tokens["ENT_FILE_GRACE_DAYS"] == str(billing.FILE_LIMIT_GRACE_DAYS)


def test_env_overrides_move_the_page_with_the_catalog(monkeypatch):
    # A re-price is config, not an HTML sweep: change the price book and the page follows.
    book = dict(money.PRICE_BOOK)
    book["plan_starter"] = {**book["plan_starter"], "INR": 119_900}
    monkeypatch.setattr(money, "PRICE_BOOK", book)
    monkeypatch.setitem(billing.PLANS["growth"], "max_seats", 30)
    tokens = epp.build_tokens()
    assert tokens["ENT_STARTER_PRICE_INR"] == "₹1,199"
    assert tokens["ENT_FROM_PRICE_INR"] == "₹1,199"
    assert tokens["ENT_TEAM_SEATS"] == "30"
    rendered = epp.render(_read("for_enterprise.html"), strict=True)
    assert "₹1,199 <span>/month</span>" in rendered


def test_cards_still_render_under_the_enterprise_free_kill_switch(monkeypatch):
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", True)
    assert billing.public_plans_payload("INR") == []
    tokens = epp.build_tokens()
    assert tokens["ENT_STARTER_PRICE_INR"] == "₹1,499"
    assert tokens["ENT_MULTI_BRANCH_OPEN_FILES"] == "500"
    for name in PRICED_PAGES:
        assert "{{ENT_" not in epp.render(_read(name), strict=True)


# ---------------------------------------------------------------------------
# Tax and yearly wording
# ---------------------------------------------------------------------------

def test_gst_wording_present_while_gst_is_charged(monkeypatch):
    # The shipped default is 0% (not GST-registered); pin the registered rate explicitly.
    monkeypatch.setattr(money, "GST_PERCENT", Decimal(18))
    tokens = epp.build_tokens()
    assert tokens["ENT_TAX_NOTE"] == "+ GST"
    assert tokens["ENT_TAX_SUFFIX"] == " + GST"
    rendered = epp.render(_read("for_enterprise.html"), strict=True)
    assert '<div class="ent-price-gst">+ GST</div>' in rendered
    assert "plans from ₹1,499/month + GST" in rendered
    f1 = epp.render(_read("us_f1_visa.html"), strict=True)
    assert "₹1,499<span>&nbsp;/month + GST</span>" in f1
    assert "in the currency shown, plus GST where an Enterprise price says + GST." in f1


def test_gst_zero_removes_every_tax_mention(gst_zero):
    tokens = epp.build_tokens()
    assert tokens["ENT_TAX_NOTE"] == tokens["ENT_TAX_SUFFIX"] == tokens["ENT_TAX_DISCLAIMER_SUFFIX"] == ""
    assert "GST" not in tokens["ENT_TAX_SENTENCE"]
    for name in PRICED_PAGES:
        rendered = _published_text(epp.render(_read(name), strict=True))
        assert "+ GST" not in rendered, name
        if name not in {"us_f1_visa.html"}:   # its legal pages discuss GSTIN; no price copy does
            assert "GST" not in rendered, name
    f1 = epp.render(_read("us_f1_visa.html"), strict=True)
    assert "₹1,499<span>&nbsp;/month</span>" in f1
    assert "You are charged exactly the amount shown, in the currency shown.\n" in f1
    assert 'data-tax-note=""' in f1
    page = epp.render(_read("for_enterprise.html"), strict=True)
    assert '<div class="ent-price-gst"></div>' in page   # hidden by .ent-price-gst:empty


def test_yearly_copy_only_while_yearly_is_on_sale(yearly_on):
    rendered = epp.render(_read("for_enterprise.html"), strict=True)
    assert '<div class="ent-price-yearly">or ₹14,990 a year (2 months free)</div>' in rendered
    assert '<div class="ent-price-yearly">or ₹39,990 a year (2 months free)</div>' in rendered
    assert '<div class="ent-price-yearly">or ₹99,990 a year (2 months free)</div>' in rendered
    assert "Pay yearly and get 2 months free." in rendered


def test_no_yearly_promotion_by_default():
    assert not billing.yearly_enabled()
    tokens = epp.build_tokens()
    assert tokens["ENT_YEARLY_SENTENCE"] == "" and tokens["ENT_STARTER_YEARLY_NOTE"] == ""
    for name in PRICED_PAGES:
        rendered = epp.render(_read(name), strict=True)
        assert "months free" not in rendered, name
        assert "ent-price-yearly\">" not in rendered, name
        assert "₹14,990" not in rendered, name


# ---------------------------------------------------------------------------
# Copy hygiene on the raw files
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", PRICED_PAGES + ("blog.html",))
def test_owned_pages_hand_type_no_plan_price_or_tax_note(name):
    raw = _read(name)
    # Current plan prices, limits and the tax note must come from tokens, never the markup.
    for literal in ("1,499", "3,999", "9,999", "14,990", "39,990", "99,990", "+ GST"):
        assert literal not in raw, f"{name} hand-types {literal!r}"
    # The retired catalog (2026-08 → 2026-10-22) must be gone from the rendered page.
    rendered = epp.render(raw, strict=True)
    for stale in ("2,999/month", "6,999", "14,999", "active clients", "sandbox", "Growth at", "Scale at",
                  "100 one-time", "10,000 credits", "1,000 AI credits"):
        assert stale not in rendered, f"{name} still says {stale!r}"


@pytest.mark.parametrize("name", MARKETING_PAGES)
def test_marketing_pages_do_not_promote_client_copilot_links_or_priority_support(name):
    rendered = epp.render(_read(name), strict=True).lower()
    assert "client copilot link" not in rendered
    assert "copilot of their own" not in rendered
    assert "per client link" not in rendered
    assert "priority support" not in rendered
    assert "priority same-day" not in rendered


def test_copilot_guide_states_the_live_client_link_allowance():
    rendered = epp.render(_read("blog-copilot-guide.html"), strict=True)
    days, messages = credits.COPILOT_CLIENT_DAYS, credits.COPILOT_CLIENT_MESSAGES
    cost = credits.ACTIONS["copilot_client"]["credits"]
    assert f"valid for {days} days and up to {messages} messages, and costs your organization {cost} credits" in rendered
    assert "100 messages" not in rendered and "20 credits" not in rendered


def test_cache_busters_are_bumped_for_the_changed_assets():
    enterprise = _read("enterprise.html")
    assert "/static/enterprise.js?v=20261022b" in enterprise
    assert "/static/enterprise.css?v=20261022a" in enterprise
    assert "/static/app.js?v=20261022a" in _read("us_f1_visa.html")
    console = _read("admin_console.html")
    assert "/static/admin_console.js?v=20261022b" in console
    assert "/static/admin_console.css?v=20261022a" in console


# ---------------------------------------------------------------------------
# Serving (app/main.py)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def main_app():
    # app.main imports every router; app/routers/upload.py refuses to import without
    # R2_PUBLIC_URL. It is read once at import, so set it only for the import itself.
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("R2_PUBLIC_URL", "https://cdn.example.test")
        from app import main
    return main


@pytest.fixture
def client(main_app):
    from fastapi.testclient import TestClient

    # No `with`: the startup hooks (schema patches, seeders, schedulers) are not needed to
    # serve static pages, and must not run against the shared test database.
    return TestClient(main_app.app)


def test_every_tokenised_page_has_a_rendering_route():
    tokenised = {p.name for p in STATIC.glob("*.html") if "{{ENT_" in p.read_text(encoding="utf-8")}
    assert tokenised <= set(ROUTES.values()), tokenised - set(ROUTES.values())


@pytest.mark.parametrize("path,name", sorted(ROUTES.items()))
def test_routes_serve_rendered_pages(client, path, name):
    res = client.get(path)
    assert res.status_code == 200, path
    assert res.headers["content-type"].startswith("text/html")
    assert "{{ENT_" not in res.text, path
    if epp.tokens_in(_read(name)) & {"ENT_STARTER_PRICE_INR", "ENT_FROM_PRICE_INR"}:
        assert "₹1,499" in res.text, path


def test_raw_static_mount_renders_html_but_leaves_other_files_alone(client):
    res = client.get("/static/for_enterprise.html")
    assert res.status_code == 200
    assert "{{ENT_" not in res.text and "₹1,499" in res.text
    assert "<!--@partial:" not in res.text
    assert "etag" not in {k.lower() for k in res.headers.keys()}
    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]
    assert "etag" in {k.lower() for k in js.headers.keys()}
    assert client.get("/static/does-not-exist.html").status_code == 404


def test_a_renderer_failure_costs_the_prices_not_the_page(client, monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise RuntimeError("catalog exploded")

    monkeypatch.setattr(epp, "render", boom)
    with caplog.at_level("ERROR"):
        res = client.get("/for-enterprise")
    assert res.status_code == 200
    assert "Run your study-abroad practice in one platform." in res.text
    assert "Enterprise price tokens failed to render" in caplog.text


def test_public_price_list_keeps_its_own_cache_headers(client):
    res = client.get("/api/enterprise/public/plans?currency=INR")
    assert res.status_code == 200
    assert res.headers["cache-control"].startswith("public, max-age=")
    assert "no-store" not in res.headers["cache-control"]
    assert "cdn-cache-control" not in {k.lower() for k in res.headers.keys()}
    vary = res.headers["vary"]
    assert "CF-IPCountry" in vary
    assert "Cookie" not in vary and "Authorization" not in vary
    # The security headers still apply.
    assert res.headers["x-content-type-options"] == "nosniff"


def test_public_price_list_errors_still_get_no_store(client, monkeypatch):
    from app.routers import enterprise as enterprise_router

    monkeypatch.setattr(enterprise_router, "check_ip_rate_limit", lambda **kwargs: (False, 30))
    res = client.get("/api/enterprise/public/plans")
    assert res.status_code == 429
    assert res.headers["cache-control"] == "private, no-store, max-age=0"


def test_other_api_responses_still_get_no_store(client):
    res = client.get("/api/meta")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "private, no-store, max-age=0"
    assert {"Cookie", "Authorization"} <= {v.strip() for v in res.headers["vary"].split(",")}


@pytest.mark.parametrize("path,status,cache_control,expected", [
    ("/api/enterprise/public/plans", 200, "public, max-age=300", True),
    ("/api/enterprise/public/plans/", 200, "public, max-age=300", True),
    ("/api/enterprise/public/plans", 429, None, False),
    ("/api/enterprise/public/plans", 200, None, False),           # forgot its own header
    ("/api/enterprise/public/plans/extra", 200, "public, max-age=300", False),
    ("/api/enterprise/billing/plans", 200, "public, max-age=300", False),
    ("/api/enterprise/public/org-logo/abc", 200, None, True),     # unchanged behaviour
])
def test_cache_exemption_rule(main_app, path, status, cache_control, expected):
    headers = {"Cache-Control": cache_control} if cache_control else {}
    response = JSONResponse({}, status_code=status, headers=headers)
    assert main_app._keeps_own_cache_headers(path, response) is expected
