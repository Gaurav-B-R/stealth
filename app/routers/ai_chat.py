from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas
from app import visa_catalog
from app import visa_pass
from app.auth import get_current_active_user
from app.subscriptions import (
    get_or_create_user_subscription,
    get_plan_limits,
    get_rilono_ai_chat_upload_quota_snapshot,
)
from app.utils.rate_limiter import check_ip_rate_limit
from app.utils.secure_artifacts import decrypt_artifact_bytes
from app import ai_guardrails
from app import ai_usage
# Import Gemini configuration
from app.utils import gemini_service as gemini_utils
from typing import Optional, List
import base64
import binascii
import hashlib
import os
import json
import re
from pathlib import Path
import boto3
from botocore.config import Config
from pydantic import BaseModel

router = APIRouter(prefix="/api/ai-chat", tags=["ai-chat"])

PUBLIC_AI_RESPONSE_ERROR_DETAIL = (
    "Sorry, I encountered an issue while responding. Please try again in a little while. "
    "This issue has been raised for review."
)

# R2 Configuration for documents
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_DOCUMENTS_BUCKET = os.getenv("R2_DOCUMENTS_BUCKET", "documents")
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL", f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com")

# Initialize R2 client
r2_client = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT_URL,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name='auto',
    config=Config(signature_version='s3v4')
)

