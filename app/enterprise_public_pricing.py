"""
Server-rendered Rilono Enterprise prices for the public marketing pages.

The marketing pages (for_enterprise.html, enterprise_demo.html, index.html, the enterprise
blog guide, the /pricing card in us_f1_visa.html, the enterprise login page …) used to carry
their prices, limits and credit costs as hand-typed HTML. Every re-price then needed a sweep
of a dozen files, and the 2026-10-22 re-cut found pages still quoting the 2026-08 catalog
(₹2,999 / 10 users / 1,000 credits) months after checkout had moved on. So the pages now
carry TOKENS — `{{ENT_STARTER_PRICE_INR}}`, `{{ENT_TEAM_SEATS}}`, `{{ENT_TAX_SUFFIX}}` … —
and app/main.py replaces them at serve time from the SAME code checkout charges from:

    billing.public_plans_payload("INR")   plan cards (app/money.py PRICE_BOOK + billing.PLANS)
    billing.trial_facts()                  the free trial
    billing.branch_pack_facts()            Branch Packs
    credits.actions_payload()              AI action prices ("4 credits per 15 pages")
    credits.packages_payload("INR")        top-up packs
    money.tax_note("INR")                  "+ GST" — or "" while ENTERPRISE_GST_PERCENT=0
    billing.yearly_enabled()               whether "2 months free" may be promoted at all

Server-side (not a JS fetch) for the same reason as the <!--@partial:--> blocks: the prices
are in the initial HTML, so crawlers, link previews and no-JS visitors see the real numbers.

Two kinds of markup:

    {{ENT_NAME}}                               replaced by the value of NAME
    {{ENT_IF_FLAG}} … {{ENT_END_IF_FLAG}}      kept only while FLAG is on (YEARLY, TAX, NO_TAX,
                                               DEMO_BONUS, FILE_GRACE), otherwise removed whole

Rules that make this safe:

  * An unknown token is a BUG, not a blank. `render(..., strict=True)` raises (the test
    suite renders every static page that way); in production the token is left in place
    and logged, never silently replaced by "" — a missing price must be visible, not a
    "Starter  /month" that reads like a typo nobody notices.
  * Values are plain text with none of  " < > & \\  or a newline, so one value is valid in
    every place a token appears: HTML text, a double-quoted attribute (meta descriptions)
    and a JSON-LD string. tests/test_enterprise_public_pricing.py pins that. render() still
    escapes the HTML specials as a backstop.
  * "+ GST" only ever comes from money.tax_note — at a 0% rate every tax token is empty and
    every TAX block disappears, so no page can promise or warn about a tax nobody charges.
  * Yearly copy only exists inside YEARLY tokens/blocks, which are empty while yearly is not
    on sale (ENTERPRISE_YEARLY_ENABLED, default off).
  * Client Copilot links are interim-priced and deliberately NOT promoted: their tokens
    exist only so the how-to guide states the real allowance instead of a stale one.

Values are computed per render: they only read constants and env-derived module state (no
DB, no network), and computing them each time means a test (or an env override picked up
by a reload) can never be served a stale cached price.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
from typing import Optional

from app import enterprise_billing as billing
from app import enterprise_credits as credits
from app import money


logger = logging.getLogger(__name__)

# `{{ENT_NAME}}`. Names are upper-case so a stray `{{ ent_x }}` in prose can never match.
TOKEN_RE = re.compile(r"\{\{(ENT_[A-Z0-9_]+)\}\}")
# `{{ENT_IF_FLAG}} … {{ENT_END_IF_FLAG}}` — the closing tag repeats the flag, so blocks for
# different flags may nest and a missing close leaves both tags in place (and fails strict).
BLOCK_RE = re.compile(r"\{\{ENT_IF_([A-Z0-9_]+)\}\}(.*?)\{\{ENT_END_IF_\1\}\}", re.DOTALL)
# Anything still looking like a token after rendering.
LEFTOVER_RE = re.compile(r"\{\{ENT_[^}]*\}\}")

# Customer-facing token prefix per internal plan key. Internal keys never change (DB rows,
# Razorpay notes); the page vocabulary follows the card labels Starter / Team / Multi-branch.
PLAN_TOKEN_PREFIX = {
    "starter": "STARTER",
    "growth": "TEAM",
    "scale": "MULTI_BRANCH",
}

# Which foreign prices the "International" line on a card quotes. A presentation choice (the
# three ladders most consultancies outside India recognise), not a price — every amount
# still comes from the price book.
INTL_PREVIEW_CURRENCIES = ("USD", "GBP", "AUD")

# Characters a token value may never contain — see the module docstring.
UNSAFE_VALUE_CHARS = frozenset('"<>&\\\n\r')


class UnknownPriceToken(ValueError):
    """A page references a token (or a conditional-block flag) that does not exist."""


def _n(value) -> str:
    return f"{int(value or 0):,}"


def _plural_credits(count) -> str:
    return f"{_n(count)} credit" + ("" if int(count or 0) == 1 else "s")


def _join_words(items: list[str], conj: str = "and") -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {conj} " + items[-1]


def _plan_cards() -> list[dict]:
    """The INR plan cards, from the same function the public API and checkout use.

    billing.public_plans_payload returns [] under the ENTERPRISE_FREE kill-switch (nothing is
    for sale). The marketing pages still need numbers to render — a page with holes is worse
    than a list price — so the same card fields are rebuilt from the catalog in that case.
    """
    cards = billing.public_plans_payload("INR")
    if cards:
        return cards
    rebuilt = []
    for key in billing.PLAN_ORDER:
        plan = billing.PLANS[key]
        monthly = billing.plan_price_minor(key, "INR")
        yearly = billing.plan_price_minor(key, "INR", "yearly") if monthly > 0 else 0
        rebuilt.append({
            "key": key,
            "label": plan["label"],
            "purpose": plan["purpose"],
            "monthly_minor": monthly,
            "monthly_display": money.format_money(monthly, "INR"),
            "yearly_minor": yearly,
            "yearly_display": money.format_money(yearly, "INR") if yearly else None,
            "yearly_months_free": max(0, 12 - int(money.YEARLY_PRICE_MONTHS)) if yearly else 0,
            "max_seats": plan["max_seats"],
            "max_open_files": plan["max_clients"],
            "included_credits": plan["included_credits"],
            "max_reads": plan["max_reads"],
            "files_note": "",
            "price_options": money.price_options(plan["price_product"]) if plan.get("price_product") else [],
            "is_free": monthly <= 0,
        })
    return rebuilt


def _action(actions: dict, key: str) -> dict:
    # A KeyError here means credits.ACTIONS lost an action the pages price — fail loudly.
    return actions[key]


def build_tokens() -> dict[str, str]:
    """Every `{{ENT_*}}` value, as plain text. See the module docstring for the rules."""
    tokens: dict[str, str] = {}
    cards = _plan_cards()
    yearly_on = billing.yearly_enabled()
    tax_note = money.tax_note("INR")          # "+ GST" or "" — the ONE source of that wording
    tax_on = bool(tax_note)

    # --- Paid plans ------------------------------------------------------------------------
    paid = [c for c in cards if c["key"] in PLAN_TOKEN_PREFIX]
    for card in paid:
        p = PLAN_TOKEN_PREFIX[card["key"]]
        tokens[f"ENT_{p}_LABEL"] = card["label"]
        tokens[f"ENT_{p}_PURPOSE"] = card.get("purpose") or ""
        tokens[f"ENT_{p}_PRICE_INR"] = card["monthly_display"]
        tokens[f"ENT_{p}_SEATS"] = _n(card["max_seats"])
        tokens[f"ENT_{p}_OPEN_FILES"] = _n(card["max_open_files"])
        tokens[f"ENT_{p}_CREDITS"] = _n(card["included_credits"])
        tokens[f"ENT_{p}_READS"] = _n(card["max_reads"])
        # The yearly PRICE is a fact even while yearly is not sold; the NOTE (the thing that
        # promotes it) is empty until it can actually be bought.
        tokens[f"ENT_{p}_YEARLY_PRICE_INR"] = card.get("yearly_display") or ""
        months_free = int(card.get("yearly_months_free") or 0)
        tokens[f"ENT_{p}_YEARLY_NOTE"] = (
            f"or {card['yearly_display']} a year ({months_free} months free)"
            if yearly_on and card.get("yearly_display") and months_free > 0 else ""
        )
        options = {o["currency"]: o["display"] for o in card.get("price_options") or []}
        for code in money.supported_charge_currencies():
            if code in options:
                tokens[f"ENT_{p}_PRICE_{code}"] = options[code]
        tokens[f"ENT_{p}_INTL_PRICES"] = " / ".join(
            options[c] for c in INTL_PREVIEW_CURRENCIES if c in options
        )

    cheapest = min((c for c in paid if c["monthly_minor"] > 0), key=lambda c: c["monthly_minor"], default=None)
    tokens["ENT_FROM_PRICE_INR"] = cheapest["monthly_display"] if cheapest else ""
    tokens["ENT_FILES_NOTE"] = next((c.get("files_note") for c in cards if c.get("files_note")), "")

    # --- Trial -----------------------------------------------------------------------------
    trial = billing.trial_facts()
    bonus = int(trial.get("demo_bonus_credits") or 0)
    tokens["ENT_TRIAL_LABEL"] = trial["label"]
    tokens["ENT_TRIAL_DAYS"] = str(int(trial["days"]))
    tokens["ENT_TRIAL_SEATS"] = _n(trial["max_seats"])
    tokens["ENT_TRIAL_OPEN_FILES"] = _n(trial["max_open_files"])
    tokens["ENT_TRIAL_CREDITS"] = _n(trial["included_credits"])
    tokens["ENT_TRIAL_READS"] = _n(trial["reads"])
    tokens["ENT_TRIAL_DEMO_BONUS"] = _n(bonus)
    tokens["ENT_TRIAL_CREDITS_NOTE"] = (
        f"{_n(trial['included_credits'])} AI credits at signup"
        + (f", +{_n(bonus)} after a demo call" if bonus > 0 else "")
    )
    # What happens on the last day: AI pauses (default) — but say nothing about pausing if
    # ENTERPRISE_AI_PAUSE_ON_EXPIRY turned the gate off.
    tokens["ENT_TRIAL_END_NOTE"] = (
        "AI pauses when the trial ends — your workspace and data stay"
        if trial.get("ai_pauses_on_expiry") else "Your workspace and data stay when the trial ends"
    )

    # --- Tax -------------------------------------------------------------------------------
    tokens["ENT_TAX_NOTE"] = tax_note
    # Leading space so "₹1,499/month{{ENT_TAX_SUFFIX}}" reads right with and without tax.
    tokens["ENT_TAX_SUFFIX"] = f" {tax_note}" if tax_on else ""
    others = [c for c in money.supported_charge_currencies() if c != "INR"]
    tokens["ENT_CURRENCIES_OTHER"] = _join_words(others, "or")
    tokens["ENT_TAX_SENTENCE"] = (
        f"Prices exclude {money.tax_label_for('INR')}, which is added at checkout for INR billing; "
        "other currencies are billed tax-free."
        if tax_on else "No tax is added at checkout — you pay the price shown."
    )
    # Appended to "You are charged exactly the amount shown, in the currency shown" on the
    # /pricing page, which is only literally true for an Enterprise INR price while no tax
    # is added on top of it.
    tokens["ENT_TAX_DISCLAIMER_SUFFIX"] = (
        f", plus {money.tax_label_for('INR')} where an Enterprise price says {tax_note}" if tax_on else ""
    )

    # --- Yearly ----------------------------------------------------------------------------
    months_free = max(0, 12 - int(money.YEARLY_PRICE_MONTHS))
    tokens["ENT_YEARLY_MONTHS_FREE"] = str(months_free)
    tokens["ENT_YEARLY_SENTENCE"] = (
        f" Pay yearly and get {months_free} months free." if yearly_on and months_free > 0 else ""
    )

    # --- AI action prices --------------------------------------------------------------------
    # Three forms per action, so copy never has to pluralise or restate a unit by hand:
    #   *_PRICE    the price list's own label   "4 credits per 15 pages", "40 credits per scan"
    #   *_COST     one unit, pluralised          "4 credits", "1 credit"
    #   *_CREDITS  the bare number               "4"
    actions = {a["key"]: a for a in credits.actions_payload()}

    def _action_tokens(prefix: str, key: str) -> dict:
        action = _action(actions, key)
        tokens[f"ENT_{prefix}_PRICE"] = action["price_label"]
        tokens[f"ENT_{prefix}_COST"] = _plural_credits(action["credits"])
        tokens[f"ENT_{prefix}_CREDITS"] = _n(action["credits"])
        return action

    doc = _action_tokens("DOC_CHECK", "document_scan")
    tokens["ENT_READ_PAGES"] = _n(doc.get("pages_per_unit") or credits.DOCUMENT_BLOCK_PAGES)
    _action_tokens("WRITING", "writing_studio")
    interview = _action_tokens("INTERVIEW", "mock_interview")
    tokens["ENT_INTERVIEW_MAX_QUESTIONS"] = _n(interview.get("max_questions"))
    deep = _action_tokens("DEEP_SCAN", "deep_scan")
    tokens["ENT_DEEP_SCAN_MAX_DOCS"] = _n(deep.get("max_documents"))
    _action_tokens("SHORTLIST", "course_finder")
    _action_tokens("UNIVERSITY_MATCH", "university_match")
    assistant = _action_tokens("ASSISTANT", "ai_copilot")
    tokens["ENT_ASSISTANT_FREE_DAILY"] = _n(assistant.get("free_daily_messages"))
    # Client Copilot links: interim pricing, NOT promoted on marketing pages. These exist so
    # the how-to guide states the link's real allowance instead of a stale one.
    link = _action_tokens("COPILOT_LINK", "copilot_client")
    tokens["ENT_COPILOT_LINK_MESSAGES"] = _n(link.get("messages_included"))
    tokens["ENT_COPILOT_LINK_DAYS"] = _n(link.get("valid_days"))
    tokens["ENT_CREDIT_VALUE_INR"] = money.format_money(credits.PAISE_PER_CREDIT, "INR")

    # --- Top-up packs ----------------------------------------------------------------------
    packs = credits.packages_payload("INR")
    tokens["ENT_TOPUP_FROM_INR"] = (
        min(packs, key=lambda p: p["amount_minor"])["amount_display"] if packs else ""
    )
    pack_bits = [
        f"{p['amount_display']} for {_n(p['total_credits'])} credits" if i == 0
        else f"{p['amount_display']} for {_n(p['total_credits'])}"
        for i, p in enumerate(packs)
    ]
    tokens["ENT_TOPUP_PACKS_INR"] = _join_words(pack_bits, "and")

    # --- Branch Packs and open files ---------------------------------------------------------
    pack = billing.branch_pack_facts()
    tokens["ENT_BRANCH_PACK_FILES"] = _n(pack["open_files"])
    tokens["ENT_BRANCH_PACK_SEATS"] = _n(pack["seats"])
    tokens["ENT_BRANCH_PACK_CREDITS"] = _n(pack["credits"])
    tokens["ENT_BRANCH_PACK_READS"] = _n(pack["reads"])
    tokens["ENT_FILE_GRACE_DAYS"] = _n(billing.FILE_LIMIT_GRACE_DAYS)

    return tokens


def build_flags() -> dict[str, bool]:
    """The conditions `{{ENT_IF_FLAG}}` blocks test."""
    tax_on = money.tax_applies("INR")
    return {
        "YEARLY": billing.yearly_enabled() and int(money.YEARLY_PRICE_MONTHS) < 12,
        "TAX": tax_on,
        "NO_TAX": not tax_on,
        "DEMO_BONUS": int(billing.TRIAL_DEMO_BONUS_CREDITS or 0) > 0,
        # ENTERPRISE_FILE_LIMIT_GRACE_DAYS=0 makes the open-file limit a hard cap; copy about
        # "keep adding for N days" must then disappear rather than promise 0 days.
        "FILE_GRACE": int(billing.FILE_LIMIT_GRACE_DAYS or 0) > 0,
    }


def _escape(value: str) -> str:
    # Backstop only — values are pinned free of these characters (see UNSAFE_VALUE_CHARS).
    # Deliberately NOT html.escape(quote=True): that also rewrites apostrophes, which would
    # print a literal "&#x27;" inside a JSON-LD answer.
    return html_lib.escape(value, quote=False).replace('"', "&quot;")


def tokens_in(page_html: str) -> set[str]:
    """Token names a page references, block tags included (for tests and diagnostics)."""
    return set(TOKEN_RE.findall(page_html))


def render(
    page_html: str,
    *,
    strict: bool = False,
    tokens: Optional[dict[str, str]] = None,
    flags: Optional[dict[str, bool]] = None,
) -> str:
    """Expand every Enterprise price block and token in `page_html`.

    `strict=True` raises UnknownPriceToken for an unknown flag or token, or a block left
    unclosed — the test suite renders every static page that way. Otherwise the offending
    markup is left in place and logged (see the module docstring for why not "")."""
    if "{{ENT_" not in page_html:
        return page_html
    values = build_tokens() if tokens is None else tokens
    conditions = build_flags() if flags is None else flags
    problems: list[str] = []

    def _block(match: re.Match) -> str:
        flag = match.group(1)
        if flag not in conditions:
            problems.append(f"ENT_IF_{flag}")
            return match.group(0)
        return match.group(2) if conditions[flag] else ""

    # Blocks first (repeated, so nested blocks of different flags resolve), then the plain
    # tokens inside whatever survived. Most pages have no blocks: skip the scan for them.
    previous = None
    while "{{ENT_IF_" in page_html and previous != page_html:
        previous = page_html
        page_html = BLOCK_RE.sub(_block, page_html)
        if problems:
            break

    def _token(match: re.Match) -> str:
        name = match.group(1)
        if name.startswith(("ENT_IF_", "ENT_END_IF_")):
            # A block tag that BLOCK_RE could not pair (unclosed or mismatched).
            problems.append(name)
            return match.group(0)
        value = values.get(name)
        if value is None:
            problems.append(name)
            return match.group(0)
        return _escape(value)

    page_html = TOKEN_RE.sub(_token, page_html)
    if problems:
        unique = sorted(set(problems))
        if strict:
            raise UnknownPriceToken("Unknown or unclosed Enterprise price token(s): " + ", ".join(unique))
        logger.error("Static page references unknown Enterprise price token(s): %s", ", ".join(unique))
    return page_html


def leftover_tokens(rendered_html: str) -> list[str]:
    """Anything that still looks like a price token after render() — must be empty."""
    return LEFTOVER_RE.findall(rendered_html)
