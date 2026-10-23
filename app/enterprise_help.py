"""Rilono Enterprise product help — the assistant's knowledge base about the platform itself.

The dashboard assistant (enterprise_ai) answers questions about the ORG'S DATA from live
database tools. This module gives it the other half of "help and support": authoritative
knowledge of the PRODUCT — how to invite a teammate, what a role can do, what a Deep Scan
costs, where a screen lives — so "how do I…" questions get grounded answers instead of
guesses.

Content is merged from two sources at render time:

  * CURATED — app/prompts/ENTERPRISE_HELP_GUIDE.md, split into topics by
    `## [topic-key] Title` headings. This is the hand-written walkthrough of screens and
    flows. It must be updated when the UI changes (docs/workflows/docs-update-checklist.md
    lists it, and tests/test_enterprise_help.py fails when it drifts from the registries).

  * GENERATED — blocks built live from the same registries the product itself runs on
    (enterprise_access.ALL_CAPABILITIES / ROLE_PRESETS / SCOPES, enterprise_billing.PLANS /
    TIER_FEATURES / trial and grace constants, enterprise_catalog.CLIENT_STAGES,
    enterprise_credits.actions_payload() / packages_payload(), money.tax_note). A
    `{{PLACEHOLDER}}` line in the guide is replaced by the generated block, so capability
    names, role contents, plan limits, prices, tax wording and credit prices in help answers
    always match the shipping code — including env-var overrides — with no second copy to
    forget.

Since the 2026-10-22 pricing model, every number a customer pays or is limited by lives in a
generated block — the hand-written guide must not restate one (the drift tests scan its raw
text for that). Three rules shape the generators:

  * "+ GST" is printed only when money.tax_note says tax applies. ENTERPRISE_GST_PERCENT=0
    is a live configuration (the owner deferred GST registration); at 0 the help must not
    mention GST at all, exactly like the price cards and checkout.
  * Facts that only exist behind a switch are printed only while the switch is on: yearly
    billing (billing.yearly_enabled()), free Deep Scans (credits.DEEP_SCAN_FREE_SCANS_PER_CLIENT
    > 0), the AI-paused rule (billing.AI_PAUSE_ON_EXPIRY). A help answer promising "2 months
    free" while yearly can't be bought is a support ticket we wrote ourselves.
  * Prices come from the registries' own labels (credits.actions_payload()["price_label"],
    e.g. "4 credits per 15 pages"), never a bare `credits` number — a per-block or per-bundle
    price read as a flat price under-quotes a long PDF by 10x.

Everything here is product documentation, not org data: no DB session, no tenant state,
safe to hand to any signed-in member regardless of capabilities.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger("rilono.enterprise_help")

GUIDE_PATH = Path(__file__).resolve().parent / "prompts" / "ENTERPRISE_HELP_GUIDE.md"

# A rendered topic must fit inside one assistant tool result with headroom below
# enterprise_ai.TOOL_RESULT_CHAR_CAP (14k default) — the result is re-sent on every
# later round of the same turn, so an oversized topic would be billed repeatedly.
TOPIC_CHAR_CAP = 12_000

_SECTION_RE = re.compile(r"^##\s*\[(?P<key>[a-z0-9-]+)\]\s*(?P<title>.+?)\s*$", re.MULTILINE)
# Trailing blanks only — `\s*` here used to swallow the newline after the placeholder, gluing
# the generated block onto the next paragraph of the guide.
_PLACEHOLDER_RE = re.compile(r"^\{\{(?P<name>[A-Z_]+)\}\}[ \t]*$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Generated blocks — one function per {{PLACEHOLDER}}.
#
# These read ONLY module-level registries (plus env-derived constants), never the
# database: the same help text must render identically for every org and every caller.
# ---------------------------------------------------------------------------

def _access_mod():
    from app import enterprise_access
    return enterprise_access


def _billing_mod():
    from app import enterprise_billing
    return enterprise_billing


def _credits_mod():
    from app import enterprise_credits
    return enterprise_credits


def _money_mod():
    from app import money
    return money


def _catalog_mod():
    from app import enterprise_catalog
    return enterprise_catalog


# --- small wording helpers ----------------------------------------------------------------

def _n(value) -> str:
    return f"{int(value):,}"


def _plural(count, word: str) -> str:
    return f"{_n(count)} {word}" + ("" if int(count) == 1 else "s")


def _join(items: list[str], conj: str = "and") -> str:
    """'a', 'a and b', 'a, b and c' (or 'a, b or c' with conj="or")."""
    items = [str(i) for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {conj} " + items[-1]


def _percent(value) -> str:
    """18 -> '18', 12.5 -> '12.5' (Decimal-safe; no trailing '.0')."""
    text = f"{value:f}" if hasattr(value, "as_tuple") else str(value)
    return text.rstrip("0").rstrip(".") if "." in text else text


def _inr(minor: int) -> str:
    return _money_mod().format_money(int(minor or 0), "INR")


def _with_tax_note(text: str) -> str:
    """Append money.tax_note('INR') ("+ GST") — and nothing at a 0% rate. The ONLY way a plan
    price is printed here, so ENTERPRISE_GST_PERCENT=0 removes "+ GST" from every answer."""
    note = _money_mod().tax_note("INR")
    return f"{text} {note}" if note else text


# Display names for the INR-region country codes. Wording only (no price or limit hangs on
# it); an override of ENTERPRISE_INR_REGION_COUNTRIES with a code not listed here prints the
# bare code, which is still correct.
_COUNTRY_NAMES = {
    "IN": "India", "NP": "Nepal", "BD": "Bangladesh", "LK": "Sri Lanka",
    "NG": "Nigeria", "GH": "Ghana", "KE": "Kenya",
}

# How the tier-gated features read in prose, in billing.FEATURE_KEYS order. A key missing
# here (a future feature) still prints, as its key with spaces.
_FEATURE_WORDS = {
    "branches": "multiple offices",
    "custom_roles": "custom roles",
    "branch_reporting": "per-branch reporting",
}


def _feature_words() -> str:
    billing = _billing_mod()
    return _join([_FEATURE_WORDS.get(k, k.replace("_", " ")) for k in billing.FEATURE_KEYS])


def _tier_has_all_features(plan: dict) -> bool:
    billing = _billing_mod()
    tier = billing.TIER_FEATURES.get(plan.get("features_tier") or "starter", frozenset())
    return set(billing.FEATURE_KEYS) <= set(tier)


def _paid_plans_with_features(with_features: bool) -> list[str]:
    """Labels of the PAID plans that do (or don't) include every tier-gated feature."""
    billing = _billing_mod()
    return [
        billing.PLANS[k]["label"] for k in billing.PLAN_ORDER
        if k in billing.PAID_PLAN_KEYS and _tier_has_all_features(billing.PLANS[k]) == with_features
    ]


def _action(key: str) -> dict:
    """One row of credits.actions_payload() — the price list the Credits screen renders, so
    the help quotes the same `price_label` ("4 credits per 15 pages") the customer sees."""
    for row in _credits_mod().actions_payload():
        if row["key"] == key:
            return row
    return {}


# --- generated blocks ------------------------------------------------------------------------

def _capability_matrix_block() -> str:
    """Every permission in the product, grouped exactly as the Roles & Permissions
    matrix groups them, with the same labels and descriptions the UI shows."""
    access = _access_mod()
    lines: list[str] = []
    for section in access.CAPABILITY_SECTIONS:
        lines.append(f"**{section}**")
        for cap in access.ALL_CAPABILITIES:
            if cap["section"] != section:
                continue
            flags = []
            if cap["owner_only"]:
                flags.append("owner-only")
            elif cap["dangerous"]:
                flags.append("high-impact")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"- {cap['label']} (`{cap['key']}`){suffix}: {cap['desc']}")
    lines.append("")
    lines.append(
        "Granting a permission automatically grants what it needs to make sense (e.g. "
        "\"Edit clients\" brings \"View clients\"); an explicit deny always wins over any "
        "grant. \"Owner-only\" permissions can never be held by anyone but the owner. "
        "\"High-impact\" permissions are flagged in the matrix so admins grant them "
        "deliberately."
    )
    return "\n".join(lines)