MAX_SESSION_ATTACHMENTS = 8
MAX_SESSION_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_SESSION_ATTACHMENTS_TOTAL_BYTES = 20 * 1024 * 1024
MAX_SESSION_ATTACHMENT_TEXT_CHARS = 40000
ALLOWED_CHAT_ATTACHMENT_MIME_PREFIXES = ("image/", "text/")
ALLOWED_CHAT_ATTACHMENT_MIME_TYPES = {
    "application/pdf",
    "application/json",
    "application/csv",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/rtf",
    "text/rtf",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

TEXT_ATTACHMENT_MIME_TYPES = {
    "application/json",
    "application/csv",
    "application/rtf",
    "text/rtf",
}
ATTACHMENT_ID_ALLOWED_PATTERN = re.compile(r"[^A-Za-z0-9._:-]+")


def sanitize_ai_response_for_public_display(text: str) -> str:
    """Keep internal provider/model names out of user-visible AI responses.

    Delegates to the shared scrubber in ai_guardrails so B2C and enterprise
    surfaces apply identical rules — including phrase-level leaks like
    "trained by Google" that the old token pattern missed."""
    return ai_guardrails.sanitize_provider_disclosures(text)


def _build_ai_chat_model(provider: str, model_name: str, generation_config: Optional[dict] = None):
    """Build the chat model, optionally with a generation config (e.g. a short output cap
    for fast, clipped interview turns). generation_config is a plain dict so it works across
    both providers; it's translated to each SDK's shape here."""
    if provider == "vertex":
        from vertexai.generative_models import GenerativeModel, GenerationConfig

        if generation_config:
            return GenerativeModel(model_name, generation_config=GenerationConfig(**generation_config))
        return GenerativeModel(model_name)
    if provider == "genai":
        if generation_config:
            # google.generativeai accepts a plain dict generation_config.
            return gemini_utils.genai.GenerativeModel(model_name, generation_config=generation_config)
        return gemini_utils.genai.GenerativeModel(model_name)
    raise RuntimeError("Rilono AI model provider is not configured")


def _generate_with_ai_chat_model(
    *,
    model,
    provider: str,
    full_prompt: str,
    inline_session_attachment_parts: list[dict],
):
    if inline_session_attachment_parts:
        if provider == "vertex":
            from vertexai.generative_models import Part
            prompt_parts = [full_prompt]
            for file_part in inline_session_attachment_parts:
                prompt_parts.append(
                    Part.from_data(
                        data=file_part["data"],
                        mime_type=file_part["mime_type"],
                    )
                )
            return model.generate_content(prompt_parts)

        if provider == "genai":
            prompt_parts = [full_prompt]
            for file_part in inline_session_attachment_parts:
                prompt_parts.append(
                    {
                        "mime_type": file_part["mime_type"],
                        "data": file_part["data"],
                    }
                )
            return model.generate_content(prompt_parts)

    return model.generate_content(full_prompt)


def _extract_ai_text(response) -> tuple[str, bool]:
    """Return (text, truncated) for a model response; raise when there is no text at all.

    Thinking models spend max_output_tokens on private reasoning BEFORE they speak, so an
    exhausted budget comes back as finish_reason=MAX_TOKENS carrying either no content parts
    at all (touching `.text` then raises) or a sentence cut off mid-word. Neither is usable,
    and — crucially — neither raises at the point of the call: the SDK reports the request as
    a success. That is why this classification lives here, to be called INSIDE the retry loop,
    instead of `.text` being read after it. Reading `.text` after the loop is what turned one
    truncated candidate into a 500 for the whole turn, with the healthy fallback models never
    tried.
    """
    finish_reason = ""
    try:
        first_candidate = (getattr(response, "candidates", None) or [None])[0]
        raw_reason = getattr(first_candidate, "finish_reason", None)
        finish_reason = str(getattr(raw_reason, "name", raw_reason) or "").upper()
    except Exception:  # noqa: BLE001 — introspection must never mask a usable reply
        finish_reason = ""
    truncated = finish_reason in ("MAX_TOKENS", "2")

    try:
        text = (response.text or "").strip()
    except Exception as exc:  # `.text` raises when the candidate carries no content parts
        raise RuntimeError(
            f"model returned no usable reply (finish_reason={finish_reason or 'unknown'})"
        ) from exc
    if not text:
        raise RuntimeError(
            f"model returned an empty reply (finish_reason={finish_reason or 'unknown'})"
        )
    return text, truncated


class ChatSessionAttachment(BaseModel):
    id: Optional[str] = None
    name: str
    mime_type: str
    size_bytes: Optional[int] = None
    content_base64: str

class ChatMessage(BaseModel):
    message: str
    conversation_history: Optional[List[dict]] = None
    session_attachments: Optional[List[ChatSessionAttachment]] = None
    source: Optional[str] = "rilono_ai_chat"
    # Extracted text from the user's END-TO-END-ENCRYPTED documents, decrypted in the browser
    # and supplied here only when the user has their vault unlocked. The server can't read those
    # documents itself, so this is the only way that content reaches the AI — consented + transient.
    e2e_document_context: Optional[str] = None

class ChatResponse(BaseModel):
    response: str

ALLOWED_CHAT_SOURCES = {
    "rilono_ai_chat",
    "rilono_ai_copilot",
    "visa_prep",
    "mock_interview",
    # Final evaluation/report generated after a mock interview ends. Kept separate from
    # `mock_interview` so it does NOT inherit the in-character visa-officer persona (which
    # is instructed to give no scores/feedback) — the report needs to score and advise.
    "mock_interview_report",
}

QUOTA_TRACKED_CHAT_SOURCES = {
    "rilono_ai_chat",
    "rilono_ai_copilot",
    "visa_prep",
    "mock_interview",
    "mock_interview_report",
}

AI_CHAT_RATE_LIMIT = int(os.getenv("AI_CHAT_RATE_LIMIT", "120"))
AI_CHAT_RATE_WINDOW_SECONDS = int(os.getenv("AI_CHAT_RATE_WINDOW_SECONDS", "60"))
AI_CHAT_USER_RATE_LIMIT = int(os.getenv("AI_CHAT_USER_RATE_LIMIT", "40"))


def _enforce_rate_limit_or_429(
    request: Request,
    scope: str,
    limit: int,
    window_seconds: int,
    extra_key: str | None = None,
) -> None:
    allowed, retry_after = check_ip_rate_limit(
        request=request,
        scope=scope,
        limit=limit,
        window_seconds=window_seconds,
        extra_key=extra_key,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many chat requests. Please slow down and try again.",
            headers={"Retry-After": str(retry_after)},
        )


def get_student_profile_raw_text(user_id: int) -> str | None:
    """
    Fetch decrypted STUDENT_PROFILE_AND_F1_VISA_STATUS.json raw text from R2.
    Returns raw JSON string or None if not found.
    """
    try:
        r2_key = f"user_{user_id}/STUDENT_PROFILE_AND_F1_VISA_STATUS.json"
        response = r2_client.get_object(Bucket=R2_DOCUMENTS_BUCKET, Key=r2_key)
        encrypted_blob = response['Body'].read()
        return decrypt_artifact_bytes(encrypted_blob).decode('utf-8')
    except Exception:
        return None


def get_user_navigation_guide_text() -> str:
    """
    Read the user navigation guide that should be attached to Gemini prompts.
    """
    try:
        guide_path = Path(__file__).resolve().parents[1] / "prompts" / "USER_NAVIGATION_GUIDE.md"
        if not guide_path.exists():
            return "User navigation guide file is not available."
        return guide_path.read_text(encoding="utf-8")
    except Exception:
        return "User navigation guide file could not be loaded."


def get_student_profile_and_status(user_id: int) -> dict:
    """
    Fetch student's comprehensive profile and visa status from R2.
    Returns the full profile dict or None if not found.
    """
    try:
        r2_key = f"user_{user_id}/STUDENT_PROFILE_AND_F1_VISA_STATUS.json"
        response = r2_client.get_object(Bucket=R2_DOCUMENTS_BUCKET, Key=r2_key)
        encrypted_blob = response['Body'].read()
        json_content = decrypt_artifact_bytes(encrypted_blob).decode('utf-8')
        return json.loads(json_content)
    except Exception:
        return None


def format_student_profile_context(profile_data: dict) -> str:
    """
    Format comprehensive student profile as context string for the AI.
    Includes profile info, documentation preferences, and visa journey status.
    """
    if not profile_data:
        return "Student profile: Not yet available. User should visit their dashboard."
    
    # Extract sections
    student_profile = profile_data.get('student_profile', {})
    doc_prefs = profile_data.get('documentation_preferences', {})
    visa_journey = profile_data.get('visa_journey', {})
    docs_summary = profile_data.get('documents_summary', {})

    # Destination + visa type personalize the whole context (defaults to US F-1).
    target_country = doc_prefs.get('target_country') or visa_journey.get('destination_country') or 'United States'
    visa_type = doc_prefs.get('visa_type') or visa_journey.get('visa_type') or 'F-1 Student Visa'
    total_stages = visa_journey.get('total_stages', 7)

    context = f"""
=== STUDENT PROFILE AND {visa_type.upper()} STATUS ({target_country}) ===

STUDENT INFORMATION:
- Name: {student_profile.get('full_name', 'Unknown')}
- Email: {student_profile.get('email', 'Unknown')}
- University: {student_profile.get('university', 'Not set')}
- University Email: {student_profile.get('university_email', 'Not provided')}
- Phone: {student_profile.get('phone', 'Not provided')}
- Home Country: {student_profile.get('current_residence_country', 'Not provided')}
- Visa Case Status: {student_profile.get('visa_case_status', 'Not provided')}
- Current Situation / Story: {student_profile.get('current_situation_story', 'Not provided')}
- Account Created: {student_profile.get('account_created', 'Unknown')}

DESTINATION PREFERENCES:
- Destination Country: {target_country}
- Visa Type: {visa_type}
- Intake Semester: {doc_prefs.get('intake_semester', 'Not set')}
- Intake Year: {doc_prefs.get('intake_year', 'Not set')}

{visa_type.upper()} JOURNEY STATUS ({target_country}):
- Current Stage: {visa_journey.get('current_stage', 1)} of {total_stages} - "{visa_journey.get('stage_name', 'Getting Started')}"
- Progress: {visa_journey.get('progress_percent', 0)}%
- Stage Description: {visa_journey.get('stage_description', '')}
- Next Step Required: {visa_journey.get('next_step_required', '')}

DOCUMENTS SUMMARY:
- Total Documents Uploaded: {docs_summary.get('total_documents_uploaded', 0)}
- Document Types: {', '.join(docs_summary.get('uploaded_document_types', [])) or 'None yet'}

Last Updated: {profile_data.get('last_updated', 'Unknown')}
"""
    return context


def get_user_documents_context(user_id: int, db: Session) -> str:
    """
    Fetch user's documents from R2 and create context string with document list.
    Returns a formatted string with document names (detailed content is attached separately).
    """
    try:
        # List ALL of the user's documents (including end-to-end-encrypted ones) so the AI is
        # aware of what they've uploaded. For E2E docs the server can't read the CONTENT — only
        # the metadata below — so the detailed extracted text comes from the client (if shared).
        documents = db.query(models.Document).filter(
            models.Document.user_id == user_id,
        ).all()

        if not documents:
            return "No documents have been uploaded yet."

        context_parts = [f"User's Uploaded Documents ({len(documents)} total):"]

        for doc in documents:
            if doc.is_valid is None:
                validation_status = "Not AI-checked"
            else:
                validation_status = "Valid" if doc.is_valid else "Needs Review"
            e2e_note = " (end-to-end encrypted)" if getattr(doc, "e2e_scheme", None) else ""
            context_parts.append(
                f"- {doc.document_type or 'Document'}: {doc.original_filename} [{validation_status}]{e2e_note}"
            )

        return "\n".join(context_parts)
    except Exception as e:
        print(f"Error fetching documents context: {str(e)}")
        return "Unable to retrieve document information at this time."


def get_user_document_files(user_id: int, db: Session) -> List[dict]:
    """
    Fetch user's document JSON files from R2 for attachment to Gemini prompt.
    Returns a list of dicts with document_type, filename, and json_content.
    """
    document_files = []

    try:
        # Only legacy (server-side-encrypted) documents can be read here. End-to-end-encrypted
        # docs (e2e_scheme set) hold their extracted text as client-encrypted artifacts the
        # server has no key for — that content, if shared, arrives via ChatMessage.e2e_document_context.
        documents = db.query(models.Document).filter(
            models.Document.user_id == user_id,
            models.Document.extracted_text_file_url.isnot(None),
            models.Document.e2e_scheme.is_(None),
        ).all()

        for doc in documents:
            try:
                # Get extracted text/JSON file from R2
                response = r2_client.get_object(
                    Bucket=R2_DOCUMENTS_BUCKET, 
                    Key=doc.extracted_text_file_url
                )
                encrypted_blob = response['Body'].read()
                extracted_content = decrypt_artifact_bytes(encrypted_blob).decode('utf-8')
                
                # Try to parse as JSON, otherwise use raw content
                try:
                    json_data = json.loads(extracted_content)
                    content = json.dumps(json_data, indent=2)
                except json.JSONDecodeError:
                    content = extracted_content
                
                document_files.append({
                    "document_type": doc.document_type or "document",
                    "filename": doc.original_filename,
                    "is_valid": doc.is_valid,
                    "validation_message": doc.validation_message,
                    "content": content
                })
            except Exception as e:
                print(f"Warning: Failed to fetch document {doc.id}: {str(e)}")
                continue
        
        return document_files
    except Exception as e:
        print(f"Error fetching document files: {str(e)}")
        return []


def _decode_session_attachments(session_attachments: Optional[List[ChatSessionAttachment]]) -> List[dict]:
    """
    Decode in-session attachments from the chat request.
    These files are never persisted; they are only used for the current request lifecycle.
    """
    if not session_attachments:
        return []

    decoded_attachments: List[dict] = []
    total_bytes = 0

    for index, attachment in enumerate(session_attachments[:MAX_SESSION_ATTACHMENTS], start=1):
        try:
            name = (attachment.name or f"attachment_{index}").strip()[:200]
            if not name:
                name = f"attachment_{index}"

            mime_type = (attachment.mime_type or "application/octet-stream").strip().lower()[:150]
            if not (
                any(mime_type.startswith(prefix) for prefix in ALLOWED_CHAT_ATTACHMENT_MIME_PREFIXES)
                or mime_type in ALLOWED_CHAT_ATTACHMENT_MIME_TYPES
            ):
                continue

            decoded_bytes = base64.b64decode(attachment.content_base64, validate=True)
            byte_size = len(decoded_bytes)
            if byte_size <= 0:
                continue
            if byte_size > MAX_SESSION_ATTACHMENT_BYTES:
                continue
            if total_bytes + byte_size > MAX_SESSION_ATTACHMENTS_TOTAL_BYTES:
                break

            total_bytes += byte_size
            decoded_attachments.append(
                {
                    "name": name,
                    "mime_type": mime_type,
                    "size_bytes": byte_size,
                    "bytes": decoded_bytes,
                }
            )
        except (binascii.Error, ValueError):
            continue
        except Exception:
            continue

    return decoded_attachments


def _extract_text_from_attachment_bytes(attachment_bytes: bytes, mime_type: str) -> Optional[str]:
    if not attachment_bytes:
        return None
    if not (mime_type.startswith("text/") or mime_type in TEXT_ATTACHMENT_MIME_TYPES):
        return None

    try:
        text = attachment_bytes.decode("utf-8", errors="replace").strip()
        if not text:
            return None
        return text[:MAX_SESSION_ATTACHMENT_TEXT_CHARS]
    except Exception:
        return None


def build_session_attachments_context(session_attachments: Optional[List[ChatSessionAttachment]]) -> tuple[str, List[dict]]:
    """
    Build text context for chat-session attachments and prepare inline multimodal parts when possible.
    """
    decoded_attachments = _decode_session_attachments(session_attachments)
    if not decoded_attachments:
        return "", []

    context_lines = [
        f"=== ATTACHED CHAT SESSION FILES ({len(decoded_attachments)} files) ===",
        "These files were attached in this chat session only and are not persisted.",
    ]
    inline_parts: List[dict] = []

    for index, attachment in enumerate(decoded_attachments, start=1):
        name = attachment["name"]
        mime_type = attachment["mime_type"]
        size_bytes = attachment["size_bytes"]
        attachment_bytes = attachment["bytes"]

        context_lines.append(f"\n--- CHAT FILE {index}: {name} ({mime_type}, {size_bytes} bytes) ---")

        # Gemini handles image and PDF inline parts reliably in current setup.
        if mime_type.startswith("image/") or mime_type == "application/pdf":
            inline_parts.append({"mime_type": mime_type, "data": attachment_bytes})
            context_lines.append("File is attached inline for model-level analysis.")

        extracted_text = _extract_text_from_attachment_bytes(attachment_bytes, mime_type)
        if extracted_text:
            context_lines.append("Extracted text preview:")
            context_lines.append(extracted_text)
        elif not (mime_type.startswith("image/") or mime_type == "application/pdf"):
            context_lines.append("Binary/structured file attached. Use filename and mime type as context.")

    context_lines.append("\n=== END ATTACHED CHAT SESSION FILES ===")
    return "\n".join(context_lines), inline_parts


def _build_attachment_tracking_id(attachment: ChatSessionAttachment, index: int) -> str:
    raw_id = str(attachment.id or "").strip()
    if raw_id:
        normalized_id = ATTACHMENT_ID_ALLOWED_PATTERN.sub("", raw_id)[:128]
        if normalized_id:
            return normalized_id

    seed = (
        f"{attachment.name}|{attachment.mime_type}|{attachment.size_bytes or 0}|"
        f"{str(attachment.content_base64 or '')[:256]}|{index}"
    )
    return f"att_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:48]}"


def get_session_attachment_tracking_ids(session_attachments: Optional[List[ChatSessionAttachment]]) -> List[str]:
    if not session_attachments:
        return []

    attachment_ids: List[str] = []
    seen_ids = set()
    for index, attachment in enumerate(session_attachments[:MAX_SESSION_ATTACHMENTS], start=1):
        tracking_id = _build_attachment_tracking_id(attachment, index)
        if tracking_id in seen_ids:
            continue
        seen_ids.add(tracking_id)
        attachment_ids.append(tracking_id)
    return attachment_ids


def enforce_and_track_session_upload_quota(
    db: Session,
    *,
    user_id: int,
    plan: str,
    session_attachments: Optional[List[ChatSessionAttachment]],
) -> None:
    """
    Enforce and persist 24-hour upload quota events for Rilono AI chat attachments.
    """
    attachment_ids = get_session_attachment_tracking_ids(session_attachments)
    if not attachment_ids:
        return

    quota_snapshot = get_rilono_ai_chat_upload_quota_snapshot(
        db,
        user_id=user_id,
        plan=plan,
    )
    limit = quota_snapshot["limit"]
    if limit < 0:
        # Paid plans stay unlimited and do not consume/record free-tier counters.
        return

    existing_ids = {
        row[0]
        for row in db.query(models.RilonoAiChatUploadEvent.attachment_id)
        .filter(
            models.RilonoAiChatUploadEvent.user_id == user_id,
            models.RilonoAiChatUploadEvent.attachment_id.in_(attachment_ids),
        )
        .all()
    }
    new_ids = [attachment_id for attachment_id in attachment_ids if attachment_id not in existing_ids]
    if not new_ids:
        return

    window_hours = quota_snapshot["window_hours"]
    if limit >= 0 and quota_snapshot["used"] + len(new_ids) > limit:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Free plan Rilono AI chat upload limit reached ({limit} uploads per {window_hours} hours). "
                "Unlock the Visa Success Pass for unlimited Rilono AI chat uploads."
            ),
        )

    for attachment_id in new_ids:
        db.add(
            models.RilonoAiChatUploadEvent(
                user_id=user_id,
                attachment_id=attachment_id,
            )
        )


