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
    (enterprise_access.ALL_CAPABILITIES / ROLE_PRESETS / SCOPES, enterprise_billing.PLANS,
    enterprise_credits.ACTIONS / PACKAGES). A `{{PLACEHOLDER}}` line in the guide is
    replaced by the generated block, so capability names, role contents, plan limits and
    credit prices in help answers always match the shipping code — including env-var
    overrides — with no second copy to forget.

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
_PLACEHOLDER_RE = re.compile(r"^\{\{(?P<name>[A-Z_]+)\}\}\s*$", re.MULTILINE)


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


def _plans_block() -> str:
    """Current plans with live limits and prices (env overrides included)."""
    billing = _billing_mod()
    from app import money as money_mod
    lines: list[str] = []
    for key in billing.PLAN_ORDER:
        plan = billing.PLANS.get(key) or {}
        price_paise = plan.get("monthly_paise")
        if price_paise is None:
            try:
                price_paise = billing.plan_amount_paise(key)
            except Exception:
                price_paise = 0
        # INR anchor price. The KB renders identically for every org (see the module
        # rule), so it quotes the INR list price rather than any per-org currency; the
        # ladder note below covers the rest.
        price = (
            "Free" if not price_paise
            else f"{money_mod.format_money(price_paise, 'INR')}/month + GST"
        )
        recur = "every month" if plan.get("credits_recur") else "one-time"
        lines.append(
            f"- **{plan.get('label', key)}** (`{key}`) — {price}. "
            f"{plan.get('max_seats')} team seats, up to {plan.get('max_clients')} active clients, "
            f"{plan.get('included_credits'):,} AI credits ({recur}). {plan.get('tagline', '')}"
        )
    other_codes = [c for c in money_mod.supported_charge_currencies() if c != "INR"]
    lines.append(
        "Paid plans can also be billed in " + ", ".join(other_codes) + " at fixed "
        "per-currency prices (pick the billing currency on the Plans & Billing screen "
        "at checkout). GST applies only to INR billing; other currencies are zero-rated "
        "exports with no tax line."
    )
    lines.append(
        f"Plans renew every {billing.PLAN_PERIOD_DAYS} days with a {billing.PLAN_GRACE_DAYS}-day "
        "grace period. Managed under Credits & Billing by anyone with the \"Plans & subscription\" "
        "permission."
    )
    return "\n".join(lines)


def _credit_pricing_block() -> str:
    """What each AI action costs, straight from the wallet's own price table."""
    credits = _credits_mod()
    lines: list[str] = []
    for action in credits.ACTIONS.values():
        lines.append(f"- **{action['label']}** — {action['credits']} credit(s). {action['description']}")
    lines.append("")
    lines.append("Credit top-up packs (bought under Credits & Billing):")
    for key in credits.PACKAGE_ORDER:
        pack = credits.PACKAGES.get(key) or {}
        total = int(pack.get("credits") or 0) + int(pack.get("bonus_credits") or 0)
        bonus = f" (includes {pack['bonus_credits']} bonus)" if pack.get("bonus_credits") else ""
        lines.append(
            f"- **{pack.get('label', key)}** — ₹{int(pack.get('amount_paise') or 0) / 100:,.0f} "
            f"for {total} credits{bonus}."
        )
    lines.append(
        f"1 credit = ₹{credits.PAISE_PER_CREDIT / 100:,.0f}. Free allowances before anything is "
        f"charged: {credits.COPILOT_FREE_DAILY} AI assistant messages per workspace per day "
        f"(then 1 credit per {credits.COPILOT_MSGS_PER_CREDIT} messages), "
        f"{credits.DEEP_SCAN_FREE_MONTHLY_ORG_CAP} free Deep Scans per workspace per month "
        f"(each client's first scan free), and "
        f"{credits.INTERVIEW_FREE_STAFF_PREVIEWS} free staff mock-interview previews. "
        "Plan credits arrive with the subscription; purchased credits never expire while the "
        "workspace is active."
    )
    return "\n".join(lines)


def _workspace_limits_block() -> str:
    """Product guardrails that show up as 'why can't I add another…' questions."""
    access = _access_mod()
    return (
        f"- Up to {access.MAX_CUSTOM_ROLES} custom roles and {access.MAX_BRANCHES} offices "
        "per workspace.\n"
        "- Team seats and active-client limits come from the plan (see the plans list): "
        "inviting past the seat limit or adding clients past the client limit asks for an "
        "upgrade.\n"
        "- Exactly one owner per workspace; ownership moves only through Transfer ownership."
    )


_GENERATORS = {
    "CAPABILITY_MATRIX": _capability_matrix_block,
    "ROLE_PRESETS": _role_presets_block,
    "RECORD_SCOPES": _record_scopes_block,
    "PLANS": _plans_block,
    "CREDIT_PRICING": _credit_pricing_block,
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
