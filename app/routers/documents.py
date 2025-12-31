from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query, Form
from fastapi.responses import StreamingResponse
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
    except Exception as e:
        # Log error but don't fail the upload if Gemini processing fails
        print(f"Warning: Failed to process document with Gemini: {str(e)}")
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
        encrypted_file_key=base64.b64encode(encrypted_file_key).decode('utf-8')  # Store encrypted key
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

