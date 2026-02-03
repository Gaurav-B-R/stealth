from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query, Form
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from app.database import get_db
from app import models, schemas
from app.auth import get_current_active_user, get_current_admin_user, verify_password
from app.utils.security import (
    encrypt_file_with_user_password,
    decrypt_file_with_user_password,
    generate_user_salt,
    encode_salt_for_storage,
    decode_salt_from_storage
)
from app.utils.gemini_service import extract_text_from_document, create_extracted_text_file, validate_and_extract_document
from typing import Optional, List
import os
import uuid
from pathlib import Path
import boto3
from botocore.config import Config
from io import BytesIO
import base64
import json
from datetime import datetime

router = APIRouter(prefix="/api/documents", tags=["documents"])

# R2 Configuration for documents
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_DOCUMENTS_BUCKET = os.getenv("R2_DOCUMENTS_BUCKET", "documents")  # Separate bucket for documents
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL", f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "")

# Initialize R2 client for documents
if not R2_ACCESS_KEY_ID or not R2_SECRET_ACCESS_KEY:
    raise ValueError("R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY must be set in environment variables")

r2_client = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT_URL,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name='auto',
    config=Config(signature_version='s3v4')
)

# Allowed document file types
ALLOWED_DOCUMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".txt", ".jpg", ".jpeg", ".png", 
    ".gif", ".webp", ".xls", ".xlsx", ".csv", ".zip", ".rar"
}
MAX_DOCUMENT_SIZE = 50 * 1024 * 1024  # 50MB for documents

def is_allowed_document(filename: str) -> bool:
    """Check if file extension is allowed"""
    return Path(filename).suffix.lower() in ALLOWED_DOCUMENT_EXTENSIONS

def get_content_type(filename: str) -> str:
    """Get MIME type based on file extension"""
    ext = Path(filename).suffix.lower()
    content_types = {
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".csv": "text/csv",
        ".zip": "application/zip",
        ".rar": "application/x-rar-compressed"
    }
    return content_types.get(ext, "application/octet-stream")

def upload_document_to_r2(file_contents: bytes, filename: str, content_type: str) -> str:
    """Upload document to R2 and return the R2 key/path"""
    try:
        r2_client.put_object(
            Bucket=R2_DOCUMENTS_BUCKET,
            Key=filename,
            Body=file_contents,
            ContentType=content_type,
            # Set metadata for security
            Metadata={
                'uploaded-by': 'rilono-system',
                'encrypted': 'false'  # Can be enhanced with encryption later
            }
        )
        
        # Return the R2 key (we'll use presigned URLs for access)
        return filename
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload document to R2: {str(e)}")

def get_presigned_url(r2_key: str, expiration: int = 3600) -> str:
    """Generate a presigned URL for secure document access"""
    try:
        url = r2_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': R2_DOCUMENTS_BUCKET, 'Key': r2_key},
            ExpiresIn=expiration
        )
        return url
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate presigned URL: {str(e)}")

