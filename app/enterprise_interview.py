"""
Rilono Enterprise — AI mock visa interview.

A Gemini chat that role-plays the SPECIFIC visa officer for a client's destination
and visa type, conducting a realistic mock interview seeded with the client's
profile + notes. After the interview, a separate pass produces a coaching
assessment (verdict, readiness score, strengths, weaknesses, tips).

No tools / no DB access from the model here — it's a pure role-play conversation,
so this does not (and must not) read other clients' data.
"""

import logging
import re
from datetime import datetime
from typing import Optional

from app import models
from app import ai_usage
from app import enterprise_catalog as catalog
from app.enterprise_ai import is_ai_configured  # reuse the same availability check
from app.utils import gemini_service as gemini_utils

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 40


# Per-destination officer persona — what a real officer for that country probes.
_OFFICER_PERSONAS = {
    "US": ("a U.S. Consular Officer at a U.S. Embassy/Consulate conducting a student "
           "(F-1/J-1/M-1) visa interview. You are brisk, ask rapid-fire questions, and probe "
           "hard on genuine student intent, university/course choice, funding and sponsor, and "
           "strong ties to the home country (intent to return after studies)."),
    "CA": ("an IRCC officer assessing a Canadian Study Permit. You probe genuineness as a "
           "student, the study plan and choice of institution, proof of funds, and ties to the "
           "home country."),
    "UK": ("a UK Entry Clearance Officer conducting a Student visa credibility interview. You "
           "probe genuineness, the choice of course and university, English ability, financial "
           "evidence, and post-study intentions."),
    "AU": ("an Australian Department of Home Affairs officer assessing a student visa (Subclass "
           "500/590) against the Genuine Student requirement. You probe the rationale for the "
           "course and Australia, immediate circumstances at home, financial capacity, and "
           "incentives to return."),
    "DE": ("a German visa officer at a German mission assessing a national (Type D) student "
           "visa. You probe the study purpose, choice of program, German/English ability, the "
           "blocked account / financing, and plans after studies."),
    "IE": ("an Irish visa officer assessing a Study (D) visa. You probe genuineness as a student, "
           "the course and college choice, finances, and ties to the home country."),
}
_GENERIC_PERSONA = ("an experienced student-visa interviewing officer. You probe genuine student "
                    "intent, the choice of course and institution, financial capacity, and ties to "
                    "the home country.")


def _officer_persona(country_code: str) -> str:
    return _OFFICER_PERSONAS.get(str(country_code or "").upper(), _GENERIC_PERSONA)


def _client_context_block(client: models.EnterpriseClient, recent_notes: list) -> str:
    lines = [
        f"- Applicant name: {client.full_name}",
        f"- Destination country: {client.destination_country_name}",
        f"- Visa type: {client.visa_type}",
    ]
    if client.intake:
        lines.append(f"- Intended intake: {client.intake}")
    if client.nationality:
        lines.append(f"- Nationality: {client.nationality}")
    note_texts = [str(getattr(n, "body", "") or "").strip() for n in (recent_notes or [])]
    note_texts = [t for t in note_texts if t][:5]
    if note_texts:
        lines.append("- Counselor notes on file (for your context only, do not read these aloud):")
        for t in note_texts:
            lines.append(f"    • {t[:300]}")
    return "\n".join(lines)


def build_interview_system_prompt(
    client: models.EnterpriseClient,
    organization: models.EnterpriseOrganization,
    recent_notes: list,
) -> str:
    persona = _officer_persona(client.destination_country_code)
    context = _client_context_block(client, recent_notes)
    applicant = client.full_name
    return (
        f"You are {persona}\n\n"
        f"You are conducting a REALISTIC MOCK visa interview for the applicant below. Treat it "
        f"exactly like a real interview at the visa window. The applicant is practising.\n\n"
        f"=== APPLICANT PROFILE ===\n{context}\n=== END PROFILE ===\n\n"
        "RULES (follow strictly):\n"
        f"- Stay completely in character as the officer. Address {applicant} directly. Never say you "
        "are an AI, never break character, and never give feedback, scores or coaching DURING the "
        "interview.\n"
        "- Ask ONE question at a time, then wait for the answer. Keep your turns short — a brief, "
        "natural reaction (optional) plus a single question. Do not lecture.\n"
        "- Conduct a natural interview: react to what the applicant actually says and ask relevant "
        "follow-ups (including probing or slightly challenging ones, like a real officer). Cover the "
        "areas your role cares about over the course of the interview.\n"
        "- Be professional and polite but appropriately firm. Do not be unrealistically friendly.\n"
        "- Begin by greeting the applicant briefly and asking your first question.\n"
        "- Ask roughly 8–12 questions in total. When you have enough information to reach a "
        "decision, OR the applicant indicates they want to stop, END the interview yourself — do "
        "not keep asking questions afterwards.\n"
        "- To end, give a brief in-character closing (1–2 sentences) that clearly states your "
        "decision: whether the visa is APPROVED or REFUSED, with a short reason. For example: "
        "'Thank you. I'm satisfied with your answers and I'm pleased to approve your student visa "
        "today.' or 'I'm sorry, but based on this interview I'm unable to approve your visa at this "
        "time.' Base the decision honestly on how the applicant actually performed.\n"
        "- On the VERY LAST line of that closing message ONLY, append a status tag on its own line, "
        "exactly one of: [[INTERVIEW_COMPLETE: APPROVED]] or [[INTERVIEW_COMPLETE: REFUSED]]. Output "
        "this tag ONLY when you are ending the interview, never earlier, and never refer to the tag "
        "or read it aloud to the applicant.\n"
        "- Keep everything in English unless the applicant clearly cannot, and do not invent facts "
        "about the applicant beyond the profile — ask them instead."
    )


