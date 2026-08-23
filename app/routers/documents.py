from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query, Form, Request
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session, joinedload
from app.utils.rate_limiter import check_ip_rate_limit
from sqlalchemy import desc
from app.database import get_db
from app import models, schemas
from app import ai_usage
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
from app.subscriptions import PLAN_PRO
from app.document_catalog import (
    build_document_catalog_response,
    build_journey_stages,
    ensure_default_document_type_catalog,
    get_document_type_label,
    get_document_type_payload,
)
from app import visa_catalog


def _user_visa_scope(user):
    """Resolve a user's (country_code, visa_type_key), defaulting to US/F-1."""
    if user is None:
        return visa_catalog.DEFAULT_COUNTRY_CODE, visa_catalog.DEFAULT_VISA_TYPE_KEY
    return visa_catalog.resolve_selection(
        getattr(user, "destination_country_code", None),
        getattr(user, "visa_type_key", None),
    )
from typing import Optional, List
import os
import uuid
from pathlib import Path
import logging
import zipfile
import boto3
from botocore.config import Config
from io import BytesIO
import base64
import json
from datetime import datetime
from PIL import Image, UnidentifiedImageError

router = APIRouter(prefix="/api/documents", tags=["documents"])
logger = logging.getLogger(__name__)

USER_ACCOUNT_SNAPSHOT_VERSION = "1.1"
SUBSCRIPTION_SNAPSHOT_VERSION = "1.0"
PROFILE_PRICING_MODEL_MONTHLY = "pro_monthly"
PROFILE_PRICING_MODEL_SIX_MONTH = "pro_six_month"

# R2 Configuration for documents
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_DOCUMENTS_BUCKET = os.getenv("R2_DOCUMENTS_BUCKET", "documents")  # Separate bucket for documents
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL", f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "")

# Dev-only local-disk storage fallback. Activated ONLY when LOCAL_DOC_STORAGE is truthy,
# so it can never silently engage in production (prod sets real R2 keys and leaves this unset).
# It implements the small slice of the boto3 S3 client interface this module actually uses.
LOCAL_DOC_STORAGE = str(os.getenv("LOCAL_DOC_STORAGE", "")).strip().lower() in {"1", "true", "yes", "on"}