def _role_presets_block() -> str:
    """The built-in roles as the role picker offers them, with their real descriptions
    and default record scopes — derived from the presets the access checks run on."""
    access = _access_mod()
    lines: list[str] = []
    for key in access.ROLE_KEYS:
        preset = access.ROLE_PRESETS[key]
        if key == access.ROLE_CUSTOM:
            continue  # sentinel, not a shipped role — custom roles are covered in prose
        scope = access.scope_desc(preset["data_scope"]) or preset["data_scope"]
        bits = [f"default data scope: {scope}"]
        if preset["scope_locked"]:
            bits.append("scope locked")
        if not preset["assignable"]:
            bits.append("not assignable from the role picker — ownership moves only via transfer")
        lines.append(f"- **{preset['label']}** (`{key}`) — {preset['description']} ({'; '.join(bits)})")
    return "\n".join(lines)


def _record_scopes_block() -> str:
    """The three data scopes, with the exact wording the scope picker uses."""
    access = _access_mod()
    lines = [
        f"- **{s['label']}** (`{s['key']}`): {s['desc']}" for s in access.SCOPES
    ]
    lines.append(
        "A member can never hand out a scope wider than their own — a branch-scoped "
        "manager cannot create or assign a workspace-wide role."
    )
    return "\n".join(lines)


