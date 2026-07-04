from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    username: Optional[str] = None  # Optional, will be auto-generated from email if not provided
    full_name: Optional[str] = None
    university: Optional[str] = None
    phone: Optional[str] = None
    visa_case_status: Optional[str] = None
    current_situation_story: Optional[str] = None
    current_residence_country: Optional[str] = "United States"
    preferred_country: Optional[str] = "United States"
    profile_picture: Optional[str] = None

class UserCreate(UserBase):
    password: str
    cf_turnstile_token: Optional[str] = None  # Cloudflare Turnstile token
    referral_code: Optional[str] = None
    accepted_terms_privacy: bool = False
    age_confirmed: bool = False  # 18+ self-attestation (or parent/guardian agreeing)
    marketing_emails_consent: bool = False  # optional opt-in for marketing emails
    # First-touch acquisition signals captured on the landing page (see static/attribution.js).
    acq_source: Optional[str] = None
    acq_medium: Optional[str] = None
    acq_campaign: Optional[str] = None
    acq_referrer: Optional[str] = None
    acq_landing: Optional[str] = None

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    university: Optional[str] = None
    phone: Optional[str] = None
    visa_case_status: Optional[str] = None
    current_situation_story: Optional[str] = None
    current_residence_country: Optional[str] = None
    profile_picture: Optional[str] = None

class UserResponse(UserBase):
    id: int
    is_active: bool
    email_verified: bool
    is_admin: Optional[bool] = False
    is_developer: Optional[bool] = False
    referral_code: Optional[str] = None
    accepted_terms_privacy_at: Optional[datetime] = None
    email_notifications_enabled: bool = True
    marketing_emails_consent: bool = False
    # Personalized student journey (multi-country onboarding).
    destination_country_code: Optional[str] = None
    visa_type_key: Optional[str] = None
    university_email: Optional[str] = None
    onboarding_completed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class OnboardingRequest(BaseModel):
    destination_country_code: str
    visa_type_key: str
    home_country: Optional[str] = None
    university: Optional[str] = None
    university_email: Optional[str] = None
    intake: Optional[str] = None


class PublicUserResponse(BaseModel):
    id: int
    username: Optional[str] = None
    full_name: Optional[str] = None
    university: Optional[str] = None
    profile_picture: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AdminUserSummary(BaseModel):
    id: int
    email: EmailStr
    username: Optional[str] = None
    full_name: Optional[str] = None
    university: Optional[str] = None
    is_active: bool
    email_verified: bool
    is_admin: Optional[bool] = False
    is_developer: Optional[bool] = False
    referral_code: Optional[str] = None
    referred_by_user_id: Optional[int] = None
    # Destination country + visa type the student is applying for (multi-country journey).
    destination_country_code: Optional[str] = None
    visa_type_key: Optional[str] = None
    # First-touch acquisition (where they came from).
    acquisition_channel: Optional[str] = None
    acquisition_source: Optional[str] = None
    created_at: datetime
    first_login_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AdminUserListMetrics(BaseModel):
    visa_pass_users: int = 0
    free_users: int = 0


class AdminEnterpriseAccountSummary(BaseModel):
    organization_id: int
    company_name: str
    subdomain_slug: Optional[str] = None
    portal_url: Optional[str] = None
    created_at: datetime
    created_by_user_id: Optional[int] = None
    created_by_email: Optional[str] = None
    created_by_name: Optional[str] = None
    total_members: int = 0
    active_members: int = 0
    active_admins: int = 0


class AdminEnterpriseAccountListMetrics(BaseModel):
    active_members: int = 0
    active_admins: int = 0


class AdminTurnstileVerifyRequest(BaseModel):
    token: str


class AdminUserListResponse(BaseModel):
    users: List[AdminUserSummary]
    total: int
    page: int
    page_size: int
    metrics: AdminUserListMetrics


class AdminUserStatusUpdateRequest(BaseModel):
    is_active: bool


class AdminEnterpriseAccountListResponse(BaseModel):
    accounts: List[AdminEnterpriseAccountSummary]
    total: int
    page: int
    page_size: int
    metrics: AdminEnterpriseAccountListMetrics


