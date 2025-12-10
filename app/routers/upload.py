from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import FileResponse
from app.auth import get_current_active_user
from app import models
from typing import List
import os
import uuid
from pathlib import Path
import boto3
from botocore.config import Config

router = APIRouter(prefix="/api/upload", tags=["upload"])

# R2 Configuration from environment variables
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "1dfccbb465ae188db13dc9f92cc60b3b")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "images")
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL", f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "")  # Set this to your public URL (custom domain or pub-xxxxx.r2.dev)

# Initialize R2 client (required)
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

if not R2_PUBLIC_URL:
    raise ValueError("R2_PUBLIC_URL must be set in environment variables for image URLs to work")

# Allowed image extensions
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

def is_allowed_file(filename: str) -> bool:
    """Check if file extension is allowed"""
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS

def upload_to_r2(file_contents: bytes, filename: str) -> str:
    """Upload file to R2 and return public URL"""
    try:
        r2_client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=filename,
            Body=file_contents,
            ContentType='image/jpeg' if filename.endswith(('.jpg', '.jpeg')) else 
                       'image/png' if filename.endswith('.png') else
                       'image/gif' if filename.endswith('.gif') else
                       'image/webp' if filename.endswith('.webp') else
                       'application/octet-stream'
        )
        
        # Return public URL
        if R2_PUBLIC_URL:
            # Custom domain or public development URL
            return f"{R2_PUBLIC_URL.rstrip('/')}/{filename}"
        else:
            # Fallback to endpoint URL (may require authentication)
            return f"{R2_ENDPOINT_URL}/{R2_BUCKET_NAME}/{filename}"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload to R2: {str(e)}")

@router.post("/image")
async def upload_image(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_active_user)
):
    """Upload a single image file"""
    # Validate file extension
    if not is_allowed_file(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    # Read file content
    contents = await file.read()
    
    # Validate file size
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE / 1024 / 1024}MB"
        )
    
    # Generate unique filename
    file_extension = Path(file.filename).suffix.lower()
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    
    # Upload to R2 (required)
    image_url = upload_to_r2(contents, unique_filename)
    
    return {"url": image_url, "filename": unique_filename}

@router.post("/images")
async def upload_images(
    files: List[UploadFile] = File(...),
    current_user: models.User = Depends(get_current_active_user)
):
    """Upload multiple image files"""
    if len(files) > 10:  # Limit to 10 images per item
        raise HTTPException(
            status_code=400,
            detail="Maximum 10 images allowed per item"
        )
    
    uploaded_images = []
    
    for file in files:
        # Validate file extension
        if not is_allowed_file(file.filename):
            continue  # Skip invalid files
        
        # Read file content
        contents = await file.read()
        
        # Validate file size
        if len(contents) > MAX_FILE_SIZE:
            continue  # Skip files that are too large
        
        # Generate unique filename
        file_extension = Path(file.filename).suffix.lower()
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        
        # Upload to R2 (required)
        image_url = upload_to_r2(contents, unique_filename)
        
        uploaded_images.append({"url": image_url, "filename": unique_filename})
    
    return {"images": uploaded_images, "count": len(uploaded_images)}

@router.post("/profile-picture")
async def upload_profile_picture(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_active_user)
):
    """Upload a profile picture"""
    # Validate file extension
    if not is_allowed_file(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    # Read file content
    contents = await file.read()
    
    # Validate file size (smaller for profile pictures - 2MB)
    max_profile_size = 2 * 1024 * 1024  # 2MB
    if len(contents) > max_profile_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {max_profile_size / 1024 / 1024}MB"
        )
    
    # Generate unique filename
    file_extension = Path(file.filename).suffix.lower()
    unique_filename = f"profile_{current_user.id}_{uuid.uuid4()}{file_extension}"
    
    # Upload to R2 (required)
    image_url = upload_to_r2(contents, unique_filename)
    
    return {"url": image_url, "filename": unique_filename}

@router.get("/images/{filename}")
async def get_image(filename: str):
    """Serve uploaded images"""
    # Security check: prevent directory traversal
    # Remove any path components from filename
    safe_filename = Path(filename).name
    
    file_path = UPLOAD_DIR / safe_filename
    
    # Additional security: ensure resolved path is within upload directory
    try:
        file_path = file_path.resolve()
        if not str(file_path).startswith(str(UPLOAD_DIR.resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
    except (ValueError, OSError):
        raise HTTPException(status_code=403, detail="Invalid file path")
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    
    return FileResponse(file_path)