def _plan_line(key: str, plan: dict) -> str:
    billing = _billing_mod()
    is_trial = key == billing.SANDBOX_PLAN or not plan.get("price_product")
    if is_trial:
        price = "free, no card needed"
        credits_part = f"{plan.get('included_credits', 0):,} AI credits at signup"
        if billing.TRIAL_DEMO_BONUS_CREDITS > 0:
            credits_part += (
                f" (+{_n(billing.TRIAL_DEMO_BONUS_CREDITS)} once, after a demo call with Rilono)"
            )
        reads_part = f"{_n(plan.get('max_reads', 0))} AI document reads for the whole trial"
        features = (
            f"Includes {_feature_words()} while the trial runs."
            if _tier_has_all_features(plan) else ""
        )
    else:
        try:
            price_minor = billing.plan_price_minor(key, "INR")
        except Exception:
            price_minor = 0
        # INR anchor price. The KB renders identically for every org (see the module rule),
        # so it quotes the INR list price rather than any per-org currency; the currency
        # line below covers the rest.
        price = _with_tax_note(f"{_inr(price_minor)}/month")
        recur = "every month" if plan.get("credits_recur") else "one-time"
        credits_part = f"{plan.get('included_credits', 0):,} AI credits {recur}"
        reads_part = f"{_n(plan.get('max_reads', 0))} AI document reads {recur}"
        features = (
            f"Includes {_feature_words()}."
            if _tier_has_all_features(plan)
            else f"One office and the built-in roles ({_feature_words()} are not included)."
        )
    parts = [
        f"- **{plan.get('label', key)}** (`{key}`) — {price}.",
        f"{_plural(plan.get('max_seats', 0), 'staff seat')}, "
        f"{_n(plan.get('max_clients', 0))} open student files, {credits_part}, {reads_part}.",
    ]
    if features:
        parts.append(features)
    if plan.get("tagline") and not is_trial:
        parts.append(f"For: {plan['tagline']}.")
    return " ".join(parts)


