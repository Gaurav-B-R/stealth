from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, Text, Boolean, Numeric, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=True)  # Made nullable, will use email as username
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    university = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    visa_case_status = Column(String, nullable=True)  # new | refused
    current_situation_story = Column(Text, nullable=True)
    current_residence_country = Column(String, nullable=True, default="United States")
    profile_picture = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    email_verified = Column(Boolean, default=False)
    verification_token = Column(String, nullable=True, unique=True, index=True)  # Stores hashed token
    verification_token_expires = Column(DateTime(timezone=True), nullable=True)
    password_reset_token = Column(String, nullable=True, unique=True, index=True)  # Stores hashed token
    password_reset_token_expires = Column(DateTime(timezone=True), nullable=True)
    # Pending university change fields
    pending_email = Column(String, nullable=True)  # New email for university change
    pending_university = Column(String, nullable=True)  # New university name
    university_change_token = Column(String, nullable=True, unique=True, index=True)  # Stores hashed token
    university_change_token_expires = Column(DateTime(timezone=True), nullable=True)
    is_admin = Column(Boolean, default=False)  # Admin/Developer access
    is_developer = Column(Boolean, default=False)  # Developer team access
    auth_provider = Column(String, nullable=True)  # password | google | microsoft | apple
    # Personalized student journey (multi-country). Existing users are backfilled to
    # US/us_f1 with onboarding marked complete; new users leave these NULL until they
    # finish the post-signup onboarding (destination country + visa type are required).
    destination_country_code = Column(String, nullable=True)  # US | UK | CA | AU
    visa_type_key = Column(String, nullable=True)             # us_f1 | uk_student | ...
    university_email = Column(String, nullable=True)
    onboarding_completed_at = Column(DateTime(timezone=True), nullable=True)
    # On logout (or forced sign-out) this is set to "now"; any access token issued at
    # or before this instant is rejected, so logout truly ends the session server-side
    # even if a token copy survives in the browser (stateless JWTs are otherwise valid
    # until expiry).
    session_invalidated_at = Column(DateTime(timezone=True), nullable=True)
    encryption_salt = Column(String, nullable=True)  # Salt for Zero-Knowledge encryption (base64 encoded)
    # Documentation preferences
    preferred_country = Column(String, nullable=True, default="United States")
    preferred_intake = Column(String, nullable=True)  # Spring or Fall
    preferred_year = Column(Integer, nullable=True)
    referral_code = Column(String, unique=True, index=True, nullable=True)
    referred_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    first_login_at = Column(DateTime(timezone=True), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    referral_reward_granted_at = Column(DateTime(timezone=True), nullable=True)
    accepted_terms_privacy_at = Column(DateTime(timezone=True), nullable=True)
    # Proof-of-consent captured when the user accepts the Terms & Conditions and
    # Privacy Policy (IP, browser user-agent, and the version of the legal docs).
    accepted_terms_privacy_ip = Column(String, nullable=True)
    accepted_terms_privacy_user_agent = Column(Text, nullable=True)
    accepted_terms_privacy_version = Column(String, nullable=True)
    email_notifications_enabled = Column(Boolean, nullable=False, default=True)
    email_notifications_unsubscribed_at = Column(DateTime(timezone=True), nullable=True)
    email_notifications_unsubscribe_reason = Column(Text, nullable=True)
    # Explicit opt-in consent for marketing emails (product tips, offers, newsletters),
    # captured at signup. Distinct from email_notifications_enabled, which governs
    # transactional/visa notifications. Users can opt out anytime; the timestamp
    # records when consent was last given or withdrawn (proof of consent).
    marketing_emails_consent = Column(Boolean, nullable=False, default=False)
    marketing_emails_consent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    documents = relationship("Document", back_populates="uploader", cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="user", uselist=False, cascade="all, delete-orphan")
    subscription_payments = relationship("SubscriptionPayment", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("UserNotification", back_populates="user", cascade="all, delete-orphan")

class USUniversity(Base):
    __tablename__ = "us_universities"
    
    # Use email_domain as primary key since the table doesn't have an id column
    email_domain = Column(String, primary_key=True, nullable=False, index=True)
    university_name = Column(String, nullable=False, index=True)
    location = Column(String, nullable=True)

class DeveloperEmail(Base):
    __tablename__ = "developer_emails"
    
    email = Column(String, primary_key=True, nullable=False, index=True)
    university_name = Column(String, nullable=False, default="Developer Account")


class EnterpriseCredential(Base):
    __tablename__ = "enterprise_credentials"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=True, default="Enterprise Admin")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class EnterpriseOrganization(Base):
    __tablename__ = "enterprise_organizations"

    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String, nullable=False, index=True)
    subdomain_slug = Column(String, unique=True, index=True, nullable=True)
    logo_url = Column(String, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class EnterpriseOrganizationMember(Base):
    __tablename__ = "enterprise_organization_members"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String, nullable=False, default="viewer")  # admin | editor | viewer
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    invited_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_ent_org_member_org_user_unique", "organization_id", "user_id", unique=True),
    )


