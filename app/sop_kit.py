"""
Application Kit — personalized SOP / Statement of Purpose generator.

Country + university + program specific, grounded in the student's REAL profile and
uploaded documents (never invented facts), with iterative refinement ("make it more
technical", "tie it to my internship"). Every generation and refinement is stored as
an immutable SopDraft version so the student can review or restore history.

Model: SOP_GENERATOR_MODEL / SOP_GENERATOR_MODEL_CANDIDATES (defaults to the master
Gemini chain — quality matters most here; usage metered under source `sop_generator`).
"""

import json
import logging
import re

from sqlalchemy.orm import Session

from app import models
from app import visa_catalog
from app.utils import gemini_service as gemini_utils

logger = logging.getLogger(__name__)

# Grounding-size guards (characters, pre-tokenization).
MAX_PROFILE_CHARS = 8_000
MAX_DOC_CHARS = 3_500          # per document
MAX_DOCS_TOTAL_CHARS = 30_000  # across all documents
MAX_DRAFT_CHARS = 30_000       # refine input safety cap

# Per-country statement conventions. `doc_name` is what the deliverable is actually
# called in that admissions culture; conventions are injected into the prompt.
COUNTRY_SOP_SPECS: dict[str, dict] = {
    "US": {
        "doc_name": "Statement of Purpose",
        "words": "650-900 words",
        "conventions": [
            "Open with a concrete moment or problem from the student's real experience — never a famous quote, dictionary definition, or childhood-dream cliché.",
            "Build one narrative: academic background → key projects/experience → the specific gap this program fills → research/career goals it enables.",
            "US committees expect specificity: reference the university's courses, labs, or faculty. If those specifics aren't in the student's materials, insert a [PLACEHOLDER: ...] telling them exactly what to look up.",
            "Confident and forward-looking; no melodrama, no flattery like 'esteemed university'.",
        ],
    },
    "UK": {
        "doc_name": "Personal Statement",
        "words": "500-700 words (must stay under 4,000 characters)",
        "conventions": [
            "Course-fit first: UK admissions read for sustained engagement with the subject, evidenced by what the student has actually done — not adjectives.",
            "Plain, measured, semi-formal British tone; no flowery openings or grand claims.",
            "Reference the course's structure or modules where relevant — as [PLACEHOLDER: ...] if the specifics aren't in the student's materials.",
            "Career trajectory should follow logically from the course; keep every claim consistent with the student's CAS story and credibility-interview answers.",
        ],
    },
    "CA": {
        "doc_name": "Statement of Purpose (Study Plan)",
        "words": "800-1000 words",
        "conventions": [
            "This document doubles as the study-permit STUDY PLAN — an IRCC officer may read it, not just admissions.",
            "Explicitly answer: why Canada, why this program, and why not a comparable program in the student's home country.",
            "State the funding plan plainly and keep it consistent with the student's proof of funds / GIC documents.",
            "Address ties to the home country and the post-graduation plan directly — officers look for a coherent return/career logic.",
        ],
    },
    "AU": {
        "doc_name": "Statement of Purpose",
        "words": "800-1000 words",
        "conventions": [
            "Align with the Genuine Student criteria: the student's circumstances, the value of the course to their future, and honest course-choice logic.",
            "Explain why Australia and why this provider factually — case officers cross-check claims against the CoE and file; no exaggeration.",
            "Reference the CoE program specifics via [PLACEHOLDER: ...] where the student's materials don't contain them.",
            "Keep the statement consistent with what the student would say in GS questions.",
        ],
    },
    "DE": {
        "doc_name": "Motivationsschreiben (Letter of Motivation)",
        "words": "500-800 words (about one page)",
        "conventions": [
            "Sober, precise, German academic register — zero flattery, zero drama, no salesy language.",
            "Argue concretely from curriculum fit: connect the student's prior coursework and projects to this program's technical content and structure (modules as [PLACEHOLDER: ...] if unknown).",
            "If the program is German-taught, address language preparation; keep everything consistent with uni-assist/APS records.",
            "Close with the specific professional goal the degree enables — stated plainly, not aspirationally vague.",
        ],
    },
}

_IDENTITY_GUARDRAIL = (
    "Identity guardrail: never mention Gemini, Google, AI models, or internal tooling; "
    "you are Rilono AI. Never include meta-commentary about being an AI."
)

_GROUNDING_RULES = """GROUNDING RULES (absolute):
- Use ONLY facts found in the student's profile, their uploaded documents, and their stated inputs below.
- NEVER invent achievements, grades, test scores, employers, project names, dates, or people.
- Where the statement needs a fact you don't have (a module name, a professor, a company detail), insert an explicit placeholder in the form [PLACEHOLDER: what the student must fill in].
- Write in the first person, in a natural human voice a real student would use — vary sentence length, no template phrasing, no bullet lists inside the letter body."""