def _plans_block() -> str:
    """Current plans with live limits and prices (env overrides included), plus the billing
    rules a buyer asks about: cycle, currency, tax, plan changes, Branch Packs, coupons."""
    billing = _billing_mod()
    money = _money_mod()
    lines: list[str] = []
    if billing.ENTERPRISE_FREE:
        lines.append(
            "Billing is currently switched off by Rilono: no plan is sold and plan limits "
            "aren't enforced. The plans below apply once billing is switched back on."
        )
    for key in billing.PLAN_ORDER:
        plan = billing.PLANS.get(key) or {}
        if plan:
            lines.append(_plan_line(key, plan))
    lines.append(
        "\"Open student files\" are clients in an open stage — finished and paused files "
        "don't count (see the clients topic). Every plan includes every AI feature."
    )

    # Billing cycle. Yearly is described ONLY while it can be bought.
    if billing.yearly_enabled():
        months = int(money.YEARLY_PRICE_MONTHS)
        free = max(0, 12 - months)
        examples = _join([
            f"{billing.PLANS[k]['label']} {_inr(billing.plan_price_minor(k, 'INR', 'yearly'))}"
            for k in billing.PLAN_ORDER if k in billing.PAID_PLAN_KEYS
        ])
        free_note = f" — {free} months free" if free else ""
        lines.append(
            f"Plans are billed monthly or yearly. Yearly costs {months} months' price for 12 "
            f"months{free_note}: " + _with_tax_note(f"{examples} a year") + ". Choose "
            f"\"Yearly\" on Plans & Billing; it is paid once for {billing.YEARLY_PERIOD_DAYS} "
            "days and doesn't renew automatically. Credits and reads still arrive every "
            f"{billing.PLAN_PERIOD_DAYS} days, as on a monthly plan."
        )
    else:
        lines.append(f"Plans are billed monthly (each payment covers {billing.PLAN_PERIOD_DAYS} days).")

    # Currency region rule (billing.charge_currency_for_org). Codes from the live set.
    region_names = sorted(
        _COUNTRY_NAMES.get(c, c) for c in billing.INR_REGION_COUNTRIES if c != "IN"
    )
    others = [c for c in money.supported_charge_currencies() if c != "INR"]
    region_text = (
        f"Workspaces in India and {_join(region_names)} are billed in INR only (outside "
        "India, Plans & Billing also shows an approximate US$ amount)."
        if region_names else "Workspaces in India are billed in INR only."
    )
    # The geo-match sentence only while billing.INR_REQUIRE_GEO_MATCH is on — the guide must
    # not describe a check the server isn't making.
    geo_text = (
        " A workspace set to one of the INR countries but paying from a country outside them "
        "is billed in that country's currency (or USD), not INR."
        if billing.INR_REQUIRE_GEO_MATCH else ""
    )
    lines.append(
        "Prices above are the INR list prices. " + region_text + " Workspaces in any other "
        "country are billed at fixed prices in " + _join(others) + " — their own currency "
        "where it's on that list, otherwise USD — and can't be billed in INR. The country is "
        "the workspace's company location (Settings), or where you are browsing from if none "
        "is set." + geo_text + " Once a plan has been paid for, the company location can only "
        "be changed by Rilono support. Plans & Billing always shows the currency you will "
        "actually be charged in."
    )
    inr_methods = _inr_payment_methods_text()
    if inr_methods:
        lines.append(inr_methods)

    # Tax. Worded from the live rate; at 0% nothing here may say "GST".
    if money.tax_applies("INR"):
        lines.append(
            f"INR prices are before tax: {_percent(money.tax_percent_for('INR'))}% GST is added "
            f"at checkout (shown as \"{money.tax_note('INR')}\" next to the price). Other "
            "currencies are billed without tax (zero-rated exports)."
        )
    else:
        lines.append("No tax is added at checkout: the listed price is the full price, in every currency.")

    # enterprise_credits.sync_plan_credits: trial -> paid is a new period (full grant); a
    # paid -> paid change inside a live period only tops up to the new tier.
    lines.append(
        "Moving from the free trial to a paid plan gives the paid plan's full allowance. "
        "Changing between paid plans in the middle of a period tops your credits and reads up "
        "to the new plan's allowance — it never adds a second full allowance — and a downgrade "
        "takes nothing back for the rest of that period."
    )
    if billing.BRANCH_PACK_FILES > 0:
        top = billing.PLANS[billing.PLAN_ORDER[-1]]
        lines.append(
            f"Bigger networks: above {top['label']}'s {_n(top['max_clients'])} open files, "
            f"Rilono sells Branch Packs by invoice on top of a paid plan. Each adds "
            f"+{_n(billing.BRANCH_PACK_FILES)} open student files, "
            f"+{_n(billing.BRANCH_PACK_SEATS)} staff seats, +{_n(billing.BRANCH_PACK_CREDITS)} "
            f"AI credits and +{_n(billing.BRANCH_PACK_READS)} AI document reads a month — ask "
            "through Help & Support. Rilono can also agree custom limits for a workspace."
        )
    try:
        from app import enterprise_coupons
        cap = enterprise_coupons.max_percent_off()
        lines.append(f"Discount codes Rilono issues take at most {_percent(cap)}% off.")
    except Exception:
        logger.debug("coupon cap unavailable for help text", exc_info=True)
    return "\n".join(lines)


def _inr_payment_methods_text() -> str:
    """D-011: what a rupee price must be paid with (billing.domestic_only_charge), and what
    happens to a card issued outside India — worded from the live INR_FOREIGN_CARD_POLICY, so
    the guide never promises a refusal (or a currency move) the server isn't making."""
    billing = _billing_mod()
    if not billing.INR_DOMESTIC_ONLY:
        return ""
    text = (
        "Workspaces in India pay rupee (INR) prices with an Indian payment method: UPI, "
        "netbanking, or an India-issued card or wallet. Plans & Billing and the top-up "
        "checkout say so whenever INR is the charge currency."
    )
    policy = billing.INR_FOREIGN_CARD_POLICY
    if policy == billing.FOREIGN_CARD_POLICY_REFUND:
        text += (
            " A card issued outside India isn't accepted for a rupee price: the payment isn't "
            "taken (on an auto-renewing plan it is refunded in full and auto-renewal stops) and "
            "nothing changes — the trial or current plan carries on."
        )
    elif policy == billing.FOREIGN_CARD_POLICY_REPRICE:
        text += (
            " A card issued outside India is accepted, but from then on the workspace is billed "
            "in its local currency (or USD) instead of INR, and an auto-renewing plan stops at "
            "the end of the period already paid for. Rilono support can review that for a "
            "business that is in India."
        )
    return text


