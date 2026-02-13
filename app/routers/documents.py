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
from app.utils.secure_artifacts import encrypt_artifact_bytes, decrypt_artifact_bytes
from app.utils.gemini_service import extract_text_from_document, create_extracted_text_file, validate_and_extract_document
from app.subscriptions import get_or_create_user_subscription, get_plan_limits
from app.document_catalog import (
    build_document_catalog_response,
    build_journey_stages,
    ensure_default_document_type_catalog,
    get_document_type_payload,
)
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

def upload_document_to_r2(file_contents: bytes, filename: str, content_type: str, encrypted: bool = False) -> str:
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
                'encrypted': 'true' if encrypted else 'false'
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


@router.get("/catalog", response_model=schemas.DocumentCatalogResponse)
def get_document_catalog(db: Session = Depends(get_db)):
    ensure_default_document_type_catalog(db)
    payload = build_document_catalog_response(db)
    return schemas.DocumentCatalogResponse(**payload)

@router.post("/upload", response_model=schemas.DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    password: str = Form(...),  # User's password for Zero-Knowledge encryption
    document_type: str = Form(...),  # Required - document type must be specified
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

    ensure_default_document_type_catalog(db)
    catalog_items = get_document_type_payload(db, active_only=True)
    allowed_document_types = {
        item["value"] for item in catalog_items
    }
    mandatory_document_types = {
        item["value"] for item in catalog_items if item.get("is_required")
    }
    if document_type not in allowed_document_types:
        raise HTTPException(
            status_code=400,
            detail="Invalid document type. Please select a valid type from the list.",
        )
    if document_type in mandatory_document_types:
        existing_mandatory_doc = db.query(models.Document.id).filter(
            models.Document.user_id == current_user.id,
            models.Document.document_type == document_type,
        ).first()
        if existing_mandatory_doc:
            document_label = next(
                (item.get("label") for item in catalog_items if item.get("value") == document_type),
                document_type,
            )
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{document_label} is already uploaded. "
                    "Delete the existing file if you want to upload it again."
                ),
            )

    # Enforce subscription upload limits
    subscription = get_or_create_user_subscription(db, current_user.id)
    limits = get_plan_limits(subscription.plan)
    upload_limit = limits["document_uploads_limit"]
    if upload_limit >= 0:
        if subscription.document_uploads_used <= 0:
            existing_uploads = db.query(models.Document).filter(
                models.Document.user_id == current_user.id
            ).count()
            if existing_uploads > 0:
                subscription.document_uploads_used = existing_uploads
                db.commit()
                db.refresh(subscription)
        if subscription.document_uploads_used >= upload_limit:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Free plan upload limit reached ({upload_limit}). "
                    "Upgrade to Pro for unlimited document uploads."
                )
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
    r2_key = upload_document_to_r2(encrypted_file_data, unique_filename, content_type, encrypted=True)
    
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
            encrypted_extracted_text_bytes = encrypt_artifact_bytes(extracted_text_bytes)
            
            # Generate unique filename for extracted text file
            extracted_text_filename = f"user_{current_user.id}/{uuid.uuid4()}_extracted.txt"
            
            # Upload extracted text file to R2 as encrypted artifact payload.
            extracted_text_r2_key = upload_document_to_r2(
                encrypted_extracted_text_bytes,
                extracted_text_filename, 
                "application/octet-stream",
                encrypted=True
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
    
    # Refresh the student profile in R2 to include the new document
    # This ensures the AI chat has accurate document counts
    try:
        all_documents = db.query(models.Document).filter(
            models.Document.user_id == current_user.id
        ).all()
        status_data = calculate_visa_journey_stage(all_documents, db)
        save_student_profile_to_r2(current_user, status_data, all_documents)
    except Exception as e:
        # Don't fail the upload if profile refresh fails
        print(f"Warning: Failed to refresh student profile after upload: {str(e)}")
    
    # Prepare response with validation information
    response_data = schemas.DocumentUploadResponse(
        document=db_document,
        validation=schemas.DocumentValidationResponse(
            is_valid=is_valid,
            message=validation_message,
            details=validation_result if validation_result else None
        )
    )

    # Count this successful upload toward subscription usage.
    subscription.document_uploads_used += 1
    db.commit()
    
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

def _is_stage_completed(
    stage_number: int,
    uploaded_doc_types: set[str],
    validated_doc_types: set[str],
    document_types: list[dict],
) -> bool:
    stage_gate_docs = [
        row
        for row in document_types
        if row.get("journey_stage") == stage_number and row.get("stage_gate_required")
    ]
    if not stage_gate_docs:
        return True

    def _has_document_for_rule(rule: dict) -> bool:
        if rule.get("stage_gate_requires_validation"):
            return rule["value"] in validated_doc_types
        return rule["value"] in uploaded_doc_types

    direct_required = [row for row in stage_gate_docs if not row.get("stage_gate_group")]
    if any(not _has_document_for_rule(rule) for rule in direct_required):
        return False

    grouped_rules: dict[str, list[dict]] = {}
    for row in stage_gate_docs:
        group_key = row.get("stage_gate_group")
        if not group_key:
            continue
        grouped_rules.setdefault(group_key, []).append(row)

    for group_rules in grouped_rules.values():
        if not any(_has_document_for_rule(rule) for rule in group_rules):
            return False

    return True


def calculate_visa_journey_stage(documents: List[models.Document], db: Optional[Session] = None) -> dict:
    """
    Calculate the current visa journey stage based on uploaded documents.
    Returns stage info and progress details.
    """
    if db is not None:
        ensure_default_document_type_catalog(db)
        document_type_catalog = get_document_type_payload(db, active_only=True)
    else:
        document_type_catalog = []

    if not document_type_catalog:
        # Fallback to built-in defaults if DB is unavailable.
        from app.document_catalog import DEFAULT_DOCUMENT_TYPES

        document_type_catalog = [
            {
                "value": row["document_type"],
                "label": row["label"],
                "description": row.get("description"),
                "sort_order": row["sort_order"],
                "is_active": True,
                "is_required": row.get("is_required", False),
                "journey_stage": row.get("journey_stage"),
                "stage_gate_required": row.get("stage_gate_required", False),
                "stage_gate_requires_validation": row.get("stage_gate_requires_validation", False),
                "stage_gate_group": row.get("stage_gate_group"),
            }
            for row in DEFAULT_DOCUMENT_TYPES
        ]

    journey_stages = build_journey_stages(document_type_catalog)

    # Get uploaded document types.
    uploaded_doc_types = set(
        doc.document_type for doc in documents if doc.document_type
    )
    validated_doc_types = set(
        doc.document_type for doc in documents if doc.document_type and doc.is_valid is True
    )

    # Calculate current stage sequentially from stage gate rules.
    current_stage = 1
    completion_map: dict[int, bool] = {}
    ordered_stages = sorted(journey_stages, key=lambda row: row["stage"])
    for stage in ordered_stages:
        stage_number = stage["stage"]
        completion_map[stage_number] = _is_stage_completed(
            stage_number,
            uploaded_doc_types,
            validated_doc_types,
            document_type_catalog,
        )

    for stage in ordered_stages:
        stage_number = stage["stage"]
        if stage_number <= 1:
            continue

        previous_stage_number = stage_number - 1
        previous_completed = completion_map.get(previous_stage_number, True)
        this_completed = completion_map.get(stage_number, False)

        # Progress to stage N only when stage N-1 is completed and stage N requirements are also met.
        if previous_completed and this_completed:
            current_stage = stage_number
            continue
        break

    # Get current stage info
    stage_info = next(
        (stage for stage in journey_stages if stage["stage"] == current_stage),
        journey_stages[0] if journey_stages else {},
    )

    # Calculate progress percentage
    total_stages = len(journey_stages) if journey_stages else 1
    completed_stage_count = 0
    for stage in ordered_stages:
        stage_number = stage["stage"]
        if completion_map.get(stage_number):
            completed_stage_count += 1
            continue
        break

    progress_percent = round((completed_stage_count / max(total_stages, 1)) * 100)

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
        "total_stages": total_stages,
        "progress_percent": progress_percent,
        "stage_info": stage_info,
        "all_stages": journey_stages,
        "uploaded_document_types": list(uploaded_doc_types),
        "documents_by_type": documents_by_stage,
        "total_documents_uploaded": len(documents)
    }