def _spec_for(country_code: str | None) -> dict:
    return COUNTRY_SOP_SPECS.get(str(country_code or "US").strip().upper(), COUNTRY_SOP_SPECS["US"])


def _model_candidates() -> list[str]:
    return gemini_utils.get_model_candidates(
        primary_env="SOP_GENERATOR_MODEL",
        candidates_env="SOP_GENERATOR_MODEL_CANDIDATES",
    )


def _profile_context(user_id: int) -> str:
    """Student profile JSON (the same artifact the AI chat grounds on)."""
    try:
        from app.routers.ai_chat import get_student_profile_and_status
        data = get_student_profile_and_status(user_id) or {}
        return json.dumps(data, indent=1, default=str)[:MAX_PROFILE_CHARS]
    except Exception:
        logger.warning("SOP: profile context unavailable for user %s", user_id, exc_info=True)
        return ""


# Document types that carry the most SOP-relevant signal, first.
_DOC_PRIORITY = ("resume", "cv", "transcript", "academic", "admission", "offer", "test", "ielts",
                 "toefl", "gre", "language", "experience", "internship", "recommendation")


def _doc_rank(doc: dict) -> int:
    label = f"{doc.get('document_type') or ''} {doc.get('filename') or ''}".lower()
    for i, key in enumerate(_DOC_PRIORITY):
        if key in label:
            return i
    return len(_DOC_PRIORITY)


def _documents_context(user_id: int, db: Session) -> str:
    """Extracted text of the student's (legacy-readable) documents, most relevant first."""
    try:
        from app.routers.ai_chat import get_user_document_files
        files = get_user_document_files(user_id, db) or []
    except Exception:
        logger.warning("SOP: document context unavailable for user %s", user_id, exc_info=True)
        return ""
    files.sort(key=_doc_rank)
    parts, total = [], 0
    for f in files:
        content = (f.get("content") or "").strip()[:MAX_DOC_CHARS]
        if not content:
            continue
        block = f"--- DOCUMENT: {f.get('document_type', 'document')} ({f.get('filename', '')}) ---\n{content}"
        if total + len(block) > MAX_DOCS_TOTAL_CHARS:
            break
        parts.append(block)
        total += len(block)
    return "\n\n".join(parts)


def _inputs_block(*, university: str, program: str, study_level: str | None,
                  intake: str | None, highlights: str | None, country_name: str, visa_label: str) -> str:
    lines = [
        f"Destination: {country_name} ({visa_label})",
        f"University: {university}",
        f"Program: {program}",
    ]
    if study_level:
        lines.append(f"Study level: {study_level}")
    if intake:
        lines.append(f"Intake: {intake}")
    if highlights:
        lines.append(f"The student specifically wants to emphasize: {highlights}")
    return "\n".join(lines)


def _build_generation_prompt(spec: dict, inputs: str, profile_json: str, docs_text: str) -> str:
    conventions = "\n".join(f"- {c}" for c in spec["conventions"])
    return f"""You are Rilono AI, an elite study-abroad admissions writing coach. Write a {spec['doc_name']} of {spec['words']} for the student below.

{_GROUNDING_RULES}

COUNTRY CONVENTIONS ({spec['doc_name']}):
{conventions}

STUDENT'S REQUEST:
{inputs}

STUDENT PROFILE (JSON):
{profile_json or '(no structured profile available)'}

STUDENT'S UPLOADED DOCUMENTS (extracted text):
{docs_text or '(no readable documents uploaded yet — rely on the profile and request, and use placeholders where specifics are missing)'}

OUTPUT FORMAT (Markdown):
# {spec['doc_name']} — <university name>
<the full statement body in flowing paragraphs>

---
**Rilono notes:** 2-4 short bullets listing every [PLACEHOLDER: ...] you inserted and the single highest-impact personalization the student should add before submitting.

{_IDENTITY_GUARDRAIL}"""


def _build_refine_prompt(spec: dict, inputs: str, current_draft: str, instruction: str,
                         profile_json: str, docs_text: str) -> str:
    conventions = "\n".join(f"- {c}" for c in spec["conventions"])
    return f"""You are Rilono AI, an elite study-abroad admissions writing coach. Revise the student's {spec['doc_name']} below according to their instruction, keeping it {spec['words']}.

STUDENT'S REVISION INSTRUCTION: {instruction}

{_GROUNDING_RULES}
- Apply the instruction decisively, but preserve everything that already works; do not rewrite from scratch unless asked.

COUNTRY CONVENTIONS ({spec['doc_name']}):
{conventions}

STUDENT'S REQUEST (original brief):
{inputs}

CURRENT DRAFT:
{current_draft[:MAX_DRAFT_CHARS]}

STUDENT PROFILE (JSON):
{profile_json or '(no structured profile available)'}

STUDENT'S UPLOADED DOCUMENTS (extracted text):
{docs_text or '(no readable documents uploaded)'}

OUTPUT FORMAT (Markdown): the COMPLETE revised statement in the same format as the current draft (title line, body, then the **Rilono notes:** bullets updated for this revision).

{_IDENTITY_GUARDRAIL}"""