def _one_trial_per_domain() -> bool:
    """The signup rule's switch (ENTERPRISE_ONE_TRIAL_PER_DOMAIN), read from the router that
    enforces it rather than re-parsing the env var here. Lazy: the router imports the
    assistant, which imports this module."""
    try:
        from app.routers import enterprise as enterprise_router
        return bool(getattr(enterprise_router, "ENTERPRISE_ONE_TRIAL_PER_DOMAIN", True))
    except Exception:
        logger.debug("one-trial-per-domain flag unavailable for help text", exc_info=True)
        return True


def _trial_and_ai_pause_block() -> str:
    """What the free trial includes, what happens when it (or a paid plan) ends, and the
    shared "AI paused" rule — with the exact messages the portal and client links show."""
    billing = _billing_mod()
    trial = billing.trial_facts()
    sandbox = billing.PLANS[billing.SANDBOX_PLAN]
    bonus = (
        f" (+{_n(trial['demo_bonus_credits'])} more, once, after a demo call with Rilono)"
        if int(trial.get("demo_bonus_credits") or 0) > 0 else ""
    )
    features = (
        f", and every feature including {_feature_words()}"
        if _tier_has_all_features(sandbox) else ""
    )
    lines = [
        f"A new workspace starts on the {trial['label']} — no card needed: "
        f"{_plural(trial['max_seats'], 'staff seat')}, {_n(trial['max_open_files'])} open "
        f"student files, {_n(trial['included_credits'])} AI credits{bonus}, "
        f"{_n(trial['reads'])} AI document reads for the whole trial{features}."
    ]
    if _one_trial_per_domain():
        lines.append(
            "One free trial per company: if someone at your company's email domain (not a "
            "public mailbox such as Gmail or Outlook) already has a Rilono workspace, a new "
            "workspace starts with its trial already used — choose a plan to continue."
        )
    if billing.AI_PAUSE_ON_EXPIRY:
        lapsed_example = billing.AI_PAUSED_LAPSED_MESSAGE.format(plan=billing.PLANS["starter"]["label"])
        lines.append(
            "When the trial ends, adding clients and staff stops and AI features pause. The "
            f"portal says: \"{billing.AI_PAUSED_TRIAL_MESSAGE}\""
        )
        lines.append(
            f"A paid plan that isn't renewed within {_plural(billing.PLAN_GRACE_DAYS, 'day')} of "
            "its period ending lapses the same way, e.g. "
            f"\"{lapsed_example}\""
        )
        lines.append(
            "While AI is paused, every AI feature stops before anything runs or is charged: the "
            "assistant (including the Chrome extension), document checks, Deep Scan, Writing "
            "Studio, Course Finder and university shortlists, mock interviews, and clients' "
            "Copilot and interview links (the client sees "
            f"\"{billing.AI_PAUSED_CLIENT_MESSAGE}\"). Uploads still work: the file is stored "
            "\"Not read yet\" and can be read later with \"Read now\"."
        )
        lines.append(
            "Nothing is deleted and everything stays readable. Choosing (or renewing) a plan on "
            "Plans & Billing turns AI back on straight away. Credit top-ups can't be bought "
            "while AI is paused — a top-up adds to an active plan or a running trial."
        )
    else:
        lines.append(
            "When the trial ends — or a paid plan isn't renewed within "
            f"{_plural(billing.PLAN_GRACE_DAYS, 'day')} of its period ending — adding clients "
            "and staff stops until a plan is chosen; AI features keep working. Nothing is "
            "deleted and everything stays readable."
        )
    return "\n".join(lines)


def _open_files_block() -> str:
    """What counts toward the plan's open-file limit, the Closed stage, the over-limit
    grace period and the reopen rule — from the stage catalog and the billing constants."""
    billing = _billing_mod()
    catalog = _catalog_mod()
    open_labels = [s["label"] for s in catalog.CLIENT_STAGES if s["is_open"]]
    not_open = [s["label"] for s in catalog.CLIENT_STAGES if not s["is_open"]]
    lines = [
        "Plans are sized by open student files: clients in an open stage "
        f"({_join(open_labels)}). {_join(not_open)} files don't count, and every client stays "
        "in the workspace whatever its stage."
    ]
    closed = catalog.CLIENT_STAGE_MAP.get(getattr(catalog, "STAGE_CLOSED", "closed"))
    if closed:
        lines.append(
            "To finish a file that ended without a visa outcome — the student withdrew, "
            f"deferred or went elsewhere — move it to \"{closed['label']}\": "
            f"\"{closed['description']}\""
        )
    grace = int(billing.FILE_LIMIT_GRACE_DAYS)
    if grace > 0:
        lines.append(
            "Going over the open-file limit doesn't stop you straight away: you can keep adding "
            f"for {_plural(grace, 'day')} from the first add that takes you over (the portal "
            "shows the date). After that, adding pauses until you're back within the limit — "
            "close files you've finished, or upgrade. Once you're back within the limit, the "
            "next time you go over starts a fresh grace period."
        )
    else:
        lines.append(
            "The open-file limit is a hard limit: at the limit, adding a file asks you to close "
            "files you've finished or upgrade."
        )
    lines.append(
        f"Reopening a file — moving it from {_join(not_open)} back into an open stage — counts "
        "as adding one, so the same limit applies. Once the free trial has ended, no file can "
        "be added or reopened until a plan is chosen."
    )
    lines.append(
        "Staff seats are a hard limit with no grace period: inviting past it asks for an "
        "upgrade, and deactivating a member frees their seat."
    )
    return "\n".join(lines)