def save_student_profile_to_r2(user: models.User, status_data: dict, documents: List[models.Document]) -> str:
    """
    Save comprehensive student profile and visa status as a JSON file to R2.
    This file contains all information about the student for LLM context.
    Returns the R2 key of the saved file.
    """
    # Use user's stored documentation preferences (fallback to document values if not set)
    preferred_country = getattr(user, 'preferred_country', None) or "United States"
    preferred_intake = getattr(user, 'preferred_intake', None)
    preferred_year = getattr(user, 'preferred_year', None)
    
    # If user preferences not set, try to extract from documents
    if not preferred_intake or not preferred_year:
        for doc in documents:
            if doc.intake and not preferred_intake:
                preferred_intake = doc.intake
            if doc.year and not preferred_year:
                preferred_year = doc.year
    
    # Build comprehensive student profile
    comprehensive_data = {
        # File metadata for LLM understanding
        "_file_description": "Complete student profile, documentation preferences, uploaded documents summary, and F1 visa journey status",
        "_file_purpose": "Use this data to provide personalized F1 visa guidance based on the student's current status and documents",
        
        # Student Profile Information
        "student_profile": {
            "user_id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "university": user.university,
            "phone": user.phone,
            "account_created": user.created_at.isoformat() if user.created_at else None,
            "email_verified": user.email_verified
        },
        
        # Documentation Preferences
        "documentation_preferences": {
            "target_country": preferred_country,
            "intake_semester": preferred_intake,
            "intake_year": preferred_year
        },
        
        # Visa Journey Status (from existing calculation)
        "visa_journey": {
            "current_stage": status_data.get("current_stage"),
            "total_stages": status_data.get("total_stages", 7),
            "stage_name": status_data.get("stage_info", {}).get("name"),
            "stage_description": status_data.get("stage_info", {}).get("description"),
            "next_step_required": status_data.get("stage_info", {}).get("next_step"),
            "progress_percent": status_data.get("progress_percent", 0)
        },
        
        # Documents Summary
        "documents_summary": {
            "total_documents_uploaded": len(documents),
            "uploaded_document_types": status_data.get("uploaded_document_types", []),
            "documents_by_type": status_data.get("documents_by_type", {})
        },
        
        # All stages for reference
        "all_visa_stages": status_data.get("all_stages", []),
        
        # Metadata
        "last_updated": datetime.utcnow().isoformat(),
        "version": "2.0"
    }
    
    # Convert to JSON
    json_content = json.dumps(comprehensive_data, indent=2, default=str)
    json_bytes = json_content.encode('utf-8')
    encrypted_json_bytes = encrypt_artifact_bytes(json_bytes)
    
    # Descriptive filename for LLM to understand
    r2_key = f"user_{user.id}/STUDENT_PROFILE_AND_F1_VISA_STATUS.json"
    
    try:
        r2_client.put_object(
            Bucket=R2_DOCUMENTS_BUCKET,
            Key=r2_key,
            Body=encrypted_json_bytes,
            ContentType="application/octet-stream",
            Metadata={
                'type': 'student-profile-visa-status',
                'user-id': str(user.id),
                'student-name': user.full_name or 'Unknown',
                'encrypted': 'true'
            }
        )
        return r2_key
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save student profile to R2: {str(e)}")