def build_system_prompt(
    *,
    source: str,
    student_profile_context: str,
    documents_context: str,
    attached_docs_text: str,
    navigation_guide_text: str,
    visa_summary: str = "",
) -> str:
    normalized_source = (source or "rilono_ai_chat").strip().lower()
    is_copilot = normalized_source == "rilono_ai_copilot"
    is_mock_interview = normalized_source == "mock_interview"
    is_visa_prep = normalized_source == "visa_prep"
    is_interview = is_mock_interview or is_visa_prep

    # The student's destination + visa type (e.g. "United Kingdom — Student Visa")
    # personalizes the assistant. Falls back to the US F-1 wording when unknown.
    journey_label = (visa_summary or "").strip() or "F-1 student visa"

    if is_mock_interview:
        assistant_intro = (
            f"You are a senior, highly experienced visa officer conducting a RIGOROUS, realistic mock interview for a "
            f"candidate applying for the {journey_label}. This is a high-pressure simulation whose ONLY purpose is to "
            f"expose every weakness in THIS specific candidate's case before their real interview, so they walk in fully "
            f"prepared and genuinely confident."
        )
        role_lines = [
            "- Stay 100% in character as a real, skeptical visa officer — professional, direct, and demanding. Never break character.",
            "- Interrogate THIS specific candidate using the attached raw profile and uploaded documents — never ask generic, textbook questions.",
            "- Ask the toughest, most probing questions a real officer would realistically ask given this candidate's exact program, university, finances, sponsor, academic background, and home-country situation.",
            "- Relentlessly pressure-test the weak spots: financial capacity and sponsor credibility, genuine intent and ties to the home country, program/university choice and career logic, academic fit, and any gaps or inconsistencies in the file.",
            "- Cross-examine every answer against the documents and profile: if funds look thin, a sponsor is unclear, ties are weak, timelines don't add up, or a claim isn't supported by the documents, challenge it immediately with a sharp, pointed follow-up.",
            "- Ask ONE question at a time. React to each answer with a tougher follow-up whenever it is vague, evasive, rehearsed, generic, over-confident, or contradicts the file.",
            "- Progressively escalate the difficulty as the interview continues; do not let the candidate settle into a comfort zone.",
            "- Do NOT coach, teach, hint, reassure, praise, score, or reveal the 'right' answer during the interview — honest feedback comes only in the final report after it ends.",
        ]
        source_specific_instructions = [
            "- Keep each turn short and brisk, exactly like a real interview window — no small talk, no explanations.",
            "- Every question must be traceable to a real detail in the candidate's profile or documents so the practice mirrors their actual interview.",
            "- When you have thoroughly tested the candidate across the key areas, end the interview and include the exact token INTERVIEW_COMPLETE once, at the very end of that final message.",
        ]
    elif is_visa_prep:
        assistant_intro = (
            f"You are an elite, demanding {journey_label} interview coach preparing THIS specific student for a tough "
            f"real visa interview. You are supportive in tone but rigorous in substance — you never let a weak answer slide."
        )
        role_lines = [
            "- Ask realistic, challenging visa-officer-style questions ONE at a time, grounded in the student's attached profile and uploaded documents.",
            "- Target the areas most likely to sink THIS candidate: finances and sponsor, intent and ties to home country, program/university fit, academic background, and any gaps or inconsistencies.",
            "- After each answer, give brief, honest, direct coaching: (1) what was weak or risky, (2) a stronger model answer in 2-4 lines grounded in their real documents, then (3) the next, harder question.",
            "- Push the student out of rehearsed, generic answers — demand specificity backed by their actual documents and situation.",
            "- Keep raising the difficulty so the real interview feels easier than this practice.",
        ]
        source_specific_instructions = [
            "- Be encouraging in tone but uncompromising on substance; the goal is real confidence, not false comfort.",
            "- Keep each turn practical and concise.",
        ]
    elif is_copilot:
        assistant_intro = (
            f"You are Rilono AI Copilot, an application assistant for students on the {journey_label} journey."
        )
        role_lines = [
            "- Assist ongoing applications like university and visa forms, financial and health documents, and related application and visa workflow tasks",
            "- Help the student fill application fields and prepare responses with utmost accuracy",
            "- Ask clarifying questions whenever required details are missing, ambiguous, or inconsistent",
            "- Cross-check answers against student profile details, uploaded documents, and page context before final guidance",
            "- Keep responses practical, structured, and professional",
        ]
        source_specific_instructions = [
            "- Prioritize correctness over speed; never guess if details are missing",
            "- If page/form context is attached, reference specific field labels and explain what should be entered",
            "- If multiple valid options exist, explain tradeoffs and ask which one applies to the student",
        ]
    else:
        assistant_intro = (
            f"You are Rilono AI, a study-abroad expert assistant for the {journey_label} journey. "
            "You are guiding the student through their whole study-abroad process — university choices, "
            "SOPs, documents, finances, and their visa."
        )
        role_lines = [
            f"- Provide expert guidance on {journey_label} requirements and processes",
            "- Help with document preparation and verification",
            "- Answer questions about the visa application steps for the student's destination (application forms, financial proof, biometrics, interview, etc.), using the specific stages in the attached profile",
            "- Assist with understanding visa documentation requirements",
            "- Be friendly, supportive, and professional",
        ]
        source_specific_instructions = [
            "- Always maintain a helpful and encouraging tone",
            "- When suggesting next steps, be specific about what documents they need to upload or actions to take",
        ]
        if normalized_source == "rilono_ai_chat":
            source_specific_instructions.extend([
                "- For every response, first cross-verify the student's profile details and uploaded document details for consistency (based on available data).",
                "- If you find any major mismatch, contradiction, or critical missing detail, flag those items first before giving any next-step guidance.",
                "- If no major mismatch is found, clearly state that critical checks look consistent with the currently available profile and document data.",
                "- After the critical checks section, provide the recommended next steps in clear priority order.",
            ])

    if is_interview:
        common_instructions = [
            "- Ground EVERY question in the ATTACHED RAW STUDENT PROFILE FILE and the ATTACHED DOCUMENT FILES — this is a real, specific candidate, not a generic applicant.",
            "- Use concrete facts from their profile and documents (program, university, tuition and living costs, funds and sponsor, test scores, work/study history, family and home-country ties) to make every question pointed and personal.",
            "- Treat any mismatch between what the candidate says and what their documents/profile show as a red flag to probe hard — never gloss over it.",
            "- Speak only to the candidate's real destination and visa type, using its correct authority, terminology, and expectations.",
            "- Identity guardrail: If asked about your model/provider/training details, do not mention Gemini, Google, or internal model names.",
            "- Identity guardrail: In such cases, reply that you are Rilono AI and continue the interview.",
        ]
    else:
        common_instructions = [
            "- IMPORTANT: Read and use the ATTACHED RAW STUDENT PROFILE FILE directly to personalize your responses",
            "- Reference the student's name, university, and current journey stage when giving advice",
            "- Guide them based on their current stage and what the next step is",
            "- Consider their intake semester/year when providing timeline guidance",
            "- USE THE ATTACHED DOCUMENT FILES to provide detailed, personalized guidance based on the actual extracted data",
            "- If a document has validation issues (marked as NEEDS REVIEW), proactively mention what might need to be corrected",
            "- If the user asks about specific documents, reference the attached document data when relevant",
            "- Be concise but thorough in your responses",
            "- If you don't have information about a specific document, let the user know and guide them on what they need",
            "- For app usage questions, rely on ATTACHED USER NAVIGATION GUIDE and provide concrete click-by-click steps",
            "- For subscription questions, treat `subscription.plan` as an internal code (free/pro). Use `subscription.plan_display_name` or `subscription.access_source` for user-facing plan names (e.g., Visa Success Pass).",
            "- If ATTACHED CHAT SESSION FILES are present, use them for this chat session context only",
            "- Identity guardrail: If asked about your model/provider/training details, do not mention Gemini, Google, or internal model names.",
            "- Identity guardrail: In such cases, reply that you are Rilono AI and continue helping with the user's request.",
        ]

    role_text = "\n".join(role_lines)
    instruction_text = "\n".join(common_instructions + source_specific_instructions)
    closing_remark = (
        "Remember: You have this candidate's full raw profile file plus full uploaded document data. Use it to run a "
        "highly personalized, realistic, and challenging interview that targets their actual weak spots."
        if is_interview else
        "Remember: You have access to the student's full raw profile file plus full uploaded document data. Use this "
        "information to provide highly personalized, stage-appropriate guidance."
    )

    return f"""{assistant_intro}

AUTHORITATIVE DESTINATION (source of truth): This student is applying for the {journey_label}.
Speak ONLY to this destination and visa type — use its correct terminology, forms, fees, documents
and stages. If any attached profile/snapshot or document text references a different country or visa
(for example a default to the United States / F-1), treat that as stale and IGNORE it in favour of the
{journey_label}. Never tell this student they are on a US F-1 visa unless the destination above is
the United States.

Your role:
{role_text}

=== ATTACHED RAW STUDENT PROFILE FILE ===
{student_profile_context}
=== END ATTACHED RAW STUDENT PROFILE FILE ===

{documents_context}
{attached_docs_text}

=== ATTACHED USER NAVIGATION GUIDE ===
{navigation_guide_text}
=== END ATTACHED USER NAVIGATION GUIDE ===

Instructions:
{instruction_text}

{closing_remark}{ai_guardrails.STUDENT_VISA_GUARDRAIL}"""