def _reads_block() -> str:
    """The monthly AI document reading allowance: per-plan numbers, the 15-page unit, the
    per-document cap, 'Not read yet' / 'Read now', and why a paid check doesn't use reads."""
    billing = _billing_mod()
    credits = _credits_mod()
    pages = int(credits.DOCUMENT_BLOCK_PAGES)
    parts = []
    for key in billing.PLAN_ORDER:
        plan = billing.PLANS.get(key) or {}
        if not plan:
            continue
        span = "a month" if plan.get("credits_recur") else "for the whole trial"
        parts.append(f"{plan['label']} {_n(plan.get('max_reads', 0))} {span}")
    lines = [
        "Rilono AI reads every uploaded document for free (so the assistant, Deep Scan and "
        "the other AI features can use it), from the plan's AI document reads: "
        + _join(parts) + "."
    ]
    if billing.BRANCH_PACK_READS > 0:
        lines[-1] += f" Each Branch Pack adds +{_n(billing.BRANCH_PACK_READS)} reads a month."
    max_blocks = None
    try:
        from app.utils import gemini_service
        max_blocks = int(gemini_service.ENTERPRISE_READ_MAX_BLOCKS)
    except Exception:
        logger.debug("reader block cap unavailable for help text", exc_info=True)
    unit = (
        f"One read covers up to {pages} pages: a {pages * 2}-page PDF uses 2 reads, and an "
        "image or text file uses 1."
    )
    if max_blocks:
        unit += (
            f" Only the first {_n(max_blocks * pages)} pages of a longer document are read "
            f"(at most {_plural(max_blocks, 'read')} per document)."
        )
    lines.append(unit)
    lines.append(
        "Monthly reads refresh when the plan period renews; unused reads don't carry over. "
        "Plans & Billing and the Credits screen show how many are left."
    )
    lines.append(
        "When the reads run out — or AI is paused — the upload still succeeds: the document is "
        "stored with a \"Not read yet\" badge. Click \"Read now\" on it once reads are available "
        "again (the next month, or after an upgrade); it uses the same number of reads, and a "
        "document that needs more reads than you have left isn't read in part. A read that "
        "fails shows \"Read failed\", gives its reads back and can be retried with \"Read now\"."
    )
    lines.append(
        "A paid document check (\"Scan & validate with Rilono AI\") reads the file itself and "
        "never uses reads."
    )
    return "\n".join(lines)


def _team_features_block() -> str:
    """Which plans include offices, custom roles and per-branch reporting, and exactly what
    is gated on the others (billing.FEATURE_KEYS / TIER_FEATURES).

    Kept short on purpose: it is expanded inside the team-access topic, which also carries
    the whole capability matrix and must stay under TOPIC_CHAR_CAP."""
    billing = _billing_mod()
    team_plans = _paid_plans_with_features(True)
    other_plans = _paid_plans_with_features(False)
    trial_has = _tier_has_all_features(billing.PLANS[billing.SANDBOX_PLAN])
    words = _feature_words()
    lines = [
        f"{words[:1].upper()}{words[1:]} are part of the {_join(team_plans)} "
        f"plan{'s' if len(team_plans) != 1 else ''}"
        + (" and the free trial while it runs" if trial_has else "") + "."
    ]
    if other_plans:
        lines.append(
            f"On {_join(other_plans)}: one office (the default head office, still editable) and "
            "the built-in roles. Adding, editing or archiving other offices, creating or editing "
            "custom roles, giving a member extra Allow/Block permissions, and filtering the "
            "dashboard or client list by office ask you to upgrade."
        )
    lines.append(
        "Nothing is taken away on a lower plan: existing offices and custom roles keep working, "
        "and members and clients can still be assigned to them."
    )
    return "\n".join(lines)


