from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    username: Optional[str] = None  # Optional, will be auto-generated from email if not provided
    full_name: Optional[str] = None
    university: Optional[str] = None
    phone: Optional[str] = None
    current_residence_country: Optional[str] = "United States"
    preferred_country: Optional[str] = "United States"
    profile_picture: Optional[str] = None

class UserCreate(UserBase):
    password: str
    cf_turnstile_token: Optional[str] = None  # Cloudflare Turnstile token
    referral_code: Optional[str] = None
    accepted_terms_privacy: bool = False

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    university: Optional[str] = None
    phone: Optional[str] = None
    current_residence_country: Optional[str] = None
    profile_picture: Optional[str] = None

class UserResponse(UserBase):
    id: int
    is_active: bool
    email_verified: bool
    referral_code: Optional[str] = None
    accepted_terms_privacy_at: Optional[datetime] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class SubscriptionResponse(BaseModel):
    plan: str
    status: str
    ai_messages_used: int
    ai_messages_limit: int
    ai_messages_remaining: int
    document_uploads_used: int
    document_uploads_limit: int
    document_uploads_remaining: int
    is_pro: bool

class Token(BaseModel):
    access_token: str
    token_type: str
    referral_bonus_awarded: Optional[bool] = None
    referral_bonus_message: Optional[str] = None

class TokenData(BaseModel):
    username: Optional[str] = None

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
