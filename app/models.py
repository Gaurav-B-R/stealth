from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
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
    encryption_salt = Column(String, nullable=True)  # Salt for Zero-Knowledge encryption (base64 encoded)
    # Documentation preferences
    preferred_country = Column(String, nullable=True, default="United States")
    preferred_intake = Column(String, nullable=True)  # Spring or Fall
    preferred_year = Column(Integer, nullable=True)
    referral_code = Column(String, unique=True, index=True, nullable=True)
    referred_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    first_login_at = Column(DateTime(timezone=True), nullable=True)
    referral_reward_granted_at = Column(DateTime(timezone=True), nullable=True)
    accepted_terms_privacy_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    documents = relationship("Document", back_populates="uploader", cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="user", uselist=False, cascade="all, delete-orphan")

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
    document_type = Column(String, unique=True, index=True, nullable=False)
    label = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    is_required = Column(Boolean, nullable=False, default=False)
    journey_stage = Column(Integer, nullable=True)
    stage_gate_required = Column(Boolean, nullable=False, default=False)
    stage_gate_group = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


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
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ends_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="subscription")