def _credit_pricing_block() -> str:
    """What each AI action costs, straight from the wallet's own price list (the same
    `price_label` the Credits screen shows), plus packs, free allowances and the top-up rule."""
    billing = _billing_mod()
    credits = _credits_mod()
    lines: list[str] = []
    for action in credits.actions_payload():
        lines.append(f"- **{action['label']}** — {action['price_label']}. {action['description']}")
    lines.append("")
    lines.append("Credit top-up packs (bought under Credits; INR prices shown, other currencies have their own fixed prices):")
    for pack in credits.packages_payload("INR"):
        bonus = f" (includes {_n(pack['bonus_credits'])} bonus)" if pack.get("bonus_credits") else ""
        lines.append(
            f"- **{pack['label']}** — {pack['amount_display']} for {_n(pack['total_credits'])} "
            f"credits{bonus}."
        )
    lines.append("")
    copilot = _action(credits.COPILOT_ACTION_KEY)
    free = [
        f"{credits.COPILOT_FREE_DAILY} AI assistant messages per workspace per day (then "
        f"{copilot.get('price_label') or 'credits'}; a question that needs several lookups can "
        "count as more than one message)"
    ]
    if credits.DEEP_SCAN_FREE_SCANS_PER_CLIENT > 0:
        free.append(
            f"each client's first {_plural(credits.DEEP_SCAN_FREE_SCANS_PER_CLIENT, 'Deep Scan')} "
            f"(at most {credits.DEEP_SCAN_FREE_MONTHLY_ORG_CAP} free Deep Scans per workspace "
            "per month)"
        )
    if credits.INTERVIEW_FREE_STAFF_PREVIEWS > 0:
        free.append(
            f"{credits.INTERVIEW_FREE_STAFF_PREVIEWS} free staff mock-interview previews per "
            "workspace"
        )
    lines.append(
        f"1 credit = {credits.format_inr(credits.PAISE_PER_CREDIT)}. Free before anything is "
        "charged: " + _join(free) + "."
    )
    if credits.DEEP_SCAN_FREE_SCANS_PER_CLIENT <= 0:
        lines.append("Every Deep Scan is charged — there are no free scans.")
    lines.append(
        "When the wallet can only cover part of an assistant question, the assistant answers "
        "with what it has instead of doing more lookups. A mock interview is charged once per "
        "session, when the officer's first question is ready — a start that fails costs "
        "nothing — and the session ends with one feedback report."
    )
    if credits.PLAN_CREDITS_ROLLOVER:
        lines.append(
            "Plan credits arrive with the subscription each period (the trial's once) and "
            "unspent plan credits carry over. Purchased credits never expire while the "
            "workspace is active."
        )
    else:
        lines.append(
            "Plan credits arrive with the subscription each period (the trial's once); "
            "unspent plan credits expire when the period renews. Purchased credits never "
            "expire while the workspace is active."
        )
    if billing.AI_PAUSE_ON_EXPIRY:
        lines.append(
            "Top-ups add to an active plan or a running free trial: they can't be bought while "
            "AI is paused (trial ended or plan lapsed) — choose or renew a plan first."
        )
    return "\n".join(lines)


def _client_link_terms_block() -> str:
    """Price, allowance and lifetime of the two PAID client links, from the price list and
    the constants the link endpoints enforce (credits.COPILOT_CLIENT_* / INTERVIEW_MAX_QUESTIONS)."""
    billing = _billing_mod()
    credits = _credits_mod()
    copilot = _action(credits.COPILOT_CLIENT_ACTION_KEY)
    interview = _action("mock_interview")
    lines = [
        f"- Client Copilot link: {copilot.get('price_label', '')}, charged once when the client "
        "first opens it (an unopened link costs nothing). It allows up to "
        f"{_plural(credits.COPILOT_CLIENT_MESSAGES, 'message')} over "
        f"{_plural(credits.COPILOT_CLIENT_DAYS, 'day')}.",
        f"- Mock interview invite: {interview.get('price_label', '')} the client takes. Each "
        f"interview is one session of up to {_plural(credits.INTERVIEW_MAX_QUESTIONS, 'officer question')} "
        "and one feedback report, charged once the officer's first question is ready; a start "
        "that fails costs nothing and doesn't use up the invite.",
    ]
    if billing.AI_PAUSE_ON_EXPIRY:
        lines.append(
            "While the workspace's AI is paused (trial ended or plan lapsed), these links show "
            f"the client: \"{billing.AI_PAUSED_CLIENT_MESSAGE}\""
        )
    return "\n".join(lines)