def _run_gemini(prompt: str, user_id: int) -> tuple[str, str]:
    """Try the candidate chain; return (text, model_used). Raises RuntimeError if all fail."""
    last_error: Exception | None = None
    for model_name in _model_candidates():
        try:
            # Pass usage_source so build_generative_model's own instrumentation records
            # this under "sop_generator". It previously defaulted to "document_ai" and the
            # explicit record_gemini_usage below logged the SAME response a second time —
            # double-counting SOP spend and mislabelling half of it as document AI.
            model = gemini_utils.build_generative_model(
                model_name, usage_source="sop_generator", user_id=user_id,
            )
            response = model.generate_content(prompt)
            text = (getattr(response, "text", None) or "").strip()
            if text:
                return text, model_name
            last_error = RuntimeError(f"{model_name} returned empty text")
        except Exception as exc:  # try the next live model
            last_error = exc
            logger.warning("SOP generation failed on %s: %s", model_name, exc)
    raise RuntimeError(f"All SOP model candidates failed: {last_error}")


def _word_count(text: str) -> int:
    # Count the letter body only (strip the Rilono notes tail if present).
    body = re.split(r"\n-{3,}\n", text)[0]
    return len(re.findall(r"\b\w+\b", body))


def generate_sop(db: Session, user: models.User, *, university: str, program: str,
                 study_level: str | None = None, intake: str | None = None,
                 highlights: str | None = None) -> models.SopDraft:
    """Generate a brand-new statement (version 1 of a new root)."""
    country, visa = visa_catalog.resolve_selection(
        getattr(user, "destination_country_code", None), getattr(user, "visa_type_key", None))
    spec = _spec_for(country)
    meta = visa_catalog.country_meta(country) or {}
    inputs = _inputs_block(
        university=university, program=program, study_level=study_level, intake=intake,
        highlights=highlights, country_name=meta.get("name", country),
        visa_label=visa_catalog.visa_type_label(country, visa),
    )
    prompt = _build_generation_prompt(spec, inputs, _profile_context(user.id), _documents_context(user.id, db))
    text, model_used = _run_gemini(prompt, user.id)

    draft = models.SopDraft(
        user_id=user.id, version=1, country_code=country, visa_type_key=visa,
        university=university.strip(), program=program.strip(),
        study_level=(study_level or "").strip() or None, intake=(intake or "").strip() or None,
        highlights=(highlights or "").strip() or None, instruction=None,
        content_md=text, word_count=_word_count(text), model_used=model_used,
    )
    db.add(draft)
    db.flush()
    draft.root_id = draft.id
    db.commit()
    db.refresh(draft)
    return draft


def refine_sop(db: Session, user: models.User, latest: models.SopDraft, instruction: str) -> models.SopDraft:
    """Create the next version of an existing statement per the student's instruction."""
    spec = _spec_for(latest.country_code)
    meta = visa_catalog.country_meta(latest.country_code or "US") or {}
    inputs = _inputs_block(
        university=latest.university, program=latest.program, study_level=latest.study_level,
        intake=latest.intake, highlights=latest.highlights,
        country_name=meta.get("name", latest.country_code or "US"),
        visa_label=visa_catalog.visa_type_label(latest.country_code, latest.visa_type_key),
    )
    prompt = _build_refine_prompt(spec, inputs, latest.content_md, instruction.strip(),
                                  _profile_context(user.id), _documents_context(user.id, db))
    text, model_used = _run_gemini(prompt, user.id)

    draft = models.SopDraft(
        user_id=user.id, root_id=latest.root_id, version=(latest.version or 1) + 1,
        country_code=latest.country_code, visa_type_key=latest.visa_type_key,
        university=latest.university, program=latest.program,
        study_level=latest.study_level, intake=latest.intake, highlights=latest.highlights,
        instruction=instruction.strip(), content_md=text,
        word_count=_word_count(text), model_used=model_used,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def doc_display_name(country_code: str | None) -> str:
    return _spec_for(country_code)["doc_name"]


def serialize_draft(d: models.SopDraft) -> dict:
    return {
        "id": d.id, "root_id": d.root_id, "version": d.version,
        "country_code": d.country_code, "visa_type_key": d.visa_type_key,
        "university": d.university, "program": d.program,
        "study_level": d.study_level, "intake": d.intake, "highlights": d.highlights,
        "instruction": d.instruction, "content_md": d.content_md,
        "word_count": d.word_count, "model_used": d.model_used,
        "doc_name": doc_display_name(d.country_code),
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }
