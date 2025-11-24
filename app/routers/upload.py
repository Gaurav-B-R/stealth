from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import FileResponse
from app.auth import get_current_active_user
from app import models
from typing import List
import os
import uuid
from pathlib import Path

router = APIRouter(prefix="/api/upload", tags=["upload"])

# Create uploads directory if it doesn't exist
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads" / "images"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Allowed image extensions
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

def is_allowed_file(filename: str) -> bool:
    """Check if file extension is allowed"""
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS

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
    file_path = UPLOAD_DIR / unique_filename
    
    # Save file
    with open(file_path, "wb") as f:
        f.write(contents)
    
    # Return the URL path
    image_url = f"/uploads/images/{unique_filename}"
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
        file_path = UPLOAD_DIR / unique_filename
        
        # Save file
        with open(file_path, "wb") as f:
            f.write(contents)
        
        # Add to uploaded images
        image_url = f"/uploads/images/{unique_filename}"
        uploaded_images.append({"url": image_url, "filename": unique_filename})
    
    return {"images": uploaded_images, "count": len(uploaded_images)}

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