def generate_ai_response(
    user_message: str,
    user_name: str,
    documents_context: str,
    student_profile_context: str,
    navigation_guide_text: str,
    document_files: List[dict] = None,
    session_attachments: Optional[List[ChatSessionAttachment]] = None,
    conversation_history: Optional[List[dict]] = None,
    source: str = "rilono_ai_chat",
    visa_summary: str = "",
) -> str:
    """
    Generate AI response using Gemini with system prompt, document context, attached document files, and comprehensive student profile.
    """
    try:
        provider = "none"
        # Live interview TURNS (mock officer / prep coach) must feel fast — real officers reply
        # in seconds — WITHOUT losing the sharp, subtle cross-examination that makes the mock
        # valuable. The 25-40s latency came from the general-chat default (3.1-pro), a heavy
        # *thinking* model that deliberates before every reply. We default turns to 2.5-pro: a
        # strong reasoner (keeps the intelligent probing) but far lighter latency than 3.1-pro's
        # extended thinking. Tune via env: RILONO_INTERVIEW_MODEL=gemini-2.5-flash for max speed.
        # The one-time final REPORT (source "mock_interview_report") is NOT matched here, so its
        # deep analysis stays on the smart default model, with latency hidden behind the report
        # progress bar.
        normalized_chat_source = (source or "").strip().lower()
        is_interview_turn = normalized_chat_source in ("mock_interview", "visa_prep")
        interview_generation_config = None
        if is_interview_turn:
            model_candidates = gemini_utils.get_model_candidates(
                primary_env="RILONO_INTERVIEW_MODEL",
                candidates_env="RILONO_INTERVIEW_MODEL_CANDIDATES",
                # `gemini-3.1-pro` (bare) is NOT served by v1beta and 404s — see the warning in
                # gemini_service.DEFAULT_GEMINI_MODEL. Only live ids belong in a candidate chain.
                defaults=["gemini-2.5-pro", "gemini-2.5-flash", "gemini-3.1-pro-preview"],
            )
            # max_output_tokens is NOT a length limit on what the officer SAYS — on these thinking
            # models it also has to cover the private reasoning that happens before the reply, and
            # that reasoning dominates. Measured on a real interview prompt: ~600-1750 thinking
            # tokens against 10-224 spoken ones. The old 300/520 caps were sized for the spoken
            # half alone, so every model burned the whole budget thinking and returned MAX_TOKENS
            # with an empty or half-finished sentence — 2.5-pro returned no text at all, which made
            # `.text` raise and 500 the turn. Brevity is enforced by the system prompt, not by this
            # number, so it only needs to be big enough to never truncate: 4096 leaves >2x headroom
            # over the worst observed turn. Do not lower it without re-measuring thinking usage.
            _default_cap = "4096"
            interview_generation_config = {
                "max_output_tokens": int(os.getenv("RILONO_INTERVIEW_MAX_TOKENS", _default_cap) or _default_cap),
                "temperature": 0.85,
            }
        else:
            model_candidates = gemini_utils.get_model_candidates(
                primary_env="RILONO_AI_CHAT_MODEL",
                candidates_env="RILONO_AI_CHAT_MODEL_CANDIDATES",
            )
        # Select provider based on available service.
        if hasattr(gemini_utils, 'USE_VERTEX_AI') and gemini_utils.USE_VERTEX_AI and hasattr(gemini_utils, 'VERTEX_AI_AVAILABLE') and gemini_utils.VERTEX_AI_AVAILABLE:
            provider = "vertex"
        elif hasattr(gemini_utils, 'GENAI_AVAILABLE') and gemini_utils.GENAI_AVAILABLE and gemini_utils.genai:
            provider = "genai"
        else:
            raise Exception("Rilono AI model provider is not available.")
        
        # Build attached documents section
        attached_docs_text = ""
        if document_files and len(document_files) > 0:
            attached_docs_text = f"\n\n=== ATTACHED DOCUMENT FILES ({len(document_files)} documents) ===\nAll uploaded documents are attached below with their full extracted information for your reference.\n"
            for i, doc_file in enumerate(document_files, 1):
                validation_status = "VALID" if doc_file.get('is_valid') else "NEEDS REVIEW"
                attached_docs_text += f"\n--- DOCUMENT {i}: {doc_file['document_type'].upper()} ({doc_file['filename']}) [{validation_status}] ---\n"
                if doc_file.get('validation_message'):
                    attached_docs_text += f"Validation Note: {doc_file['validation_message']}\n"
                attached_docs_text += f"Extracted Data:\n{doc_file['content']}\n"
            attached_docs_text += "\n=== END OF ATTACHED DOCUMENTS ===\n"

        session_attachments_text, inline_session_attachment_parts = build_session_attachments_context(session_attachments)
        
        system_prompt = build_system_prompt(
            source=source,
            student_profile_context=student_profile_context,
            documents_context=documents_context,
            attached_docs_text=attached_docs_text,
            navigation_guide_text=navigation_guide_text,
            visa_summary=visa_summary,
        )

        # Build conversation context
        conversation_text = ""
        if conversation_history:
            for msg in conversation_history[-200:]:  # Last 200 messages for context
                role = msg.get('role', 'user')
                content = msg.get('content', '')
                if role == 'user':
                    conversation_text += f"User: {content}\n"
                elif role == 'assistant':
                    conversation_text += f"Assistant: {content}\n"
        
        # Build full prompt
        full_prompt = f"""{system_prompt}

{session_attachments_text if session_attachments_text else ""}

{conversation_text if conversation_text else ""}

Current user message: {user_message}

Please provide a helpful response to the user's question:"""
        
        # Privacy: never log user chat prompts, messages, or profile/document content.
        # Emit only a minimal, non-sensitive operational marker.
        print(
            f"Rilono AI chat call: source={source} "
            f"docs={len(document_files) if document_files else 0} "
            f"session_attachments={len(session_attachments) if session_attachments else 0}"
        )

        response = None
        response_text = None
        used_model_name = None
        # A truncated reply is kept aside rather than returned: we try the remaining candidates
        # first, and fall back to it only if EVERY model truncates — so this degrades to partial
        # text in the worst case, never to an error page.
        partial = None
        last_model_error = None
        for model_name in model_candidates:
            try:
                model = _build_ai_chat_model(provider, model_name, generation_config=interview_generation_config)
                candidate_response = _generate_with_ai_chat_model(
                    model=model,
                    provider=provider,
                    full_prompt=full_prompt,
                    inline_session_attachment_parts=inline_session_attachment_parts,
                )
                text, truncated = _extract_ai_text(candidate_response)
                if truncated:
                    if partial is None:
                        partial = (candidate_response, text, model_name)
                    raise RuntimeError("reply hit max_output_tokens and was cut off")
                response, response_text, used_model_name = candidate_response, text, model_name
                break
            except Exception as model_error:  # noqa: BLE001
                last_model_error = model_error
                print(f"Rilono AI model attempt failed [{model_name}] provider={provider}: {str(model_error)}")

        if response is None and partial is not None:
            response, response_text, used_model_name = partial
            print(f"Rilono AI: every candidate truncated; returning partial reply from {used_model_name}")

        if response is None:
            raise RuntimeError(f"All configured Rilono AI chat models failed: {str(last_model_error)}")

        model_name = used_model_name
        try:
            # Attribute Copilot (Chrome extension) chats to their own usage source so the
            # admin AI-cost analytics can break out extension spend from website chat.
            usage_source = (
                "student_ai_chat_copilot"
                if (source or "").strip().lower() == "rilono_ai_copilot"
                else "student_ai_chat"
            )
            ai_usage.record_gemini_usage(usage_source, model_name, response)
        except Exception:
            pass

        # Privacy: do not log the AI response content.
        return sanitize_ai_response_for_public_display(response_text)
        
    except Exception as e:
        print(f"Error generating AI response: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=PUBLIC_AI_RESPONSE_ERROR_DETAIL
        )