class AdminEnterpriseCredentialCreateRequest(BaseModel):
    email: EmailStr
    full_name: str


class AdminEnterpriseCredentialCreateResponse(BaseModel):
    email: EmailStr
    full_name: str
    temporary_password: Optional[str] = None
    uses_existing_main_password: bool = False
    credential_created: bool = False
    user_created: bool = False
    message: str


class AdminEnterpriseCouponCreateRequest(BaseModel):
    code: str
    percent_off: float
    applies_to: str = "all"  # all | credits | billing
    max_redemptions: Optional[int] = None
    note: Optional[str] = None
    is_active: bool = True


class AdminEnterpriseCouponUpdateRequest(BaseModel):
    percent_off: Optional[float] = None
    applies_to: Optional[str] = None
    max_redemptions: Optional[int] = None
    note: Optional[str] = None
    is_active: Optional[bool] = None


class AdminEnterpriseCouponSendEmailRequest(BaseModel):
    # Optional single-recipient override. When omitted, the promo is sent to
    # every active member of the account.
    email: Optional[EmailStr] = None


class AdminEnterpriseRefundRequest(BaseModel):
    kind: str  # credits | money
    reason: Optional[str] = None
    # credit / goodwill refund
    credits: Optional[int] = None
    # money refund (Razorpay)
    payment_id: Optional[int] = None
    amount_rupees: Optional[float] = None   # rupees the admin wants refunded
    clawback_credits: Optional[int] = None  # credits to deduct from the wallet (default suggested)


class AdminCompanyFinanceSummary(BaseModel):
    total_invested_usd: float = 0
    total_returns_usd: float = 0
    net_usd: float = 0
    roi_percent: float = 0
    break_even_gap_usd: float = 0
    investment_entry_count: int = 0
    return_entry_count: int = 0


class AdminCompanyFinanceSeriesPoint(BaseModel):
    month: str
    investment_usd: float = 0
    returns_usd: float = 0
    net_usd: float = 0


class AdminCompanyFinanceBreakdownItem(BaseModel):
    label: str
    amount_usd: float = 0
    percentage: float = 0


class AdminCompanyFinanceLedgerItem(BaseModel):
    id: str
    kind: str
    category: str
    vendor: str
    paid_by: Optional[str] = None
    description: Optional[str] = None
    amount_usd: float
    occurred_on: str
    source: str


class AdminCompanyFinanceAnalyticsResponse(BaseModel):
    summary: AdminCompanyFinanceSummary
    monthly_series: List[AdminCompanyFinanceSeriesPoint]
    expense_breakdown: List[AdminCompanyFinanceBreakdownItem]
    contributor_breakdown: List[AdminCompanyFinanceBreakdownItem]
    ledger: List[AdminCompanyFinanceLedgerItem]
    notes: List[str] = []


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
    rilono_ai_chat_uploads_used: int
    rilono_ai_chat_uploads_limit: int
    rilono_ai_chat_uploads_remaining: int
    rilono_ai_chat_upload_window_hours: int
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
    email_notifications_enabled: bool = True


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
    pricing_model: Optional[str] = None


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


class OtpVerifyRequest(BaseModel):
    email: EmailStr
    code: str


class OtpResendRequest(BaseModel):
    email: EmailStr


class AccountDeleteRequest(BaseModel):
    code: str


class CountryChangeRequest(BaseModel):
    destination_country_code: str
    visa_type_key: Optional[str] = None


class CountryChangeConfirm(BaseModel):
    code: str


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
    cf_turnstile_token: Optional[str] = None

class PasswordReset(BaseModel):
    token: str
    new_password: str
    cf_turnstile_token: Optional[str] = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class EmailNotificationUnsubscribeRequest(BaseModel):
    token: str
    reason: Optional[str] = None


class EmailNotificationUnsubscribePreview(BaseModel):
    email: str
    subscribed: bool


class MarketingEmailPreferenceRequest(BaseModel):
    enabled: bool


class MarketingEmailPreferenceResponse(BaseModel):
    marketing_emails_consent: bool
    marketing_emails_consent_at: Optional[datetime] = None

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
    e2e_scheme: Optional[str] = None  # non-null => client-side E2E encrypted (download via /{id}/blob)
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
