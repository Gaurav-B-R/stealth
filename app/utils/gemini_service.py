"""
Gemini AI service for document text extraction
Supports both standard Gemini API (with API key) and Vertex AI (with service account)
"""
import os
from typing import Optional
import io
from PIL import Image
from pathlib import Path
from datetime import datetime

# Try to import Vertex AI libraries
try:
    from google.cloud import aiplatform
    from vertexai.generative_models import GenerativeModel, Part
    VERTEX_AI_AVAILABLE = True
except ImportError:
    VERTEX_AI_AVAILABLE = False
    print("⚠ Warning: google-cloud-aiplatform not installed. Install with: pip install google-cloud-aiplatform")

# Also import standard Gemini API as fallback
GENAI_AVAILABLE = False
genai = None
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    print("⚠ Warning: google-generativeai not installed. Install with: pip install google-generativeai")

# Configure authentication - Check for service account first
SERVICE_ACCOUNT_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
USE_VERTEX_AI = False

# Check if service account file exists in current directory
if not os.path.exists(SERVICE_ACCOUNT_PATH):
    # Try project root directory
    current_dir_service_account = Path(__file__).parent.parent.parent / "service_account.json"
    if current_dir_service_account.exists():
        SERVICE_ACCOUNT_PATH = str(current_dir_service_account)

# Configure authentication
if os.path.exists(SERVICE_ACCOUNT_PATH) and VERTEX_AI_AVAILABLE:
    # Use Vertex AI with service account
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = SERVICE_ACCOUNT_PATH
    USE_VERTEX_AI = True
    # Initialize Vertex AI
    try:
        # Get project ID from service account JSON
        import json
        with open(SERVICE_ACCOUNT_PATH, 'r') as f:
            service_account_info = json.load(f)
            project_id = service_account_info.get('project_id', '')
            location = os.getenv("GCP_LOCATION", "us-central1")
        
        if project_id:
            aiplatform.init(project=project_id, location=location)
            print(f"✓ Using Vertex AI with service account: {SERVICE_ACCOUNT_PATH}")
            print(f"  Project: {project_id}, Location: {location}")
        else:
            print("⚠ Warning: Could not find project_id in service account JSON")
            USE_VERTEX_AI = False
    except Exception as e:
        print(f"⚠ Warning: Failed to initialize Vertex AI: {str(e)}")
        USE_VERTEX_AI = False

if not USE_VERTEX_AI:
    # Validate API key format (should start with AIza for Gemini)
    if GEMINI_API_KEY and not GEMINI_API_KEY.startswith("AIza"):
        # Invalid API key format (likely a Resend key or other service key)
        print(f"⚠ Warning: GEMINI_API_KEY doesn't appear to be a valid Gemini API key (should start with 'AIza'). Ignoring it.")
        GEMINI_API_KEY = ""
    
    if GEMINI_API_KEY and GENAI_AVAILABLE:
        # Use standard Gemini API with API key
        genai.configure(api_key=GEMINI_API_KEY)
        print("✓ Using Gemini API key for authentication")
    else:
        print("⚠ Warning: Neither service account JSON nor valid GEMINI_API_KEY found. Document text extraction will be disabled.")


def is_ai_configured() -> bool:
    """True when Gemini is usable via either the Vertex AI service account path
    or a valid Gemini API key. Callers use this to fail fast with a clean
    'temporarily unavailable' message instead of a 500 when AI isn't configured."""
    if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
        return True
    key = (GEMINI_API_KEY or "").strip()
    return bool(GENAI_AVAILABLE and key and key.startswith("AIza"))

# Supported file types for Gemini
SUPPORTED_IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
SUPPORTED_DOCUMENT_TYPES = {".pdf", ".txt"}
UPLOAD_VALIDATION_PROMPT_CONTEXT_CHARS = int(
    os.getenv("UPLOAD_VALIDATION_PROMPT_CONTEXT_CHARS", "120000") or "120000"
)
# Primary model everywhere: Gemini 3.1 Pro (strongest reasoning). Fallbacks stay on
# LIVE model ids only — gemini-2.0-flash / gemini-1.5-* are retired and now 404 on
# the v1beta API, so they must never appear in a candidate chain.
DEFAULT_GEMINI_MODEL = (os.getenv("GEMINI_MODEL", "gemini-3.1-pro").strip() or "gemini-3.1-pro")
DEFAULT_GEMINI_MODEL_CANDIDATES = [
    DEFAULT_GEMINI_MODEL,
    "gemini-3.1-pro",
    "gemini-3.1-pro-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
]


