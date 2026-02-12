from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas
from app.auth import get_current_active_user
from app.subscriptions import get_or_create_user_subscription, get_plan_limits
from app.utils.secure_artifacts import decrypt_artifact_bytes
# Import Gemini configuration
from app.utils import gemini_service as gemini_utils
from typing import Optional, List
import os
import json
import boto3
from botocore.config import Config
from pydantic import BaseModel

router = APIRouter(prefix="/api/ai-chat", tags=["ai-chat"])

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

class ChatMessage(BaseModel):
    message: str
    conversation_history: Optional[List[dict]] = None

class ChatResponse(BaseModel):
    response: str

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

def generate_ai_response(user_message: str, user_name: str, documents_context: str, student_profile_context: str, document_files: List[dict] = None, conversation_history: Optional[List[dict]] = None) -> str:
    """
    Generate AI response using Gemini with system prompt, document context, attached document files, and comprehensive student profile.
    """
    try:
        # Initialize model based on available service
        if hasattr(gemini_utils, 'USE_VERTEX_AI') and gemini_utils.USE_VERTEX_AI and hasattr(gemini_utils, 'VERTEX_AI_AVAILABLE') and gemini_utils.VERTEX_AI_AVAILABLE:
            from vertexai.generative_models import GenerativeModel
            model = GenerativeModel('gemini-3-pro-preview')
        elif hasattr(gemini_utils, 'GENAI_AVAILABLE') and gemini_utils.GENAI_AVAILABLE:
            try:
                import google.generativeai as genai
                model = genai.GenerativeModel('gemini-3-pro-preview')
            except:
                raise Exception("Gemini API not properly configured")
        else:
            raise Exception("Gemini AI not available. Please configure service account or API key.")
        
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
        
        # Build system prompt with comprehensive student profile
        system_prompt = f"""You are Rilono AI, a F1 student visa expert assistant. You are guiding the student through the F1 student visa process and documentation.

Your role:
- Provide expert guidance on F1 student visa requirements and processes
- Help with document preparation and verification
- Answer questions about visa application steps (DS-160, I-20, SEVIS, interview, etc.)
- Assist with understanding visa documentation requirements
- Be friendly, supportive, and professional

{student_profile_context}

{documents_context}
{attached_docs_text}

Instructions:
- IMPORTANT: Use the STUDENT PROFILE AND F1 VISA STATUS information above to personalize your responses
- Reference the student's name, university, and current visa journey stage when giving advice
- Guide them based on their current stage and what the next step is
- Consider their intake semester/year when providing timeline guidance
- USE THE ATTACHED DOCUMENT FILES to provide detailed, personalized guidance based on the actual extracted data
- If a document has validation issues (marked as NEEDS REVIEW), proactively mention what might need to be corrected
- If the user asks about specific documents, reference the attached document data when relevant
- Be concise but thorough in your responses
- If you don't have information about a specific document, let the user know and guide them on what they need
- Always maintain a helpful and encouraging tone
- When suggesting next steps, be specific about what documents they need to upload or actions to take

Remember: You have access to the student's complete profile including their name, university, documentation preferences, current visa journey status, AND their full uploaded document data. Use this information to provide highly personalized, stage-appropriate guidance."""

        # Build conversation context
        conversation_text = ""
        if conversation_history:
            for msg in conversation_history[-10:]:  # Last 10 messages for context
                role = msg.get('role', 'user')
                content = msg.get('content', '')
                if role == 'user':
                    conversation_text += f"User: {content}\n"
                elif role == 'assistant':
                    conversation_text += f"Assistant: {content}\n"
        
        # Build full prompt
        full_prompt = f"""{system_prompt}

{conversation_text if conversation_text else ""}

Current user message: {user_message}

Please provide a helpful response to the user's question:"""
        
        print("\n" + "="*80)
        print(f"🔵 GEMINI API CALL: generate_ai_response() - AI CHAT")
        print(f"👤 User: {user_name}")
        print(f"📎 Attached Documents: {len(document_files) if document_files else 0}")
        print("-"*80)
        print("📤 SENDING PROMPT TO GEMINI:")
        print("-"*80)
        print(full_prompt[:2000] + ("..." if len(full_prompt) > 2000 else ""))
        if len(full_prompt) > 2000:
            print(f"\n[... {len(full_prompt) - 2000} more characters ...]")
        print("-"*80)
        print("⏳ Waiting for Gemini response...")
        
        # Generate response
        response = model.generate_content(full_prompt)
        
        print("✅ RECEIVED RESPONSE FROM GEMINI:")
        print("-"*80)
        print(response.text[:1000] + ("..." if len(response.text) > 1000 else ""))
        if len(response.text) > 1000:
            print(f"\n[... {len(response.text) - 1000} more characters ...]")
        print("="*80 + "\n")
        
        return response.text
        
    except Exception as e:
        print(f"Error generating AI response: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate AI response: {str(e)}"
        )

