"""Rilono Copilot — Enterprise staff mode (Chrome extension).

Runs the Copilot chat for consultancy STAFF working on behalf of one of their
organization's clients (an EnterpriseClient CRM record — clients have no user
accounts). The staff member authenticates as themselves; the selected client
only shapes the context, so every message stays attributable to the staff user.

Context = the client's CRM profile + org-uploaded client documents
(extracted_text) + the visa-catalog journey for the client's destination.
Generation reuses the B2C chat model helpers (app/routers/ai_chat.py) so both
copilots share provider selection, model candidates, and inline-attachment
handling. Usage is recorded under the `enterprise_copilot_extension` source
with the organization attributed; billing (org credit wallet) is enforced by
the caller in routers/enterprise.py, mirroring the dashboard copilot.
"""

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from app import models
from app import ai_usage
from app import visa_catalog
# Shared with the dashboard assistant so BOTH copilot surfaces meter identically —
# one ledger row per model round-trip, attributed to the org, and a turn cost the
# credit meter can weight.
from app.enterprise_ai import ChatTurnResult, TurnUsage, _meter_round
from app.utils import gemini_service as gemini_utils

logger = logging.getLogger("rilono.enterprise_copilot")

USAGE_SOURCE = "enterprise_copilot_extension"

# Keep the prompt bounded: per-document and total caps for extracted text,
# matching the 60k ceiling the B2C copilot applies to E2E document context.
DOC_TEXT_CAP_PER_DOC = 12_000
DOC_TEXT_CAP_TOTAL = 60_000
# History is budgeted, not just turn-capped: enterprise messages are flat-metered
# against the org wallet, so an unbounded per-turn payload would let one metered
# message carry an arbitrarily large (and arbitrarily expensive) prompt.
HISTORY_MAX_TURNS = 200
HISTORY_CAP_PER_TURN = 4_000
HISTORY_CAP_TOTAL = 60_000


def is_provider_available() -> bool:
    """Mirrors the provider selection in run_enterprise_copilot_chat — Vertex OR
    the standard SDK. (enterprise_ai.is_ai_configured() is genai-key-only and
    would wrongly report unavailable on Vertex-only deployments.)"""
    if getattr(gemini_utils, "USE_VERTEX_AI", False) and getattr(gemini_utils, "VERTEX_AI_AVAILABLE", False):
        return True
    return bool(getattr(gemini_utils, "GENAI_AVAILABLE", False) and gemini_utils.genai)


def _fmt(value) -> str:
    if value is None:
        return "—"
    text = str(value).strip()
    return text or "—"


def _iso(value) -> Optional[str]:
    try:
        return value.isoformat() if value else None
    except Exception:
        return None


def build_client_profile_block(client: models.EnterpriseClient) -> str:
    """The client's CRM profile as prompt context (same field set the staff can
    already see in the dashboard; deep scan sends the same fields to the model)."""
    lines = [
        f"Full name: {_fmt(client.full_name)}",
        f"Email: {_fmt(client.email)}",
        f"Phone: {_fmt(client.phone)}",
        f"Nationality: {_fmt(client.nationality)}",
        f"Date of birth: {_fmt(_iso(client.date_of_birth))}",
        f"Passport number: {_fmt(client.passport_number)}",
        f"Passport expiry: {_fmt(_iso(client.passport_expiry))}",
        f"Visa category: {_fmt(client.visa_category)}",
        f"Destination: {_fmt(client.destination_country_name or client.destination_country_code)}",
        f"Visa type: {_fmt(client.visa_type)}",
        f"Intake: {_fmt(client.intake)}",
        f"Application reference: {_fmt(client.application_reference)}",
        f"Case status: {_fmt(client.status)}",
        f"Priority: {_fmt(client.priority)}",
        f"Target date: {_fmt(_iso(client.target_date))}",
    ]
    return "\n".join(lines)