def _dedupe_model_names(model_names: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for model_name in model_names:
        value = str(model_name or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def get_model_candidates(
    primary_env: Optional[str] = None,
    candidates_env: Optional[str] = None,
    defaults: Optional[list[str]] = None,
) -> list[str]:
    primary = os.getenv(primary_env or "", "").strip() if primary_env else ""
    configured_candidates = []
    if candidates_env:
        configured_candidates = [
            item.strip()
            for item in os.getenv(candidates_env, "").split(",")
            if item.strip()
        ]
    return _dedupe_model_names(
        [primary] + configured_candidates + list(defaults or DEFAULT_GEMINI_MODEL_CANDIDATES)
    )


def _instrument_usage(model, model_name: str, usage_source: str = "document_ai"):
    """Wrap generate_content so every document-AI call logs its token usage/cost."""
    try:
        original = model.generate_content
    except Exception:
        return

    def _wrapped(*args, **kwargs):
        resp = original(*args, **kwargs)
        try:
            from app import ai_usage
            ai_usage.record_gemini_usage(usage_source, model_name, resp)
        except Exception:
            pass
        return resp

    try:
        model.generate_content = _wrapped
    except Exception:
        pass


def build_generative_model(model_name: str, usage_source: str = "document_ai"):
    model = None
    if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
        model = GenerativeModel(model_name)
    elif GENAI_AVAILABLE:
        model = genai.GenerativeModel(model_name)
    if model is not None:
        _instrument_usage(model, model_name, usage_source)
    return model


def _generate_content_with_fallback(
    model_names: list[str],
    content,
    usage_source: str = "document_ai",
):
    """Generate with each configured model until one succeeds."""
    last_error = None
    for model_name in _dedupe_model_names(model_names):
        try:
            model = build_generative_model(model_name, usage_source=usage_source)
            if model is None:
                continue
            return model.generate_content(content)
        except Exception as exc:
            last_error = exc
            print(
                f"AI model candidate '{model_name}' failed during {usage_source}; "
                "trying the next configured candidate."
            )

    if last_error is not None:
        raise last_error
    raise RuntimeError("No configured AI model is available")

# Destination-specific date/validity rules injected into the upload-validation prompt so
# a UK/CA/AU/DE student's documents are judged by THEIR authority's rules (not US ones).
_DESTINATION_TIMELINE_RULES = {
    "US": (
        "- I-20: flag as invalid if the program start/reporting date is already in the past.\n"
        "- DS-160 and appointment/payment artifacts (DS-160 confirmation, SEVIS/MRV receipts, "
        "biometric/consular confirmations): flag if expired, stale, or not for the current visa cycle.\n"
        "- Financial proof: US consulates prefer bank statements no older than ~6 months."
    ),
    "UK": (
        "- CAS statement: flag if the course start date is in the past, or the CAS was issued more than "
        "6 months before the visa application (CAS is generally valid for one application within 6 months).\n"
        "- Financial evidence (UKVI 28-day rule): funds must be held for 28 CONSECUTIVE days, and the "
        "statement's closing date must be within 31 days of the visa application date — flag statements "
        "that are older than ~31 days or do not show a 28-day history.\n"
        "- IHS payment confirmation: must correspond to the current application.\n"
        "- TB test certificate: valid for 6 months from an approved clinic — flag if older.\n"
        "- ATAS certificate (if present): valid for 6 months from issue — flag if older.\n"
        "- UKVI eVisa/share-code evidence: flag if the passport/travel-document details do not match "
        "the student's profile or decision notice."
    ),
    "CA": (
        "- Letter of Acceptance (LOA): flag if the program start date is already in the past.\n"
        "- PAL/TAL (provincial attestation): must be valid for the current application cycle.\n"
        "- GIC certificate & proof of funds: flag stale statements (older than ~6 months) or amounts "
        "below the current IRCC requirement when evidence is available.\n"
        "- Biometrics/medical: flag expired confirmations (medical exams are valid ~12 months)."
    ),
    "AU": (
        "- CoE (Confirmation of Enrolment): flag if the course start date is already in the past.\n"
        "- OSHC (health cover): coverage must start on/before arrival and span the study period.\n"
        "- Financial capacity evidence: flag statements older than ~6 months.\n"
        "- English test: most tests are accepted within 2 years of the test date — flag older results."
    ),
    "DE": (
        "- Blocked account (Sperrkonto) confirmation: must show the current required amount and be recent.\n"
        "- University admission (Zulassungsbescheid): flag if the program start date is in the past.\n"
        "- Health insurance confirmation: must cover the intended stay."
    ),
}


def validate_and_extract_document(
    file_contents: bytes,
    filename: str,
    mime_type: str,
    document_type: Optional[str] = None,
    current_date_for_evaluation: Optional[str] = None,
    student_profile_context: Optional[str] = None,
    related_documents_context: Optional[str] = None,
    destination_country_code: Optional[str] = None,
    destination_summary: Optional[str] = None,
) -> Optional[dict]:
    """
    Validate document type and extract information using Gemini AI.
    Returns a JSON dict with validation result and extracted information, or None if extraction fails.
    
    Response format:
    {
        "Document Validation": "Yes" or "No",
        "Message": "Validation message",
        "Name": "extracted name",
        "Extracted Information": {...}
    }
    """
    # Check if we have authentication configured
    has_service_account = os.path.exists(SERVICE_ACCOUNT_PATH)
    has_valid_api_key = GEMINI_API_KEY and GEMINI_API_KEY.startswith("AIza")
    
    if not has_service_account and not has_valid_api_key:
        return None
    
    try:
        file_extension = os.path.splitext(filename)[1].lower()
        
        # Try configured candidates in order so a retired model does not break uploads.
        document_model_candidates = get_model_candidates(
            primary_env="GEMINI_DOCUMENT_MODEL",
            candidates_env="GEMINI_DOCUMENT_MODEL_CANDIDATES",
        )
        
        evaluation_date_value = (current_date_for_evaluation or "").strip() or datetime.now().isoformat()
        profile_context_value = (student_profile_context or "").strip()
        related_docs_context_value = (related_documents_context or "").strip()
        if len(profile_context_value) > UPLOAD_VALIDATION_PROMPT_CONTEXT_CHARS:
            profile_context_value = (
                profile_context_value[:UPLOAD_VALIDATION_PROMPT_CONTEXT_CHARS]
                + "\n... [student profile context truncated]"
            )
        if len(related_docs_context_value) > UPLOAD_VALIDATION_PROMPT_CONTEXT_CHARS:
            related_docs_context_value = (
                related_docs_context_value[:UPLOAD_VALIDATION_PROMPT_CONTEXT_CHARS]
                + "\n... [related documents context truncated]"
            )

        cross_validation_block = f"""
ADDITIONAL CROSS-VALIDATION CONTEXT:
Use the following context to cross-check the uploaded document against the user's profile and previously uploaded documents.

=== ATTACHED STUDENT PROFILE SNAPSHOT ===
{profile_context_value or "Not available"}
=== END ATTACHED STUDENT PROFILE SNAPSHOT ===

=== ATTACHED PREVIOUS DOCUMENTS SNAPSHOT ===
{related_docs_context_value or "Not available"}
=== END ATTACHED PREVIOUS DOCUMENTS SNAPSHOT ===

CROSS-VALIDATION REQUIREMENTS (MANDATORY):
1. Compare this uploaded document with profile + previous documents for consistency.
2. Check identity consistency across documents:
   - Name, Date of Birth, passport/document numbers, country, issue/expiry dates.
3. Check study-plan consistency:
   - University name, intake term/year, and timeline against other available evidence.
4. If there is a material conflict, set "Document Validation" to "No".
5. Clearly state each detected inconsistency in "Message", and include structured details under "Cross Validation Flags".
6. If evidence is insufficient, do not invent facts; explicitly state uncertainty.
"""

        destination_code_value = str(destination_country_code or "US").strip().upper() or "US"
        destination_summary_value = (destination_summary or "").strip()
        destination_rules = _DESTINATION_TIMELINE_RULES.get(
            destination_code_value, _DESTINATION_TIMELINE_RULES["US"]
        )
        destination_line = (
            f"This student is applying for: {destination_summary_value}. Judge every document by THAT "
            "destination's immigration rules and terminology — do not apply another country's rules."
            if destination_summary_value else
            "Judge the document by the student's destination immigration rules."
        )

        timeline_rules_block = f"""
Current Date for Evaluation: {evaluation_date_value}
{destination_line}

STRICT DATE/TIMELINE COMPLIANCE RULES (MANDATORY):
1. Cross-reference all document dates against the Current Date for Evaluation.
2. Bank statements / financial liquid-funds proofs:
   - Unless the destination-specific rules below say otherwise, flag as invalid if the statement date is older than 6 months from the Current Date for Evaluation.
   - Include the detected age in the reason.
3. Passport:
   - Flag as invalid if passport expiry is less than 6 months from expected travel/program-start date.
   - If expected travel/program-start date is unavailable, compare expiry against Current Date for Evaluation and state that assumption explicitly.
4. University offer / admission / enrolment confirmations:
   - Flag as invalid if intake term, program start date, or reporting date is already in the past relative to Current Date for Evaluation.
5. Destination-specific rules for {destination_code_value}:
{destination_rules}
6. Other date-sensitive documents:
   - Apply the same timeline-compliance logic; if expiry/validity is past, mark invalid.
7. If any date check fails:
   - Set "Document Validation" to "No"
   - Put a clear failure explanation in "Message" (this is the review reason field shown to the user), citing the destination's own rule (e.g. UKVI's 28-day rule for the UK, consulate recency expectations for the US).
8. If the document does not contain enough date evidence, do NOT invent dates; mention the assumption/limitation clearly.
"""

        # Build validation prompt based on document type
        validation_prompt = ""
        if document_type:
            validation_prompt = f"""You are a document validation system. The user claims this document is a {document_type.upper()}.

TASK:
1. Carefully examine the document
2. Determine if it actually matches a {document_type.upper()}
3. If YES: Set "Document Validation" to "Yes" and extract all information
4. If NO: Set "Document Validation" to "No", identify what document type it actually is, and provide a helpful message asking the user to upload the correct document

{timeline_rules_block}
{cross_validation_block}

REQUIREMENTS:
- You MUST respond with ONLY valid JSON, no markdown, no code blocks, no explanations
- Start your response directly with {{ and end with }}
- Do NOT include ```json or ``` markers
- Do NOT include any text before or after the JSON

REQUIRED JSON FORMAT:
{{
    "Document Validation": "Yes" or "No",
    "Message": "If 'No': Explain what the document actually looks like (e.g., 'This does not look like your passport page, it looks like your resume. Please cross check and upload the right passport'). If 'Yes': 'Document validated successfully'",
    "Name": "extracted name or null",
    "Date of Birth": "extracted date of birth or null",
    "Document Number": "extracted document number/ID or null",
    "Expiration Date": "extracted expiration date or null",
    "Issue Date": "extracted issue date or null",
    "Country": "extracted country or null",
    "Other Information": "any other relevant extracted information or null",
    "Cross Validation Flags": [
        {{
            "field": "name/date/document_number/university/intake/timeline/other",
            "status": "match/conflict/unknown",
            "current_document_value": "value from current doc or null",
            "reference_value": "value from profile/other docs or null",
            "note": "short explanation"
        }}
    ]
}}

Remember: Output ONLY the JSON object, nothing else."""
        else:
            validation_prompt = f"""Extract all information from this document.

IMPORTANT DATE CONTEXT:
Use the following Current Date for Evaluation while extracting and validating date relevance.
Current Date for Evaluation: {evaluation_date_value}

For date-sensitive docs, explicitly check expiration and timeline compliance:
- Bank statements older than 6 months should be treated as invalid.
- Passport with less than 6 months remaining validity should be treated as invalid.
- I-20/Offer/Admission date in the past should be treated as invalid.
- For other visa docs, flag stale/expired dates as invalid.

{cross_validation_block}

REQUIREMENTS:
- You MUST respond with ONLY valid JSON, no markdown, no code blocks, no explanations
- Start your response directly with {{ and end with }}
- Do NOT include ```json or ``` markers
- Do NOT include any text before or after the JSON

REQUIRED JSON FORMAT:
{{
    "Document Validation": "Yes",
    "Message": "Document information extracted successfully",
    "Name": "extracted name or null",
    "Date of Birth": "extracted date of birth or null",
    "Document Number": "extracted document number/ID or null",
    "Expiration Date": "extracted expiration date or null",
    "Issue Date": "extracted issue date or null",
    "Country": "extracted country or null",
    "Other Information": "any other relevant extracted information or null",
    "Cross Validation Flags": [
        {{
            "field": "name/date/document_number/university/intake/timeline/other",
            "status": "match/conflict/unknown",
            "current_document_value": "value from current doc or null",
            "reference_value": "value from profile/other docs or null",
            "note": "short explanation"
        }}
    ]
}}

Remember: Output ONLY the JSON object, nothing else."""
        
        # Handle different file types
        if file_extension in SUPPORTED_IMAGE_TYPES:
            # For images, use vision model
            image = Image.open(io.BytesIO(file_contents))
            
            print("\n" + "="*80)
            print(f"🔵 GEMINI API CALL: validate_and_extract_document() - IMAGE")
            print(f"📄 File: {filename} ({file_extension})")
            print(f"📝 Document Type: {document_type or 'Not specified'}")
            print("-"*80)
            print("📤 SENDING PROMPT TO GEMINI:")
            print("-"*80)
            pass  # prompt content not logged (privacy)
            print("-"*80)
            print("⏳ Waiting for Gemini response...")
            
            if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                img_bytes = io.BytesIO()
                image.save(img_bytes, format='JPEG')
                img_bytes.seek(0)
                image_part = Part.from_data(img_bytes.read(), mime_type="image/jpeg")
                response = _generate_content_with_fallback(
                    document_model_candidates, [validation_prompt, image_part]
                )
            else:
                response = _generate_content_with_fallback(
                    document_model_candidates, [validation_prompt, image]
                )
            
            response_text = response.text.strip()
            
            print("✅ RECEIVED RESPONSE FROM GEMINI:")
            print("-"*80)
            pass  # response content not logged (privacy)
            print("="*80 + "\n")
        
        elif file_extension == ".pdf":
            # For PDFs
            import tempfile
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                tmp_file.write(file_contents)
                tmp_path = tmp_file.name
            
            try:
                print("\n" + "="*80)
                print(f"🔵 GEMINI API CALL: validate_and_extract_document() - PDF")
                print(f"📄 File: {filename}")
                print(f"📝 Document Type: {document_type or 'Not specified'}")
                print("-"*80)
                print("📤 SENDING PROMPT TO GEMINI:")
                print("-"*80)
                pass  # prompt content not logged (privacy)
                print("-"*80)
                print("⏳ Waiting for Gemini response...")
                
                if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                    with open(tmp_path, 'rb') as f:
                        pdf_data = f.read()
                    pdf_part = Part.from_data(pdf_data, mime_type="application/pdf")
                    response = _generate_content_with_fallback(
                        document_model_candidates, [validation_prompt, pdf_part]
                    )
                else:
                    pdf_file = genai.upload_file(
                        path=tmp_path,
                        mime_type="application/pdf"
                    )
                    import time
                    print("📤 Uploading PDF to Gemini...")
                    while pdf_file.state.name == "PROCESSING":
                        print("   ⏳ PDF still processing...")
                        time.sleep(2)
                        pdf_file = genai.get_file(pdf_file.name)
                    
                    if pdf_file.state.name == "FAILED":
                        raise Exception(f"File processing failed: {pdf_file.state}")
                    
                    print("✅ PDF uploaded, generating content...")
                    response = _generate_content_with_fallback(
                        document_model_candidates, [validation_prompt, pdf_file]
                    )
                    
                    try:
                        genai.delete_file(pdf_file.name)
                    except:
                        pass
                
                response_text = response.text.strip()
                
                print("✅ RECEIVED RESPONSE FROM GEMINI:")
                print("-"*80)
                pass  # response content not logged (privacy)
                print("="*80 + "\n")
            finally:
                try:
                    os.unlink(tmp_path)
                except:
                    pass
        
        elif file_extension == ".txt":
            text_content = file_contents.decode('utf-8', errors='ignore')
            prompt = validation_prompt + f"\n\nDocument content:\n{text_content[:50000]}"
            
            print("\n" + "="*80)
            print(f"🔵 GEMINI API CALL: validate_and_extract_document() - TEXT")
            print(f"📄 File: {filename}")
            print(f"📝 Document Type: {document_type or 'Not specified'}")
            print("-"*80)
            print("📤 SENDING PROMPT TO GEMINI:")
            print("-"*80)
            pass  # prompt content not logged (privacy)
            print("-"*80)
            print("⏳ Waiting for Gemini response...")
            
            response = _generate_content_with_fallback(document_model_candidates, prompt)
            response_text = response.text.strip()
            
            print("✅ RECEIVED RESPONSE FROM GEMINI:")
            print("-"*80)
            pass  # response content not logged (privacy)
            print("="*80 + "\n")
        
        else:
            # Try to process as image
            try:
                image = Image.open(io.BytesIO(file_contents))
                
                print("\n" + "="*80)
                print(f"🔵 GEMINI API CALL: validate_and_extract_document() - UNKNOWN TYPE (trying as image)")
                print(f"📄 File: {filename} ({file_extension})")
                print(f"📝 Document Type: {document_type or 'Not specified'}")
                print("-"*80)
                print("📤 SENDING PROMPT TO GEMINI:")
                print("-"*80)
                pass  # prompt content not logged (privacy)
                print("-"*80)
                print("⏳ Waiting for Gemini response...")
                
                if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                    img_bytes = io.BytesIO()
                    image.save(img_bytes, format='JPEG')
                    img_bytes.seek(0)
                    image_part = Part.from_data(img_bytes.read(), mime_type="image/jpeg")
                    response = _generate_content_with_fallback(
                        document_model_candidates, [validation_prompt, image_part]
                    )
                else:
                    response = _generate_content_with_fallback(
                        document_model_candidates, [validation_prompt, image]
                    )
                response_text = response.text.strip()
                
                print("✅ RECEIVED RESPONSE FROM GEMINI:")
                print("-"*80)
                pass  # response content not logged (privacy)
                print("="*80 + "\n")
            except:
                return None
        
        # Parse JSON response
        try:
            # Clean up response text - remove markdown code blocks if present
            response_text = response_text.strip()
            
            # Remove markdown code blocks
            if response_text.startswith("```json"):
                response_text = response_text[7:].strip()
            elif response_text.startswith("```"):
                response_text = response_text[3:].strip()
            
            if response_text.endswith("```"):
                response_text = response_text[:-3].strip()
            
            # Find first { and last } to extract JSON
            first_brace = response_text.find('{')
            last_brace = response_text.rfind('}')
            
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                response_text = response_text[first_brace:last_brace + 1]
            
            import json
            result = json.loads(response_text)
            
            # Ensure required fields exist
            if "Document Validation" not in result:
                result["Document Validation"] = "Yes"
            if "Message" not in result:
                result["Message"] = "Document processed successfully"
            
            return result
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON response from Gemini: {str(e)}")
            # Privacy: do not log the response content.
            # Return a fallback response
            return {
                "Document Validation": "Yes",
                "Message": "Document processed but validation response format was invalid. Please verify your document manually.",
                "Name": None,
                "Date of Birth": None,
                "Document Number": None,
                "Expiration Date": None,
                "Issue Date": None,
                "Country": None,
                "Other Information": response_text[:500] if response_text else None
            }
    
    except Exception as e:
        print(f"Error validating and extracting document with Gemini: {str(e)}")
        return None

def extract_text_from_document(file_contents: bytes, filename: str, mime_type: str) -> Optional[str]:
    """
    Extract main information from a document using Gemini AI.
    Returns extracted text as a string, or None if extraction fails.
    """
    # Check if we have authentication configured
    has_service_account = os.path.exists(SERVICE_ACCOUNT_PATH)
    has_valid_api_key = GEMINI_API_KEY and GEMINI_API_KEY.startswith("AIza")
    
    if not has_service_account and not has_valid_api_key:
        return None
    
    try:
        file_extension = os.path.splitext(filename)[1].lower()
        
        # Try configured candidates in order so a retired model does not break extraction.
        document_model_candidates = get_model_candidates(
            primary_env="GEMINI_DOCUMENT_MODEL",
            candidates_env="GEMINI_DOCUMENT_MODEL_CANDIDATES",
        )
        
        # Handle different file types
        if file_extension in SUPPORTED_IMAGE_TYPES:
            # For images, use vision model
            image = Image.open(io.BytesIO(file_contents))
            
            prompt = """Please extract and summarize the main information from this document image. 
            Include all important details such as:
            - Document type (passport, visa, transcript, certificate, etc.)
            - Names, dates, identification numbers
            - Key dates and expiration dates
            - Important numbers and codes
            - Any other relevant information
            
            Format the output as clear, structured text that captures all essential information from the document."""
            
            print("\n" + "="*80)
            print(f"🔵 GEMINI API CALL: extract_text_from_document() - IMAGE")
            print(f"📄 File: {filename}")
            print("-"*80)
            print("📤 SENDING PROMPT TO GEMINI:")
            print("-"*80)
            pass  # prompt content not logged (privacy)
            print("-"*80)
            print("⏳ Waiting for Gemini response...")
            
            if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                # Vertex AI format - convert image to bytes
                img_bytes = io.BytesIO()
                image.save(img_bytes, format='JPEG')
                img_bytes.seek(0)
                image_part = Part.from_data(img_bytes.read(), mime_type="image/jpeg")
                response = _generate_content_with_fallback(
                    document_model_candidates, [prompt, image_part]
                )
            else:
                # Standard API format
                response = _generate_content_with_fallback(
                    document_model_candidates, [prompt, image]
                )
            
            print("✅ RECEIVED RESPONSE FROM GEMINI:")
            print("-"*80)
            pass  # response content not logged (privacy)
            print("="*80 + "\n")
            
            return response.text
        
        elif file_extension == ".pdf":
            # For PDFs, we need to save temporarily and upload
            # Gemini requires file uploads for PDFs
            import tempfile
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                tmp_file.write(file_contents)
                tmp_path = tmp_file.name
            
            try:
                prompt = """Please extract and summarize the main information from this PDF document. 
                Include all important details such as:
                - Document type and purpose
                - Names, dates, identification numbers
                - Key dates and expiration dates
                - Important numbers, codes, and references
                - Academic information (if applicable): grades, courses, GPA, etc.
                - Any other relevant information
                
                Format the output as clear, structured text that captures all essential information from the document."""
                
                print("\n" + "="*80)
                print(f"🔵 GEMINI API CALL: extract_text_from_document() - PDF")
                print(f"📄 File: {filename}")
                print("-"*80)
                print("📤 SENDING PROMPT TO GEMINI:")
                print("-"*80)
                pass  # prompt content not logged (privacy)
                print("-"*80)
                print("⏳ Waiting for Gemini response...")
                
                if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                    # Vertex AI - read PDF directly
                    with open(tmp_path, 'rb') as f:
                        pdf_data = f.read()
                    pdf_part = Part.from_data(pdf_data, mime_type="application/pdf")
                    response = _generate_content_with_fallback(
                        document_model_candidates, [prompt, pdf_part]
                    )
                else:
                    # Standard API - upload file first
                    print("📤 Uploading PDF to Gemini...")
                    pdf_file = genai.upload_file(
                        path=tmp_path,
                        mime_type="application/pdf"
                    )
                    
                    # Wait for file to be processed
                    import time
                    while pdf_file.state.name == "PROCESSING":
                        print("   ⏳ PDF still processing...")
                        time.sleep(2)
                        pdf_file = genai.get_file(pdf_file.name)
                    
                    if pdf_file.state.name == "FAILED":
                        raise Exception(f"File processing failed: {pdf_file.state}")
                    
                    print("✅ PDF uploaded, generating content...")
                    response = _generate_content_with_fallback(
                        document_model_candidates, [prompt, pdf_file]
                    )
                    
                    # Clean up uploaded file
                    try:
                        genai.delete_file(pdf_file.name)
                    except:
                        pass
                
                print("✅ RECEIVED RESPONSE FROM GEMINI:")
                print("-"*80)
                pass  # response content not logged (privacy)
                print("="*80 + "\n")
                
                return response.text
            finally:
                # Clean up temporary file
                try:
                    os.unlink(tmp_path)
                except:
                    pass
        
        elif file_extension == ".txt":
            # For text files, read and summarize
            text_content = file_contents.decode('utf-8', errors='ignore')
            
            prompt = f"""Please extract and summarize the main information from this text document. 
            Include all important details such as:
            - Document type and purpose
            - Names, dates, identification numbers
            - Key dates and expiration dates
            - Important numbers, codes, and references
            - Any other relevant information
            
            Format the output as clear, structured text that captures all essential information.
            
            Document content:
            {text_content[:50000]}"""  # Limit to 50k chars to avoid token limits
            
            print("\n" + "="*80)
            print(f"🔵 GEMINI API CALL: extract_text_from_document() - TEXT")
            print(f"📄 File: {filename}")
            print("-"*80)
            print("📤 SENDING PROMPT TO GEMINI:")
            print("-"*80)
            pass  # prompt content not logged (privacy)
            print("-"*80)
            print("⏳ Waiting for Gemini response...")
            
            response = _generate_content_with_fallback(document_model_candidates, prompt)
            
            print("✅ RECEIVED RESPONSE FROM GEMINI:")
            print("-"*80)
            pass  # response content not logged (privacy)
            print("="*80 + "\n")
            
            return response.text
        
        else:
            # For other file types, try to process as image if possible
            try:
                image = Image.open(io.BytesIO(file_contents))
                prompt = """Please extract and summarize the main information from this document. 
                Include all important details such as:
                - Document type (passport, visa, transcript, certificate, etc.)
                - Names, dates, identification numbers
                - Key dates and expiration dates
                - Important numbers and codes
                - Any other relevant information
                
                Format the output as clear, structured text that captures all essential information from the document."""
                
                print("\n" + "="*80)
                print(f"🔵 GEMINI API CALL: extract_text_from_document() - UNKNOWN TYPE (trying as image)")
                print(f"📄 File: {filename} ({file_extension})")
                print("-"*80)
                print("📤 SENDING PROMPT TO GEMINI:")
                print("-"*80)
                pass  # prompt content not logged (privacy)
                print("-"*80)
                print("⏳ Waiting for Gemini response...")
                
                if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                    # Vertex AI format - convert image to bytes
                    img_bytes = io.BytesIO()
                    image.save(img_bytes, format='JPEG')
                    img_bytes.seek(0)
                    image_part = Part.from_data(img_bytes.read(), mime_type="image/jpeg")
                    response = _generate_content_with_fallback(
                        document_model_candidates, [prompt, image_part]
                    )
                else:
                    # Standard API format
                    response = _generate_content_with_fallback(
                        document_model_candidates, [prompt, image]
                    )
                
                print("✅ RECEIVED RESPONSE FROM GEMINI:")
                print("-"*80)
                pass  # response content not logged (privacy)
                print("="*80 + "\n")
                
                return response.text
            except:
                # If it's not an image, return None
                return None
    
    except Exception as e:
        print(f"Error extracting text from document with Gemini: {str(e)}")
        return None

RED_FLAG_PROMPT = """You are an expert study-visa document auditor for Rilono's supported destinations
(US, UK, Canada, Australia, Germany and future student-visa destinations). Inspect this document and
find "red flags" — concrete errors or risks that could cause a visa refusal (expired/stale dates,
name/DOB/passport-number mismatches, insufficient or unexplained funds, missing signatures/stamps,
wrong document for the claimed purpose, sponsor/financial gaps).

Respond with ONLY valid JSON (no markdown, no code fences), starting with {{ and ending with }}:
{{
  "summary": "one-sentence overall read of this document",
  "flags": [
    {{"title": "short label", "detail": "what is wrong and why it matters", "severity": "high|medium|low"}}
  ]
}}
Order flags most-severe first. If the document looks clean, return an empty "flags" list.
Current date for evaluation: {eval_date}"""


def scan_document_red_flags(file_contents: bytes, filename: str, mime_type: str) -> Optional[dict]:
    """
    Run a focused "red flag" audit over a single document for the B2C Visa Success Pass.
    Returns {"summary": str, "flags": [{"title","detail","severity"}]} or None if AI is
    unavailable. Usage is logged under the "red_flag_scan" source for B2C economics.
    """
    has_service_account = os.path.exists(SERVICE_ACCOUNT_PATH)
    has_valid_api_key = GEMINI_API_KEY and GEMINI_API_KEY.startswith("AIza")
    if not has_service_account and not has_valid_api_key:
        return None

    try:
        model_candidates = get_model_candidates(
            primary_env="GEMINI_DOCUMENT_MODEL",
            candidates_env="GEMINI_DOCUMENT_MODEL_CANDIDATES",
        )

        prompt = RED_FLAG_PROMPT.format(eval_date=datetime.now().date().isoformat())
        file_extension = os.path.splitext(filename)[1].lower()

        if file_extension in SUPPORTED_IMAGE_TYPES:
            image = Image.open(io.BytesIO(file_contents))
            if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                buf = io.BytesIO(); image.save(buf, format="JPEG"); buf.seek(0)
                response = _generate_content_with_fallback(
                    model_candidates,
                    [prompt, Part.from_data(buf.read(), mime_type="image/jpeg")],
                    usage_source="red_flag_scan",
                )
            else:
                response = _generate_content_with_fallback(
                    model_candidates, [prompt, image], usage_source="red_flag_scan"
                )
        elif file_extension == ".pdf":
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(file_contents); tmp_path = tmp.name
            try:
                if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                    with open(tmp_path, "rb") as f:
                        response = _generate_content_with_fallback(
                            model_candidates,
                            [prompt, Part.from_data(f.read(), mime_type="application/pdf")],
                            usage_source="red_flag_scan",
                        )
                else:
                    import time
                    pdf_file = genai.upload_file(path=tmp_path, mime_type="application/pdf")
                    while pdf_file.state.name == "PROCESSING":
                        time.sleep(2); pdf_file = genai.get_file(pdf_file.name)
                    if pdf_file.state.name == "FAILED":
                        raise Exception("PDF processing failed")
                    response = _generate_content_with_fallback(
                        model_candidates,
                        [prompt, pdf_file],
                        usage_source="red_flag_scan",
                    )
                    try: genai.delete_file(pdf_file.name)
                    except Exception: pass
            finally:
                try: os.unlink(tmp_path)
                except Exception: pass
        else:
            text_content = file_contents.decode("utf-8", errors="ignore")
            response = _generate_content_with_fallback(
                model_candidates,
                prompt + f"\n\nDocument content:\n{text_content[:50000]}",
                usage_source="red_flag_scan",
            )

        import json
        raw = (response.text or "").strip()
        if raw.startswith("```json"): raw = raw[7:].strip()
        elif raw.startswith("```"): raw = raw[3:].strip()
        if raw.endswith("```"): raw = raw[:-3].strip()
        fb, lb = raw.find("{"), raw.rfind("}")
        if fb != -1 and lb != -1 and lb > fb:
            raw = raw[fb:lb + 1]
        data = json.loads(raw)
        flags = data.get("flags") if isinstance(data, dict) else None
        if not isinstance(flags, list):
            flags = []
        normalized = []
        for f in flags:
            if not isinstance(f, dict):
                continue
            normalized.append({
                "title": str(f.get("title") or "Issue").strip()[:140],
                "detail": str(f.get("detail") or "").strip()[:600],
                "severity": str(f.get("severity") or "medium").strip().lower(),
            })
        return {"summary": str((data or {}).get("summary") or "").strip()[:400], "flags": normalized}
    except Exception as e:
        print(f"Error running red-flag scan with Gemini: {str(e)}")
        return None


def create_extracted_text_file(extracted_text: str, original_filename: str) -> bytes:
    """
    Create a .txt file from extracted text.
    Returns the file contents as bytes.
    """
    if not extracted_text:
        return b""
    
    # Add header with original filename
    header = f"Extracted information from: {original_filename}\n"
    header += "=" * 80 + "\n\n"
    
    full_text = header + extracted_text
    return full_text.encode('utf-8')