def refresh_student_profile_if_stale(user: models.User, db: Session) -> dict:
    """
    Check if the cached student profile is stale (document count mismatch) and refresh if needed.
    Returns the up-to-date profile data.
    """
    from app.routers.documents import calculate_visa_journey_stage, save_student_profile_to_r2
    
    # Get actual document count from database
    actual_documents = db.query(models.Document).filter(
        models.Document.user_id == user.id
    ).all()
    actual_count = len(actual_documents)
    
    # Get cached profile
    cached_profile = get_student_profile_and_status(user.id)
    
    if cached_profile:
        cached_count = cached_profile.get('documents_summary', {}).get('total_documents_uploaded', 0)
        
        # If counts match, profile is up-to-date
        if cached_count == actual_count:
            return cached_profile
        
        # Profile is stale - refresh it
        print(f"🔄 Refreshing stale profile for user {user.id}: cached={cached_count}, actual={actual_count}")
    else:
        print(f"🔄 Creating new profile for user {user.id}")
    
    # Refresh the profile
    try:
        status_data = calculate_visa_journey_stage(actual_documents, db)
        save_student_profile_to_r2(user, status_data, actual_documents)
        # Return the fresh profile
        return get_student_profile_and_status(user.id)
    except Exception as e:
        print(f"Warning: Failed to refresh profile: {str(e)}")
        return cached_profile  # Fall back to cached if refresh fails


@router.post("/chat", response_model=ChatResponse)
async def chat_with_ai(
    chat_message: ChatMessage,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Chat with Rilono AI. The AI has access to the user's complete profile, documents, and visa journey status.
    Document JSON files are attached to the prompt for detailed context.
    """
    try:
        subscription = get_or_create_user_subscription(db, current_user.id)
        limits = get_plan_limits(subscription.plan)
        ai_limit = limits["ai_messages_limit"]
        if ai_limit >= 0 and subscription.ai_messages_used >= ai_limit:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Free plan message limit reached ({ai_limit}). "
                    "Upgrade to Pro for unlimited Rilono AI messages."
                )
            )

        # Get user's name
        user_name = current_user.full_name or current_user.username or "Student"
        
        # Get comprehensive student profile from R2, auto-refresh if stale
        student_profile = refresh_student_profile_if_stale(current_user, db)
        student_profile_context = format_student_profile_context(student_profile)
        
        # Get documents context (summary list of uploaded documents)
        documents_context = get_user_documents_context(current_user.id, db)
        
        # Get document files (full JSON content) to attach to the prompt
        document_files = get_user_document_files(current_user.id, db)
        
        # Generate response with attached document files
        response_text = generate_ai_response(
            user_message=chat_message.message,
            user_name=user_name,
            documents_context=documents_context,
            student_profile_context=student_profile_context,
            document_files=document_files,
            conversation_history=chat_message.conversation_history
        )

        # Count only successful AI responses toward message usage.
        subscription.ai_messages_used += 1
        db.commit()
        
        return ChatResponse(response=response_text)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred: {str(e)}"
        )