def get_student_profile_from_r2(user_id: int) -> Optional[dict]:
    """
    Get the student profile and visa status JSON file from R2.
    Returns None if not found.
    """
    r2_key = f"user_{user_id}/STUDENT_PROFILE_AND_F1_VISA_STATUS.json"
    
    try:
        response = r2_client.get_object(Bucket=R2_DOCUMENTS_BUCKET, Key=r2_key)
        encrypted_blob = response['Body'].read()
        json_content = decrypt_artifact_bytes(encrypted_blob).decode('utf-8')
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
    Reads from R2 if exists, otherwise creates it (for new users).
    Does NOT write to R2 on every load - only reads.
    """
    # First, try to get existing profile from R2
    existing_profile = get_student_profile_from_r2(current_user.id)
    
    if existing_profile:
        # Profile exists in R2 - just return it (no write needed)
        # Calculate fresh stage data for UI display
        documents = db.query(models.Document).filter(
            models.Document.user_id == current_user.id
        ).all()
        status_data = calculate_visa_journey_stage(documents, db)
        
        # Merge with existing profile data
        status_data["r2_key"] = f"user_{current_user.id}/STUDENT_PROFILE_AND_F1_VISA_STATUS.json"
        status_data["user_email"] = current_user.email
        status_data["user_name"] = current_user.full_name
        status_data["from_cache"] = True
        
        return JSONResponse(content=status_data)
    
    # Profile doesn't exist in R2 - create it for the first time
    documents = db.query(models.Document).filter(
        models.Document.user_id == current_user.id
    ).all()
    
    status_data = calculate_visa_journey_stage(documents, db)
    
    # Create the R2 file for the first time
    r2_key = save_student_profile_to_r2(current_user, status_data, documents)
    
    status_data["r2_key"] = r2_key
    status_data["user_email"] = current_user.email
    status_data["user_name"] = current_user.full_name
    status_data["from_cache"] = False
    
    return JSONResponse(content=status_data)


@router.post("/visa-status/refresh")
async def refresh_visa_journey_status(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Force refresh the visa journey status and save comprehensive profile to R2.
    Use this after uploading new documents.
    """
    # Get user's documents
    documents = db.query(models.Document).filter(
        models.Document.user_id == current_user.id
    ).all()
    
    # Calculate current journey status
    status_data = calculate_visa_journey_stage(documents, db)
    
    # Save comprehensive student profile to R2
    r2_key = save_student_profile_to_r2(current_user, status_data, documents)
    
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
    Get the last saved student profile and visa status from R2 storage.
    Returns the cached status without recalculating.
    """
    status_data = get_student_profile_from_r2(current_user.id)
    
    if not status_data:
        raise HTTPException(
            status_code=404,
            detail="No student profile found. Please visit your dashboard to generate one."
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
        # Get extracted text file from R2 and decrypt artifact payload if needed.
        response = r2_client.get_object(Bucket=R2_DOCUMENTS_BUCKET, Key=document.extracted_text_file_url)
        encrypted_blob = response['Body'].read()
        file_content = decrypt_artifact_bytes(encrypted_blob)
        
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
        
        # Refresh the student profile in R2 to update document counts
        try:
            all_documents = db.query(models.Document).filter(
                models.Document.user_id == current_user.id
            ).all()
            status_data = calculate_visa_journey_stage(all_documents, db)
            save_student_profile_to_r2(current_user, status_data, all_documents)
        except Exception as refresh_error:
            # Don't fail the delete if profile refresh fails
            print(f"Warning: Failed to refresh student profile after delete: {str(refresh_error)}")
        
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
    
    # Get the document owner for profile refresh
    document_owner_id = document.user_id
    
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
        
        # Refresh the document owner's student profile in R2
        try:
            document_owner = db.query(models.User).filter(models.User.id == document_owner_id).first()
            if document_owner:
                all_documents = db.query(models.Document).filter(
                    models.Document.user_id == document_owner_id
                ).all()
                status_data = calculate_visa_journey_stage(all_documents, db)
                save_student_profile_to_r2(document_owner, status_data, all_documents)
        except Exception as refresh_error:
            # Don't fail the delete if profile refresh fails
            print(f"Warning: Failed to refresh student profile after admin delete: {str(refresh_error)}")
        
        return None
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {str(e)}")
