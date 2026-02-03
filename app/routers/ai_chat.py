from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas
from app.auth import get_current_active_user
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
        json_content = response['Body'].read().decode('utf-8')
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
    Fetch user's documents from R2 and create context string with extracted information.
    Returns a formatted string with document information.
    """
    try:
        documents = db.query(models.Document).filter(
            models.Document.user_id == user_id,
            models.Document.extracted_text_file_url.isnot(None)
        ).all()
        
        if not documents:
            return "No documents have been uploaded yet."
        
        context_parts = ["User's Uploaded Documents:"]
        
        for doc in documents:
            try:
                # Get extracted text file from R2
                response = r2_client.get_object(
                    Bucket=R2_DOCUMENTS_BUCKET, 
                    Key=doc.extracted_text_file_url
                )
                extracted_text = response['Body'].read().decode('utf-8')
                
                # Parse JSON if possible - look for JSON in the text
                try:
                    # Try to find JSON object in the text
                    text_lines = extracted_text.split('\n')
                    json_start = -1
                    json_end = -1
                    
                    for i, line in enumerate(text_lines):
                        if line.strip().startswith('{'):
                            json_start = i
                            break
                    
                    if json_start >= 0:
                        # Find the closing brace
                        json_text = '\n'.join(text_lines[json_start:])
                        # Try to extract JSON
                        brace_count = 0
                        json_end_pos = -1
                        for i, char in enumerate(json_text):
                            if char == '{':
                                brace_count += 1
                            elif char == '}':
                                brace_count -= 1
                                if brace_count == 0:
                                    json_end_pos = i + 1
                                    break
                        
                        if json_end_pos > 0:
                            json_str = json_text[:json_end_pos]
                            doc_data = json.loads(json_str)
                            
                            context_parts.append(f"\n- {doc.document_type or 'Document'}: {doc.original_filename}")
                            if doc_data.get('Name'):
                                context_parts.append(f"  Name: {doc_data.get('Name')}")
                            if doc_data.get('Document Number'):
                                context_parts.append(f"  Document Number: {doc_data.get('Document Number')}")
                            if doc_data.get('Date of Birth'):
                                context_parts.append(f"  Date of Birth: {doc_data.get('Date of Birth')}")
                            if doc_data.get('Expiration Date'):
                                context_parts.append(f"  Expiration Date: {doc_data.get('Expiration Date')}")
                            if doc_data.get('Issue Date'):
                                context_parts.append(f"  Issue Date: {doc_data.get('Issue Date')}")
                            if doc_data.get('Country'):
                                context_parts.append(f"  Country: {doc_data.get('Country')}")
                            if doc_data.get('Other Information'):
                                context_parts.append(f"  Additional Info: {doc_data.get('Other Information')}")
                        else:
                            raise json.JSONDecodeError("No valid JSON found", json_text, 0)
                    else:
                        raise json.JSONDecodeError("No JSON start found", extracted_text, 0)
                except (json.JSONDecodeError, ValueError) as e:
                    # If not JSON, use the text as-is (skip header)
                    text_content = extracted_text.split('=' * 80, 1)[-1].strip() if '=' * 80 in extracted_text else extracted_text
                    context_parts.append(f"\n- {doc.document_type or 'Document'}: {doc.original_filename}")
                    context_parts.append(f"  Extracted Information: {text_content[:500]}...")
            except Exception as e:
                # Skip documents that can't be read
                continue
        
        return "\n".join(context_parts)
    except Exception as e:
        print(f"Error fetching documents context: {str(e)}")
        return "Unable to retrieve document information at this time."

def generate_ai_response(user_message: str, user_name: str, documents_context: str, student_profile_context: str, conversation_history: Optional[List[dict]] = None) -> str:
    """
    Generate AI response using Gemini with system prompt, document context, and comprehensive student profile.
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
        
        # Build system prompt with comprehensive student profile
        system_prompt = f"""You are Rilono AI, a F1 student visa expert assistant. You are guiding the student through the F1 student visa process and documentation.

Your role:
- Provide expert guidance on F1 student visa requirements and processes
- Help with document preparation and verification
- Answer questions about visa application steps (DS-160, I-20, SEVIS, interview, etc.)
- Assist with understanding visa documentation requirements
- Be friendly, supportive, and professional

{student_profile_context}

User's uploaded documents and extracted information:
{documents_context}

Instructions:
- IMPORTANT: Use the STUDENT PROFILE AND F1 VISA STATUS information above to personalize your responses
- Reference the student's name, university, and current visa journey stage when giving advice
- Guide them based on their current stage and what the next step is
- Consider their intake semester/year when providing timeline guidance
- Use the document information to provide personalized guidance
- If the user asks about specific documents, reference their uploaded documents when relevant
- Be concise but thorough in your responses
- If you don't have information about a specific document, let the user know and guide them on what they need
- Always maintain a helpful and encouraging tone
- When suggesting next steps, be specific about what documents they need to upload or actions to take

Remember: You have access to the student's complete profile including their name, university, documentation preferences, and current visa journey status. Use this information to provide highly personalized, stage-appropriate guidance."""

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

@router.post("/chat", response_model=ChatResponse)
async def chat_with_ai(
    chat_message: ChatMessage,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Chat with Rilono AI. The AI has access to the user's complete profile, documents, and visa journey status.
    """
    try:
        # Get user's name
        user_name = current_user.full_name or current_user.username or "Student"
        
        # Get comprehensive student profile from R2 (includes profile, preferences, visa status)
        student_profile = get_student_profile_and_status(current_user.id)
        student_profile_context = format_student_profile_context(student_profile)
        
        # Get documents context (extracted text from uploaded documents)
        documents_context = get_user_documents_context(current_user.id, db)
        
        # Generate response
        response_text = generate_ai_response(
            user_message=chat_message.message,
            user_name=user_name,
            documents_context=documents_context,
            student_profile_context=student_profile_context,
            conversation_history=chat_message.conversation_history
        )
        
        return ChatResponse(response=response_text)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred: {str(e)}"
        )

