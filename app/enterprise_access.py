"""
Rilono Enterprise access control — capabilities, role presets and scope resolution.

A consultancy is not a flat team. The owner signs the cheques, a branch manager runs
one office, a counsellor works their own caseload, and an accountant should see money
without ever opening a passport scan. The three legacy booleans
(`can_view_data` / `can_edit_data` / `can_manage_users`) cannot express any of that, so
this module replaces them with two orthogonal axes:

  * WHAT a member may do  → a set of fine-grained capability keys ("clients.edit").
  * WHICH records they may do it to → a data scope ("all" | "branch" | "assigned").

Everything here is deliberately declarative and (almost) pure:

  1. A frozen capability registry (§ CAPABILITY REGISTRY) — the single list of every
     permission the product has, with the UI copy that describes it.
  2. Role presets defined in CODE, never as rows (§ ROLE PRESETS). Presets are product
     decisions; storing them would let a bad migration silently widen everyone's access,
     and would make "what does Counsellor mean?" un-reviewable in a diff.
  3. A resolution engine (§ RESOLUTION ENGINE) that folds preset + custom role +
     per-member grants/denies + office assignments into one immutable `AccessContext`.

Design rules that the rest of the platform depends on — change them only deliberately:

  * FAIL CLOSED. Every unknown, malformed or missing value resolves to *less* access,
    never more: unknown role → Viewer, unknown scope → "assigned", unparseable JSON →
    no capabilities, an archived custom role → contributes nothing.
  * NEVER LOCK THE OWNER OUT. The owner short-circuits every check, so a mis-saved deny
    list can never leave a workspace with nobody able to fix it.
  * DENY IS THE LAST WORD (except for `BASE_CAPABILITIES`, which nothing can remove
    because the app cannot render at all without them).
  * NO ROUTER IMPORTS. `app.routers.enterprise` imports this module, so importing
    anything from `app.routers.*` here would be a circular import. This module only
    ever touches `app.models`.

The router owns the HTTP gate and record-level query scoping; this module owns the
*answer* to "what may this member do, and to which records".
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy.orm import Session

from app import models

logger = logging.getLogger(__name__)


# ===========================================================================
# CAPABILITY REGISTRY
#
# One entry per permission the product actually enforces. `label` and `desc` are
# USER-FACING copy: they are rendered verbatim in the permission matrix and reused
# inside 403 messages, so they read as plain English an agency owner understands —
# never as endpoint names.
#
# `section` groups the matrix; SECTION ORDER BELOW IS THE UI ORDER.
# `dangerous` draws the amber warning rail (money, deletion, bulk email, raw files).
# `owner_only` means the capability is structurally unavailable to anyone but the
#   workspace owner — it is stripped in effective_capabilities(), so even a hand-edited
#   grant row cannot deliver it.
# ===========================================================================

_CAP_CLIENTS = "Clients"
_CAP_CASEWORK = "Case work"
_CAP_COMMS = "Communication"
_CAP_DOCS = "Documents"
_CAP_AI = "AI & credits"
_CAP_MONEY = "Money"
_CAP_WORKSPACE = "Workspace"


def _cap(
    key: str,
    label: str,
    desc: str,
    section: str,
    *,
    dangerous: bool = False,
    owner_only: bool = False,
) -> dict:
    return {
        "key": key,
        "label": label,
        "desc": desc,
        "section": section,
        "dangerous": bool(dangerous),
        "owner_only": bool(owner_only),
    }


ALL_CAPABILITIES: tuple[dict, ...] = (
    # --- Clients -----------------------------------------------------------
    _cap("dashboard.view", "View dashboard",
         "Pipeline KPIs, approval rate and revenue roll-ups.", _CAP_CLIENTS),
    _cap("clients.view", "View clients",
         "Open the client list and client records within their data scope.", _CAP_CLIENTS),
    _cap("clients.view_sensitive", "View sensitive fields",
         "Passport number and other identity fields.", _CAP_CLIENTS, dangerous=True),
    _cap("clients.create", "Add clients",
         "Create a new client record.", _CAP_CLIENTS),
    _cap("clients.edit", "Edit clients",
         "Change client details, stage and per-stage case record.", _CAP_CLIENTS),
    _cap("clients.assign", "Assign clients",
         "Set or change the counsellor a case belongs to.", _CAP_CLIENTS),
    _cap("clients.set_branch", "Move clients between offices",
         "Change which office a client belongs to.", _CAP_CLIENTS, dangerous=True),
    _cap("clients.delete", "Delete clients",
         "Permanently delete a client and everything attached.", _CAP_CLIENTS, dangerous=True),
    _cap("catalog.view", "View dropdown data",
         "Country, visa and stage option lists. Everyone needs this.", _CAP_CLIENTS),

    # --- Case work ---------------------------------------------------------
    _cap("notes.view", "View notes",
         "Read the case timeline.", _CAP_CASEWORK),
    _cap("notes.write", "Add notes",
         "Add notes, and delete their own.", _CAP_CASEWORK),
    _cap("notes.moderate", "Delete anyone's notes",
         "Remove notes written by colleagues.", _CAP_CASEWORK, dangerous=True),
    _cap("calendar.view", "View calendar",
         "Appointments, deadlines and reminders in scope.", _CAP_CASEWORK),
    _cap("calendar.manage", "Manage calendar",
         "Create, edit and delete calendar events.", _CAP_CASEWORK),
    _cap("universities.view", "View shortlist",
         "The client's university shortlist.", _CAP_CASEWORK),
    _cap("universities.manage", "Manage shortlist",
         "Add, update and remove shortlist entries.", _CAP_CASEWORK),
    _cap("coursefinder.view", "Browse course catalog",
         "Free university and course catalog browse.", _CAP_CASEWORK),
    _cap("interviews.view", "View mock interviews",
         "Past sessions, transcripts and feedback.", _CAP_CASEWORK),
    _cap("interviews.run", "Run mock interviews",
         "Conduct a staff mock interview. Spends credits.", _CAP_CASEWORK),
    _cap("interviews.invite", "Send interview invites",
         "Email a client a self-serve mock interview link.", _CAP_CASEWORK),
    _cap("portal.share", "Share client portal",
         "Email a client a view-only portal link.", _CAP_CASEWORK),
    _cap("copilot.invite", "Share client copilot",
         "Email a client their own Copilot chat link. Spends credits.", _CAP_CASEWORK),

    # --- Communication -----------------------------------------------------
    _cap("emails.view", "View email history",
         "The email thread with a client.", _CAP_COMMS),
    _cap("emails.send", "Send emails",
         "Email a client from the workspace.", _CAP_COMMS),
    _cap("emails.send_bulk", "Send bulk emails",
         "Email many clients at once.", _CAP_COMMS, dangerous=True),
    _cap("notifications.view", "Notifications",
         "Their own bell feed. Everyone.", _CAP_COMMS),
    _cap("support.request", "Contact Rilono support",
         "Raise a support ticket.", _CAP_COMMS),
    _cap("support.manage", "Manage support tickets",
         "Read every ticket the workspace has raised.", _CAP_COMMS),

    # --- Documents ---------------------------------------------------------
    _cap("documents.view", "View documents",
         "See the document list and AI verdicts.", _CAP_DOCS),
    _cap("documents.download", "Download documents",
         "Download raw files: passports, bank letters, transcripts.", _CAP_DOCS, dangerous=True),
    _cap("documents.upload", "Upload documents",
         "Add documents to a client record.", _CAP_DOCS),
    _cap("documents.accept", "Accept documents",
         "Approve a document; writes extracted fields onto the client.", _CAP_DOCS),
    _cap("documents.delete", "Delete documents",
         "Remove a document and its file.", _CAP_DOCS, dangerous=True),
    _cap("documents.request", "Request documents",
         "Email a client a secure upload link.", _CAP_DOCS),

    # --- AI & credits ------------------------------------------------------
    _cap("ai.assistant", "Rilono AI Assistant",
         "Ask the workspace assistant questions.", _CAP_AI),
    _cap("ai.shortlist", "AI university shortlist",
         "Generate AI university matches.", _CAP_AI),
    _cap("ai.coursefinder", "AI course shortlist",
         "Run the grounded course-finder shortlist.", _CAP_AI),
    _cap("ai.writing", "Writing Studio",
         "Generate and refine SOPs and LORs.", _CAP_AI),
    _cap("ai.deepscan", "Deep Scan",
         "Run the full-dossier AI audit.", _CAP_AI),
    _cap("credits.spend", "Spend credits",
         "Required on top of any AI action that debits the wallet.", _CAP_AI, dangerous=True),
    _cap("credits.view", "View credit balance",
         "Wallet balance and the usage ledger.", _CAP_AI),
    _cap("credits.purchase", "Buy credits",
         "Top up the credit wallet.", _CAP_AI, dangerous=True),

    # --- Money -------------------------------------------------------------
    _cap("finance.view", "View payments",
         "Payment requests and receipts for clients in scope.", _CAP_MONEY),
    _cap("finance.manage", "Manage payments",
         "Raise invoices, record offline payments, resend pay links.", _CAP_MONEY, dangerous=True),
    _cap("finance.refund", "Issue refunds",
         "Move real money back out to a student.", _CAP_MONEY, dangerous=True, owner_only=True),
    _cap("finance.payout_account", "Payout bank account",
         "Set where all settlement money lands.", _CAP_MONEY, dangerous=True, owner_only=True),
    _cap("finance.books", "Company books",
         "Profit & loss, expenses, receivables and cash position.", _CAP_MONEY, dangerous=True),
    _cap("finance.books_manage", "Edit company books",
         "Add and change income and expense entries.", _CAP_MONEY, dangerous=True),
    _cap("finance.export", "Export financial data",
         "Download ledgers and accounting exports.", _CAP_MONEY, dangerous=True),
    _cap("billing.manage", "Plans & subscription",
         "Choose and pay for the workspace plan, and manage the subscription.", _CAP_MONEY,
         dangerous=True),

    # --- Workspace ---------------------------------------------------------
    _cap("team.view", "View team",
         "The staff directory.", _CAP_WORKSPACE),
    _cap("team.manage", "Manage team",
         "Invite, edit, deactivate and remove members.", _CAP_WORKSPACE, dangerous=True),
    _cap("roles.manage", "Manage roles & permissions",
         "Create roles and change what members can do.", _CAP_WORKSPACE, dangerous=True),
    _cap("branches.view", "View offices",
         "The office list.", _CAP_WORKSPACE),
    _cap("branches.manage", "Manage offices",
         "Add, rename, archive offices and move clients between them.", _CAP_WORKSPACE,
         dangerous=True),
    _cap("settings.manage", "Workspace settings",
         "Company name, logo, location and workspace URL.", _CAP_WORKSPACE, dangerous=True),
    _cap("audit.view", "View access log",
         "Who changed permissions, roles and offices.", _CAP_WORKSPACE),
    _cap("org.legal_accept", "Accept legal agreements",
         "Accept the Data Processing Agreement.", _CAP_WORKSPACE, dangerous=True),
    _cap("org.transfer_ownership", "Transfer ownership",
         "Hand the workspace owner role to someone else.", _CAP_WORKSPACE,
         dangerous=True, owner_only=True),
)

CAPABILITY_BY_KEY: dict[str, dict] = {c["key"]: c for c in ALL_CAPABILITIES}
CAPABILITY_KEYS: frozenset[str] = frozenset(CAPABILITY_BY_KEY)

# UI section order, derived from the registry so the two can never drift apart.
CAPABILITY_SECTIONS: tuple[str, ...] = tuple(
    dict.fromkeys(c["section"] for c in ALL_CAPABILITIES)
)

DANGEROUS_CAPABILITIES: frozenset[str] = frozenset(
    c["key"] for c in ALL_CAPABILITIES if c["dangerous"]
)

# Only these three are pinned to the owner. Deliberately NOT owner-only:
#   * `billing.manage` — pinning it would block client creation past the free student
#     limit for any workspace whose owner has stopped logging in.
#   * `org.legal_accept` — pinning it would make the DPA banner permanently unclearable.
# Both are still `dangerous`, so they are visibly gated in the matrix.
OWNER_ONLY_CAPABILITIES: frozenset[str] = frozenset(
    c["key"] for c in ALL_CAPABILITIES if c["owner_only"]
)

# Undeniable. Without the option lists every dropdown in the app renders empty (so the
# client form 400s on save), and without the bell feed the topbar throws. These are not
# "permissions" in any product sense — they are the chrome the SPA needs to boot — so no
# preset, deny list or archived role may remove them.
#
# `support.request` is deliberately NOT here even though everyone gets it: it is an
# outbound email channel that accepts attachments, so it has to stay revocable. Every
# preset grants it explicitly instead.
BASE_CAPABILITIES: frozenset[str] = frozenset({"catalog.view", "notifications.view"})


# ---------------------------------------------------------------------------
# Implications: granting X necessarily grants Y.
#
# These exist so the permission matrix behaves the way a human expects. Ticking
# "Edit clients" without "View clients" would produce a member who can PATCH a record
# they cannot open — a nonsense state that reads as a bug, so the closure below removes
# it from the space of possible configurations. The relation is applied transitively:
# `clients.delete → clients.edit → clients.view`.
#
# `credits.spend` is deliberately NOT implied by any `ai.*` key or `interviews.run`.
# It is checked independently on every wallet-debiting endpoint, which makes it a real
# kill-switch: an owner can leave the AI features visible and still stop a member from
# burning credits. Folding it into the AI grants would quietly disarm that.
# ---------------------------------------------------------------------------

IMPLIES: dict[str, frozenset[str]] = {
    "clients.edit": frozenset({"clients.view"}),
    "clients.create": frozenset({"clients.view"}),
    "clients.delete": frozenset({"clients.edit"}),
    "clients.assign": frozenset({"clients.edit"}),
    "clients.set_branch": frozenset({"clients.edit"}),
    "notes.write": frozenset({"notes.view"}),
    "notes.moderate": frozenset({"notes.write"}),
    "emails.send": frozenset({"emails.view"}),
    "emails.send_bulk": frozenset({"emails.send"}),
    "documents.upload": frozenset({"documents.view"}),
    "documents.download": frozenset({"documents.view"}),
    "documents.delete": frozenset({"documents.view"}),
    "documents.accept": frozenset({"documents.view"}),
    "documents.request": frozenset({"documents.view", "emails.send"}),
    "universities.manage": frozenset({"universities.view"}),
    "calendar.manage": frozenset({"calendar.view"}),
    "interviews.run": frozenset({"interviews.view"}),
    "interviews.invite": frozenset({"interviews.view", "emails.send"}),
    "portal.share": frozenset({"clients.view", "emails.send"}),
    "copilot.invite": frozenset({"clients.view", "emails.send"}),
    "finance.manage": frozenset({"finance.view"}),
    "finance.refund": frozenset({"finance.manage"}),
    "finance.books_manage": frozenset({"finance.books"}),
    "finance.export": frozenset({"finance.books"}),
    "team.manage": frozenset({"team.view"}),
    "roles.manage": frozenset({"team.view"}),
    "branches.manage": frozenset({"branches.view"}),
    "credits.purchase": frozenset({"credits.view"}),
    "support.manage": frozenset({"support.request"}),
}


def expand_implied(keys: Iterable[str] | None) -> frozenset[str]:
    """Transitive closure of `keys` under IMPLIES.

    Iterates to a fixed point rather than recursing, so a future cycle in IMPLIES
    (`a → b → a`) terminates instead of blowing the stack. The loop counter is a
    belt-and-braces guard: the closure can only grow, and it is bounded by the
    registry size, so it always converges well before the cap.
    """
    current = {k for k in (keys or ()) if k in CAPABILITY_KEYS}
    for _ in range(len(CAPABILITY_KEYS) + 1):
        grown = set(current)
        for key in current:
            grown |= IMPLIES.get(key, frozenset())
        grown &= CAPABILITY_KEYS  # an implication typo can never mint a phantom key
        if grown == current:
            break
        current = grown
    return frozenset(current)


def sanitize_capabilities(raw: Any) -> frozenset[str]:
    """Coerce stored/incoming capability data into a trusted set of known keys.

    NEVER RAISES, and never widens on garbage. This is the only door through which
    untrusted capability data enters the engine: a JSON column written by an older
    build, a hand-edited row, or a request body. It accepts a JSON array string, a
    Python list/tuple/set, or None, and drops anything it does not recognise.

    Malformed input (`"{"`, `"null"`, `"[1,2]"`, a dict, a number) resolves to the
    EMPTY set rather than an error, because the callers are a permission gate and a
    request validator: a 500 on a corrupt grants column would lock a whole workspace
    out of its portal, whereas an empty set just falls back to the role preset.
    """
    if raw is None:
        return frozenset()

    values: Optional[Sequence[Any]] = None
    if isinstance(raw, (list, tuple, set, frozenset)):
        values = list(raw)
    elif isinstance(raw, (bytes, bytearray)):
        try:
            return sanitize_capabilities(bytes(raw).decode("utf-8", "ignore"))
        except Exception:
            return frozenset()
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return frozenset()
        try:
            parsed = json.loads(text)
        except Exception:
            # Not JSON at all. Fail closed — do NOT try to salvage a comma-separated
            # string, because guessing at the shape of corrupt permission data is how
            # you accidentally grant something.
            return frozenset()
        if isinstance(parsed, (list, tuple, set)):
            values = list(parsed)
        else:
            # "null" → None, "5" → int, '"x"' → str, "{}" → dict. None of these is a
            # capability array, so none of them grants anything.
            return frozenset()
    else:
        return frozenset()

    out: set[str] = set()
    for value in values:
        if isinstance(value, str):
            key = value.strip()
            if key in CAPABILITY_KEYS:
                out.add(key)
    return frozenset(out)


def dump_capabilities(keys: Iterable[str] | None) -> Optional[str]:
    """Serialize a capability set for a `*_json` Text column (sorted for stable diffs).

    Returns None for an empty set so "no overrides" is stored as NULL rather than the
    string "[]" — the audit log's before/after pairs read much better that way.
    """
    cleaned = sorted(sanitize_capabilities(list(keys or ())))
    return json.dumps(cleaned) if cleaned else None


def label_for(key: str) -> str:
    """User-facing label for a capability key (falls back to the key itself)."""
    entry = CAPABILITY_BY_KEY.get(str(key or ""))
    return entry["label"] if entry else str(key or "")


# Labels are lowercased inside a sentence, but the brand never is.
_BRAND_FIX = re.compile(r"\brilono\b")


def denied_detail(key: str) -> str:
    """The 403 body for a missing capability.

    One sentence, in the product's own words, that tells the member exactly what they
    lack and who can give it to them — not "Forbidden", and not an endpoint name.
    """
    label = _BRAND_FIX.sub("Rilono", label_for(key).lower())
    return (
        f"You don't have permission to {label}. "
        "Ask a workspace admin for access."
    )


def capability_detail(key: str) -> str:
    """The `desc` line for a capability key (empty string when unknown)."""
    entry = CAPABILITY_BY_KEY.get(str(key or ""))
    return entry["desc"] if entry else ""


# ===========================================================================
# DATA SCOPES
# ===========================================================================

SCOPE_ALL = "all"
SCOPE_BRANCH = "branch"
SCOPE_ASSIGNED = "assigned"

# Narrowest → widest. This ordering IS the escalation check: an actor may only hand
# out a scope at or below its own index (see scope_is_wider), which stops a
# branch-scoped manager from minting a second, workspace-wide identity for themselves.
SCOPE_ORDER: tuple[str, ...] = (SCOPE_ASSIGNED, SCOPE_BRANCH, SCOPE_ALL)

# UI order (widest first) plus the copy shown next to each radio. The `assigned` desc
# is worded precisely because the predicate is an OR of two columns — a member sees
# cases assigned to them AND cases they created; anything vaguer would be a lie.
SCOPES: tuple[dict, ...] = (
    {"key": SCOPE_ALL, "label": "Entire workspace",
     "desc": "Every client in every office."},
    {"key": SCOPE_BRANCH, "label": "Their office only",
     "desc": "Only clients that belong to the offices they are assigned to."},
    {"key": SCOPE_ASSIGNED, "label": "Only their own clients",
     "desc": "Clients assigned to them, plus ones they created"},
)


def normalize_scope(raw: Any, *, default: str = SCOPE_ASSIGNED) -> str:
    """Coerce any scope value to a known scope, failing closed to `assigned`.

    Used on both the write path (so nothing unknown is ever stored) and the read path
    (so nothing unknown already stored is ever honoured as "all").
    """
    kind = str(raw or "").strip().lower()
    return kind if kind in SCOPE_ORDER else default


def _scope_rank(raw: Any) -> int:
    return SCOPE_ORDER.index(normalize_scope(raw))


def scope_is_wider(candidate: Any, actor: Any) -> bool:
    """True when `candidate` grants access to strictly more records than `actor`.

    The router uses this for scope clamping on EVERY write path (invite, edit access,
    bulk, reactivate, role create/edit) — not just for branch-scoped actors. Without
    it, an `assigned`-scope member with delegated `roles.manage` could create a role
    with `data_scope="all"`, assign it to themselves, and read the whole workspace.
    """
    return _scope_rank(candidate) > _scope_rank(actor)


def scope_label(scope_kind: Any, *, branch_count: int = 0) -> str:
    """Short human label for a resolved scope — the chip in the members table.

    Deliberately terser than the radio-button copy in SCOPES: a table chip has ~14
    characters of room, and "2 offices" tells a manager more at a glance than
    "Their office only" repeated on every row.
    """
    kind = normalize_scope(scope_kind)
    if kind == SCOPE_ALL:
        return "Entire workspace"
    if kind == SCOPE_BRANCH:
        count = int(branch_count or 0)
        if count > 1:
            return f"{count} offices"
        return "Their office"
    return "Only their own clients"


def scope_desc(scope_kind: Any) -> str:
    """The longer explanatory sentence for a resolved scope."""
    kind = normalize_scope(scope_kind)
    for entry in SCOPES:
        if entry["key"] == kind:
            return entry["desc"]
    return ""


# ===========================================================================
# ROLE PRESETS
#
# Code, never rows. A preset is a product decision about what "Counsellor" means, so it
# belongs in a reviewable diff; as data it would be silently mutable by any migration.
#
# Every preset is passed through expand_implied() at import time, so a hand-edit that
# forgets a prerequisite ("Manage shortlist" without "View shortlist") cannot ship an
# incoherent role.
# ===========================================================================

ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_BRANCH_MANAGER = "branch_manager"
ROLE_COUNSELLOR = "counsellor"
ROLE_FINANCE = "finance"
ROLE_VIEWER = "viewer"
ROLE_CUSTOM = "custom"


def _preset(
    label: str,
    description: str,
    capabilities: Iterable[str],
    data_scope: str,
    *,
    scope_locked: bool = False,
    is_system: bool = True,
    assignable: bool = True,
) -> dict:
    return {
        "label": label,
        "description": description,
        "capabilities": expand_implied(capabilities),
        "data_scope": data_scope,
        "scope_locked": bool(scope_locked),
        "is_system": bool(is_system),
        "assignable": bool(assignable),
    }


_BRANCH_MANAGER_CAPS = (
    "dashboard.view", "clients.view", "clients.view_sensitive", "clients.create",
    "clients.edit", "clients.assign",
    "notes.view", "notes.write", "notes.moderate",
    "calendar.view", "calendar.manage",
    "universities.view", "universities.manage", "coursefinder.view",
    "interviews.view", "interviews.run", "interviews.invite", "portal.share",
    "copilot.invite",
    "emails.view", "emails.send", "emails.send_bulk",
    "documents.view", "documents.download", "documents.upload", "documents.accept",
    "documents.request",
    "ai.assistant", "ai.shortlist", "ai.coursefinder", "ai.writing", "ai.deepscan",
    "credits.spend", "credits.view",
    "finance.view", "finance.manage",
    "team.view", "branches.view", "audit.view",
    "support.request", "support.manage",
    "catalog.view", "notifications.view",
)

_COUNSELLOR_CAPS = (
    "dashboard.view", "clients.view", "clients.view_sensitive", "clients.create",
    "clients.edit",
    "notes.view", "notes.write",
    "calendar.view", "calendar.manage",
    "universities.view", "universities.manage", "coursefinder.view",
    "interviews.view", "interviews.run", "interviews.invite", "portal.share",
    "copilot.invite",
    "emails.view", "emails.send",
    "documents.view", "documents.download", "documents.upload", "documents.accept",
    "documents.request",
    "ai.assistant", "ai.shortlist", "ai.coursefinder", "ai.writing", "ai.deepscan",
    "credits.spend", "credits.view",
    "finance.view",
    "team.view", "branches.view",
    "support.request",
    "catalog.view", "notifications.view",
)

_FINANCE_CAPS = (
    "dashboard.view", "clients.view",
    "finance.view", "finance.manage", "finance.books", "finance.books_manage",
    "finance.export",
    "credits.view", "credits.purchase", "billing.manage",
    "emails.view",
    "team.view", "branches.view", "audit.view",
    "support.request",
    "catalog.view", "notifications.view",
)

_VIEWER_CAPS = (
    "dashboard.view", "clients.view",
    "notes.view", "calendar.view", "universities.view", "coursefinder.view",
    "interviews.view", "emails.view", "documents.view",
    "credits.view",
    "team.view", "branches.view",
    "support.request",
    "catalog.view", "notifications.view",
)


ROLE_PRESETS: dict[str, dict] = {
    # The owner holds every key by definition and its scope is locked to the whole
    # workspace. Not assignable through the role picker: ownership moves only through
    # POST /organization/transfer-ownership, which is a deliberate, audited, one-at-a-
    # time operation (exactly one active owner per workspace).
    ROLE_OWNER: _preset(
        "Owner",
        "Full control of the workspace, including refunds, the payout bank account and "
        "transferring ownership. Exactly one owner per workspace.",
        CAPABILITY_KEYS,
        SCOPE_ALL,
        scope_locked=True,
        assignable=False,
    ),
    # Everything the owner has minus the three owner-only keys. An admin runs the
    # business day to day but cannot move settled money back out, repoint the payout
    # bank account, or take the workspace from its owner.
    ROLE_ADMIN: _preset(
        "Admin",
        "Runs the whole workspace day to day — every client, every office, the team and "
        "billing. Cannot issue refunds, change the payout bank account or transfer "
        "ownership.",
        CAPABILITY_KEYS - OWNER_ONLY_CAPABILITIES,
        SCOPE_ALL,
        scope_locked=True,
    ),
    ROLE_BRANCH_MANAGER: _preset(
        "Branch manager",
        "Runs one or more offices: their offices' full caseload, team output, emails, "
        "documents and payments. No workspace settings, no deletions, no top-ups.",
        _BRANCH_MANAGER_CAPS,
        SCOPE_BRANCH,
    ),
    ROLE_COUNSELLOR: _preset(
        "Counsellor",
        "Works their own caseload end to end — clients, documents, shortlists, mock "
        "interviews and the AI tools. Cannot reassign or delete cases.",
        _COUNSELLOR_CAPS,
        SCOPE_ASSIGNED,
    ),
    ROLE_FINANCE: _preset(
        "Finance",
        "Money only: student payments, invoices, the company books, credit top-ups and "
        "the subscription. No client editing, no documents, no AI.",
        _FINANCE_CAPS,
        SCOPE_ALL,
    ),
    ROLE_VIEWER: _preset(
        "Viewer",
        "Read-only. Can look at their own cases but change nothing, download no files "
        "and spend no credits.",
        _VIEWER_CAPS,
        SCOPE_ASSIGNED,
    ),
    # REQUIRED pseudo-preset. A member whose role_key is "custom" still has to resolve
    # through ROLE_PRESETS like everyone else; without an entry here every lookup on
    # that member would KeyError and the gate would 500 for the entire workspace.
    # It contributes NO capabilities of its own — everything comes from the
    # EnterpriseRole row — and it is not assignable as a bare key (the picker sends
    # "custom:<id>", see parse_role_assignment).
    ROLE_CUSTOM: _preset(
        "Custom role",
        "A role this workspace defined itself. Its permissions come from the saved role.",
        (),
        SCOPE_ASSIGNED,
        is_system=False,
        assignable=False,
    ),
}

# Every role key, in UI order.
ROLE_KEYS: tuple[str, ...] = tuple(ROLE_PRESETS)

# The built-in roles. `custom` is excluded — it is a sentinel, not a shipped role.
SYSTEM_ROLE_KEYS: tuple[str, ...] = tuple(
    k for k, p in ROLE_PRESETS.items() if p["is_system"]
)

# What the role picker may offer. Owner is excluded (transfer-only) and so is the
# `custom` sentinel (offered as the concrete custom roles instead).
ASSIGNABLE_ROLE_KEYS: tuple[str, ...] = tuple(
    k for k, p in ROLE_PRESETS.items() if p["assignable"]
)

# A custom role's slug may not collide with any role key — including `custom` itself,
# which would make "custom:<id>" vs "custom" ambiguous in parse_role_assignment.
RESERVED_ROLE_SLUGS: frozenset[str] = frozenset(ROLE_KEYS)

# Limits. Both are product guardrails, not storage limits: a picker with 60 roles in it
# is unusable, and an unbounded office list makes /team/meta unbounded too.
MAX_CUSTOM_ROLES = 20
MAX_BRANCHES = 50

# Charset-restricted display names (§ sanitize_display_name).
ROLE_NAME_MIN_LEN = 2
ROLE_NAME_MAX_LEN = 60
ROLE_SLUG_MAX_LEN = 40
BRANCH_NAME_MIN_LEN = 2
BRANCH_NAME_MAX_LEN = 80


def preset_for(role_key: Any) -> dict:
    """The preset for a role key, falling back to Viewer for anything unrecognised.

    Every read of ROLE_PRESETS in this module goes through here or an explicit
    `.get(key, ROLE_PRESETS[ROLE_VIEWER])` — never `ROLE_PRESETS[key]`. A stale or
    hand-edited `role_key` in the DB must degrade to the least-privileged role, not
    raise a KeyError that 500s every request that member makes.
    """
    return ROLE_PRESETS.get(str(role_key or "").strip().lower(), ROLE_PRESETS[ROLE_VIEWER])


def role_label_for(role_key: Any) -> str:
    return preset_for(role_key)["label"]


# ---------------------------------------------------------------------------
# Legacy `role` column mirror
# ---------------------------------------------------------------------------

LEGACY_ROLE_TO_ROLE_KEY: dict[str, str] = {
    "admin": ROLE_ADMIN,
    "editor": ROLE_COUNSELLOR,
    "viewer": ROLE_VIEWER,
}

LEGACY_ROLES: tuple[str, ...] = ("admin", "editor", "viewer")


def normalize_role_key(role_key: Any = None, legacy_role: Any = None) -> str:
    """Coerce a stored `role_key` to a known key. Never raises.

    Resolution order, each step strictly less trusted than the last:
      1. `role_key` itself, when it names a real preset.
      2. `LEGACY_ROLE_TO_ROLE_KEY[legacy_role]` — a row written before this feature
         shipped has a blank `role_key` but a valid legacy `role` mirror.
      3. `viewer`.

    Always returns one of SYSTEM_ROLE_KEYS or "custom", so every downstream
    `ROLE_PRESETS` read is guaranteed to hit.
    """
    key = str(role_key or "").strip().lower()
    if key in ROLE_PRESETS:
        return key
    legacy = str(legacy_role or "").strip().lower()
    return LEGACY_ROLE_TO_ROLE_KEY.get(legacy, ROLE_VIEWER)


def legacy_role_for(role_key: Any, capabilities: Iterable[str] | None = None) -> str:
    """The value written to `enterprise_organization_members.role`.

    That column is now a MAINTAINED MIRROR, not a source of truth — but it is still
    read directly by code paths that predate this module, so it has to stay honest.

    `"admin"` is reserved for `role_key in {owner, admin}` and nothing else. It is
    tempting to also mirror `team.manage`/`roles.manage` holders to `"admin"` (they do
    manage the team, after all), but three separate places treat `role == "admin"` as
    "trusted with everything": `/finance/summary`'s `include_sensitive` flag, the
    payment-dispute alert recipients, and the inbound-email fallback recipients. A
    delegated team manager mirrored to `"admin"` would therefore start receiving bank
    details and student PII. Since a workspace always has at least one active owner,
    the existing `_active_admin_count() >= 1` invariant still holds with this narrower
    rule.
    """
    key = str(role_key or "").strip().lower()
    if key in (ROLE_OWNER, ROLE_ADMIN):
        return "admin"
    if "clients.edit" in (capabilities or frozenset()):
        return "editor"
    return "viewer"


def parse_role_assignment(raw: Any) -> tuple[str, Optional[int]]:
    """Parse a role selection into `(role_key, custom_role_id)`.

    Accepts the three shapes the API has to live with at once:
      * a system role key   — "admin", "branch_manager", "viewer", …
      * a custom role       — "custom:37"  (what the new role picker submits)
      * a legacy role       — "admin" | "editor" | "viewer"  (old SPA builds, invites)

    Raises ValueError on anything else so the caller can answer 422 with a precise
    message; it never guesses, because guessing a role is guessing a permission set.
    Note it does NOT enforce assignability — "owner" parses fine and the router is
    responsible for rejecting it (ownership moves only via transfer-ownership).
    """
    text = str(raw or "").strip()
    if not text:
        raise ValueError("A role is required.")

    lowered = text.lower()
    if lowered.startswith("custom:"):
        suffix = lowered.split(":", 1)[1].strip()
        try:
            role_id = int(suffix)
        except (TypeError, ValueError):
            raise ValueError(f"Unknown role: {text}") from None
        if role_id <= 0:
            raise ValueError(f"Unknown role: {text}")
        return ROLE_CUSTOM, role_id

    if lowered in ROLE_PRESETS:
        # Bare "custom" carries no role id. It is returned as-is (the resolver treats a
        # custom role with no row as zero capabilities), but callers that are assigning
        # a role should reject it — see the router's validation.
        return lowered, None

    if lowered in LEGACY_ROLE_TO_ROLE_KEY:
        return LEGACY_ROLE_TO_ROLE_KEY[lowered], None

    raise ValueError(f"Unknown role: {text}")


# ---------------------------------------------------------------------------
# Display-name hygiene for branch and custom-role names
#
# These two strings are the only free-text values this feature renders back into the
# UI in a dozen places (chips, pickers, the access log, notification bodies, and
# `enterprise_clients.branch_name`). Restricting the charset on WRITE means every one
# of those read sites is safe without having to audit each one, and it also keeps
# names out of the territory where a stray control character or RTL override makes two
# different offices look identical in the picker.
# ---------------------------------------------------------------------------

# Punctuation an office or role name may contain. Everything else is either a letter/digit
# (allowed, see _is_display_name_char) or stripped: "Mumbai (Andheri West)", "R&D / Docs",
# "St. John's", "Delhi-NCR", "Sales+Ops", "Kochi — MG Road", "Pune, Baner".
#
# En/em dashes and commas are in the set because the branch-name backfill already produced
# "Kochi — MG Road" from live data — stripping the dash on the first rename would silently
# mangle a real office's name.
_DISPLAY_NAME_PUNCT = frozenset(" &()-–—/.,'+")
# `\s` already covers tabs/newlines and most Unicode spaces; the explicit escapes add
# the zero-width characters Unicode does NOT classify as whitespace (zero-width space,
# the joiners, and the BOM). Written as escapes rather than literals so the pattern
# stays reviewable in a diff and survives any re-encoding of this file.
_WHITESPACE_LIKE = re.compile(
    "[\\s\u00a0\u1680\u2000-\u200f\u2028\u2029\u202f\u205f\u2060\u3000\ufeff]+"
)


def _is_display_name_char(ch: str) -> bool:
    """Whether one character may appear in an office or role name.

    Letters, digits and COMBINING MARKS from any script pass, plus the small punctuation set
    above. Marks matter and are easy to miss: Python's `\\w` excludes Unicode category Mn, so an
    allowlist built on `\\w` silently eats the vowel signs out of Devanagari — "बेंगलुरु कार्यालय"
    comes back as "बगलर करयलय". This is an Indian-market product; an office name has to survive
    being renamed.

    Everything else goes, which keeps angle brackets, quotes and control characters out of names
    that end up interpolated into audit-log summaries. The UI escapes on output as well; this is
    defence in depth, not the only line.
    """
    if ch in _DISPLAY_NAME_PUNCT:
        return True
    return unicodedata.category(ch)[0] in ("L", "N", "M")


def sanitize_display_name(raw: Any, *, max_len: int) -> str:
    """Normalize a user-supplied branch or role name.

    Whitespace-ish characters (tabs, newlines, non-breaking and zero-width spaces)
    collapse to a single plain space FIRST — otherwise the charset filter would eat a
    newline and weld two words together ("Delhi\\nOffice" → "DelhiOffice"). Everything
    outside the allowed charset is then removed, whitespace collapses again, and the
    result is trimmed to `max_len` (re-trimmed after truncation, so a cut in the middle
    of a gap cannot leave a trailing space).

    Returns "" for input that is empty or entirely disallowed; the caller enforces the
    minimum length and answers 422.
    """
    text = "" if raw is None else str(raw)
    text = _WHITESPACE_LIKE.sub(" ", text)
    text = "".join(ch for ch in text if _is_display_name_char(ch))
    text = _WHITESPACE_LIKE.sub(" ", text).strip()
    limit = int(max_len or 0)
    if limit > 0 and len(text) > limit:
        text = text[:limit].strip()
    return text


def slugify_role_name(name: Any) -> str:
    """Stable machine key for a custom role name ("Front Desk / AE" → "front_desk_ae").

    Slugs are what the API and the frontend match on, so they are lowercase, ASCII and
    underscore-only. Uniqueness (case-insensitive, INCLUDING archived roles) and the
    reserved-key check are the router's job — this function only produces the candidate.
    """
    base = str(name or "").strip().lower()
    slug = re.sub(r"[^a-z0-9_]+", "_", base).strip("_")[:ROLE_SLUG_MAX_LEN].strip("_")
    return slug or "role"


# ===========================================================================
# RESOLUTION ENGINE
# ===========================================================================


@dataclass(frozen=True)
class AccessContext:
    """Everything the request needs to know about who is asking.

    Immutable on purpose: it is resolved once per request by the gate and then read by
    dozens of handlers, serializers and query builders. If a handler could mutate it,
    "may this member see this record?" would depend on call order.
    """

    organization_id: int
    user_id: int
    member_id: int
    role_key: str
    role_label: str
    custom_role_id: Optional[int]
    is_owner: bool
    # role_key in {"owner", "admin"}. This — NOT `has("team.manage")` — is what backs
    # the legacy gate flags for money and workspace settings, so delegating team
    # management can never reach a refund or the payout bank account.
    is_admin_like: bool
    capabilities: frozenset[str]
    scope_kind: str                       # "all" | "branch" | "assigned"
    branch_ids: frozenset[int]            # ACTIVE offices in scope; empty unless scope_kind == "branch"
    primary_branch_id: Optional[int]
    status: str
    # Kept for the "My access" tab and the audit detail: what the role gave vs. what
    # was added or blocked for this individual member.
    preset_capabilities: frozenset[str] = field(default_factory=frozenset)
    granted_capabilities: frozenset[str] = field(default_factory=frozenset)
    denied_capabilities: frozenset[str] = field(default_factory=frozenset)

    # -- checks ------------------------------------------------------------
    def has(self, cap: str) -> bool:
        """The owner short-circuits every capability check.

        A workspace with nobody able to fix its own permissions is unrecoverable
        without support intervention, so the owner is structurally un-lockable-out:
        no deny list, archived role or corrupt JSON column can take a key from them.
        """
        return self.is_owner or cap in self.capabilities

    def has_all(self, *caps: str) -> bool:
        if self.is_owner:
            return True
        return all(c in self.capabilities for c in caps)

    def has_any(self, *caps: str) -> bool:
        if self.is_owner:
            return True
        if not caps:
            return True  # nothing required → nothing to fail
        return any(c in self.capabilities for c in caps)

    def missing(self, *caps: str) -> tuple[str, ...]:
        """Which of `caps` this member lacks, in the order given (for 403 copy)."""
        if self.is_owner:
            return ()
        return tuple(c for c in caps if c not in self.capabilities)

    # -- scope -------------------------------------------------------------
    @property
    def is_org_scope(self) -> bool:
        return self.scope_kind == SCOPE_ALL

    @property
    def is_branch_scope(self) -> bool:
        return self.scope_kind == SCOPE_BRANCH

    @property
    def is_assigned_scope(self) -> bool:
        return self.scope_kind == SCOPE_ASSIGNED

    @property
    def scope_label(self) -> str:
        return scope_label(self.scope_kind, branch_count=len(self.branch_ids))

    @property
    def has_overrides(self) -> bool:
        return bool(self.granted_capabilities or self.denied_capabilities)

    @property
    def override_count(self) -> int:
        return len(self.granted_capabilities) + len(self.denied_capabilities)


def effective_capabilities(
    *,
    role_key: Any,
    custom_role_caps: Any = None,
    custom_role_active: bool = False,
    grants: Any = None,
    denies: Any = None,
) -> frozenset[str]:
    """Fold a role plus its per-member overrides into one capability set.

    The ORDER of the steps below is load-bearing:

      1. Owner short-circuits — see AccessContext.has().
      2. Start from the preset (via .get(), never [...]).
      3. Union the custom role's own capabilities, gated on `role_key == "custom"`
         ALONE — never on "the row exists". If the union were keyed off
         `custom_role_id` being set, demoting someone from a custom role to Viewer by
         changing only `role_key` would silently keep every capability that role gave
         them. An archived custom role contributes nothing (fail closed).
      4. Union the member's explicit grants.
      5. Expand implications — BEFORE denies. Expanding is a convenience ("Edit
         clients" shouldn't need "View clients" ticked too); denying is an intent. If
         denies ran first, the closure would re-grant exactly what an admin had just
         blocked, which is the one outcome a deny list must never produce.
      6. Subtract denies. Explicit deny always wins.
      7. Add BASE_CAPABILITIES back — undeniable app chrome (see its comment).
      8. Subtract OWNER_ONLY_CAPABILITIES. Applied last so no path — preset, custom
         role, grant, or implication (`finance.refund → finance.manage`) — can leave a
         non-owner holding a refund button or the payout bank account.
    """
    key = str(role_key or "").strip().lower()
    if key == ROLE_OWNER:
        return CAPABILITY_KEYS

    caps: set[str] = set(preset_for(key)["capabilities"])

    if key == ROLE_CUSTOM and custom_role_active:
        caps |= sanitize_capabilities(custom_role_caps)

    caps |= sanitize_capabilities(grants)
    caps = set(expand_implied(caps))
    caps -= sanitize_capabilities(denies)
    caps |= BASE_CAPABILITIES
    caps -= OWNER_ONLY_CAPABILITIES
    return frozenset(caps)


def resolved_scope_kind(
    *,
    role_key: Any,
    member_scope: Any = None,
    custom_role_scope: Any = None,
) -> str:
    """The scope a member resolves to BEFORE the "has an active office?" check.

    Split out from effective_scope() so the resolver can decide whether it needs to
    touch the branch tables at all: only a `branch` outcome requires a query, and
    `all`/`assigned` members (the large majority) get their context with zero extra
    round trips on a hot path.

    Precedence: the member's own override, then their custom role's default, then the
    preset's default, then `assigned`. `member_scope` is NULLABLE by design — NULL
    means "inherit", which is what makes the role defaults real instead of dead code.
    """
    key = str(role_key or "").strip().lower()
    if key == ROLE_OWNER:
        return SCOPE_ALL
    preset = preset_for(key)
    if preset["scope_locked"]:
        return SCOPE_ALL
    raw = (
        str(member_scope or "").strip().lower()
        or str(custom_role_scope or "").strip().lower()
        or str(preset["data_scope"] or "").strip().lower()
    )
    # Unknown fails closed to the narrowest scope — never to "all".
    return normalize_scope(raw)


def effective_scope(
    *,
    role_key: Any,
    member_scope: Any = None,
    custom_role_scope: Any = None,
    branch_ids: Optional[Iterable[int]] = None,
    primary_branch_id: Optional[int] = None,
) -> tuple[str, frozenset[int]]:
    """Resolve `(scope_kind, branch_ids)`. Pure — it never touches the database.

    `branch_ids` are ALREADY filtered by the caller to offices that are ACTIVE and
    belong to this organization (resolve_access_context does that in SQL; the bulk
    recipient fan-out in `enterprise_notifications` does it with one query for the
    whole workspace). Keeping the query out of here is what makes this function
    unit-testable and safe to call thousands of times in a loop.

    `primary_branch_id` is only folded in when it already appears in `branch_ids`. It
    is a pointer that can dangle at an archived office, and unioning it blind would
    resurrect a dead office id into the scope set, producing a scope that is non-empty
    (so it looks fine) but matches no client rows — a silent total data blackout for
    that member.

    A `branch` scope with no active office falls back to `assigned`, NEVER to `all`.
    Someone who has not been given an office yet must see their own caseload, not the
    entire workspace; widening on missing data is exactly the failure mode that turns a
    half-finished setup into a privacy incident.
    """
    key = str(role_key or "").strip().lower()
    if key == ROLE_OWNER:
        return SCOPE_ALL, frozenset()

    kind = resolved_scope_kind(
        role_key=key, member_scope=member_scope, custom_role_scope=custom_role_scope
    )
    if kind != SCOPE_BRANCH:
        # `all` and `assigned` carry no office set — an empty frozenset here keeps
        # ctx.branch_ids meaningless-but-safe for those members.
        return kind, frozenset()

    ids: set[int] = set()
    for bid in (branch_ids or ()):
        try:
            ids.add(int(bid))
        except (TypeError, ValueError):
            continue
    if primary_branch_id is not None:
        try:
            primary = int(primary_branch_id)
        except (TypeError, ValueError):
            primary = None
        if primary is not None and primary in ids:
            ids.add(primary)

    if not ids:
        return SCOPE_ASSIGNED, frozenset()
    return SCOPE_BRANCH, frozenset(ids)


def _custom_role_row(db: Session, *, organization_id: int, custom_role_id: Any):
    """Load a custom role, scoped to the organization.

    The `organization_id` filter is NOT optional. `custom_role_id` lives on a member
    row and is only ever an integer; without the tenant filter, a stale or tampered id
    pointing at another consultancy's role would inject that role's capability set into
    this workspace — cross-tenant privilege escalation through a single integer.
    """
    try:
        role_id = int(custom_role_id)
    except (TypeError, ValueError):
        return None
    if role_id <= 0:
        return None
    return (
        db.query(models.EnterpriseRole)
        .filter(
            models.EnterpriseRole.id == role_id,
            models.EnterpriseRole.organization_id == int(organization_id),
        )
        .first()
    )


def _active_branch_ids_for_member(
    db: Session,
    *,
    organization_id: int,
    member_id: int,
    primary_branch_id: Any = None,
) -> set[int]:
    """Active offices this member may see, from their link rows plus their primary.

    The join to `EnterpriseBranch` with `is_active.is_(True)` is the important part:
    archiving an office does not delete the member's link rows, so reading
    `enterprise_member_branches` alone would hand back ids of dead offices. That set is
    non-empty (so the branch scope survives) but matches no live client — a silent,
    complete data blackout for that member, with no error anywhere to explain it.
    """
    ids: set[int] = set()
    rows = (
        db.query(models.EnterpriseMemberBranch.branch_id)
        .join(
            models.EnterpriseBranch,
            models.EnterpriseBranch.id == models.EnterpriseMemberBranch.branch_id,
        )
        .filter(
            models.EnterpriseMemberBranch.member_id == int(member_id),
            models.EnterpriseBranch.organization_id == int(organization_id),
            models.EnterpriseBranch.is_active.is_(True),
        )
        .all()
    )
    for (branch_id,) in rows:
        if branch_id is not None:
            ids.add(int(branch_id))

    # A member's primary office counts even if nobody created the link row (the invite
    # path sets primary_branch_id first). Verified active + same-tenant before use.
    try:
        primary = int(primary_branch_id) if primary_branch_id is not None else None
    except (TypeError, ValueError):
        primary = None
    if primary and primary not in ids:
        exists = (
            db.query(models.EnterpriseBranch.id)
            .filter(
                models.EnterpriseBranch.id == primary,
                models.EnterpriseBranch.organization_id == int(organization_id),
                models.EnterpriseBranch.is_active.is_(True),
            )
            .first()
        )
        if exists:
            ids.add(primary)
    return ids


def resolve_access_context(db: Session, membership, organization) -> AccessContext:
    """Build the request's AccessContext from a membership row.

    Called once per authenticated enterprise request, so it is written to be cheap
    (at most two extra indexed queries, and none at all for `all`/`assigned` members)
    and to be UNABLE to fail: both DB lookups are wrapped, and a failure degrades to
    the role preset rather than 500ing every enterprise endpoint. Reading columns via
    `getattr(..., None)` means an un-migrated database — one where `data_scope` or
    `role_key` does not exist yet — still resolves through the legacy `role` mirror
    instead of exploding on attribute access.
    """
    org_id = int(getattr(organization, "id", organization) or 0)

    if membership is None:
        # Defensive: the gate should never get here, but a context is still safer to
        # return than an exception. Zero capabilities, narrowest scope.
        return AccessContext(
            organization_id=org_id,
            user_id=0,
            member_id=0,
            role_key=ROLE_VIEWER,
            role_label=role_label_for(ROLE_VIEWER),
            custom_role_id=None,
            is_owner=False,
            is_admin_like=False,
            capabilities=frozenset(),
            scope_kind=SCOPE_ASSIGNED,
            branch_ids=frozenset(),
            primary_branch_id=None,
            status="suspended",
        )

    member_id = int(getattr(membership, "id", 0) or 0)
    user_id = int(getattr(membership, "user_id", 0) or 0)

    # --- role -------------------------------------------------------------
    # Blank (pre-migration row), unknown, or garbage → derive from the legacy `role`
    # mirror, and from Viewer if even that is unrecognisable.
    role_key = normalize_role_key(
        getattr(membership, "role_key", None),
        getattr(membership, "role", None),
    )

    # --- custom role ------------------------------------------------------
    custom_role_id_raw = getattr(membership, "custom_role_id", None)
    custom_role_id: Optional[int] = None
    custom_role_caps: Any = None
    custom_role_scope: Any = None
    custom_role_label: Optional[str] = None
    custom_role_active = False
    if role_key == ROLE_CUSTOM and custom_role_id_raw:
        row = None
        try:
            row = _custom_role_row(
                db, organization_id=org_id, custom_role_id=custom_role_id_raw
            )
        except Exception:
            # Table missing (un-migrated), connection hiccup, anything: degrade to the
            # bare `custom` preset (no capabilities) instead of failing the request.
            logger.warning(
                "enterprise_access: custom role lookup failed for member %s in org %s",
                member_id, org_id, exc_info=True,
            )
        if row is not None:
            custom_role_id = int(getattr(row, "id", 0) or 0) or None
            custom_role_label = getattr(row, "name", None) or None
            if bool(getattr(row, "is_active", False)):
                custom_role_active = True
                custom_role_caps = getattr(row, "capabilities_json", None)
                custom_role_scope = getattr(row, "data_scope", None)

    # --- capabilities -----------------------------------------------------
    grants_raw = getattr(membership, "capability_grants_json", None)
    denies_raw = getattr(membership, "capability_denies_json", None)
    capabilities = effective_capabilities(
        role_key=role_key,
        custom_role_caps=custom_role_caps,
        custom_role_active=custom_role_active,
        grants=grants_raw,
        denies=denies_raw,
    )

    # --- scope ------------------------------------------------------------
    member_scope = getattr(membership, "data_scope", None)   # NULL = inherit
    primary_branch_id = getattr(membership, "primary_branch_id", None)
    tentative = resolved_scope_kind(
        role_key=role_key, member_scope=member_scope, custom_role_scope=custom_role_scope
    )
    active_branch_ids: set[int] = set()
    if tentative == SCOPE_BRANCH:
        try:
            active_branch_ids = _active_branch_ids_for_member(
                db,
                organization_id=org_id,
                member_id=member_id,
                primary_branch_id=primary_branch_id,
            )
        except Exception:
            # Same reasoning as above — and note the consequence is a fallback to
            # `assigned` inside effective_scope(), i.e. LESS access, never more.
            logger.warning(
                "enterprise_access: branch lookup failed for member %s in org %s",
                member_id, org_id, exc_info=True,
            )
            active_branch_ids = set()

    scope_kind, branch_ids = effective_scope(
        role_key=role_key,
        member_scope=member_scope,
        custom_role_scope=custom_role_scope,
        branch_ids=active_branch_ids,
        primary_branch_id=primary_branch_id,
    )

    # At branch scope we already know which offices are live, so a primary pointing at
    # an archived office is dropped here rather than being handed to the client form as
    # a default that would 404 on save. At other scopes the pointer is passed through
    # unvalidated (validating it would cost a query on every request) — callers that
    # write it must still resolve it through the router's _get_org_branch_or_404.
    resolved_primary: Optional[int] = None
    try:
        resolved_primary = int(primary_branch_id) if primary_branch_id is not None else None
    except (TypeError, ValueError):
        resolved_primary = None
    if scope_kind == SCOPE_BRANCH and resolved_primary not in branch_ids:
        resolved_primary = None

    # --- label & status ---------------------------------------------------
    role_label = preset_for(role_key)["label"]
    if role_key == ROLE_CUSTOM and custom_role_label:
        role_label = custom_role_label

    status = str(getattr(membership, "status", "") or "").strip().lower()
    if status not in ("active", "suspended"):
        # Pre-migration rows have no `status`; `is_active` is the older signal.
        status = "active" if bool(getattr(membership, "is_active", True)) else "suspended"

    return AccessContext(
        organization_id=org_id,
        user_id=user_id,
        member_id=member_id,
        role_key=role_key,
        role_label=role_label,
        custom_role_id=custom_role_id,
        is_owner=(role_key == ROLE_OWNER),
        is_admin_like=(role_key in (ROLE_OWNER, ROLE_ADMIN)),
        capabilities=capabilities,
        scope_kind=scope_kind,
        branch_ids=branch_ids,
        primary_branch_id=resolved_primary,
        status=status,
        preset_capabilities=preset_for(role_key)["capabilities"],
        granted_capabilities=sanitize_capabilities(grants_raw),
        denied_capabilities=sanitize_capabilities(denies_raw),
    )


# ===========================================================================
# LEGACY SHIMS & PAYLOADS
# ===========================================================================


def legacy_permissions(ctx: AccessContext) -> dict:
    """The three booleans ~79 existing response payloads still carry.

    Keeping one producer for them is the point: before this, the router computed
    `permissions` from a role string in one place and from something else in another,
    and the two disagreed. Now every site derives from the resolved context.

    `can_manage_users` keeps its TODAY-meaning for the UI (does this member see team
    actions?), which is why delegated `team.manage` satisfies it. The SERVER gate for
    money and workspace settings uses `ctx.is_admin_like` instead — so a delegated team
    manager can show the invite button without ever being able to reach a refund or the
    payout bank account.
    """
    return {
        "can_view_data": ctx.has("clients.view") or ctx.has("dashboard.view"),
        "can_edit_data": ctx.has("clients.edit"),
        "can_manage_users": ctx.is_admin_like or ctx.has("team.manage"),
    }


def access_payload(ctx: AccessContext) -> dict:
    """The `access` block attached to every response that carries `permissions`.

    Owner capabilities collapse to `["*"]` rather than all ~58 keys: the owner holds
    everything by definition, the frontend's `can()` treats `"*"` as "yes", and it
    keeps a hot payload small.
    """
    return {
        "role_key": ctx.role_key,
        "role_label": ctx.role_label,
        "custom_role_id": ctx.custom_role_id,
        "is_owner": ctx.is_owner,
        "is_admin_like": ctx.is_admin_like,
        "capabilities": ["*"] if ctx.is_owner else sorted(ctx.capabilities),
        "data_scope": ctx.scope_kind,
        "scope_label": ctx.scope_label,
        "branch_ids": sorted(ctx.branch_ids),
        "primary_branch_id": ctx.primary_branch_id,
        "status": ctx.status,
    }


def blocked_access_payload() -> dict:
    """The `access` block for a caller with no usable membership.

    Everything off, narrowest scope. Used where a payload must still be shaped like an
    enterprise response (the portal, a suspended member, an error envelope) so the SPA
    renders its "no access" card instead of tripping over a missing key.
    """
    return {
        "role_key": ROLE_VIEWER,
        "role_label": role_label_for(ROLE_VIEWER),
        "custom_role_id": None,
        "is_owner": False,
        "is_admin_like": False,
        "capabilities": [],
        "data_scope": SCOPE_ASSIGNED,
        "scope_label": scope_label(SCOPE_ASSIGNED),
        "branch_ids": [],
        "primary_branch_id": None,
        "status": "suspended",
    }


def role_preset_payload(role_key: str) -> dict:
    """One entry of `/team/meta`'s `role_presets` array."""
    preset = preset_for(role_key)
    return {
        "key": str(role_key or "").strip().lower(),
        "label": preset["label"],
        "description": preset["description"],
        "data_scope": preset["data_scope"],
        "scope_locked": preset["scope_locked"],
        "assignable": preset["assignable"],
        "is_system": preset["is_system"],
        "capabilities": sorted(preset["capabilities"]),
    }


def capability_registry_payload() -> dict:
    """The static half of `GET /team/meta`.

    Everything here is derived from module constants, so it is identical for every
    workspace: the capability catalog with its UI copy, the section order, the role
    presets, and the scope options. The router merges in the per-org half (custom
    roles, branches, seats, `me`, `actor_capabilities`) and the limits.
    """
    return {
        "capabilities": [dict(cap) for cap in ALL_CAPABILITIES],
        "sections": list(CAPABILITY_SECTIONS),
        "role_presets": [role_preset_payload(key) for key in ROLE_KEYS],
        "scopes": [dict(scope) for scope in SCOPES],
    }


def limits_payload() -> dict:
    """`/team/meta`'s `limits` block."""
    return {"max_custom_roles": MAX_CUSTOM_ROLES, "max_branches": MAX_BRANCHES}


# ===========================================================================
# AUDIT LOG
# ===========================================================================

_AUDIT_SUMMARY_MAX = 500
_AUDIT_NAME_MAX = 200
_AUDIT_DETAIL_MAX = 20000


def _actor_name(subject) -> Optional[str]:
    if subject is None:
        return None
    name = getattr(subject, "full_name", None) or getattr(subject, "email", None)
    return str(name)[:_AUDIT_NAME_MAX] if name else None


def audit(
    db: Session,
    *,
    organization_id: int,
    actor=None,
    action: str,
    summary: str,
    target_user=None,
    target_name: Optional[str] = None,
    target_role_id: Optional[int] = None,
    target_branch_id: Optional[int] = None,
    before: Any = None,
    after: Any = None,
    ip_address: Optional[str] = None,
    commit: bool = False,
) -> None:
    """Append one row to the append-only access log. NEVER RAISES.

    Two deliberate choices:

    * Names are SNAPSHOTTED, not joined. The log has to stay readable after the member
      it describes has been deleted from the workspace — "Priya removed Rahul" must
      still say that a year later, which is also why `target_role_id` and
      `target_branch_id` carry no foreign key: the audit outlives its subject.

    * Failure is swallowed (logged, not raised). Audit is observability, not the
      business action. A full disk or a missing table must never turn a successful
      permission change into a 500 that leaves the caller unsure whether it applied.
      `commit=False` by default so the row joins the caller's transaction and cannot
      commit a half-finished change on their behalf.
    """
    try:
        detail_json = None
        if before is not None or after is not None:
            detail_json = json.dumps({"before": before, "after": after}, default=str)
            if len(detail_json) > _AUDIT_DETAIL_MAX:
                detail_json = json.dumps({
                    "before": "(truncated)",
                    "after": "(truncated)",
                    "note": "Detail exceeded the audit size limit.",
                })

        row = models.EnterpriseAccessAudit(
            organization_id=int(organization_id),
            action=str(action or "unknown")[:100],
            actor_user_id=(int(getattr(actor, "id", 0)) or None) if actor is not None else None,
            actor_name=_actor_name(actor),
            target_user_id=(
                (int(getattr(target_user, "id", 0)) or None) if target_user is not None else None
            ),
            target_name=(
                str(target_name)[:_AUDIT_NAME_MAX] if target_name else _actor_name(target_user)
            ),
            target_role_id=(int(target_role_id) if target_role_id else None),
            target_branch_id=(int(target_branch_id) if target_branch_id else None),
            summary=str(summary or "")[:_AUDIT_SUMMARY_MAX],
            detail_json=detail_json,
            ip_address=(str(ip_address)[:64] if ip_address else None),
        )
        db.add(row)
        if commit:
            db.commit()
    except Exception:
        logger.warning(
            "enterprise_access: failed to write access audit (%s) for org %s",
            action, organization_id, exc_info=True,
        )
        if commit:
            # A failed commit leaves the session dirty; roll back so the caller's next
            # statement does not inherit a poisoned transaction.
            try:
                db.rollback()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# RECORD-SCOPE QUERY HELPERS
#
# These live here, next to the scope resolution they belong to, rather than in the router: the
# router, the AI tool surface and the notification fan-out all have to apply the exact same
# predicate, and three copies of "which clients can this person see" is precisely the kind of
# drift that turns into a data leak the first time one of them is edited.
# ---------------------------------------------------------------------------


def scope_client_query(query, ctx):
    """Restrict a query over EnterpriseClient to the member's record scope.

    Apply this to the BASE query, before any caller-supplied filter, so a request parameter can
    only ever narrow the result set — never widen it.
    """
    if ctx is None or getattr(ctx, "scope_kind", SCOPE_ALL) == SCOPE_ALL:
        return query
    from sqlalchemy import or_

    client_model = models.EnterpriseClient
    if ctx.scope_kind == SCOPE_BRANCH:
        # An unfiled client (branch_id IS NULL) is visible workspace-wide only. Every existing row
        # is filed by the migration and every new one is stamped on create, so NULL means "nobody
        # has said which office owns this" — which must not land in everyone's scope.
        return query.filter(client_model.branch_id.in_(set(ctx.branch_ids) or {-1}))
    return query.filter(
        or_(
            client_model.assigned_to_user_id == ctx.user_id,
            client_model.created_by_user_id == ctx.user_id,
        )
    )


def client_in_scope(client, ctx) -> bool:
    """Whether a already-loaded client row falls inside the member's record scope."""
    if ctx is None or getattr(ctx, "scope_kind", SCOPE_ALL) == SCOPE_ALL:
        return True
    if client is None:
        return False
    if ctx.scope_kind == SCOPE_BRANCH:
        branch_id = getattr(client, "branch_id", None)
        return bool(branch_id) and int(branch_id) in ctx.branch_ids
    assigned = getattr(client, "assigned_to_user_id", None)
    created = getattr(client, "created_by_user_id", None)
    return (assigned is not None and int(assigned) == ctx.user_id) or (
        created is not None and int(created) == ctx.user_id
    )