def refresh_student_profile_if_stale(user: models.User, db: Session) -> dict:
    """
    Check if the cached student profile is stale (document count mismatch) and refresh if needed.
    Returns the up-to-date profile data.
    """
    from app.routers.documents import (
        calculate_visa_journey_stage,
        is_student_profile_snapshot_stale,
        save_student_profile_to_r2,
    )
    
    # Get actual document count from database
    actual_documents = db.query(models.Document).filter(
        models.Document.user_id == user.id
    ).all()
    actual_count = len(actual_documents)
    
    # Get cached profile
    cached_profile = get_student_profile_and_status(user.id)
    
    if cached_profile:
        if not is_student_profile_snapshot_stale(cached_profile, user, actual_count, db=db):
            return cached_profile

        cached_count = cached_profile.get('documents_summary', {}).get('total_documents_uploaded', 0)
        print(
            f"🔄 Refreshing stale profile for user {user.id}: "
            f"cached_docs={cached_count}, actual_docs={actual_count}"
        )
    else:
        print(f"🔄 Creating new profile for user {user.id}")
    
    # Refresh the profile
    try:
        status_data = calculate_visa_journey_stage(
            actual_documents, db,
            getattr(user, "destination_country_code", None),
            getattr(user, "visa_type_key", None),
        )
        save_student_profile_to_r2(user, status_data, actual_documents, db=db)
        # Return the fresh profile
        return get_student_profile_and_status(user.id)
    except Exception as e:
        print(f"Warning: Failed to refresh profile: {str(e)}")
        return cached_profile  # Fall back to cached if refresh fails