class EnterpriseStudent(Base):
    __tablename__ = "enterprise_students"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    student_name = Column(String, nullable=False)
    study_country_code = Column(String, nullable=False)
    study_country_name = Column(String, nullable=False)
    visa_type = Column(String, nullable=False)
    intake = Column(String, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_ent_students_org_created", "organization_id", "created_at"),
    )


class EnterpriseClient(Base):
    """A visa client/applicant managed by an enterprise organization (any visa category)."""
    __tablename__ = "enterprise_clients"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)

    # Identity & contact
    full_name = Column(String, nullable=False)
    email = Column(String, nullable=True, index=True)
    phone = Column(String, nullable=True)
    nationality = Column(String, nullable=True)
    date_of_birth = Column(Date, nullable=True)
    passport_number = Column(String, nullable=True)
    passport_expiry = Column(Date, nullable=True)

    # Visa case
    visa_category = Column(String, nullable=False, default="student")  # student|tourist|work|immigration
    destination_country_code = Column(String, nullable=False)
    destination_country_name = Column(String, nullable=False)
    visa_type = Column(String, nullable=False)
    intake = Column(String, nullable=True)
    application_reference = Column(String, nullable=True)

    # Pipeline
    status = Column(String, nullable=False, default="new_lead", index=True)
    priority = Column(String, nullable=False, default="normal")
    target_date = Column(Date, nullable=True)  # interview / travel / intake deadline

    # Assignment & meta
    assigned_to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    notes = relationship(
        "EnterpriseClientNote",
        back_populates="client",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    emails = relationship(
        "EnterpriseClientEmail",
        back_populates="client",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    documents = relationship(
        "EnterpriseClientDocument",
        back_populates="client",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    interview_sessions = relationship(
        "EnterpriseInterviewSession",
        back_populates="client",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    interview_invites = relationship(
        "EnterpriseInterviewInvite",
        back_populates="client",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_ent_clients_org_status", "organization_id", "status"),
        Index("ix_ent_clients_org_created", "organization_id", "created_at"),
    )


class EnterpriseClientNote(Base):
    """A free-text note on a client's timeline."""
    __tablename__ = "enterprise_client_notes"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("enterprise_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    author_name = Column(String, nullable=True)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    client = relationship("EnterpriseClient", back_populates="notes")


class EnterpriseClientEmail(Base):
    """Log of an email sent to a client from the dashboard."""
    __tablename__ = "enterprise_client_emails"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("enterprise_clients.id", ondelete="CASCADE"), nullable=True, index=True)
    sent_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    sent_by_name = Column(String, nullable=True)
    to_email = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="sent")  # sent|failed
    provider_message_id = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    client = relationship("EnterpriseClient", back_populates="emails")


class EnterpriseClientDocument(Base):
    """A document uploaded for a client (passport, I-20, financials, etc.)."""
    __tablename__ = "enterprise_client_documents"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("enterprise_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    document_type = Column(String, nullable=False, default="Other")
    original_filename = Column(String, nullable=False)
    storage_key = Column(String, nullable=False)  # private R2 object key (not a public URL)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String, nullable=True)
    extracted_text = Column(Text, nullable=True)  # AI-extracted text contents (for the copilot)
    uploaded_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    uploaded_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    client = relationship("EnterpriseClient", back_populates="documents")


class EnterpriseInterviewSession(Base):
    """A completed AI mock visa interview for a client (transcript + feedback)."""
    __tablename__ = "enterprise_interview_sessions"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("enterprise_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    conducted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    conducted_by_name = Column(String, nullable=True)
    mode = Column(String, nullable=False, default="chat")  # chat | voice
    transcript = Column(Text, nullable=True)  # JSON list of {role, content}
    feedback = Column(Text, nullable=True)
    verdict = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    client = relationship("EnterpriseClient", back_populates="interview_sessions")


class EnterpriseInterviewInvite(Base):
    """A secure email invite letting a client take N self-serve mock interviews via a link."""
    __tablename__ = "enterprise_interview_invites"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("enterprise_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)  # hashed capability token
    email = Column(String, nullable=False)  # client email the link was sent to
    allowed_count = Column(Integer, nullable=False, default=1)
    used_count = Column(Integer, nullable=False, default=0)
    # One-time email verification (OTP)
    code_hash = Column(String, nullable=True)
    code_expires_at = Column(DateTime(timezone=True), nullable=True)
    code_attempts = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked = Column(Boolean, nullable=False, default=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    client = relationship("EnterpriseClient", back_populates="interview_invites")


class EnterpriseDocumentRequest(Base):
    """A secure email request asking a client to upload specific documents via a link.

    Mirrors the interview-invite security model: a high-entropy capability token
    (stored hashed) plus a one-time email code (OTP) the client must confirm
    before they can upload. Each requested document type is tracked as a child
    item so staff can see exactly what's been received and what's still pending."""
    __tablename__ = "enterprise_document_requests"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("enterprise_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)  # hashed capability token
    email = Column(String, nullable=False)  # client email the link was sent to
    message = Column(Text, nullable=True)  # optional note from staff shown to the client
    status = Column(String, nullable=False, default="pending")  # pending | partial | completed
    # One-time email verification (OTP) — same scheme as EnterpriseInterviewInvite.
    code_hash = Column(String, nullable=True)
    code_expires_at = Column(DateTime(timezone=True), nullable=True)
    code_attempts = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked = Column(Boolean, nullable=False, default=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    client = relationship("EnterpriseClient")
    items = relationship(
        "EnterpriseDocumentRequestItem",
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="EnterpriseDocumentRequestItem.id",
    )


class EnterpriseDocumentRequestItem(Base):
    """One requested document type within a document request, with its fulfillment state."""
    __tablename__ = "enterprise_document_request_items"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("enterprise_document_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    document_type = Column(String, nullable=False, default="Other")
    status = Column(String, nullable=False, default="pending")  # pending | received
    document_id = Column(Integer, ForeignKey("enterprise_client_documents.id", ondelete="SET NULL"), nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    request = relationship("EnterpriseDocumentRequest", back_populates="items")


class EnterpriseCalendarEvent(Base):
    """A staff-created calendar event / reminder / task for the org's timeline.

    The calendar also surfaces auto-derived deadlines from client data (target dates,
    passport expiries); those are computed on the fly and not stored here. This table
    only holds the manual events staff add ("call Rohan", "VFS appointment", etc.)."""
    __tablename__ = "enterprise_calendar_events"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("enterprise_clients.id", ondelete="CASCADE"), nullable=True, index=True)
    title = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    event_type = Column(String, nullable=False, default="reminder")  # reminder|task|follow_up|appointment|deadline|other
    event_date = Column(Date, nullable=False, index=True)
    event_time = Column(String, nullable=True)  # "HH:MM" (24h), optional
    is_done = Column(Boolean, nullable=False, default=False, index=True)
    # When a client is @-mentioned in the title, optionally email that client when the
    # reminder is due. notify_client gates it; client_notified_at dedups so an overdue
    # reminder doesn't email the client every day.
    notify_client = Column(Boolean, nullable=False, default=False)
    client_notified_at = Column(DateTime(timezone=True), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_ent_calendar_org_date", "organization_id", "event_date"),
    )


class EnterpriseCalendarReminderRun(Base):
    """Idempotency guard for the daily enterprise calendar-reminder email job
    (one run per UTC day), mirroring AIDailyNotificationRun."""
    __tablename__ = "enterprise_calendar_reminder_runs"

    id = Column(Integer, primary_key=True, index=True)
    run_date = Column(Date, nullable=False, unique=True, index=True)
    status = Column(String, nullable=False, default="running")  # running | completed | failed
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    recipients_emailed = Column(Integer, nullable=False, default=0)
    events_considered = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)


class EnterpriseSupportRequest(Base):
    """A help request or feature request submitted by an enterprise staff member."""
    __tablename__ = "enterprise_support_requests"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    requester_name = Column(String, nullable=True)
    requester_email = Column(String, nullable=True)
    request_type = Column(String, nullable=False, default="support", index=True)  # support | feature_request
    subject = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="open")  # open | in_progress | closed
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_ent_support_org_created", "organization_id", "created_at"),
    )


class EnterpriseSubscription(Base):
    """Per-organization SaaS subscription (the consultancy's own plan)."""
    __tablename__ = "enterprise_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, unique=True, index=True)
    plan = Column(String, nullable=False, default="trial")  # trial|starter|growth|scale
    status = Column(String, nullable=False, default="trialing")  # trialing|active|past_due|canceled
    trial_ends_at = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    razorpay_subscription_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class EnterpriseSubscriptionPayment(Base):
    """Payment/checkout record for an organization subscription."""
    __tablename__ = "enterprise_subscription_payments"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    provider = Column(String, nullable=False, default="razorpay")
    plan = Column(String, nullable=False, default="starter")
    billing_cycle = Column(String, nullable=False, default="monthly")  # monthly|yearly
    amount_paise = Column(Integer, nullable=False)
    currency = Column(String, nullable=False, default="INR")
    razorpay_order_id = Column(String, nullable=False, unique=True, index=True)
    razorpay_payment_id = Column(String, nullable=True, unique=True, index=True)
    razorpay_subscription_id = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default="created")  # created|verified|failed
    # Per-account discount applied at checkout (admin-managed; see EnterpriseCoupon).
    coupon_code = Column(String, nullable=True, index=True)
    coupon_percent_off = Column(Numeric(5, 2), nullable=True)
    original_amount_paise = Column(Integer, nullable=True)  # pre-discount amount
    verified_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class EnterpriseCreditWallet(Base):
    """Prepaid 'Rilono Credits' wallet for an organization (the B2B revenue model).

    Agencies top up via Razorpay and spend credits on premium Gemini features
    (Deep Scan document audits, AI mock interviews). 1 credit = ₹10 (see
    app/enterprise_credits.py). The core CRM is free up to a student limit; beyond
    it a flat monthly infrastructure fee applies (tracked via infra_fee_paid_until).
    """
    __tablename__ = "enterprise_credit_wallets"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, unique=True, index=True)
    balance_credits = Column(Integer, nullable=False, default=0)
    lifetime_purchased_credits = Column(Integer, nullable=False, default=0)
    lifetime_spent_credits = Column(Integer, nullable=False, default=0)
    infra_fee_paid_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class EnterpriseCreditTransaction(Base):
    """One entry in an organization's credit ledger (top-up, debit, bonus, adjustment)."""
    __tablename__ = "enterprise_credit_transactions"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    type = Column(String, nullable=False, index=True)  # topup | debit | bonus | adjustment
    action_key = Column(String, nullable=True, index=True)  # deep_scan | mock_interview (for debits)
    credits = Column(Integer, nullable=False)  # signed: + for topup/bonus, - for debit
    balance_after = Column(Integer, nullable=False, default=0)
    description = Column(String, nullable=True)
    reference_type = Column(String, nullable=True)  # interview_session | client | payment
    reference_id = Column(Integer, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        Index("ix_ent_credit_txn_org_created", "organization_id", "created_at"),
    )


class EnterpriseCreditPayment(Base):
    """A Razorpay charge in the credit system: a credit-package top-up or the
    monthly infrastructure server fee."""
    __tablename__ = "enterprise_credit_payments"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    provider = Column(String, nullable=False, default="razorpay")
    kind = Column(String, nullable=False, default="credits", index=True)  # credits | infra_fee
    package_key = Column(String, nullable=True)  # starter | pro | enterprise | infra
    credits = Column(Integer, nullable=False, default=0)        # base credits in the package
    bonus_credits = Column(Integer, nullable=False, default=0)  # promotional bonus credits
    amount_paise = Column(Integer, nullable=False)
    currency = Column(String, nullable=False, default="INR")
    razorpay_order_id = Column(String, nullable=False, unique=True, index=True)
    razorpay_payment_id = Column(String, nullable=True, unique=True, index=True)
    status = Column(String, nullable=False, default="created")  # created | verified | failed
    # Per-account discount applied at checkout (admin-managed; see EnterpriseCoupon).
    coupon_code = Column(String, nullable=True, index=True)
    coupon_percent_off = Column(Numeric(5, 2), nullable=True)
    original_amount_paise = Column(Integer, nullable=True)  # pre-discount amount
    verified_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class EnterpriseCoupon(Base):
    """Admin-managed discount code scoped to a single enterprise organization.

    Created from the Admin Console (per account) and redeemed by that org's
    admins at checkout (Rilono Credits top-ups and/or the enterprise plan
    billing). Redemptions are counted live from verified payment rows that
    carry this code, so there is no mutable counter to keep in sync.
    """
    __tablename__ = "enterprise_coupons"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    code = Column(String, nullable=False, index=True)  # stored normalized (uppercase)
    percent_off = Column(Numeric(5, 2), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    applies_to = Column(String, nullable=False, default="all")  # all | credits | billing
    max_redemptions = Column(Integer, nullable=True)  # total cap across the org (null = unlimited)
    note = Column(String, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("uq_enterprise_coupon_org_code", "organization_id", "code", unique=True),
    )


class CompanyFinanceEntry(Base):
    __tablename__ = "company_finance_entries"

    id = Column(Integer, primary_key=True, index=True)
    seed_key = Column(String, unique=True, index=True, nullable=True)
    entry_type = Column(String, nullable=False, default="expense")  # expense | return
    category = Column(String, nullable=False, index=True)
    vendor = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    amount_usd = Column(Numeric(12, 2), nullable=False)
    occurred_on = Column(Date, nullable=False, index=True)
    paid_by = Column(String, nullable=False, default="Gaurav", index=True)
    source = Column(String, nullable=False, default="manual")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Document(Base):
    __tablename__ = "documents"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    file_url = Column(String, nullable=False)  # R2 URL
    file_size = Column(Integer, nullable=False)  # Size in bytes
    file_type = Column(String, nullable=True)  # MIME type
    document_type = Column(String, nullable=True)  # e.g., "passport", "visa", "transcript", etc.
    country = Column(String, nullable=True)  # Country for documentation
    intake = Column(String, nullable=True)  # Spring or Fall
    year = Column(Integer, nullable=True)  # Year
    description = Column(Text, nullable=True)  # Optional description
    is_processed = Column(Boolean, default=False)  # Whether AI has processed it
    extracted_text_file_url = Column(String, nullable=True)  # R2 URL for Gemini-extracted text file
    encrypted_file_key = Column(Text, nullable=True)  # File encryption key encrypted with user password (base64)
    is_valid = Column(Boolean, nullable=True)  # Whether document validation passed (from Gemini)
    validation_message = Column(Text, nullable=True)  # Validation message from Gemini (e.g., "Document validated successfully" or error message)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    uploader = relationship("User", back_populates="documents")


class DocumentTypeCatalog(Base):
    __tablename__ = "document_type_catalog"

    id = Column(Integer, primary_key=True, index=True)
    # Scoped per (country, visa type): the SAME document_type (e.g. "passport") can
    # exist for multiple destinations with different stages/gating. Uniqueness is the
    # composite (country_code, visa_type_key, document_type) — see __table_args__.
    document_type = Column(String, index=True, nullable=False)
    country_code = Column(String, nullable=False, default="US", server_default="US", index=True)
    visa_type_key = Column(String, nullable=False, default="us_f1", server_default="us_f1", index=True)
    label = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    is_required = Column(Boolean, nullable=False, default=False)
    journey_stage = Column(Integer, nullable=True)
    stage_gate_required = Column(Boolean, nullable=False, default=False)
    stage_gate_requires_validation = Column(Boolean, nullable=False, default=False)
    stage_gate_group = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("country_code", "visa_type_key", "document_type", name="uq_doc_catalog_scope"),
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    plan = Column(String, nullable=False, default="free")  # free | pro
    status = Column(String, nullable=False, default="active")  # active | canceled
    ai_messages_used = Column(Integer, nullable=False, default=0)
    document_uploads_used = Column(Integer, nullable=False, default=0)
    prep_sessions_used = Column(Integer, nullable=False, default=0)
    mock_interviews_used = Column(Integer, nullable=False, default=0)
    # Visa Success Pass (B2C one-time pass) freemium counters.
    ds160_autofills_used = Column(Integer, nullable=False, default=0)
    red_flag_scans_used = Column(Integer, nullable=False, default=0)
    pass_voice_interviews_used = Column(Integer, nullable=False, default=0)
    university_recommendations_used = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ends_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="subscription")


class SubscriptionPayment(Base):
    __tablename__ = "subscription_payments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String, nullable=False, default="razorpay")  # razorpay
    plan = Column(String, nullable=False, default="pro")  # pro
    amount_paise = Column(Integer, nullable=False)
    currency = Column(String, nullable=False, default="INR")
    razorpay_plan_id = Column(String, nullable=True, index=True)
    razorpay_order_id = Column(String, nullable=False, unique=True, index=True)
    razorpay_subscription_id = Column(String, nullable=True, index=True)
    razorpay_invoice_id = Column(String, nullable=True, index=True)
    razorpay_payment_id = Column(String, nullable=True, unique=True, index=True)
    coupon_code = Column(String, nullable=True, index=True)
    coupon_percent_off = Column(Numeric(5, 2), nullable=True)
    pricing_model = Column(String, nullable=True, default="pro_monthly")
    status = Column(String, nullable=False, default="created")  # created | verified | failed
    signature_verified_at = Column(DateTime(timezone=True), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="subscription_payments")


class UniversityShortlistEntry(Base):
    """A university a student is considering / applying to (B2C shortlisting).

    Entries are created manually or saved from the AI recommendation engine, and the
    student tracks each university's application status from the dashboard.
    """
    __tablename__ = "university_shortlist_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    country_code = Column(String, nullable=True)  # destination country when added
    university_name = Column(String, nullable=False)
    program = Column(String, nullable=True)
    location = Column(String, nullable=True)
    status = Column(String, nullable=False, default="considering")  # considering|applied|admitted|rejected
    source = Column(String, nullable=False, default="manual")  # manual|ai
    est_tuition = Column(String, nullable=True)       # free-text estimate (from AI)
    rationale = Column(Text, nullable=True)           # why recommended (from AI)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_university_shortlist_user_created", "user_id", "created_at"),
    )


class CouponCode(Base):
    __tablename__ = "coupon_codes"

    coupon_code = Column(String, primary_key=True, index=True, nullable=False)
    percent_off = Column(Numeric(5, 2), nullable=False)
    max_uses_per_user = Column(Integer, nullable=True)


class UserNotification(Base):
    __tablename__ = "user_notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    notification_type = Column(String, nullable=False, default="info")  # success | error | warning | info
    source = Column(String, nullable=True)  # ai_daily_assistant | subscription | system
    is_read = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="notifications")


class AIDailyNotificationRun(Base):
    __tablename__ = "ai_daily_notification_runs"

    id = Column(Integer, primary_key=True, index=True)
    run_date = Column(Date, nullable=False, unique=True, index=True)
    status = Column(String, nullable=False, default="running")  # running | completed | failed
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    users_scanned = Column(Integer, nullable=False, default=0)
    notifications_sent = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)


class RilonoAiChatUploadEvent(Base):
    __tablename__ = "rilono_ai_chat_upload_events"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    attachment_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        Index("ix_rilono_ai_chat_upload_events_user_attachment", "user_id", "attachment_id"),
    )


class F1VisaNewsItem(Base):
    __tablename__ = "f1_visa_news"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    why_it_matters = Column(Text, nullable=True)
    source_name = Column(String, nullable=False, default="Source")
    source_url = Column(String, nullable=True)
    published_date = Column(String, nullable=True)  # "YYYY-MM-DD" or "unknown"
    ingested_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class AiOptimizationEvent(Base):
    """A GCP cost-optimization event: an off-topic prompt blocked before hitting the
    model, or a context-cache hit/miss. Powers the admin 'tokens/₹ saved' report."""
    __tablename__ = "ai_optimization_events"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String, nullable=False, index=True)   # guardrail_block | cache_hit | cache_miss
    source = Column(String, nullable=False, index=True)  # feature, e.g. student_ai_chat, deep_scan
    tokens_saved = Column(Integer, nullable=False, default=0)
    cost_saved_usd = Column(Numeric(12, 6), nullable=False, default=0)
    detail = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class GeminiUsageEvent(Base):
    """One Gemini API call's token usage + estimated cost, for the admin AI-cost tracker."""
    __tablename__ = "gemini_usage_events"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, nullable=False, index=True)   # feature, e.g. enterprise_copilot, mock_interview
    model = Column(String, nullable=False, index=True)
    # Which account incurred this AI cost — lets us attribute Gemini spend per user (B2C)
    # and per organization (B2B) so we can compute per-account cost and profit.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=True, index=True)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    estimated_cost_usd = Column(Numeric(12, 6), nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
