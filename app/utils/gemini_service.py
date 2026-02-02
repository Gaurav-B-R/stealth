"""
Gemini AI service for document text extraction
Supports both standard Gemini API (with API key) and Vertex AI (with service account)
"""
import os
from typing import Optional
import io
from PIL import Image
from pathlib import Path

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

# Supported file types for Gemini
SUPPORTED_IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
SUPPORTED_DOCUMENT_TYPES = {".pdf", ".txt"}

def validate_and_extract_document(file_contents: bytes, filename: str, mime_type: str, document_type: Optional[str] = None) -> Optional[dict]:
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
        
        # Initialize the model
        if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
            model = GenerativeModel('gemini-3-pro-preview')
        elif GENAI_AVAILABLE:
            model = genai.GenerativeModel('gemini-3-pro-preview')
        else:
            print("Error: Neither Vertex AI nor standard Gemini API available")
            return None
        
        # Build validation prompt based on document type
        validation_prompt = ""
        if document_type:
            validation_prompt = f"""You are a document validation system. The user claims this document is a {document_type.upper()}.

TASK:
1. Carefully examine the document
2. Determine if it actually matches a {document_type.upper()}
3. If YES: Set "Document Validation" to "Yes" and extract all information
4. If NO: Set "Document Validation" to "No", identify what document type it actually is, and provide a helpful message asking the user to upload the correct document

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
    "Other Information": "any other relevant extracted information or null"
}}

Remember: Output ONLY the JSON object, nothing else."""
        else:
            validation_prompt = """Extract all information from this document.

REQUIREMENTS:
- You MUST respond with ONLY valid JSON, no markdown, no code blocks, no explanations
- Start your response directly with { and end with }
- Do NOT include ```json or ``` markers
- Do NOT include any text before or after the JSON

REQUIRED JSON FORMAT:
{
    "Document Validation": "Yes",
    "Message": "Document information extracted successfully",
    "Name": "extracted name or null",
    "Date of Birth": "extracted date of birth or null",
    "Document Number": "extracted document number/ID or null",
    "Expiration Date": "extracted expiration date or null",
    "Issue Date": "extracted issue date or null",
    "Country": "extracted country or null",
    "Other Information": "any other relevant extracted information or null"
}

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
            print(validation_prompt)
            print("-"*80)
            print("⏳ Waiting for Gemini response...")
            
            if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                img_bytes = io.BytesIO()
                image.save(img_bytes, format='JPEG')
                img_bytes.seek(0)
                image_part = Part.from_data(img_bytes.read(), mime_type="image/jpeg")
                response = model.generate_content([validation_prompt, image_part])
            else:
                response = model.generate_content([validation_prompt, image])
            
            response_text = response.text.strip()
            
            print("✅ RECEIVED RESPONSE FROM GEMINI:")
            print("-"*80)
            print(response_text[:1000] + ("..." if len(response_text) > 1000 else ""))
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
                print(validation_prompt)
                print("-"*80)
                print("⏳ Waiting for Gemini response...")
                
                if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                    with open(tmp_path, 'rb') as f:
                        pdf_data = f.read()
                    pdf_part = Part.from_data(pdf_data, mime_type="application/pdf")
                    response = model.generate_content([validation_prompt, pdf_part])
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
                    response = model.generate_content([validation_prompt, pdf_file])
                    
                    try:
                        genai.delete_file(pdf_file.name)
                    except:
                        pass
                
                response_text = response.text.strip()
                
                print("✅ RECEIVED RESPONSE FROM GEMINI:")
                print("-"*80)
                print(response_text[:1000] + ("..." if len(response_text) > 1000 else ""))
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
            print(prompt[:2000] + ("..." if len(prompt) > 2000 else ""))
            print("-"*80)
            print("⏳ Waiting for Gemini response...")
            
            response = model.generate_content(prompt)
            response_text = response.text.strip()
            
            print("✅ RECEIVED RESPONSE FROM GEMINI:")
            print("-"*80)
            print(response_text[:1000] + ("..." if len(response_text) > 1000 else ""))
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
                print(validation_prompt)
                print("-"*80)
                print("⏳ Waiting for Gemini response...")
                
                if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                    img_bytes = io.BytesIO()
                    image.save(img_bytes, format='JPEG')
                    img_bytes.seek(0)
                    image_part = Part.from_data(img_bytes.read(), mime_type="image/jpeg")
                    response = model.generate_content([validation_prompt, image_part])
                else:
                    response = model.generate_content([validation_prompt, image])
                response_text = response.text.strip()
                
                print("✅ RECEIVED RESPONSE FROM GEMINI:")
                print("-"*80)
                print(response_text[:1000] + ("..." if len(response_text) > 1000 else ""))
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
            print(f"Response text: {response_text[:500]}")
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
        
        # Initialize the model - Use Vertex AI if available, otherwise standard API
        if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
            model = GenerativeModel('gemini-3-pro-preview')
        elif GENAI_AVAILABLE:
            model = genai.GenerativeModel('gemini-3-pro-preview')
        else:
            print("Error: Neither Vertex AI nor standard Gemini API available")
            return None
        
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
            print(prompt)
            print("-"*80)
            print("⏳ Waiting for Gemini response...")
            
            if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                # Vertex AI format - convert image to bytes
                img_bytes = io.BytesIO()
                image.save(img_bytes, format='JPEG')
                img_bytes.seek(0)
                image_part = Part.from_data(img_bytes.read(), mime_type="image/jpeg")
                response = model.generate_content([prompt, image_part])
            else:
                # Standard API format
                response = model.generate_content([prompt, image])
            
            print("✅ RECEIVED RESPONSE FROM GEMINI:")
            print("-"*80)
            print(response.text[:1000] + ("..." if len(response.text) > 1000 else ""))
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
                print(prompt)
                print("-"*80)
                print("⏳ Waiting for Gemini response...")
                
                if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                    # Vertex AI - read PDF directly
                    with open(tmp_path, 'rb') as f:
                        pdf_data = f.read()
                    pdf_part = Part.from_data(pdf_data, mime_type="application/pdf")
                    response = model.generate_content([prompt, pdf_part])
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
                    response = model.generate_content([prompt, pdf_file])
                    
                    # Clean up uploaded file
                    try:
                        genai.delete_file(pdf_file.name)
                    except:
                        pass
                
                print("✅ RECEIVED RESPONSE FROM GEMINI:")
                print("-"*80)
                print(response.text[:1000] + ("..." if len(response.text) > 1000 else ""))
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
            print(prompt[:2000] + ("..." if len(prompt) > 2000 else ""))
            print("-"*80)
            print("⏳ Waiting for Gemini response...")
            
            response = model.generate_content(prompt)
            
            print("✅ RECEIVED RESPONSE FROM GEMINI:")
            print("-"*80)
            print(response.text[:1000] + ("..." if len(response.text) > 1000 else ""))
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
                print(prompt)
                print("-"*80)
                print("⏳ Waiting for Gemini response...")
                
                if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                    # Vertex AI format - convert image to bytes
                    img_bytes = io.BytesIO()
                    image.save(img_bytes, format='JPEG')
                    img_bytes.seek(0)
                    image_part = Part.from_data(img_bytes.read(), mime_type="image/jpeg")
                    response = model.generate_content([prompt, image_part])
                else:
                    # Standard API format
                    response = model.generate_content([prompt, image])
                
                print("✅ RECEIVED RESPONSE FROM GEMINI:")
                print("-"*80)
                print(response.text[:1000] + ("..." if len(response.text) > 1000 else ""))
                print("="*80 + "\n")
                
                return response.text
            except:
                # If it's not an image, return None
                return None
    
    except Exception as e:
        print(f"Error extracting text from document with Gemini: {str(e)}")
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

