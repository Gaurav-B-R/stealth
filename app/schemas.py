from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    username: Optional[str] = None  # Optional, will be auto-generated from email if not provided
    full_name: Optional[str] = None
    university: Optional[str] = None
    phone: Optional[str] = None
    profile_picture: Optional[str] = None

class UserCreate(UserBase):
    password: str
    cf_turnstile_token: Optional[str] = None  # Cloudflare Turnstile token

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    university: Optional[str] = None
    phone: Optional[str] = None
    profile_picture: Optional[str] = None

class UserResponse(UserBase):
    id: int
    is_active: bool
    email_verified: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class ItemImageResponse(BaseModel):
    id: int
    image_url: str
    order: int
    
    class Config:
        from_attributes = True

class ItemBase(BaseModel):
    title: str
    description: Optional[str] = None
    price: float
    category: Optional[str] = None
    condition: Optional[str] = None
    image_url: Optional[str] = None  # Deprecated: kept for backward compatibility
    image_urls: Optional[List[str]] = None  # For creating items with multiple images
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class ItemCreate(ItemBase):
    pass

class ItemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    category: Optional[str] = None
    condition: Optional[str] = None
    image_url: Optional[str] = None
    image_urls: Optional[List[str]] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_sold: Optional[bool] = None

class ItemResponse(ItemBase):
    id: int
    seller_id: int
    seller: UserResponse
    is_sold: bool
    images: List[ItemImageResponse] = []
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class MessageCreate(BaseModel):
    item_id: int
    receiver_id: int
    content: str

class MessageResponse(BaseModel):
    id: int
    item_id: int
    sender_id: int
    receiver_id: int
    content: str
    is_read: bool
    created_at: datetime
    sender: UserResponse
    receiver: UserResponse
    
    class Config:
        from_attributes = True

class ConversationResponse(BaseModel):
    other_user: UserResponse
    item: ItemResponse
    last_message: Optional[MessageResponse] = None
    unread_count: int = 0
    
    class Config:
        from_attributes = True

class UniversityInfo(BaseModel):
    university_name: Optional[str] = None
    email_domain: str
    is_valid: bool

class ResendVerificationRequest(BaseModel):
    email: str

class PasswordResetRequest(BaseModel):
    email: str

class PasswordReset(BaseModel):
    token: str
    new_password: str

class UniversityChangeRequest(BaseModel):
    new_email: str
    new_university: str

class UniversityChangeVerify(BaseModel):
    token: str

class DocumentationPreferences(BaseModel):
    country: Optional[str] = "United States"
    intake: Optional[str] = None  # Spring or Fall
    year: Optional[int] = None

class DocumentCreate(BaseModel):
    document_type: Optional[str] = None
    country: Optional[str] = None
    intake: Optional[str] = None
    year: Optional[int] = None
    description: Optional[str] = None
    password: str  # User's password for Zero-Knowledge encryption

class DocumentResponse(BaseModel):
    id: int
    user_id: int
    filename: str
    original_filename: str
    file_url: str
    file_size: int
    file_type: Optional[str] = None
    document_type: Optional[str] = None
    country: Optional[str] = None
    intake: Optional[str] = None
    year: Optional[int] = None
    description: Optional[str] = None
    is_processed: bool
    extracted_text_file_url: Optional[str] = None
    is_valid: Optional[bool] = None
    validation_message: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    uploader: UserResponse
    
    class Config:
        from_attributes = True

class DocumentValidationResponse(BaseModel):
    is_valid: bool
    message: Optional[str] = None
    details: Optional[dict] = None

class DocumentUploadResponse(BaseModel):
    document: DocumentResponse
    validation: DocumentValidationResponse

class DocumentListResponse(BaseModel):
    documents: List[DocumentResponse]
    total: int
    page: int
    page_size: int