class _LocalDiskDocStore:
    """Filesystem stand-in for R2 for local development/testing (LOCAL_DOC_STORAGE=1)."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    def _path(self, key: str) -> str:
        # Keep keys inside root; reject path traversal.
        rel = (key or "").lstrip("/").replace("..", "_")
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def put_object(self, Bucket=None, Key=None, Body=None, ContentType=None, Metadata=None):
        data = Body if isinstance(Body, (bytes, bytearray)) else Body.read()
        with open(self._path(Key), "wb") as fh:
            fh.write(data)
        return {}

    def get_object(self, Bucket=None, Key=None):
        with open(self._path(Key), "rb") as fh:
            return {"Body": BytesIO(fh.read())}

    def delete_object(self, Bucket=None, Key=None):
        try:
            os.remove(self._path(Key))
        except FileNotFoundError:
            pass
        return {}

    def generate_presigned_url(self, *args, **kwargs):
        return ""


# Initialize R2 client for documents
if LOCAL_DOC_STORAGE:
    r2_client = _LocalDiskDocStore(os.path.join(os.path.dirname(__file__), "..", "_local_doc_storage"))
    logger.warning("documents: LOCAL_DOC_STORAGE is ON — using local disk instead of R2 (dev only).")
else:
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
    ".gif", ".webp"
}
MAX_DOCUMENT_SIZE_MB = int(os.getenv("DOCUMENT_MAX_SIZE_MB", "5") or "5")
MAX_DOCUMENT_SIZE = MAX_DOCUMENT_SIZE_MB * 1024 * 1024
READ_CHUNK_SIZE = 1024 * 1024
OLE_DOCUMENT_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
UPLOAD_VALIDATION_MAX_PROFILE_CHARS = int(
    os.getenv("UPLOAD_VALIDATION_MAX_PROFILE_CHARS", "45000") or "45000"
)
UPLOAD_VALIDATION_MAX_DOCS_CONTEXT_CHARS = int(
    os.getenv("UPLOAD_VALIDATION_MAX_DOCS_CONTEXT_CHARS", "75000") or "75000"
)
UPLOAD_VALIDATION_MAX_RELATED_DOCS = int(
    os.getenv("UPLOAD_VALIDATION_MAX_RELATED_DOCS", "10") or "10"
)
IMAGE_FORMATS_BY_EXTENSION = {
    ".jpg": {"JPEG"},
    ".jpeg": {"JPEG"},
    ".png": {"PNG"},
    ".gif": {"GIF"},
    ".webp": {"WEBP"},
}

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
        ".webp": "image/webp"
    }
    return content_types.get(ext, "application/octet-stream")


def read_upload_file_with_limit(file: UploadFile, max_bytes: int) -> bytes:
    """
    Read upload content in chunks and stop as soon as it exceeds max_bytes.
    """
    total = 0
    chunks: list[bytes] = []

    while True:
        chunk = file.file.read(READ_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size is {max_bytes // 1024 // 1024}MB",
            )
        chunks.append(chunk)

    return b"".join(chunks)


def validate_image_content(file_contents: bytes, file_extension: str) -> None:
    expected_formats = IMAGE_FORMATS_BY_EXTENSION.get(file_extension, set())
    if not expected_formats:
        raise HTTPException(status_code=400, detail="Unsupported image format.")

    try:
        with Image.open(BytesIO(file_contents)) as image:
            image.verify()
        with Image.open(BytesIO(file_contents)) as image:
            detected_format = str(image.format or "").upper()
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid or corrupted image file.")

    if detected_format not in expected_formats:
        raise HTTPException(
            status_code=400,
            detail="Image content does not match the file extension.",
        )


def validate_document_content(filename: str, file_contents: bytes) -> None:
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_FORMATS_BY_EXTENSION:
        validate_image_content(file_contents, ext)
        return

    if ext == ".pdf":
        if not file_contents.startswith(b"%PDF-"):
            raise HTTPException(status_code=400, detail="Invalid PDF file.")
        return

    if ext == ".doc":
        if not file_contents.startswith(OLE_DOCUMENT_MAGIC):
            raise HTTPException(status_code=400, detail="Invalid DOC file.")
        return

    if ext == ".docx":
        try:
            with zipfile.ZipFile(BytesIO(file_contents)) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid DOCX file.")

        if "[Content_Types].xml" not in names or not any(name.startswith("word/") for name in names):
            raise HTTPException(status_code=400, detail="Invalid DOCX file structure.")
        return

    if ext == ".txt":
        decoded_text = None
        for encoding in ("utf-8", "utf-16"):
            try:
                decoded_text = file_contents.decode(encoding)
                break
            except UnicodeDecodeError:
                continue

        if decoded_text is None:
            raise HTTPException(status_code=400, detail="Invalid TXT file encoding.")

        sample = decoded_text[:4096]
        if not sample.strip():
            raise HTTPException(status_code=400, detail="Text file is empty.")
        non_text_chars = sum(1 for ch in sample if ord(ch) < 32 and ch not in {"\n", "\r", "\t"})
        if sample and (non_text_chars / len(sample)) > 0.05:
            raise HTTPException(status_code=400, detail="Text file appears to be binary data.")
        return

    raise HTTPException(status_code=400, detail="Unsupported document format.")

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
    except Exception:
        logger.exception("Failed to upload document to R2 key=%s", filename)
        raise HTTPException(status_code=500, detail="Failed to store document securely. Please try again.")


def _truncate_text_for_upload_validation(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated for upload-time cross-validation]"


def build_upload_validation_context(
    user_id: int,
    db: Session,
) -> tuple[str, str]:
    """
    Build bounded profile + prior-documents context for upload-time Gemini validation.
    """
    profile_context = "Student profile snapshot not available."
    related_docs_context = "No previously uploaded documents are available for cross-validation."

    try:
        profile_data = get_student_profile_from_r2(user_id)
        if profile_data:
            profile_json = json.dumps(profile_data, indent=2, default=str)
            profile_context = _truncate_text_for_upload_validation(
                profile_json,
                UPLOAD_VALIDATION_MAX_PROFILE_CHARS,
            )
    except Exception as exc:
        print(f"Warning: Failed to load profile snapshot for upload validation: {str(exc)}")

    try:
        prior_documents = (
            db.query(models.Document)
            .filter(
                models.Document.user_id == user_id,
                models.Document.extracted_text_file_url.isnot(None),
            )
            .order_by(desc(models.Document.created_at))
            .limit(UPLOAD_VALIDATION_MAX_RELATED_DOCS)
            .all()
        )

        blocks = []
        accumulated_chars = 0
        for index, prior_doc in enumerate(prior_documents, start=1):
            if not prior_doc.extracted_text_file_url:
                continue

            try:
                response = r2_client.get_object(
                    Bucket=R2_DOCUMENTS_BUCKET,
                    Key=prior_doc.extracted_text_file_url,
                )
                encrypted_blob = response["Body"].read()
                raw_content = decrypt_artifact_bytes(encrypted_blob).decode("utf-8")
            except Exception as exc:
                print(
                    f"Warning: Failed to load prior document {prior_doc.id} for upload validation: {str(exc)}"
                )
                continue

            doc_status = "VALID" if prior_doc.is_valid else "NEEDS REVIEW"
            header = (
                f"\n--- PRIOR DOCUMENT {index}: "
                f"{(prior_doc.document_type or 'document').upper()} "
                f"({prior_doc.original_filename}) [{doc_status}] ---\n"
            )
            note_line = f"Validation Note: {prior_doc.validation_message or 'N/A'}\n"
            fixed_len = len(header) + len(note_line)
            remaining = UPLOAD_VALIDATION_MAX_DOCS_CONTEXT_CHARS - accumulated_chars - fixed_len
            if remaining <= 0:
                break

            bounded_content = _truncate_text_for_upload_validation(raw_content, remaining)
            block = header + note_line + bounded_content + "\n"
            blocks.append(block)
            accumulated_chars += len(block)

            if accumulated_chars >= UPLOAD_VALIDATION_MAX_DOCS_CONTEXT_CHARS:
                break

        if blocks:
            related_docs_context = (
                "Previously uploaded documents (decrypted extracted payloads) for cross-validation:\n"
                + "".join(blocks)
            )
    except Exception as exc:
        print(f"Warning: Failed to build related-documents context for upload validation: {str(exc)}")

    return profile_context, related_docs_context


def _datetime_to_iso(value) -> Optional[str]:
    if not value:
        return None
    try:
        return value.isoformat()
    except Exception:
        return str(value)


def build_user_account_snapshot(user: models.User) -> dict:
    """
    Build a stable, non-sensitive account snapshot used for profile JSON freshness checks.
    """
    return {
        "snapshot_version": USER_ACCOUNT_SNAPSHOT_VERSION,
        "user_id": user.id,
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "university": user.university,
        "phone": user.phone,
        "visa_case_status": user.visa_case_status,
        "current_situation_story": user.current_situation_story,
        "current_residence_country": user.current_residence_country or "United States",
        # Destination journey — changing country/visa (e.g. onboarding to Australia)
        # must mark the snapshot stale so it rebuilds with the correct country. Without
        # these, a US-defaulted snapshot would persist and the AI would keep saying "US F-1".
        "destination_country_code": getattr(user, "destination_country_code", None),
        "visa_type_key": getattr(user, "visa_type_key", None),
        "profile_picture": user.profile_picture,
        "is_active": bool(user.is_active),
        "email_verified": bool(user.email_verified),
        "is_admin": bool(getattr(user, "is_admin", False)),
        "is_developer": bool(getattr(user, "is_developer", False)),
        "preferred_country": user.preferred_country or "United States",
        "preferred_intake": user.preferred_intake,
        "preferred_year": user.preferred_year,
        "referral_code": user.referral_code,
        "referred_by_user_id": user.referred_by_user_id,
        "first_login_at": _datetime_to_iso(user.first_login_at),
        "referral_reward_granted_at": _datetime_to_iso(user.referral_reward_granted_at),
        "accepted_terms_privacy_at": _datetime_to_iso(user.accepted_terms_privacy_at),
        "email_notifications_enabled": bool(user.email_notifications_enabled),
        "email_notifications_unsubscribed_at": _datetime_to_iso(user.email_notifications_unsubscribed_at),
        "email_notifications_unsubscribe_reason": user.email_notifications_unsubscribe_reason,
        "pending_email": user.pending_email,
        "pending_university": user.pending_university,
        "university_change_token_expires": _datetime_to_iso(user.university_change_token_expires),
        "created_at": _datetime_to_iso(user.created_at),
    }


def is_student_profile_snapshot_stale(
    cached_profile: Optional[dict],
    user: models.User,
    document_count: int,
    db: Optional[Session] = None,
) -> bool:
    """
    A profile snapshot is stale if document count or user-account snapshot differs.
    """
    if not cached_profile:
        return True

    cached_doc_count = cached_profile.get("documents_summary", {}).get("total_documents_uploaded", 0)
    if cached_doc_count != document_count:
        return True

    cached_user_snapshot = cached_profile.get("user_account")
    if not isinstance(cached_user_snapshot, dict):
        return True

    current_snapshot = build_user_account_snapshot(user)
    if cached_user_snapshot != current_snapshot:
        return True

    cached_subscription = cached_profile.get("subscription")
    if not isinstance(cached_subscription, dict):
        return True

    if cached_subscription.get("snapshot_version") != SUBSCRIPTION_SNAPSHOT_VERSION:
        return True

    if db is not None:
        current_subscription = _build_subscription_snapshot_for_profile(user, db)
        subscription_identity_keys = (
            "plan",
            "status",
            "ends_at",
            "access_source",
            "plan_display_name",
            "pricing_model",
        )
        for key in subscription_identity_keys:
            if cached_subscription.get(key) != current_subscription.get(key):
                return True

    return False

def get_presigned_url(r2_key: str, expiration: int = 3600) -> str:
    """Generate a presigned URL for secure document access"""
    try:
        url = r2_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': R2_DOCUMENTS_BUCKET, 'Key': r2_key},
            ExpiresIn=expiration
        )
        return url
    except Exception:
        logger.exception("Failed to generate presigned URL for key=%s", r2_key)
        raise HTTPException(status_code=500, detail="Document link is temporarily unavailable.")


@router.get("/catalog", response_model=schemas.DocumentCatalogResponse)
def get_document_catalog(
    country: Optional[str] = Query(None),
    visa_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    # Public endpoint: anonymous/marketing pages get the US F-1 catalog; the dashboard
    # passes the student's destination + visa type for a personalized journey.
    ensure_default_document_type_catalog(db)
    payload = build_document_catalog_response(db, country, visa_type)
    return schemas.DocumentCatalogResponse(**payload)

@router.post("/upload", response_model=schemas.DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
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

    # Attribute the document-AI (validation/extraction) Gemini cost to this account.
    ai_usage.set_usage_account(user_id=current_user.id)

    ensure_default_document_type_catalog(db)
    _scope_country, _scope_visa = _user_visa_scope(current_user)
    catalog_items = get_document_type_payload(
        db, active_only=True, country_code=_scope_country, visa_type_key=_scope_visa
    )
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
    
    upload_filename = file.filename or ""

    # Validate file extension
    if not is_allowed_document(upload_filename):
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed types: {', '.join(ALLOWED_DOCUMENT_EXTENSIONS)}"
        )

    # Read file content in bounded chunks and validate binary signature/content.
    contents = read_upload_file_with_limit(file, MAX_DOCUMENT_SIZE)
    validate_document_content(upload_filename, contents)
    
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
    except Exception:
        logger.exception("Failed to encrypt document for user_id=%s", current_user.id)
        raise HTTPException(
            status_code=500,
            detail="Failed to encrypt document. Please try again."
        )
    
    # Generate unique filename with user ID prefix for organization
    file_extension = Path(upload_filename).suffix.lower()
    unique_filename = f"user_{current_user.id}/{uuid.uuid4()}{file_extension}"
    original_filename = upload_filename
    
    # Get content type
    content_type = get_content_type(upload_filename)
    
    # Upload ENCRYPTED file to R2 (stored as encrypted blob)
    r2_key = upload_document_to_r2(encrypted_file_data, unique_filename, content_type, encrypted=True)
    
    # Process document with Gemini AI for validation and text extraction
    extracted_text_file_url = None
    is_processed = False
    validation_result = None
    validation_message = None
    is_valid = True
    
    try:
        student_profile_context, related_documents_context = build_upload_validation_context(
            current_user.id,
            db,
        )

        # Validate document type and extract information (judged by the student's OWN
        # destination's rules — e.g. UKVI 28-day funds rule for UK, I-20/DS-160 for US).
        _dest_code, _dest_visa = _user_visa_scope(current_user)
        _dest_name = (visa_catalog.country_meta(_dest_code) or {}).get("name", _dest_code)
        _dest_label = visa_catalog.visa_type_label(_dest_code, _dest_visa) or "Student Visa"
        validation_result = validate_and_extract_document(
            contents,
            original_filename,
            content_type,
            document_type,  # Pass the document type for validation
            current_date_for_evaluation=datetime.now().isoformat(),
            student_profile_context=student_profile_context,
            related_documents_context=related_documents_context,
            destination_country_code=_dest_code,
            destination_summary=f"{_dest_name} — {_dest_label}",
            document_type_label=get_document_type_label(db, document_type, _dest_code, _dest_visa),
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

    # Refresh profile snapshot after both document + usage updates are committed.
    try:
        all_documents = db.query(models.Document).filter(
            models.Document.user_id == current_user.id
        ).all()
        status_data = calculate_visa_journey_stage(all_documents, db, *_user_visa_scope(current_user))
        save_student_profile_to_r2(current_user, status_data, all_documents, db=db)
    except Exception as e:
        # Don't fail the upload if profile refresh fails.
        print(f"Warning: Failed to refresh student profile after upload: {str(e)}")
    
    return response_data


@router.post("/upload-e2e", status_code=status.HTTP_201_CREATED)
def upload_document_e2e(
    file: UploadFile = File(...),          # client-encrypted ciphertext blob (AES-GCM, IV prepended)
    wrapped_dek: str = Form(...),          # per-file DEK wrapped by the E2E master key (base64)
    original_filename: str = Form(...),    # real filename for display; the content stays encrypted
    document_type: str = Form(...),
    file_type: Optional[str] = Form(None), # original MIME type (used after the browser decrypts)
    country: Optional[str] = Form(None),
    intake: Optional[str] = Form(None),
    year: Optional[int] = Form(None),
    description: Optional[str] = Form(None),
    # Optional outputs from a prior consent-based /ai-validate call. is_valid is a non-sensitive
    # verdict; the extracted DETAILS stay E2E (extracted_blob is client-encrypted, like the file).
    is_valid: Optional[bool] = Form(None),
    extracted_blob: Optional[UploadFile] = File(None),
    extracted_wrapped_dek: Optional[str] = Form(None),
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Store a CLIENT-ENCRYPTED document (true end-to-end encryption).

    The server only ever receives ciphertext plus the wrapped data-encryption key — never
    the plaintext, the user's password, or the DEK. No Gemini/AI runs here (that is the
    separate consent-based transient flow). The user must have an E2E vault set up
    (POST /api/e2e/setup) so a master key exists to unwrap the DEK on download.
    """
    if not getattr(current_user, "e2e_enabled", False):
        raise HTTPException(
            status_code=409,
            detail="Set up end-to-end encryption before uploading encrypted documents.",
        )

    wrapped_dek = (wrapped_dek or "").strip()
    if not wrapped_dek or len(wrapped_dek) > 4096:
        raise HTTPException(status_code=400, detail="Invalid wrapped key.")
    try:
        base64.b64decode(wrapped_dek, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="wrapped_dek must be valid base64.")

    original_filename = (original_filename or "").strip() or "document"
    if not is_allowed_document(original_filename):
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed types: {', '.join(sorted(ALLOWED_DOCUMENT_EXTENSIONS))}",
        )

    # Validate the document type against the catalog (same allow-list as the legacy path).
    ensure_default_document_type_catalog(db)
    _scope_country, _scope_visa = _user_visa_scope(current_user)
    catalog_items = get_document_type_payload(
        db, active_only=True, country_code=_scope_country, visa_type_key=_scope_visa
    )
    allowed_document_types = {item["value"] for item in catalog_items}
    mandatory_document_types = {item["value"] for item in catalog_items if item.get("is_required")}
    if document_type not in allowed_document_types:
        raise HTTPException(
            status_code=400, detail="Invalid document type. Please select a valid type from the list."
        )
    if document_type in mandatory_document_types:
        existing = db.query(models.Document.id).filter(
            models.Document.user_id == current_user.id,
            models.Document.document_type == document_type,
        ).first()
        if existing:
            label = next(
                (i.get("label") for i in catalog_items if i.get("value") == document_type), document_type
            )
            raise HTTPException(
                status_code=409,
                detail=f"{label} is already uploaded. Delete the existing file if you want to upload it again.",
            )

    # Enforce subscription upload limits (same rule as the legacy upload path).
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
                ),
            )

    # Read the ciphertext (bounded). Allow a margin over the plaintext cap for AES-GCM overhead.
    ciphertext = read_upload_file_with_limit(file, MAX_DOCUMENT_SIZE + 1024 * 1024)
    if not ciphertext:
        raise HTTPException(status_code=400, detail="Encrypted file is empty.")

    r2_key = f"user_{current_user.id}/{uuid.uuid4()}.enc"
    upload_document_to_r2(ciphertext, r2_key, "application/octet-stream", encrypted=True)

    # Optional E2E-encrypted extracted-text artifact from a prior /ai-validate (client-encrypted,
    # like the file itself). Stored as opaque ciphertext; the server cannot read the details.
    extracted_r2_key = None
    extracted_dek_value = None
    if extracted_blob is not None and extracted_wrapped_dek:
        extracted_wrapped_dek = extracted_wrapped_dek.strip()
        if len(extracted_wrapped_dek) > 4096:
            raise HTTPException(status_code=400, detail="Invalid extracted-text wrapped key.")
        try:
            base64.b64decode(extracted_wrapped_dek, validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="extracted_wrapped_dek must be valid base64.")
        extracted_ciphertext = read_upload_file_with_limit(extracted_blob, MAX_DOCUMENT_SIZE + 1024 * 1024)
        if extracted_ciphertext:
            extracted_r2_key = f"user_{current_user.id}/{uuid.uuid4()}_extracted.enc"
            upload_document_to_r2(extracted_ciphertext, extracted_r2_key, "application/octet-stream", encrypted=True)
            extracted_dek_value = extracted_wrapped_dek

    # Persist only the non-sensitive verdict; the detailed extracted text stays E2E.
    if is_valid is None:
        validation_message = None
    else:
        validation_message = "AI-validated" if is_valid else "AI flagged — open the document to review details."

    db_document = models.Document(
        user_id=current_user.id,
        filename=r2_key,
        original_filename=original_filename,
        file_url="",  # encrypted; downloaded via /{id}/blob and decrypted in-browser
        file_size=len(ciphertext),
        file_type=(file_type or "application/octet-stream"),
        document_type=document_type,
        country=country,
        intake=intake,
        year=year,
        description=description,
        is_processed=extracted_r2_key is not None,
        extracted_text_file_url=extracted_r2_key,
        encrypted_file_key=None,
        e2e_scheme="v2-aesgcm",
        e2e_wrapped_dek=wrapped_dek,
        e2e_extracted_wrapped_dek=extracted_dek_value,
        is_valid=is_valid,
        validation_message=validation_message,
    )
    db.add(db_document)
    subscription.document_uploads_used += 1
    db.commit()
    db.refresh(db_document)

    # Best-effort profile snapshot refresh (uses document METADATA only — no plaintext).
    try:
        all_documents = db.query(models.Document).filter(
            models.Document.user_id == current_user.id
        ).all()
        status_data = calculate_visa_journey_stage(all_documents, db, *_user_visa_scope(current_user))
        save_student_profile_to_r2(current_user, status_data, all_documents, db=db)
    except Exception as exc:
        logger.warning("E2E upload: profile snapshot refresh failed for user_id=%s: %s", current_user.id, exc)

    return {
        "id": db_document.id,
        "original_filename": db_document.original_filename,
        "document_type": db_document.document_type,
        "file_size": db_document.file_size,
        "e2e_scheme": db_document.e2e_scheme,
        "encrypted": True,
        "created_at": db_document.created_at.isoformat() if db_document.created_at else None,
        "message": "Document encrypted on your device and stored. Our servers only hold ciphertext.",
    }


