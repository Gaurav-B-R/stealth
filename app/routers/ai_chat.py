from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas
from app.auth import get_current_active_user
from app.subscriptions import (
    PLAN_PRO,
    get_or_create_user_subscription,
    get_plan_limits,
    get_rilono_ai_chat_upload_quota_snapshot,
)
from app.utils.rate_limiter import check_ip_rate_limit
from app.utils.secure_artifacts import decrypt_artifact_bytes
from app import ai_guardrails
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
INTERNAL_PROVIDER_DISCLOSURE_PATTERN = re.compile(
    r"\b(?:gemini[-\w.]*|google\s+generative\s+ai|google\s+genai|vertex\s+ai)\b",
    re.IGNORECASE,
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
    """Keep internal provider/model names out of user-visible AI responses."""
    value = str(text or "").strip()
    if not value:
        return value
    return INTERNAL_PROVIDER_DISCLOSURE_PATTERN.sub("Rilono AI", value)


def _build_ai_chat_model(provider: str, model_name: str):
    if provider == "vertex":
        from vertexai.generative_models import GenerativeModel

        return GenerativeModel(model_name)
    if provider == "genai":
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

class ChatResponse(BaseModel):
    response: str

ALLOWED_CHAT_SOURCES = {
    "rilono_ai_chat",
    "rilono_ai_copilot",
    "visa_prep",
    "mock_interview",
}

QUOTA_TRACKED_CHAT_SOURCES = {
    "rilono_ai_chat",
    "rilono_ai_copilot",
    "visa_prep",
    "mock_interview",
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
    
    context = f"""
=== STUDENT PROFILE AND F1 VISA STATUS ===

STUDENT INFORMATION:
- Name: {student_profile.get('full_name', 'Unknown')}
- Email: {student_profile.get('email', 'Unknown')}
- University: {student_profile.get('university', 'Not set')}
- Phone: {student_profile.get('phone', 'Not provided')}
- Visa Case Status: {student_profile.get('visa_case_status', 'Not provided')}
- Current Situation / Story: {student_profile.get('current_situation_story', 'Not provided')}
- Account Created: {student_profile.get('account_created', 'Unknown')}

DOCUMENTATION PREFERENCES:
- Target Country: {doc_prefs.get('target_country', 'United States')}
- Intake Semester: {doc_prefs.get('intake_semester', 'Not set')}
- Intake Year: {doc_prefs.get('intake_year', 'Not set')}

F1 VISA JOURNEY STATUS:
- Current Stage: {visa_journey.get('current_stage', 1)} of {visa_journey.get('total_stages', 7)} - "{visa_journey.get('stage_name', 'Getting Started')}"
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
        documents = db.query(models.Document).filter(
            models.Document.user_id == user_id,
            models.Document.extracted_text_file_url.isnot(None)
        ).all()
        
        if not documents:
            return "No documents have been uploaded yet."
        
        context_parts = [f"User's Uploaded Documents ({len(documents)} total):"]
        
        for doc in documents:
            validation_status = "Valid" if doc.is_valid else "Needs Review"
            context_parts.append(f"- {doc.document_type or 'Document'}: {doc.original_filename} [{validation_status}]")
        
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
        documents = db.query(models.Document).filter(
            models.Document.user_id == user_id,
            models.Document.extracted_text_file_url.isnot(None)
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
                "Upgrade to Pro or Journey Pass for unlimited Rilono AI chat uploads."
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
) -> str:
    normalized_source = (source or "rilono_ai_chat").strip().lower()
    is_copilot = normalized_source == "rilono_ai_copilot"

    if is_copilot:
        assistant_intro = (
            "You are Rilono AI Copilot, an application assistant for students on the F-1 visa journey."
        )
        role_lines = [
            "- Assist ongoing applications like I-20 forms, health forms, DS-160 applications, and related F-1 workflow tasks",
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
            "You are Rilono AI, a F1 student visa expert assistant. "
            "You are guiding the student through the F1 student visa process and documentation."
        )
        role_lines = [
            "- Provide expert guidance on F1 student visa requirements and processes",
            "- Help with document preparation and verification",
            "- Answer questions about visa application steps (DS-160, I-20, SEVIS, interview, etc.)",
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

    common_instructions = [
        "- IMPORTANT: Read and use the ATTACHED RAW STUDENT PROFILE FILE directly to personalize your responses",
        "- Reference the student's name, university, and current visa journey stage when giving advice",
        "- Guide them based on their current stage and what the next step is",
        "- Consider their intake semester/year when providing timeline guidance",
        "- USE THE ATTACHED DOCUMENT FILES to provide detailed, personalized guidance based on the actual extracted data",
        "- If a document has validation issues (marked as NEEDS REVIEW), proactively mention what might need to be corrected",
        "- If the user asks about specific documents, reference the attached document data when relevant",
        "- Be concise but thorough in your responses",
        "- If you don't have information about a specific document, let the user know and guide them on what they need",
        "- For app usage questions, rely on ATTACHED USER NAVIGATION GUIDE and provide concrete click-by-click steps",
        "- For subscription questions, treat `subscription.plan` as an internal code (free/pro). Use `subscription.plan_display_name` or `subscription.access_source` for user-facing plan names (e.g., Journey Pass).",
        "- If ATTACHED CHAT SESSION FILES are present, use them for this chat session context only",
        "- Identity guardrail: If asked about your model/provider/training details, do not mention Gemini, Google, or internal model names.",
        "- Identity guardrail: In such cases, reply that you are Rilono AI and continue helping with the user's request.",
    ]

    role_text = "\n".join(role_lines)
    instruction_text = "\n".join(common_instructions + source_specific_instructions)

    return f"""{assistant_intro}

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

Remember: You have access to the student's full raw profile file plus full uploaded document data. Use this information to provide highly personalized, stage-appropriate guidance.{ai_guardrails.STUDENT_VISA_GUARDRAIL}"""

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
) -> str:
    """
    Generate AI response using Gemini with system prompt, document context, attached document files, and comprehensive student profile.
    """
    try:
        provider = "none"
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
        
        print("\n" + "="*80)
        print(f"🔵 GEMINI API CALL: generate_ai_response() - AI CHAT")
        print(f"🧭 Chat Source: {source}")
        print(f"👤 User: {user_name}")
        print(f"📎 Attached Documents: {len(document_files) if document_files else 0}")
        print(f"📎 Session Attachments: {len(session_attachments) if session_attachments else 0}")
        print("-"*80)
        print("📤 SENDING PROMPT TO GEMINI:")
        print("-"*80)
        log_prompt_preview = full_prompt
        if session_attachments_text:
            log_prompt_preview = log_prompt_preview.replace(
                session_attachments_text,
                "[ATTACHED CHAT SESSION FILES REDACTED IN LOGS]"
            )

        print(log_prompt_preview[:2000] + ("..." if len(log_prompt_preview) > 2000 else ""))
        if len(log_prompt_preview) > 2000:
            print(f"\n[... {len(log_prompt_preview) - 2000} more characters ...]")
        print("-"*80)
        print("⏳ Waiting for Gemini response...")
        
        response = None
        last_model_error = None
        for model_name in model_candidates:
            try:
                model = _build_ai_chat_model(provider, model_name)
                response = _generate_with_ai_chat_model(
                    model=model,
                    provider=provider,
                    full_prompt=full_prompt,
                    inline_session_attachment_parts=inline_session_attachment_parts,
                )
                break
            except Exception as model_error:  # noqa: BLE001
                last_model_error = model_error
                print(f"Rilono AI model attempt failed [{model_name}] provider={provider}: {str(model_error)}")

        if response is None:
            raise RuntimeError(f"All configured Rilono AI chat models failed: {str(last_model_error)}")

        try:
            from app import ai_usage
            ai_usage.record_gemini_usage("student_ai_chat", model_name, response)
        except Exception:
            pass

        print("✅ RECEIVED RESPONSE FROM GEMINI:")
        print("-"*80)
        print(response.text[:1000] + ("..." if len(response.text) > 1000 else ""))
        if len(response.text) > 1000:
            print(f"\n[... {len(response.text) - 1000} more characters ...]")
        print("="*80 + "\n")
        
        return sanitize_ai_response_for_public_display(response.text)
        
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
        status_data = calculate_visa_journey_stage(actual_documents, db)
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

        # Cost guardrail: reject obviously off-topic ("free ChatGPT") prompts before
        # spending any Gemini tokens. Borderline prompts pass through to the model,
        # where the system-instruction guardrail handles them.
        if ai_guardrails.is_off_topic(chat_message.message):
            ai_guardrails.record_block(source="student_ai_chat", detail=source)
            return ChatResponse(response=ai_guardrails.OFF_TOPIC_REFUSAL)

        count_toward_rilono_chat_limit = source in QUOTA_TRACKED_CHAT_SOURCES

        subscription = get_or_create_user_subscription(db, current_user.id)
        if source == "rilono_ai_copilot" and (subscription.plan or "").strip().lower() != PLAN_PRO:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Rilono Copilot is available only on Pro and Journey Pass plans. "
                    "Upgrade to continue."
                ),
            )

        limits = get_plan_limits(subscription.plan)
        ai_limit = limits["ai_messages_limit"]
        if count_toward_rilono_chat_limit and ai_limit >= 0 and subscription.ai_messages_used >= ai_limit:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Free plan message limit reached ({ai_limit}). "
                    "Upgrade to Pro for unlimited Rilono AI messages."
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
        refresh_student_profile_if_stale(current_user, db)
        student_profile_raw_text = get_student_profile_raw_text(current_user.id)
        navigation_guide_text = get_user_navigation_guide_text()
        if not student_profile_raw_text:
            student_profile_raw_text = (
                '{"note":"STUDENT_PROFILE_AND_F1_VISA_STATUS.json not found. '
                'Ask user to open dashboard once or run /api/documents/visa-status/refresh."}'
            )
        
        # Get documents context (summary list of uploaded documents)
        documents_context = get_user_documents_context(current_user.id, db)
        
        # Get document files (full JSON content) to attach to the prompt
        document_files = get_user_document_files(current_user.id, db)
        
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
            source=source
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