def _convert_history(history: Optional[list]) -> list:
    out = []
    if not history:
        return out
    for turn in history[-MAX_HISTORY_TURNS:]:
        role = str((turn or {}).get("role", "")).strip().lower()
        content = str((turn or {}).get("content", "")).strip()
        if not content:
            continue
        genai_role = "model" if role in ("model", "assistant", "ai", "officer") else "user"
        out.append({"role": genai_role, "parts": [content]})
    return out


def _model_name() -> str:
    return gemini_utils.get_model_candidates(
        primary_env="ENTERPRISE_AI_MODEL",
        candidates_env="ENTERPRISE_AI_MODEL_CANDIDATES",
    )[0]


def _model(system_instruction: str):
    return gemini_utils.genai.GenerativeModel(_model_name(), system_instruction=system_instruction)


# The officer ends the interview by emitting this tag on the last line of its
# closing message. We strip it from what the applicant sees and surface the
# decision (approved/refused) to the UI so the interview can wrap up on its own.
_COMPLETION_RE = re.compile(
    r"\[\[\s*INTERVIEW[ _]COMPLETE\s*:\s*(APPROVED|APPROVE|REFUSED|REFUSE|REJECTED|REJECT)\s*\]\]",
    re.IGNORECASE,
)


def parse_completion(text: str) -> tuple[str, bool, Optional[str]]:
    """Return (clean_reply, finished, decision) where decision is 'approved' | 'refused' | None."""
    raw = text or ""
    match = _COMPLETION_RE.search(raw)
    if not match:
        return raw.strip(), False, None
    decision = "approved" if match.group(1).upper().startswith("APPROV") else "refused"
    cleaned = _COMPLETION_RE.sub("", raw).strip()
    return cleaned, True, decision


def run_interview_turn(
    *,
    client: models.EnterpriseClient,
    organization: models.EnterpriseOrganization,
    recent_notes: list,
    history: Optional[list],
    message: str,
    is_start: bool = False,
) -> dict:
    """One officer turn. Returns {'reply', 'finished', 'decision'}.

    'finished' is True when the officer has ended the interview; 'decision' is then
    'approved' or 'refused'. If is_start, the model opens the interview.
    """
    if not is_ai_configured():
        return {
            "reply": "The mock interview isn't available right now — Rilono AI isn't configured on the server.",
            "finished": False,
            "decision": None,
        }

    system = build_interview_system_prompt(client, organization, recent_notes)
    model = _model(system)
    chat = model.start_chat(history=_convert_history(history))

    if is_start:
        user_message = (
            "[The applicant has just sat down at the visa window and is ready. Greet them briefly "
            "and ask your first question now.]"
        )
    else:
        user_message = (message or "").strip()[:3000] or "(no answer given)"

    response = chat.send_message(user_message)
    ai_usage.record_gemini_usage("mock_interview", _model_name(), response)
    text = (getattr(response, "text", None) or "").strip()
    cleaned, finished, decision = parse_completion(text)
    return {
        "reply": cleaned or "Could you please repeat that?",
        "finished": finished,
        "decision": decision,
    }


def generate_interview_feedback(
    *,
    client: models.EnterpriseClient,
    organization: models.EnterpriseOrganization,
    history: list,
    officer_decision: Optional[str] = None,
) -> str:
    """One-shot coaching assessment of the interview transcript (markdown)."""
    if not is_ai_configured():
        return "Feedback isn't available right now — Rilono AI isn't configured on the server."

    transcript_lines = []
    for turn in (history or []):
        role = str((turn or {}).get("role", "")).strip().lower()
        content = str((turn or {}).get("content", "")).strip()
        if not content:
            continue
        speaker = "Officer" if role in ("model", "assistant", "ai", "officer") else "Applicant"
        transcript_lines.append(f"{speaker}: {content}")
    transcript = "\n".join(transcript_lines) or "(no interview took place)"

    system = (
        "You are an expert student-visa interview coach. You are given a transcript of a MOCK "
        f"{client.destination_country_name} student-visa interview (visa type: {client.visa_type}) "
        f"for the applicant {client.full_name}. Assess the APPLICANT's performance honestly and "
        "specifically, as preparation for the real interview.\n\n"
        "Respond in clean markdown with EXACTLY these sections:\n"
        "1. A first line in this exact format: `**Verdict:** <Likely Approved | Borderline | Needs "
        "Work> · **Readiness:** <N>/5`\n"
        "2. `### What went well` — 2–4 concise bullets.\n"
        "3. `### Red flags & weaknesses` — 2–4 concise bullets referencing what the applicant said.\n"
        "4. `### How to improve` — 3–5 specific, actionable tips.\n"
        "5. `### Stronger sample answers` — rewrite 1–2 of the applicant's weakest answers as model "
        "answers.\n"
        "Be direct and practical. Do not invent facts that weren't in the transcript."
    )
    if officer_decision in ("approved", "refused"):
        system += (
            f"\n\nNote: in this mock, the simulated officer's final decision was "
            f"'{officer_decision.upper()}'. Keep your coaching consistent with that outcome, but "
            "still give your own honest, constructive assessment."
        )
    model = _model(system)
    response = model.start_chat(history=[]).send_message(
        "Here is the interview transcript to assess:\n\n" + transcript[:24000]
    )
    ai_usage.record_gemini_usage("interview_feedback", _model_name(), response)
    return (getattr(response, "text", None) or "").strip() or "No feedback could be generated."


def extract_verdict(feedback_text: str) -> Optional[str]:
    """Pull a short verdict label out of the feedback for the sessions list."""
    text = (feedback_text or "").lower()
    if "likely approved" in text:
        return "Likely Approved"
    if "needs work" in text:
        return "Needs Work"
    if "borderline" in text:
        return "Borderline"
    return None