def _workspace_limits_block() -> str:
    """Product guardrails that show up as 'why can't I add another…' questions."""
    access = _access_mod()
    billing = _billing_mod()
    team_plans = _paid_plans_with_features(True)
    grace = int(billing.FILE_LIMIT_GRACE_DAYS)
    over_files = (
        f"adding past the open-file limit is allowed for {_plural(grace, 'day')}, then asks "
        "you to close finished files or upgrade (see the clients topic)"
        if grace > 0 else
        "adding past the open-file limit asks you to close finished files or upgrade"
    )
    return (
        f"- Up to {access.MAX_CUSTOM_ROLES} custom roles and {access.MAX_BRANCHES} offices "
        f"per workspace; offices beyond the first and custom roles need a "
        f"{_join(team_plans, 'or')} plan (see the plans list).\n"
        "- Staff seats and open student files come from the plan (see the plans list): "
        f"inviting past the seat limit asks for an upgrade; {over_files}.\n"
        "- Exactly one owner per workspace; ownership moves only through Transfer ownership."
    )


_GENERATORS = {
    "CAPABILITY_MATRIX": _capability_matrix_block,
    "ROLE_PRESETS": _role_presets_block,
    "RECORD_SCOPES": _record_scopes_block,
    "PLANS": _plans_block,
    "TRIAL_AND_AI_PAUSE": _trial_and_ai_pause_block,
    "OPEN_FILES": _open_files_block,
    "AI_READS": _reads_block,
    "TEAM_FEATURES": _team_features_block,
    "CREDIT_PRICING": _credit_pricing_block,
    "CLIENT_LINK_TERMS": _client_link_terms_block,
    "WORKSPACE_LIMITS": _workspace_limits_block,
}


# ---------------------------------------------------------------------------
# Guide parsing
# ---------------------------------------------------------------------------

_cache: dict = {"mtime": None, "topics": None}


def _parse_guide(text: str) -> dict[str, dict]:
    """Split the guide into {key: {title, body}} by `## [key] Title` headings."""
    topics: dict[str, dict] = {}
    matches = list(_SECTION_RE.finditer(text))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        topics[m.group("key")] = {
            "key": m.group("key"),
            "title": m.group("title").strip(),
            "body": text[start:end].strip(),
        }
    return topics


def _topics() -> dict[str, dict]:
    """Parsed guide, re-read when the file changes (cheap stat; instant help edits in dev)."""
    try:
        mtime = GUIDE_PATH.stat().st_mtime
    except OSError:
        logger.warning("Enterprise help guide missing at %s", GUIDE_PATH)
        return {}
    if _cache["topics"] is None or _cache["mtime"] != mtime:
        _cache["topics"] = _parse_guide(GUIDE_PATH.read_text(encoding="utf-8"))
        _cache["mtime"] = mtime
    return _cache["topics"]


def _expand(body: str) -> str:
    def _sub(m: re.Match) -> str:
        gen = _GENERATORS.get(m.group("name"))
        if gen is None:
            logger.warning("Enterprise help guide uses unknown placeholder %s", m.group(0))
            return ""
        try:
            return gen()
        except Exception:
            # A broken generator must degrade to a gap in the help text, never a 500 in
            # the assistant turn.
            logger.warning("Enterprise help generator %s failed", m.group("name"), exc_info=True)
            return ""
    return _PLACEHOLDER_RE.sub(_sub, body)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def topic_keys() -> list[str]:
    return list(_topics().keys())


def topics_index() -> list[dict]:
    """[{key, title, summary}] — summary is the section's first paragraph line."""
    out = []
    for t in _topics().values():
        first_line = next((ln.strip() for ln in t["body"].splitlines() if ln.strip()), "")
        out.append({"key": t["key"], "title": t["title"], "summary": first_line})
    return out


def render_topic(key: str) -> Optional[dict]:
    """One topic with its generated blocks expanded, bounded for a tool result."""
    topic = _topics().get(str(key or "").strip().lower())
    if not topic:
        return None
    content = _expand(topic["body"])
    if len(content) > TOPIC_CHAR_CAP:
        content = content[:TOPIC_CHAR_CAP] + "\n[…truncated — ask about a more specific part of this topic…]"
    return {"key": topic["key"], "title": topic["title"], "content": content}


def full_guide_text() -> str:
    """Every topic rendered — for the drift tests, not for prompts."""
    return "\n\n".join(
        f"## {t['title']}\n{_expand(t['body'])}" for t in _topics().values()
    )


def topics_overview_block() -> str:
    """One line per topic for the assistant's system instruction, so the model knows
    what product help it can look up without carrying the whole guide every turn."""
    lines = [f"- {t['key']}: {t['title']}" for t in _topics().values()]
    return "\n".join(lines)