@router.post("/chat", response_model=ChatResponse)
def chat_with_ai(
    chat_message: ChatMessage,
    request: Request,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Chat with Rilono AI. The AI has access to the user's complete profile, documents, and visa journey status.
    Document JSON files are attached to the prompt for detailed context.
    """
    try:
        source = (chat_message.source or "rilono_ai_chat").strip().lower()
        if source not in ALLOWED_CHAT_SOURCES:
            raise HTTPException(
                status_code=400,
                detail="Unsupported chat source.",
            )

        _enforce_rate_limit_or_429(
            request=request,
            scope="ai_chat.chat.ip",
            limit=AI_CHAT_RATE_LIMIT,
            window_seconds=AI_CHAT_RATE_WINDOW_SECONDS,
        )
        _enforce_rate_limit_or_429(
            request=request,
            scope="ai_chat.chat.user",
            limit=AI_CHAT_USER_RATE_LIMIT,
            window_seconds=AI_CHAT_RATE_WINDOW_SECONDS,
            extra_key=str(current_user.id),
        )

        # Fail fast with a clean message when Gemini isn't configured, instead of
        # doing all the profile/document work and then surfacing a raw 500 from the
        # model call. Mirrors the enterprise interview endpoint's availability guard.
        if not gemini_utils.is_ai_configured():
            raise HTTPException(
                status_code=503,
                detail="Rilono AI is temporarily unavailable. Please try again in a little while.",
            )

        # Attribute every Gemini call in this request to the signed-in account.
        ai_usage.set_usage_account(user_id=current_user.id)

        # Cost guardrail: reject obviously off-topic ("free ChatGPT") prompts before
        # spending any Gemini tokens. Borderline prompts pass through to the model,
        # where the system-instruction guardrail handles them.
        if ai_guardrails.is_off_topic(chat_message.message):
            ai_guardrails.record_block(source="student_ai_chat", detail=source)
            return ChatResponse(response=ai_guardrails.OFF_TOPIC_REFUSAL)

        count_toward_rilono_chat_limit = source in QUOTA_TRACKED_CHAT_SOURCES

        subscription = get_or_create_user_subscription(db, current_user.id)
        if source == "rilono_ai_copilot" and not visa_pass.has_active_pass(subscription):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Rilono Copilot is available with the Visa Success Pass. "
                    "Unlock the pass to continue."
                ),
            )

        limits = get_plan_limits(subscription.plan)
        ai_limit = limits["ai_messages_limit"]
        if count_toward_rilono_chat_limit and ai_limit >= 0 and subscription.ai_messages_used >= ai_limit:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Free plan message limit reached ({ai_limit}). "
                    "Unlock the Visa Success Pass for unlimited Rilono AI messages."
                )
            )

        if count_toward_rilono_chat_limit:
            enforce_and_track_session_upload_quota(
                db,
                user_id=current_user.id,
                plan=subscription.plan,
                session_attachments=chat_message.session_attachments,
            )

        # Get user's name
        user_name = current_user.full_name or current_user.username or "Student"
        
        # Keep profile file fresh when needed, then attach the full raw decrypted JSON directly.
        # A snapshot refresh is a convenience step: if it fails (2026-08-23: a datetime
        # comparison bug in the snapshot builder), answer from the cached profile rather than
        # turning the whole chat into a 500.
        try:
            refresh_student_profile_if_stale(current_user, db)
        except Exception as refresh_error:
            print(f"Warning: profile snapshot refresh failed for user {current_user.id}: {refresh_error}")
        student_profile_raw_text = get_student_profile_raw_text(current_user.id)
        navigation_guide_text = get_user_navigation_guide_text()
        if not student_profile_raw_text:
            student_profile_raw_text = (
                '{"note":"STUDENT_PROFILE_AND_F1_VISA_STATUS.json not found. '
                'Ask user to open dashboard once or run /api/documents/visa-status/refresh."}'
            )
        
        # Get documents context (summary list of uploaded documents)
        documents_context = get_user_documents_context(current_user.id, db)

        # Merge in extracted details the browser decrypted from the user's END-TO-END-ENCRYPTED
        # documents and chose to share for this message (consented + transient — never stored
        # server-side). Bounded to avoid prompt bloat / abuse.
        client_e2e_context = (chat_message.e2e_document_context or "").strip()
        if client_e2e_context:
            documents_context = (
                documents_context
                + "\n\nExtracted details from the user's end-to-end-encrypted documents "
                "(decrypted and shared by the user for this message):\n"
                + client_e2e_context[:60000]
            )

        # Get document files (full JSON content) to attach to the prompt
        document_files = get_user_document_files(current_user.id, db)
        
        # Destination + visa type personalize the assistant's persona.
        _vc_country, _vc_visa = visa_catalog.resolve_selection(
            getattr(current_user, "destination_country_code", None),
            getattr(current_user, "visa_type_key", None),
        )
        _vc_country_name = (visa_catalog.country_meta(_vc_country) or {}).get("name", _vc_country)
        _vc_visa_label = visa_catalog.visa_type_label(_vc_country, _vc_visa) or "Student Visa"
        visa_summary = f"{_vc_country_name} — {_vc_visa_label}"

        # Generate response with attached document files
        response_text = generate_ai_response(
            user_message=chat_message.message,
            user_name=user_name,
            documents_context=documents_context,
            student_profile_context=student_profile_raw_text,
            navigation_guide_text=navigation_guide_text,
            document_files=document_files,
            session_attachments=chat_message.session_attachments,
            conversation_history=chat_message.conversation_history,
            source=source,
            visa_summary=visa_summary,
        )

        # Track free-tier usage for all chat sources that are quota-tracked.
        if count_toward_rilono_chat_limit:
            subscription.ai_messages_used += 1
            db.commit()
            try:
                from app.routers.documents import refresh_student_profile_snapshot_for_user_id
                refresh_student_profile_snapshot_for_user_id(user_id=current_user.id, db=db)
            except Exception:
                pass
        
        return ChatResponse(response=response_text)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected Rilono AI chat error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=PUBLIC_AI_RESPONSE_ERROR_DETAIL
        )


# ---------------------------------------------------------------------------
# Consulate Window: neural officer voice (US launch) — Visa Success Pass perk
# ---------------------------------------------------------------------------

class OfficerTtsRequest(BaseModel):
    text: str
    country: Optional[str] = None  # defaults to the student's journey destination


@router.post("/tts/officer")
def synthesize_officer_voice(
    payload: OfficerTtsRequest,
    request: Request,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Accent-matched neural officer voice for the mock interview (Consulate Window).

    Pass-gated: free users get 403 with fallback=true and the client keeps the basic
    browser voice. Any infrastructure problem returns 503 with fallback=true — the
    interview itself must never break because of voice synthesis. Every successful
    synthesis is metered under `mock_interview_tts` in the AI cost tracker.
    """
    from app import officer_tts

    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Nothing to speak.")

    _enforce_rate_limit_or_429(
        request=request,
        scope="ai_chat.tts.user",
        limit=30,
        window_seconds=60,
        extra_key=str(current_user.id),
    )

    # The immersive officer voice is a Visa Success Pass perk (basic voice stays free).
    subscription = get_or_create_user_subscription(db, current_user.id)
    if not visa_pass.has_active_pass(subscription):
        return JSONResponse(
            status_code=403,
            content={
                "fallback": True,
                "detail": "The realistic officer voice is a Visa Success Pass perk. "
                          "Your interview continues with the standard voice.",
            },
        )

    country = (payload.country or getattr(current_user, "destination_country_code", None) or "US")
    if not officer_tts.voice_config(country):
        # Not launched for this destination yet — client falls back silently.
        return JSONResponse(status_code=200, content={"fallback": True})

    try:
        result = officer_tts.synthesize_officer_line(text, country)
    except officer_tts.TtsUnavailable:
        return JSONResponse(status_code=503, content={"fallback": True})

    ai_usage.record_tts_usage(
        "mock_interview_tts",
        result["voice"],
        result["characters"],
        cost_usd=officer_tts.estimate_tts_cost_usd(result["characters"]),
        user_id=current_user.id,
    )
    return {
        "fallback": False,
        "audio": result["audio_b64"],
        "voice": result["voice"],
        "characters": result["characters"],
    }