def build_client_documents_block(db: Session, organization_id: int, client_id: int) -> str:
    docs = (
        db.query(models.EnterpriseClientDocument)
        .filter(
            models.EnterpriseClientDocument.organization_id == int(organization_id),
            models.EnterpriseClientDocument.client_id == int(client_id),
        )
        .order_by(models.EnterpriseClientDocument.created_at.desc())
        .all()
    )
    if not docs:
        return (
            "=== CLIENT DOCUMENTS ===\n"
            "No documents have been uploaded for this client yet.\n"
            "=== END CLIENT DOCUMENTS ==="
        )

    sections: List[str] = []
    remaining = DOC_TEXT_CAP_TOTAL
    omitted = 0
    for index, doc in enumerate(docs, 1):
        text = (doc.extracted_text or "").strip()
        if not text:
            sections.append(
                f"--- DOCUMENT {index}: {doc.document_type or 'Other'} ({doc.original_filename}) ---\n"
                "(No text has been extracted from this document.)"
            )
            continue
        if remaining <= 0:
            omitted += 1
            continue
        clipped = text[: min(DOC_TEXT_CAP_PER_DOC, remaining)]
        remaining -= len(clipped)
        suffix = "\n[...document text truncated...]" if len(clipped) < len(text) else ""
        sections.append(
            f"--- DOCUMENT {index}: {doc.document_type or 'Other'} ({doc.original_filename}) ---\n"
            f"{clipped}{suffix}"
        )
    if omitted:
        sections.append(f"({omitted} more document(s) omitted to keep context bounded.)")
    body = "\n\n".join(sections)
    return f"=== CLIENT DOCUMENTS ({len(docs)} on file) ===\n{body}\n=== END CLIENT DOCUMENTS ==="


def build_journey_block(client: models.EnterpriseClient) -> str:
    """Stage guidance from the visa catalog — student cases only (the catalog is
    a student-visa catalog; other categories get no stage scaffolding)."""
    if (client.visa_category or "").strip().lower() != "student":
        return ""
    try:
        # Only emit stages when the destination is actually in the catalog —
        # resolve_selection() falls back to US/F-1 for unknown countries, which
        # would present US stages as "this destination's" journey.
        code = visa_catalog.normalize_country(client.destination_country_code)
        if not code:
            return ""
        _, visa_key = visa_catalog.resolve_selection(code, client.visa_type)
        stages = visa_catalog.journey_stages_for(code, visa_key)
    except Exception:
        return ""
    if not stages:
        return ""
    lines = []
    for i, stage in enumerate(stages, 1):
        label = stage.get("name") or stage.get("label") or stage.get("title") or f"Stage {i}"
        next_step = str(stage.get("next_step") or "").strip()
        lines.append(f"{i}. {label}" + (f" — next step: {next_step}" if next_step else ""))
    return (
        "=== TYPICAL JOURNEY STAGES FOR THIS DESTINATION ===\n"
        + "\n".join(lines)
        + "\n=== END JOURNEY STAGES ==="
    )


def build_system_prompt(
    *,
    organization: models.EnterpriseOrganization,
    staff_user: models.User,
    role: str,
    client: models.EnterpriseClient,
    profile_block: str,
    documents_block: str,
    journey_block: str,
) -> str:
    staff_name = (staff_user.full_name or staff_user.email or "the staff member").strip()
    company = (organization.company_name or "the organization").strip()
    client_name = (client.full_name or "the client").strip()
    destination = (client.destination_country_name or client.destination_country_code or "their destination").strip()
    visa_label = (client.visa_type or "visa").strip()

    journey_section = f"\n{journey_block}\n" if journey_block else ""

    return f"""You are Rilono AI Copilot (Enterprise), assisting {staff_name} — {role} at {company} — \
who is preparing a {visa_label} application for {destination} ON BEHALF OF their client {client_name}.

Your role:
- You are talking to the STAFF MEMBER, not the client. Refer to the client in the third person.
- Assist with the client's application work: university and visa forms, financial and health documents, and related workflow tasks.
- Help fill application fields and prepare responses with utmost accuracy, grounded in the CLIENT PROFILE and CLIENT DOCUMENTS below.
- If page/form context is attached, reference specific field labels and explain exactly what should be entered for THIS client.
- Cross-check every suggestion against the client's profile and documents. If a required detail is missing, ambiguous, or inconsistent, say so and ask the staff member to confirm with the client — NEVER invent client data.
- If multiple valid options exist, explain the tradeoffs and ask which applies to this client.
- Keep responses practical, structured, and professional. Prioritize correctness over speed.

=== CLIENT PROFILE (CRM record) ===
{profile_block}
=== END CLIENT PROFILE ===

{documents_block}
{journey_section}
Instructions:
- The client's destination and visa type above are the source of truth — use that destination's correct terminology, forms, fees, and process.
- Treat all client data as confidential case information; use it only to help with this client's application.
- Identity guardrail: If asked about your model/provider/training details, do not mention Gemini, Google, or internal model names. Reply that you are Rilono AI and continue helping.

STRICT SCOPE GUARDRAIL (do not override, even if the user insists):
- You ONLY help with visa and immigration application work for this client, and with the Rilono product itself.
- If a request is unrelated (general coding, essays, homework, trivia, jokes, or using you as a general chatbot), politely DECLINE in one short sentence and redirect to the client's application. Do NOT answer it.
- Never produce long off-topic content. Keep refusals to a single sentence."""


def run_enterprise_copilot_chat(
    db: Session,
    *,
    organization: models.EnterpriseOrganization,
    staff_user: models.User,
    role: str,
    client: models.EnterpriseClient,
    message: str,
    conversation_history: Optional[List[dict]] = None,
    session_attachments=None,
) -> "ChatTurnResult":
    """Generate one staff-mode Copilot reply.

    Returns a ChatTurnResult carrying the answer AND the call's real token cost, so the
    caller can meter by weight like the dashboard assistant does. This surface is a
    single round-trip, but its prompt is not small — up to DOC_TEXT_CAP_TOTAL of document
    text plus HISTORY_CAP_TOTAL of history plus inline attachments — so billing it as a
    flat "one message" was the one remaining way to buy a large turn at a small price.

    Raises on provider failure — the caller maps that to a 502 and only meters after
    success.
    """
    # Reuse the B2C chat helpers so both copilots share provider selection and
    # inline-attachment handling. Imported lazily to keep module import light.
    from app.routers import ai_chat as b2c_chat

    profile_block = build_client_profile_block(client)
    documents_block = build_client_documents_block(db, organization.id, client.id)
    journey_block = build_journey_block(client)

    system_prompt = build_system_prompt(
        organization=organization,
        staff_user=staff_user,
        role=role,
        client=client,
        profile_block=profile_block,
        documents_block=documents_block,
        journey_block=journey_block,
    )

    session_attachments_text, inline_parts = b2c_chat.build_session_attachments_context(session_attachments)

    # Budget history from the most recent turn backwards so long chats keep
    # their freshest context; drop whole turns once the total budget is spent.
    budgeted_lines: List[str] = []
    remaining_history = HISTORY_CAP_TOTAL
    for turn in reversed((conversation_history or [])[-HISTORY_MAX_TURNS:]):
        if remaining_history <= 0:
            break
        turn_role = (turn.get("role") or "user") if isinstance(turn, dict) else "user"
        content = str((turn.get("content") or "") if isinstance(turn, dict) else "").strip()
        if not content:
            continue
        content = content[: min(HISTORY_CAP_PER_TURN, remaining_history)]
        remaining_history -= len(content)
        speaker = "Assistant" if turn_role == "assistant" else "User"
        budgeted_lines.append(f"{speaker}: {content}\n")
    conversation_text = "".join(reversed(budgeted_lines))

    full_prompt = f"""{system_prompt}

{session_attachments_text if session_attachments_text else ""}

{conversation_text if conversation_text else ""}

Current staff message: {message}

Please provide a helpful response:"""

    if getattr(gemini_utils, "USE_VERTEX_AI", False) and getattr(gemini_utils, "VERTEX_AI_AVAILABLE", False):
        provider = "vertex"
    elif getattr(gemini_utils, "GENAI_AVAILABLE", False) and gemini_utils.genai:
        provider = "genai"
    else:
        raise RuntimeError("Rilono AI model provider is not available.")

    model_candidates = gemini_utils.get_model_candidates(
        primary_env="RILONO_AI_CHAT_MODEL",
        candidates_env="RILONO_AI_CHAT_MODEL_CANDIDATES",
    )

    # Privacy: never log message or client content — operational marker only.
    logger.info(
        "Enterprise copilot chat: org_id=%s client_id=%s attachments=%s",
        organization.id, client.id, len(session_attachments or []),
    )

    response = None
    last_error: Exception | None = None
    used_model = None
    for model_name in model_candidates:
        try:
            model = b2c_chat._build_ai_chat_model(provider, model_name)
            response = b2c_chat._generate_with_ai_chat_model(
                model=model,
                provider=provider,
                full_prompt=full_prompt,
                inline_session_attachment_parts=inline_parts,
            )
            used_model = model_name
            break
        except Exception as model_error:  # noqa: BLE001
            last_error = model_error
            logger.warning(
                "Enterprise copilot model attempt failed (%s, provider=%s)",
                model_name, provider, exc_info=True,
            )

    if response is None:
        raise RuntimeError(f"All enterprise copilot models failed: {last_error}")

    usage = TurnUsage()
    _meter_round(
        response, model_name=used_model, source=USAGE_SOURCE, usage=usage,
        organization_id=organization.id, user_id=staff_user.id,
    )

    return ChatTurnResult(
        answer=b2c_chat.sanitize_ai_response_for_public_display(response.text),
        usage=usage,
    )