@router.post("/upload", response_model=schemas.DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    password: str = Form(...),  # User's password for Zero-Knowledge encryption
    document_type: Optional[str] = Form(None),
    country: Optional[str] = Form(None),
    intake: Optional[str] = Form(None),
    year: Optional[int] = Form(None),
    description: Optional[str] = Form(None),
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Upload a document file to R2 storage with Zero-Knowledge encryption.
    Files are encrypted with a key derived from the user's password.
    Even admins cannot decrypt the files without the user's password.
    """
    # Verify password is correct
    if not verify_password(password, current_user.hashed_password):
        raise HTTPException(
            status_code=401,
            detail="Incorrect password. Please provide your login password to encrypt the document."
        )
    
    # Validate file extension
    if not is_allowed_document(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed types: {', '.join(ALLOWED_DOCUMENT_EXTENSIONS)}"
        )
    
    # Read file content
    contents = await file.read()
    
    # Validate file size
    if len(contents) > MAX_DOCUMENT_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {MAX_DOCUMENT_SIZE / 1024 / 1024}MB"
        )
    
    # Generate or get user's encryption salt
    if not current_user.encryption_salt:
        # First time uploading - generate salt
        salt_bytes = generate_user_salt()
        current_user.encryption_salt = encode_salt_for_storage(salt_bytes)
        db.commit()
    else:
        salt_bytes = decode_salt_from_storage(current_user.encryption_salt)
    
    # Encrypt the file using Zero-Knowledge encryption
    try:
        encrypted_file_data, encrypted_file_key = encrypt_file_with_user_password(
            contents, password, salt_bytes
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Encryption failed: {str(e)}"
        )
    
    # Generate unique filename with user ID prefix for organization
    file_extension = Path(file.filename).suffix.lower()
    unique_filename = f"user_{current_user.id}/{uuid.uuid4()}{file_extension}"
    original_filename = file.filename
    
    # Get content type
    content_type = get_content_type(file.filename)
    
    # Upload ENCRYPTED file to R2 (stored as encrypted blob)
    r2_key = upload_document_to_r2(encrypted_file_data, unique_filename, content_type)
    
    # Process document with Gemini AI for validation and text extraction
    extracted_text_file_url = None
    is_processed = False
    validation_result = None
    validation_message = None
    is_valid = True
    
    try:
        # Validate document type and extract information
        validation_result = validate_and_extract_document(
            contents, 
            original_filename, 
            content_type,
            document_type  # Pass the document type for validation
        )
        
        if validation_result:
            # Check validation result
            is_valid = validation_result.get("Document Validation", "No").upper() == "YES"
            validation_message = validation_result.get("Message", "")
            
            # Create JSON file with validation and extracted information
            import json
            validation_json = json.dumps(validation_result, indent=2)
            extracted_text_bytes = validation_json.encode('utf-8')
            
            # Generate unique filename for extracted text file
            extracted_text_filename = f"user_{current_user.id}/{uuid.uuid4()}_extracted.txt"
            
            # Upload extracted text file to R2 (stored as plain text, not encrypted)
            extracted_text_r2_key = upload_document_to_r2(
                extracted_text_bytes, 
                extracted_text_filename, 
                "text/plain"
            )
            
            extracted_text_file_url = extracted_text_r2_key
            is_processed = True
        else:
            # If validation_result is None (Gemini returned None), mark as invalid
            is_valid = False
            validation_message = "Document uploaded but validation could not be completed. Please verify your document manually."
    except Exception as e:
        # Log error but don't fail the upload if Gemini processing fails
        print(f"Warning: Failed to process document with Gemini: {str(e)}")
        is_valid = False  # Mark as invalid when processing fails
        validation_message = "Document uploaded but validation failed. Please verify your document manually."
        # Continue with document upload even if Gemini processing fails
    
    # Create database record with encrypted key
    db_document = models.Document(
        user_id=current_user.id,
        filename=r2_key,
        original_filename=original_filename,
        file_url=r2_key,  # Store R2 key, we'll generate presigned URLs when needed
        file_size=len(encrypted_file_data),  # Store encrypted size
        file_type=content_type,
        document_type=document_type,
        country=country,
        intake=intake,
        year=year,
        description=description,
        is_processed=is_processed,
        extracted_text_file_url=extracted_text_file_url,  # R2 key for extracted text file
        encrypted_file_key=base64.b64encode(encrypted_file_key).decode('utf-8'),  # Store encrypted key
        is_valid=is_valid,  # Store validation status from Gemini
        validation_message=validation_message  # Store validation message from Gemini
    )
    
    db.add(db_document)
    db.commit()
    db.refresh(db_document)
    
    # Note: We don't generate a presigned URL here because the file is encrypted
    # Users will need to provide password to decrypt when viewing/downloading
    db_document.file_url = ""  # Empty URL - requires password to decrypt
    
    # Prepare response with validation information
    response_data = schemas.DocumentUploadResponse(
        document=db_document,
        validation=schemas.DocumentValidationResponse(
            is_valid=is_valid,
            message=validation_message,
            details=validation_result if validation_result else None
        )
    )
    
    return response_data

@router.get("/my-documents", response_model=List[schemas.DocumentResponse])
async def get_my_documents(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get all documents uploaded by the current user.
    Note: file_url will be empty for encrypted documents - use /download endpoint with password.
    """
    documents = db.query(models.Document).options(
        joinedload(models.Document.uploader)
    ).filter(
        models.Document.user_id == current_user.id
    ).order_by(desc(models.Document.created_at)).all()
    
    # For encrypted documents, don't generate presigned URL (requires password to decrypt)
    for doc in documents:
        if doc.encrypted_file_key:
            doc.file_url = ""  # Empty - requires password via /download endpoint
        else:
            # Legacy unencrypted document - generate presigned URL
            doc.file_url = get_presigned_url(doc.filename, expiration=3600)
    
    return documents


# ========== VISA JOURNEY STATUS ENDPOINTS ==========
# NOTE: These must be defined BEFORE /{document_id} to avoid route conflicts

def calculate_visa_journey_stage(documents: List[models.Document]) -> dict:
    """
    Calculate the current visa journey stage based on uploaded documents.
    Returns stage info and progress details.
    """
    # Get uploaded document types
    uploaded_doc_types = set(
        doc.document_type for doc in documents if doc.document_type
    )
    
    # Define stages and their required documents
    stages = [
        {
            "stage": 1,
            "name": "Getting Started",
            "emoji": "📝",
            "description": "Welcome! Start your F1 visa journey.",
            "next_step": "Upload your university offer/admission letter",
            "required_docs": []
        },
        {
            "stage": 2,
            "name": "Admission Received",
            "emoji": "🎓",
            "description": "University admission confirmed!",
            "next_step": "Upload your passport and academic documents",
            "required_docs": ["university-admission-letter"]
        },
        {
            "stage": 3,
            "name": "Documents Ready",
            "emoji": "📄",
            "description": "Essential documents collected.",
            "next_step": "Get your signed I-20 from your university",
            "required_docs": ["passport", "degree-certificates", "transcripts-marksheets"]
        },
        {
            "stage": 4,
            "name": "I-20 Received",
            "emoji": "📘",
            "description": "Great! You have your I-20 from the university.",
            "next_step": "Complete your DS-160 application online",
            "required_docs": ["form-i20-signed"]
        },
        {
            "stage": 5,
            "name": "DS-160 Filed",
            "emoji": "📋",
            "description": "DS-160 application submitted successfully.",
            "next_step": "Pay your SEVIS I-901 fee and visa fee",
            "required_docs": ["ds-160-confirmation"]
        },
        {
            "stage": 6,
            "name": "Fees Paid",
            "emoji": "💳",
            "description": "SEVIS and visa fees payment confirmed.",
            "next_step": "Schedule your visa interview appointment",
            "required_docs": ["i901-sevis-fee-confirmation", "visa-fee-receipt"]
        },
        {
            "stage": 7,
            "name": "Ready to Fly!",
            "emoji": "✈️",
            "description": "Interview scheduled! All documents ready.",
            "next_step": "You're all set! Good luck with your visa interview!",
            "required_docs": ["us-visa-appointment-letter", "photograph-2x2", "bank-balance-certificate"]
        }
    ]
    
    # Calculate current stage based on documents
    current_stage = 1
    
    # Check stage 2: University admission letter
    if "university-admission-letter" in uploaded_doc_types:
        current_stage = 2
    
    # Check stage 3: Passport and academic documents
    has_basic_docs = ("passport" in uploaded_doc_types and 
                      ("degree-certificates" in uploaded_doc_types or 
                       "transcripts-marksheets" in uploaded_doc_types))
    if current_stage >= 2 and has_basic_docs:
        current_stage = 3
    
    # Check stage 4: I-20
    if current_stage >= 3 and "form-i20-signed" in uploaded_doc_types:
        current_stage = 4
    
    # Check stage 5: DS-160
    if current_stage >= 4 and "ds-160-confirmation" in uploaded_doc_types:
        current_stage = 5
    
    # Check stage 6: SEVIS and visa fees
    if current_stage >= 5 and "i901-sevis-fee-confirmation" in uploaded_doc_types:
        current_stage = 6
    
    # Check stage 7: Interview scheduled and all docs ready
    interview_ready = ("us-visa-appointment-letter" in uploaded_doc_types and
                       "photograph-2x2" in uploaded_doc_types and
                       "bank-balance-certificate" in uploaded_doc_types)
    if current_stage >= 6 and interview_ready:
        current_stage = 7
    
    # Get current stage info
    stage_info = stages[current_stage - 1]
    
    # Calculate progress percentage
    progress_percent = round(((current_stage - 1) / (len(stages) - 1)) * 100)
    
    # Get documents by stage
    documents_by_stage = {}
    for doc in documents:
        if doc.document_type:
            if doc.document_type not in documents_by_stage:
                documents_by_stage[doc.document_type] = []
            documents_by_stage[doc.document_type].append({
                "id": doc.id,
                "filename": doc.original_filename,
                "uploaded_at": doc.created_at.isoformat() if doc.created_at else None,
                "is_valid": doc.is_valid
            })
    
    return {
        "current_stage": current_stage,
        "total_stages": len(stages),
        "progress_percent": progress_percent,
        "stage_info": stage_info,
        "all_stages": stages,
        "uploaded_document_types": list(uploaded_doc_types),
        "documents_by_type": documents_by_stage,
        "total_documents_uploaded": len(documents)
    }


def save_visa_status_to_r2(user_id: int, status_data: dict) -> str:
    """
    Save the visa journey status as a JSON file to R2.
    Returns the R2 key of the saved file.
    """
    # Add metadata
    status_data["user_id"] = user_id
    status_data["last_updated"] = datetime.utcnow().isoformat()
    status_data["version"] = "1.0"
    
    # Convert to JSON
    json_content = json.dumps(status_data, indent=2, default=str)
    json_bytes = json_content.encode('utf-8')
    
    # R2 key for the status file
    r2_key = f"user_{user_id}/visa_journey_status.json"
    
    try:
        r2_client.put_object(
            Bucket=R2_DOCUMENTS_BUCKET,
            Key=r2_key,
            Body=json_bytes,
            ContentType="application/json",
            Metadata={
                'type': 'visa-journey-status',
                'user-id': str(user_id)
            }
        )
        return r2_key
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save visa status to R2: {str(e)}")


def get_visa_status_from_r2(user_id: int) -> Optional[dict]:
    """
    Get the visa journey status JSON file from R2.
    Returns None if not found.
    """
    r2_key = f"user_{user_id}/visa_journey_status.json"
    
    try:
        response = r2_client.get_object(Bucket=R2_DOCUMENTS_BUCKET, Key=r2_key)
        json_content = response['Body'].read().decode('utf-8')
        return json.loads(json_content)
    except r2_client.exceptions.NoSuchKey:
        return None
    except Exception:
        return None


@router.get("/visa-status")
async def get_visa_journey_status(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get the current visa journey status for the user.
    Calculates the stage based on uploaded documents and saves to R2.
    """
    # Get user's documents
    documents = db.query(models.Document).filter(
        models.Document.user_id == current_user.id
    ).all()
    
    # Calculate current journey status
    status_data = calculate_visa_journey_stage(documents)
    
    # Save to R2
    r2_key = save_visa_status_to_r2(current_user.id, status_data)
    
    # Add R2 key to response
    status_data["r2_key"] = r2_key
    status_data["user_email"] = current_user.email
    status_data["user_name"] = current_user.full_name
    
    return JSONResponse(content=status_data)


@router.post("/visa-status/refresh")
async def refresh_visa_journey_status(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Force refresh the visa journey status and save to R2.
    Use this after uploading new documents.
    """
    # Get user's documents
    documents = db.query(models.Document).filter(
        models.Document.user_id == current_user.id
    ).all()
    
    # Calculate current journey status
    status_data = calculate_visa_journey_stage(documents)
    
    # Save to R2
    r2_key = save_visa_status_to_r2(current_user.id, status_data)
    
    # Add metadata to response
    status_data["r2_key"] = r2_key
    status_data["user_email"] = current_user.email
    status_data["user_name"] = current_user.full_name
    status_data["refreshed_at"] = datetime.utcnow().isoformat()
    
    return JSONResponse(content=status_data)


@router.get("/visa-status/history")
async def get_visa_status_from_storage(
    current_user: models.User = Depends(get_current_active_user)
):
    """
    Get the last saved visa journey status from R2 storage.
    Returns the cached status without recalculating.
    """
    status_data = get_visa_status_from_r2(current_user.id)
    
    if not status_data:
        raise HTTPException(
            status_code=404,
            detail="No visa status found. Please visit your dashboard to generate one."
        )
    
    return JSONResponse(content=status_data)


# ========== DOCUMENT BY ID ENDPOINTS ==========

@router.get("/{document_id}", response_model=schemas.DocumentResponse)
async def get_document(
    document_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get a specific document. Users can only access their own documents.
    Note: file_url will be empty for encrypted documents - use /download endpoint with password.
    """
    document = db.query(models.Document).options(
        joinedload(models.Document.uploader)
    ).filter(models.Document.id == document_id).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Security: Users can only access their own documents (unless admin)
    if document.user_id != current_user.id and not (current_user.is_admin or current_user.is_developer):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # For encrypted documents, don't generate presigned URL (requires password to decrypt)
    if document.encrypted_file_key:
        document.file_url = ""  # Empty - requires password via /download endpoint
    else:
        # Legacy unencrypted document - generate presigned URL
        document.file_url = get_presigned_url(document.filename, expiration=3600)
    
    return document

@router.post("/{document_id}/download")
async def download_document(
    document_id: int,
    password: str = Form(...),  # User's password for decryption
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Download a document file. Users can only download their own documents.
    Requires password for Zero-Knowledge decryption.
    """
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Security: Users can only download their own documents (unless admin)
    if document.user_id != current_user.id and not (current_user.is_admin or current_user.is_developer):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Verify password
    if not verify_password(password, current_user.hashed_password):
        raise HTTPException(
            status_code=401,
            detail="Incorrect password. Please provide your login password to decrypt the document."
        )
    
    # Check if document has encryption (new documents) or is unencrypted (old documents)
    if not document.encrypted_file_key:
        # Legacy unencrypted document - download directly
        try:
            response = r2_client.get_object(Bucket=R2_DOCUMENTS_BUCKET, Key=document.filename)
            file_content = response['Body'].read()
            
            return StreamingResponse(
                BytesIO(file_content),
                media_type=document.file_type or "application/octet-stream",
                headers={
                    "Content-Disposition": f'attachment; filename="{document.original_filename}"'
                }
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to download document: {str(e)}")
    
    # Zero-Knowledge encrypted document - decrypt it
    try:
        # Get encrypted file from R2
        response = r2_client.get_object(Bucket=R2_DOCUMENTS_BUCKET, Key=document.filename)
        encrypted_file_data = response['Body'].read()
        
        # Get user's salt
        if not current_user.encryption_salt:
            raise HTTPException(
                status_code=500,
                detail="Encryption salt not found. Cannot decrypt document."
            )
        salt_bytes = decode_salt_from_storage(current_user.encryption_salt)
        
        # Decrypt the encrypted file key
        encrypted_file_key = base64.b64decode(document.encrypted_file_key.encode('utf-8'))
        
        # Decrypt the file
        decrypted_file_data = decrypt_file_with_user_password(
            encrypted_file_data,
            encrypted_file_key,
            password,
            salt_bytes
        )
        
        return StreamingResponse(
            BytesIO(decrypted_file_data),
            media_type=document.file_type or "application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{document.original_filename}"'
            }
        )
    except ValueError as e:
        # Decryption failed (wrong password or corrupted data)
        raise HTTPException(
            status_code=401,
            detail=f"Decryption failed: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download document: {str(e)}")

@router.get("/{document_id}/extracted-text")
async def get_extracted_text(
    document_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get the extracted text file for a document.
    This returns the Gemini-processed text file without requiring password.
    Users can only access their own documents.
    """
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Security: Users can only access their own documents (unless admin)
    if document.user_id != current_user.id and not (current_user.is_admin or current_user.is_developer):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Check if document has been processed
    if not document.extracted_text_file_url:
        raise HTTPException(
            status_code=404,
            detail="Extracted text not available. Document may not have been processed yet."
        )
    
    try:
        # Get extracted text file from R2 (stored as plain text, not encrypted)
        response = r2_client.get_object(Bucket=R2_DOCUMENTS_BUCKET, Key=document.extracted_text_file_url)
        file_content = response['Body'].read()
        
        return StreamingResponse(
            BytesIO(file_content),
            media_type="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="{document.original_filename}_extracted.txt"'
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download extracted text: {str(e)}")

# ========== ADMIN/DEVELOPER ENDPOINTS ==========

@router.get("/admin/all", response_model=schemas.DocumentListResponse)
async def get_all_documents_admin(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: Optional[int] = None,
    country: Optional[str] = None,
    intake: Optional[str] = None,
    year: Optional[int] = None,
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Get all documents (admin/developer only).
    Allows filtering and pagination for document management.
    """
    query = db.query(models.Document)
    
    # Apply filters
    if user_id:
        query = query.filter(models.Document.user_id == user_id)
    if country:
        query = query.filter(models.Document.country == country)
    if intake:
        query = query.filter(models.Document.intake == intake)
    if year:
        query = query.filter(models.Document.year == year)
    
    # Get total count
    total = query.count()
    
    # Apply pagination with eager loading
    documents = query.options(
        joinedload(models.Document.uploader)
    ).order_by(desc(models.Document.created_at)).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    
    # Generate presigned URLs for each document
    for doc in documents:
        doc.file_url = get_presigned_url(doc.filename, expiration=3600)
    
    return {
        "documents": documents,
        "total": total,
        "page": page,
        "page_size": page_size
    }

@router.get("/admin/{document_id}", response_model=schemas.DocumentResponse)
async def get_document_admin(
    document_id: int,
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Get any document by ID (admin/developer only)"""
    document = db.query(models.Document).options(
        joinedload(models.Document.uploader)
    ).filter(models.Document.id == document_id).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Generate presigned URL
    document.file_url = get_presigned_url(document.filename, expiration=3600)
    
    return document

@router.get("/admin/{document_id}/download")
async def download_document_admin(
    document_id: int,
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Download any document (admin/developer only)"""
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    try:
        # Get file from R2
        response = r2_client.get_object(Bucket=R2_DOCUMENTS_BUCKET, Key=document.filename)
        file_content = response['Body'].read()
        
        return StreamingResponse(
            BytesIO(file_content),
            media_type=document.file_type or "application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{document.original_filename}"'
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download document: {str(e)}")

@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Delete a document. Users can only delete their own documents.
    This will delete the file from R2 and remove the database record.
    """
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Security: Users can only delete their own documents (unless admin)
    if document.user_id != current_user.id and not (current_user.is_admin or current_user.is_developer):
        raise HTTPException(status_code=403, detail="Access denied. You can only delete your own documents.")
    
    try:
        # Delete original file from R2
        try:
            r2_client.delete_object(Bucket=R2_DOCUMENTS_BUCKET, Key=document.filename)
        except Exception as r2_error:
            # Log the error but continue with database deletion
            # The file might already be deleted or not exist
            print(f"Warning: Failed to delete file from R2: {str(r2_error)}")
        
        # Delete extracted text file from R2 if it exists
        if document.extracted_text_file_url:
            try:
                r2_client.delete_object(Bucket=R2_DOCUMENTS_BUCKET, Key=document.extracted_text_file_url)
            except Exception as r2_error:
                # Log the error but continue with database deletion
                print(f"Warning: Failed to delete extracted text file from R2: {str(r2_error)}")
        
        # Delete from database
        db.delete(document)
        db.commit()
        
        return None
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {str(e)}")

@router.delete("/admin/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document_admin(
    document_id: int,
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Delete a document (admin/developer only)"""
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    try:
        # Delete original file from R2
        r2_client.delete_object(Bucket=R2_DOCUMENTS_BUCKET, Key=document.filename)
        
        # Delete extracted text file from R2 if it exists
        if document.extracted_text_file_url:
            try:
                r2_client.delete_object(Bucket=R2_DOCUMENTS_BUCKET, Key=document.extracted_text_file_url)
            except Exception as r2_error:
                # Log the error but continue with database deletion
                print(f"Warning: Failed to delete extracted text file from R2: {str(r2_error)}")
        
        # Delete from database
        db.delete(document)
        db.commit()
        
        return None
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {str(e)}")