@router.get("/{document_id}/blob")
def download_document_blob(
    document_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Return the raw CIPHERTEXT of a client-encrypted (E2E) document.

    The browser unwraps the per-file DEK (from the X-E2E-Wrapped-Dek header, using the session
    master key) and decrypts locally. The server cannot decrypt this: no password is involved
    and no key is derivable here.
    """
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    # Owner-only (an admin/dev could fetch the ciphertext but still couldn't decrypt it).
    if document.user_id != current_user.id and not (current_user.is_admin or current_user.is_developer):
        raise HTTPException(status_code=403, detail="Access denied")
    if not document.e2e_scheme or not document.e2e_wrapped_dek:
        raise HTTPException(
            status_code=400,
            detail="This document is not end-to-end encrypted. Use the standard download.",
        )

    try:
        response = r2_client.get_object(Bucket=R2_DOCUMENTS_BUCKET, Key=document.filename)
        ciphertext = response["Body"].read()
    except Exception:
        logger.exception(
            "Failed to fetch E2E blob document_id=%s user_id=%s", document_id, current_user.id
        )
        raise HTTPException(status_code=500, detail="Failed to fetch document. Please try again.")

    return StreamingResponse(
        BytesIO(ciphertext),
        media_type="application/octet-stream",
        headers={
            "X-E2E-Scheme": document.e2e_scheme,
            "X-E2E-Wrapped-Dek": document.e2e_wrapped_dek,
            "Content-Disposition": 'attachment; filename="document.enc"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/{document_id}/extracted-blob")
def download_extracted_blob(
    document_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Return the E2E-encrypted extracted-text artifact (from consent-based AI validation).

    Like /blob, this is opaque ciphertext the server cannot read; the browser unwraps the DEK
    from the X-E2E-Wrapped-Dek header with the session master key and decrypts locally. Used to
    feed AI-chat context client-side without the server ever holding the extracted details.
    """
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.user_id != current_user.id and not (current_user.is_admin or current_user.is_developer):
        raise HTTPException(status_code=403, detail="Access denied")
    if not document.e2e_extracted_wrapped_dek or not document.extracted_text_file_url:
        raise HTTPException(status_code=404, detail="No encrypted extracted text for this document.")

    try:
        response = r2_client.get_object(Bucket=R2_DOCUMENTS_BUCKET, Key=document.extracted_text_file_url)
        ciphertext = response["Body"].read()
    except Exception:
        logger.exception(
            "Failed to fetch extracted E2E blob document_id=%s user_id=%s", document_id, current_user.id
        )
        raise HTTPException(status_code=500, detail="Failed to fetch extracted text. Please try again.")

    return StreamingResponse(
        BytesIO(ciphertext),
        media_type="application/octet-stream",
        headers={
            "X-E2E-Scheme": document.e2e_scheme or "v2-aesgcm",
            "X-E2E-Wrapped-Dek": document.e2e_extracted_wrapped_dek,
            "Cache-Control": "no-store",
        },
    )


AI_VALIDATE_RATE_LIMIT = int(os.getenv("AI_VALIDATE_RATE_LIMIT", "20"))
AI_VALIDATE_RATE_WINDOW_SECONDS = int(os.getenv("AI_VALIDATE_RATE_WINDOW_SECONDS", "3600"))


@router.post("/ai-validate")
def ai_validate_document_transient(
    request: Request,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    consent: bool = Form(...),
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Consent-based, TRANSIENT AI validation for end-to-end-encrypted documents.

    The browser sends the *plaintext* file here ONLY when the user explicitly opts in. We run
    Gemini validation/extraction fully in memory, return the result, and persist NOTHING — no
    R2 object, no DB row, no logging of the content. This is how AI features coexist with E2E:
    the server reads the file once, with consent, and never stores it. The encrypted document
    itself is uploaded separately via /upload-e2e, and the browser stores the returned
    extracted JSON re-encrypted under the user's master key.
    """
    if not consent:
        raise HTTPException(status_code=400, detail="AI validation requires explicit consent.")

    # Rate-limit per IP to bound Gemini cost / abuse.
    allowed, retry_after = check_ip_rate_limit(
        request=request,
        scope="documents.ai_validate",
        limit=AI_VALIDATE_RATE_LIMIT,
        window_seconds=AI_VALIDATE_RATE_WINDOW_SECONDS,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many validation requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    upload_filename = file.filename or "document"
    if not is_allowed_document(upload_filename):
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed types: {', '.join(sorted(ALLOWED_DOCUMENT_EXTENSIONS))}",
        )

    # Validate the document type against the catalog.
    ensure_default_document_type_catalog(db)
    _scope_country, _scope_visa = _user_visa_scope(current_user)
    catalog_items = get_document_type_payload(
        db, active_only=True, country_code=_scope_country, visa_type_key=_scope_visa
    )
    if document_type not in {item["value"] for item in catalog_items}:
        raise HTTPException(
            status_code=400, detail="Invalid document type. Please select a valid type from the list."
        )

    # Read the plaintext into memory (bounded) and sanity-check it is a real document.
    contents = read_upload_file_with_limit(file, MAX_DOCUMENT_SIZE)
    validate_document_content(upload_filename, contents)
    content_type = get_content_type(upload_filename)

    # Attribute the Gemini cost to this account.
    ai_usage.set_usage_account(user_id=current_user.id)

    try:
        student_profile_context, related_documents_context = build_upload_validation_context(
            current_user.id, db
        )
        _dest_code, _dest_visa = _user_visa_scope(current_user)
        _dest_name = (visa_catalog.country_meta(_dest_code) or {}).get("name", _dest_code)
        _dest_label = visa_catalog.visa_type_label(_dest_code, _dest_visa) or "Student Visa"
        validation_result = validate_and_extract_document(
            contents,
            upload_filename,
            content_type,
            document_type,
            current_date_for_evaluation=datetime.now().isoformat(),
            student_profile_context=student_profile_context,
            related_documents_context=related_documents_context,
            destination_country_code=_dest_code,
            destination_summary=f"{_dest_name} — {_dest_label}",
            document_type_label=get_document_type_label(db, document_type, _dest_code, _dest_visa),
        )
    except Exception:
        logger.exception("ai-validate: Gemini processing failed for user_id=%s", current_user.id)
        raise HTTPException(status_code=502, detail="AI validation could not be completed. Please try again.")
    finally:
        # Drop the plaintext reference promptly; it is never persisted anywhere.
        contents = None

    if not validation_result:
        return {"is_valid": False, "message": "Validation could not be completed.", "details": None}

    is_valid = str(validation_result.get("Document Validation", "No")).upper() == "YES"
    message = validation_result.get("Message", "")
    return {"is_valid": is_valid, "message": message, "details": validation_result}


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
    
    # For encrypted documents, don't generate presigned URL (a presigned URL to ciphertext
    # would be useless). E2E docs are downloaded via /{id}/blob and decrypted in-browser;
    # legacy v1 docs via /{id}/download with the password.
    for doc in documents:
        if doc.encrypted_file_key or doc.e2e_scheme:
            doc.file_url = ""
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


def calculate_visa_journey_stage(
    documents: List[models.Document],
    db: Optional[Session] = None,
    country_code: Optional[str] = None,
    visa_type_key: Optional[str] = None,
) -> dict:
    """
    Calculate the current visa journey stage based on uploaded documents, scoped to
    the student's destination country + visa type (defaults to US F-1).
    Returns stage info and progress details.
    """
    country_code, visa_type_key = visa_catalog.resolve_selection(country_code, visa_type_key)
    if db is not None:
        ensure_default_document_type_catalog(db)
        document_type_catalog = get_document_type_payload(
            db, active_only=True, country_code=country_code, visa_type_key=visa_type_key
        )
    else:
        document_type_catalog = []

    if not document_type_catalog:
        # Fallback to built-in defaults for this scope if the DB is unavailable.
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
            for row in visa_catalog.documents_for(country_code, visa_type_key)
        ]

    journey_stages = build_journey_stages(
        document_type_catalog, visa_catalog.journey_stages_for(country_code, visa_type_key)
    )

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


def _normalize_profile_pricing_model(raw_model: str | None) -> str:
    normalized = str(raw_model or "").strip().lower()
    if normalized in {
        PROFILE_PRICING_MODEL_SIX_MONTH,
        "pro_6_month",
        "pro_6month",
        "6_month",
        "6month",
        "six_month",
        "one_time_6_month",
    }:
        return PROFILE_PRICING_MODEL_SIX_MONTH
    if normalized in {
        PROFILE_PRICING_MODEL_MONTHLY,
        "monthly",
        "pro",
        "default",
    }:
        return PROFILE_PRICING_MODEL_MONTHLY
    return PROFILE_PRICING_MODEL_MONTHLY


def _build_subscription_snapshot_for_profile(user: models.User, db: Session) -> dict:
    user_id = user.id
    subscription = get_or_create_user_subscription(db, user_id, commit=False)
    limits = get_plan_limits(subscription.plan)
    # Shared settled-first rule: abandoned 'created' checkout orders must not mask
    # the payment that actually settled, or the assistant tells a paid buyer their
    # latest payment is still pending. Function-local import — subscription.py
    # lazy-imports this module, so a top-level import would be a cycle.
    from app.routers.subscription import _find_latest_payment_for_user
    latest_payment = _find_latest_payment_for_user(db, user_id)
    latest_verified_payment = (
        db.query(models.SubscriptionPayment)
        .filter(
            models.SubscriptionPayment.user_id == user_id,
            models.SubscriptionPayment.status == "verified",
        )
        .order_by(desc(models.SubscriptionPayment.id))
        .first()
    )
    latest_razorpay_subscription = (
        db.query(models.SubscriptionPayment)
        .filter(
            models.SubscriptionPayment.user_id == user_id,
            models.SubscriptionPayment.provider == "razorpay",
            models.SubscriptionPayment.razorpay_subscription_id.isnot(None),
        )
        .order_by(desc(models.SubscriptionPayment.id))
        .first()
    )
    latest_verified_provider = (
        str(latest_verified_payment.provider or "").strip().lower()
        if latest_verified_payment and latest_verified_payment.provider
        else ""
    )
    latest_verified_pricing_model = _normalize_profile_pricing_model(
        getattr(latest_verified_payment, "pricing_model", None)
    )
    has_verified_payment = latest_verified_payment is not None
    # ends_at is a timezone-aware column; `now` is naive UTC. Strip tzinfo before comparing
    # (same rule as app/subscriptions._normalize_datetime and the twin snapshot in
    # routers/subscription.py). 2026-08-23: this was the one unnormalized comparison — it
    # only ran for a Pro user with BOTH a referral reward and an end date, and then raised
    # "can't compare offset-naive and offset-aware datetimes" on every profile-snapshot
    # refresh, which 500ed the Rilono AI chat / extension Copilot for that user.
    ends_at = subscription.ends_at
    if getattr(ends_at, "tzinfo", None):
        ends_at = ends_at.replace(tzinfo=None)
    now = datetime.utcnow()
    referral_bonus_active = bool(
        subscription.plan == PLAN_PRO
        and user.referral_reward_granted_at
        and ends_at
        and ends_at > now
        and not has_verified_payment
        and not latest_razorpay_subscription
    )
    if subscription.plan != PLAN_PRO:
        access_source = "Free Plan"
    elif referral_bonus_active:
        access_source = "Referral Bonus (Visa Success Pass)"
    else:
        # Paid access is now presented uniformly as the Visa Success Pass (old Pro
        # Monthly / Journey Pass products are retired).
        access_source = "Visa Success Pass"

    if subscription.plan != PLAN_PRO:
        plan_display_name = "Free"
    else:
        plan_display_name = "Visa Success Pass"

    return {
        "snapshot_version": SUBSCRIPTION_SNAPSHOT_VERSION,
        "plan": (subscription.plan or "free").lower(),
        "status": (subscription.status or "active").lower(),
        "plan_display_name": plan_display_name,
        "access_source": access_source,
        "pricing_model": (
            latest_verified_pricing_model if subscription.plan == PLAN_PRO and has_verified_payment else None
        ),
        "started_at": subscription.started_at.isoformat() if subscription.started_at else None,
        "ends_at": subscription.ends_at.isoformat() if subscription.ends_at else None,
        "usage": {
            "ai_messages_used": int(subscription.ai_messages_used or 0),
            "document_uploads_used": int(subscription.document_uploads_used or 0),
            "prep_sessions_used": int(subscription.prep_sessions_used or 0),
            "mock_interviews_used": int(subscription.mock_interviews_used or 0),
        },
        "limits": {
            "ai_messages_limit": int(limits.get("ai_messages_limit", 0)),
            "document_uploads_limit": int(limits.get("document_uploads_limit", 0)),
            "prep_sessions_limit": int(limits.get("prep_sessions_limit", 0)),
            "mock_interviews_limit": int(limits.get("mock_interviews_limit", 0)),
        },
        "latest_payment": (
            {
                "provider": latest_payment.provider,
                "status": latest_payment.status,
                "amount_paise": int(latest_payment.amount_paise or 0),
                "currency": latest_payment.currency,
                "coupon_code": latest_payment.coupon_code,
                "coupon_percent_off": (
                    float(latest_payment.coupon_percent_off)
                    if latest_payment.coupon_percent_off is not None
                    else None
                ),
                "pricing_model": _normalize_profile_pricing_model(getattr(latest_payment, "pricing_model", None)),
                "verified_at": latest_payment.verified_at.isoformat() if latest_payment.verified_at else None,
                "created_at": latest_payment.created_at.isoformat() if latest_payment.created_at else None,
            }
            if latest_payment
            else None
        ),
        "latest_razorpay_subscription_id": (
            latest_razorpay_subscription.razorpay_subscription_id
            if latest_razorpay_subscription
            else None
        ),
    }


def save_student_profile_to_r2(
    user: models.User,
    status_data: dict,
    documents: List[models.Document],
    db: Optional[Session] = None,
) -> str:
    """
    Save comprehensive student profile and visa status as a JSON file to R2.
    This file contains all information about the student for LLM context.
    Returns the R2 key of the saved file.
    """
    # Use user's stored documentation preferences (fallback to document values if not set)
    preferred_country = getattr(user, 'preferred_country', None) or "United States"
    preferred_intake = getattr(user, 'preferred_intake', None)
    preferred_year = getattr(user, 'preferred_year', None)

    # Personalized destination + visa type (drives the country-specific AI guidance).
    _scope_country, _scope_visa = _user_visa_scope(user)
    destination_country = (visa_catalog.country_meta(_scope_country) or {}).get("name") or preferred_country
    visa_type_label = visa_catalog.visa_type_label(_scope_country, _scope_visa) or "Student Visa"

    # If user preferences not set, try to extract from documents
    if not preferred_intake or not preferred_year:
        for doc in documents:
            if doc.intake and not preferred_intake:
                preferred_intake = doc.intake
            if doc.year and not preferred_year:
                preferred_year = doc.year
    
    subscription_snapshot = _build_subscription_snapshot_for_profile(user, db) if db else {}
    user_account_snapshot = build_user_account_snapshot(user)

    # Build comprehensive student profile
    comprehensive_data = {
        # File metadata for LLM understanding
        "_file_description": f"Complete student profile, documentation preferences, uploaded documents summary, and {visa_type_label} journey status for {destination_country}",
        "_file_purpose": f"Use this data to provide personalized {destination_country} {visa_type_label} guidance based on the student's current status and documents",

        # Student Profile Information
        "student_profile": {
            "user_id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "username": user.username,
            "university": user.university,
            "university_email": getattr(user, 'university_email', None),
            "phone": user.phone,
            "visa_case_status": user.visa_case_status,
            "current_situation_story": user.current_situation_story,
            "current_residence_country": user.current_residence_country or "United States",
            "destination_country": destination_country,
            "destination_country_code": _scope_country,
            "visa_type": visa_type_label,
            "visa_type_key": _scope_visa,
            "profile_picture": user.profile_picture,
            "account_created": user.created_at.isoformat() if user.created_at else None,
            "email_verified": user.email_verified,
            "is_active": bool(user.is_active),
        },
        "user_account": user_account_snapshot,

        # Documentation Preferences
        "documentation_preferences": {
            "target_country": destination_country,
            "destination_country_code": _scope_country,
            "visa_type": visa_type_label,
            "current_residence_country": user.current_residence_country or "United States",
            "intake_semester": preferred_intake,
            "intake_year": preferred_year
        },

        # Subscription Details
        "subscription": subscription_snapshot,

        # Visa Journey Status (from existing calculation)
        "visa_journey": {
            "destination_country": destination_country,
            "visa_type": visa_type_label,
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
    except Exception:
        logger.exception("Failed to save student profile snapshot for user_id=%s", user.id)
        raise HTTPException(status_code=500, detail="Failed to refresh profile snapshot. Please try again.")


def refresh_student_profile_snapshot_for_user(
    user: models.User,
    db: Session,
) -> str:
    documents = db.query(models.Document).filter(
        models.Document.user_id == user.id
    ).all()
    status_data = calculate_visa_journey_stage(documents, db, *_user_visa_scope(user))
    return save_student_profile_to_r2(user, status_data, documents, db=db)


def refresh_student_profile_snapshot_for_user_id(user_id: int, db: Session) -> Optional[str]:
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        return None
    return refresh_student_profile_snapshot_for_user(user=user, db=db)


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
    documents = db.query(models.Document).filter(
        models.Document.user_id == current_user.id
    ).all()
    status_data = calculate_visa_journey_stage(documents, db, *_user_visa_scope(current_user))

    # First, try to get existing profile from R2
    existing_profile = get_student_profile_from_r2(current_user.id)
    
    if existing_profile and not is_student_profile_snapshot_stale(
        existing_profile,
        current_user,
        len(documents),
        db=db,
    ):
        # Profile exists in R2 - just return it (no write needed)
        # Merge with fresh stage data for UI display
        status_data["r2_key"] = f"user_{current_user.id}/STUDENT_PROFILE_AND_F1_VISA_STATUS.json"
        status_data["user_email"] = current_user.email
        status_data["user_name"] = current_user.full_name
        status_data["from_cache"] = True
        
        return JSONResponse(content=status_data)
    
    # Profile missing or stale - create/refresh R2 snapshot
    r2_key = save_student_profile_to_r2(current_user, status_data, documents, db=db)
    
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
    status_data = calculate_visa_journey_stage(documents, db, *_user_visa_scope(current_user))
    
    # Save comprehensive student profile to R2
    r2_key = save_student_profile_to_r2(current_user, status_data, documents, db=db)
    
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
        except Exception:
            logger.exception(
                "Failed to download legacy document document_id=%s user_id=%s",
                document_id,
                current_user.id,
            )
            raise HTTPException(status_code=500, detail="Failed to download document. Please try again.")
    
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
    except ValueError:
        # Decryption failed (wrong password or corrupted data)
        raise HTTPException(
            status_code=401,
            detail="Decryption failed. Please verify your password and try again."
        )
    except Exception:
        logger.exception(
            "Failed to decrypt/download document document_id=%s user_id=%s",
            document_id,
            current_user.id,
        )
        raise HTTPException(status_code=500, detail="Failed to download document. Please try again.")

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
    except Exception:
        logger.exception(
            "Failed to download extracted text document_id=%s user_id=%s",
            document_id,
            current_user.id,
        )
        raise HTTPException(status_code=500, detail="Failed to download extracted text. Please try again.")

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
    except Exception:
        logger.exception("Admin download failed for document_id=%s", document_id)
        raise HTTPException(status_code=500, detail="Failed to download document. Please try again.")

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
            status_data = calculate_visa_journey_stage(all_documents, db, *_user_visa_scope(current_user))
            save_student_profile_to_r2(current_user, status_data, all_documents, db=db)
        except Exception as refresh_error:
            # Don't fail the delete if profile refresh fails
            print(f"Warning: Failed to refresh student profile after delete: {str(refresh_error)}")
        
        return None
    except Exception:
        db.rollback()
        logger.exception("Failed to delete document document_id=%s user_id=%s", document_id, current_user.id)
        raise HTTPException(status_code=500, detail="Failed to delete document. Please try again.")

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
                status_data = calculate_visa_journey_stage(all_documents, db, *_user_visa_scope(document_owner))
                save_student_profile_to_r2(document_owner, status_data, all_documents, db=db)
        except Exception as refresh_error:
            # Don't fail the delete if profile refresh fails
            print(f"Warning: Failed to refresh student profile after admin delete: {str(refresh_error)}")
        
        return None
    except Exception:
        db.rollback()
        logger.exception("Admin failed to delete document document_id=%s", document_id)
        raise HTTPException(status_code=500, detail="Failed to delete document. Please try again.")
