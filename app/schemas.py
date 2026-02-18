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


class PublicUserResponse(BaseModel):
    id: int
    username: Optional[str] = None
    full_name: Optional[str] = None
    university: Optional[str] = None
    profile_picture: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SubscriptionResponse(BaseModel):
    plan: str
    status: str
    started_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    next_renewal_at: Optional[datetime] = None
    ai_messages_used: int
    ai_messages_limit: int
    ai_messages_remaining: int
    document_uploads_used: int
    document_uploads_limit: int
    document_uploads_remaining: int
    prep_sessions_used: int
    prep_sessions_limit: int
    prep_sessions_remaining: int
    mock_interviews_used: int
    mock_interviews_limit: int
    mock_interviews_remaining: int
    is_pro: bool
    access_source: Optional[str] = None
    referral_bonus_active: bool = False
    referral_bonus_granted_at: Optional[datetime] = None
    recurring_subscription_id: Optional[str] = None
    latest_payment_status: Optional[str] = None
    latest_payment_amount_paise: Optional[int] = None
    latest_payment_currency: Optional[str] = None
    latest_payment_verified_at: Optional[datetime] = None
    auto_renew_enabled: Optional[bool] = None
    recurring_subscription_status: Optional[str] = None


class RazorpayPaymentVerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class RazorpayRecurringPaymentVerifyRequest(BaseModel):
    razorpay_subscription_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class SubscriptionUpgradeRequest(BaseModel):
    coupon_code: Optional[str] = None


class SubscriptionSessionConsumeRequest(BaseModel):
    session_type: str  # prep | mock


class NotificationResponse(BaseModel):
    id: int
    title: str
    message: str
    notification_type: str
    source: Optional[str] = None
    is_read: bool
    created_at: datetime
    read_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    notifications: List[NotificationResponse]
    unread_count: int

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


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class EmailNotificationUnsubscribeRequest(BaseModel):
    token: str
    reason: Optional[str] = None


class EmailNotificationUnsubscribePreview(BaseModel):
    email: str
    subscribed: bool

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


class DocumentTypeCatalogItem(BaseModel):
    value: str
    label: str
    description: Optional[str] = None
    sort_order: int
    is_active: bool
    is_required: bool
    journey_stage: Optional[int] = None
    stage_gate_required: bool
    stage_gate_requires_validation: bool
    stage_gate_group: Optional[str] = None


class JourneyStageDefinition(BaseModel):
    stage: int
    name: str
    emoji: str
    description: str
    next_step: str
    required_docs: List[str]


class DocumentCatalogResponse(BaseModel):
    document_types: List[DocumentTypeCatalogItem]
    required_document_types: List[str]
    journey_stages: List[JourneyStageDefinition]
