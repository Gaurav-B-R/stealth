"""
Rilono Enterprise — AI mock visa interview.

A Gemini chat that role-plays the SPECIFIC visa officer for a client's destination
and visa type, conducting a realistic, demanding mock interview grounded in the
client's own profile, uploaded documents, and counselor notes so it can ask the
toughest, most personalized questions and cross-examine inconsistencies. After the
interview, a separate pass produces a coaching assessment (verdict, readiness
score, strengths, weaknesses, tips).

No tools / no live DB access from the model here — it's a pure role-play
conversation seeded only with THIS client's own data, so it never reads other
clients' data.
"""

import logging
import re
from datetime import datetime
from typing import Optional

from app import models
from app import ai_usage
from app import enterprise_catalog as catalog
from app.enterprise_ai import is_ai_configured, sanitize_public_ai_text  # reuse the same availability check
from app.utils import gemini_service as gemini_utils

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 40


# Per-destination officer persona — what a real officer for that country probes.
_OFFICER_PERSONAS = {
    "US": ("a U.S. consular officer working the student window at the post covering the applicant's "
           "residence, deciding an F-1, M-1 or J-1 case in about two minutes against the INA 214(b) "
           "presumption that everyone in front of you intends to immigrate. With the DS-160 and "
           "their public online presence already open, you probe why this school and this major "
           "over the others that admitted them, who is funding it and where that money came from, "
           "how the full I-20 cost is met, and what actually brings them home."),
    "CA": ("an IRCC officer at the migration office covering the applicant's region, calling in a "
           "study-permit applicant whose paper file has raised questions you now want answered in "
           "person. You probe whether the programme is a rational next step given their existing "
           "qualifications and its cost, where the tuition and living funds came from and how long "
           "they have sat there, who the sponsor is and what they earn, and what the applicant "
           "would actually return home to under R216(1)(b)."),
    "UK": ("a UK Entry Clearance Officer at a decision-making centre, running the Genuine Student "
           "credibility interview by video after the sponsor's own pre-CAS call. You probe why this "
           "course at this licensed sponsor rather than one at home, what the applicant actually "
           "knows about the modules, fees and the city, whose account the maintenance funds sat in "
           "for the 28 days and where they came from, prior refusals and how much of it an agent "
           "did — judging their English from the answers, not the certificate."),
    "AU": ("a Department of Home Affairs case officer running a telephone credibility interview on "
           "a Subclass 500 file, testing it against the Genuine Student criterion at clause "
           "500.212. You probe current circumstances at home, why this CRICOS provider and course "
           "rather than one already open to the applicant, any change of direction or study gap "
           "since the last qualification, who is paying and where that money sat three months ago, "
           "and what they intend to do when the visa ends."),
    "DE": ("a visa officer in the national-visa section of a German mission, deciding a Type D "
           "study file before it goes to the Ausländerbehörde for consent. You probe how the study "
           "plan coheres with the APS-verified record — a change of field, gap years, a second "
           "master's — whether the applicant's German or English really matches the language of "
           "instruction named on the Zulassungsbescheid, whose money filled the Sperrkonto and "
           "where it came from, and what they intend to do once the degree is finished."),
    "IE": ("an Irish visa officer at the Dublin Visa Office assessing a Long Stay (D) Study "
           "application, so you interrogate the file as much as the person. You probe why this ILEP "
           "or TrustEd Ireland programme rather than one at home, how it follows on from the "
           "applicant's education and what filled any gap since, who paid the €6,000 fee instalment "
           "and where the €10,000 living funds came from, every large lodgement in the six-month "
           "statements, undisclosed refusals anywhere, and what obliges them to return."),
    "FR": ("a Campus France adviser conducting the compulsory entretien pédagogique at an Espace "
           "Campus France, the academic interview every Études en France applicant sits before any "
           "consular step. You authenticate the originals against the dossier and probe the "
           "coherence of the projet d'études: why this programme and this institution, why France, "
           "any change of level or field, the language level for the language of instruction, and "
           "how the year is funded and by whom."),
    "ES": ("a Spanish consular officer at the mission with jurisdiction over the applicant's "
           "residence, assessing a long-stay national (Type D) study visa. You probe whether the "
           "course and the centre cohere with the applicant's academic record, whether their "
           "Spanish is genuinely enough to follow the teaching, where the money shown against the "
           "IPREM requirement came from and when it appeared, accommodation and insurance, and "
           "whether the study purpose is genuine rather than a way to settle in Spain."),
    "NL": ("a Dutch university admissions panellist running a selection and credibility screening "
           "for a numerus-fixus or English-taught programme at a recognised-sponsor institution. "
           "You probe motivation for THIS programme, how named prior coursework maps onto its "
           "curriculum, English fluency for small-group seminar teaching, how the year is funded, "
           "and what the applicant intends to do after graduating, including the orientation year."),
    "AE": ("a department head on the admissions panel of a MoHESR/CAA-licensed UAE university, "
           "deciding whether the applicant is offered a place. You probe academic fit and grades, "
           "English against the level this programme actually demands, why this campus rather than "
           "its home campus or a university back home, how tuition and the institution's refundable "
           "deposit will be paid, and how the applicant will manage life in the Emirates."),
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


# Per-document caps keep the interview grounded without bloating the prompt (which
# also keeps the stable system-instruction cache-friendly).
_DOC_TEXT_CAP = 1800
_DOCS_TOTAL_CAP = 14000
_MAX_DOCS = 12


def _documents_context_block(documents: list) -> str:
    """Format THIS client's uploaded documents (type + bounded extracted text) so the
    officer can ask document-specific questions and catch inconsistencies. Empty when
    the client has no documents on file."""
    docs = list(documents or [])[:_MAX_DOCS]
    if not docs:
        return ""
    lines = []
    total = 0
    for i, d in enumerate(docs, 1):
        dtype = str(getattr(d, "document_type", "") or "Document").strip() or "Document"
        fname = str(getattr(d, "original_filename", "") or "").strip()
        lines.append(f"--- Document {i}: {dtype}" + (f" ({fname})" if fname else "") + " ---")
        text = str(getattr(d, "extracted_text", "") or "").strip()
        if not text:
            lines.append("(on file; contents not yet extracted)")
            continue
        remaining = _DOCS_TOTAL_CAP - total
        if remaining <= 0:
            lines.append("(further document contents omitted for brevity)")
            break
        snippet = text[: min(_DOC_TEXT_CAP, remaining)]
        total += len(snippet)
        lines.append(snippet)
    body = "\n".join(lines)
    return (
        "\n\n=== APPLICANT'S UPLOADED DOCUMENTS (for your context only — do NOT read them aloud; "
        "use them to ask pointed, specific questions and to catch any inconsistencies) ===\n"
        f"{body}\n=== END DOCUMENTS ==="
    )


def build_interview_system_prompt(
    client: models.EnterpriseClient,
    organization: models.EnterpriseOrganization,
    recent_notes: list,
    documents: Optional[list] = None,
) -> str:
    persona = _officer_persona(client.destination_country_code)
    context = _client_context_block(client, recent_notes)
    documents_block = _documents_context_block(documents)
    applicant = client.full_name
    return (
        f"You are {persona}\n\n"
        f"You are conducting a REALISTIC, DEMANDING MOCK visa interview for the applicant below. Treat "
        f"it exactly like a real, high-pressure interview at the visa window. The applicant is "
        f"practising and must be genuinely challenged so the real interview feels easier.\n\n"
        f"=== APPLICANT PROFILE ===\n{context}\n=== END PROFILE ==={documents_block}\n\n"
        "RULES (follow strictly):\n"
        f"- Stay completely in character as the officer. Address {applicant} directly. Never say you "
        "are an AI, never break character, and never give feedback, scores or coaching DURING the "
        "interview.\n"
        "- Ask ONE question at a time, then wait for the answer. Keep your turns short — a brief, "
        "natural reaction (optional) plus a single question. Do not lecture.\n"
        "- Use the applicant's PROFILE and UPLOADED DOCUMENTS to ask the toughest, most SPECIFIC "
        "questions for THIS applicant — never generic textbook questions. Ground questions in real "
        "details (course, institution, tuition and living costs, funds and sponsor, test scores, "
        "gaps, work history, family and home-country ties).\n"
        "- Cross-examine. If an answer is vague, rehearsed, evasive, over-confident, or inconsistent "
        "with the documents/profile (e.g. funds look short, a sponsor is unclear, ties are weak, or "
        "timelines don't add up), press hard with a sharper, pointed follow-up instead of moving on.\n"
        "- Progressively escalate the difficulty as the interview proceeds; do not let the applicant "
        "settle into a comfort zone.\n"
        "- Conduct a natural interview: react to what the applicant actually says and cover the areas "
        "your role cares about over the course of the interview.\n"
        "- Be professional and polite but firm and appropriately skeptical. Do not be unrealistically "
        "friendly or hand the applicant an easy pass.\n"
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
        "about the applicant beyond the profile/documents — ask them instead."
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


def _model_candidates() -> list[str]:
    return gemini_utils.get_model_candidates(
        primary_env="ENTERPRISE_AI_MODEL",
        candidates_env="ENTERPRISE_AI_MODEL_CANDIDATES",
    )


def _model(model_name: str, system_instruction: str):
    return gemini_utils.genai.GenerativeModel(model_name, system_instruction=system_instruction)


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
    documents: Optional[list] = None,
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

    if is_start:
        user_message = (
            "[The applicant has just sat down at the visa window and is ready. Greet them briefly "
            "and ask your first question now.]"
        )
    else:
        user_message = (message or "").strip()[:3000] or "(no answer given)"

    system = build_interview_system_prompt(client, organization, recent_notes, documents)
    last_error = None
    for model_name in _model_candidates():
        try:
            model = _model(model_name, system)
            chat = model.start_chat(history=_convert_history(history))
            response = chat.send_message(user_message)
            ai_usage.record_gemini_usage("mock_interview", model_name, response)
            text = sanitize_public_ai_text((getattr(response, "text", None) or "").strip())
            cleaned, finished, decision = parse_completion(text)
            return {
                "reply": cleaned or "Could you please repeat that?",
                "finished": finished,
                "decision": decision,
            }
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("Enterprise interview model attempt failed (%s)", model_name, exc_info=True)

    raise RuntimeError("The mock interview could not answer right now.") from last_error


def generate_interview_feedback(
    *,
    client: models.EnterpriseClient,
    organization: models.EnterpriseOrganization,
    history: list,
    officer_decision: Optional[str] = None,
    documents: Optional[list] = None,
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
        f"for the applicant {client.full_name}. Assess the APPLICANT's performance honestly.\n\n"
        "Write a SHORT, scannable report a busy student can skim in ~20 seconds. Clean markdown, "
        "EXACTLY these sections and nothing else:\n"
        "1. First line, EXACTLY this format: `**Verdict:** <Likely Approved | Borderline | Needs "
        "Work> · **Readiness:** <N>/5`\n"
        "2. `### What went well` — 1–3 bullets. If the applicant barely answered, say so in ONE bullet.\n"
        "3. `### Red flags` — 2–3 bullets.\n"
        "4. `### How to improve` — exactly 3 bullets.\n"
        "5. `### Model answer` — ONE improved answer to the single most important question, 2–3 short "
        "sentences. Omit this whole section if the applicant gave no real answers.\n\n"
        "STRICT style rules (follow exactly):\n"
        "- Every bullet = a **bold 2–4 word label**, an em dash, then ONE short clause. Max ~16 words "
        "per bullet. One line each.\n"
        "- No long paragraphs, no quoting the transcript back, no repetition, no preamble or sign-off.\n"
        "- Be specific and practical. Never invent facts that weren't in the transcript."
    )
    documents_block = _documents_context_block(documents)
    if documents_block:
        system += (
            "\n\nUse the applicant's uploaded documents below to judge whether their answers were "
            "backed by real evidence; specifically flag any answer that contradicted or wasn't "
            "supported by these documents (e.g. funds, sponsor, ties, timelines)." + documents_block
        )
    if officer_decision in ("approved", "refused"):
        system += (
            f"\n\nNote: in this mock, the simulated officer's final decision was "
            f"'{officer_decision.upper()}'. Keep your coaching consistent with that outcome, but "
            "still give your own honest, constructive assessment."
        )
    last_error = None
    for model_name in _model_candidates():
        try:
            model = _model(model_name, system)
            response = model.start_chat(history=[]).send_message(
                "Here is the interview transcript to assess:\n\n" + transcript[:24000]
            )
            ai_usage.record_gemini_usage("interview_feedback", model_name, response)
            text = sanitize_public_ai_text((getattr(response, "text", None) or "").strip())
            return text or "No feedback could be generated."
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("Enterprise feedback model attempt failed (%s)", model_name, exc_info=True)

    raise RuntimeError("Interview feedback could not be generated right now.") from last_error


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
