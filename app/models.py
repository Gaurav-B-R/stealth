from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Date, ForeignKey, Text, Boolean, Numeric, Float, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
from app.utils.field_encryption import EncryptedString

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
    # Product separation (B2B vs B2C). True when this account's ORIGIN is the Rilono
    # Enterprise (B2B) product — i.e. it was created as a workspace owner via
    # /api/enterprise/signup, or created BY an organization when it invited a brand-new
    # teammate. Such accounts are BLOCKED from the individual/B2C consumer app so the two
    # products stay disconnected (same credentials can't cross over). A person who existed
    # as a B2C user first and later joins a team keeps their consumer access (the flag is
    # only set when the account itself is enterprise-created). Rilono's own platform
    # admins/developers are always exempt. See app.auth.is_enterprise_only_account.
    is_enterprise_account = Column(Boolean, nullable=False, default=False)
    auth_provider = Column(String, nullable=True)  # password | google | microsoft | apple
    # Personalized student journey (multi-country). Existing users are backfilled to
    # US/us_f1 with onboarding marked complete; new users leave these NULL until they
    # finish the post-signup onboarding (destination country + visa type are required).
    destination_country_code = Column(String, nullable=True)  # US | UK | CA | AU | DE
    visa_type_key = Column(String, nullable=True)             # us_f1 | uk_student | ...
    university_email = Column(String, nullable=True)
    onboarding_completed_at = Column(DateTime(timezone=True), nullable=True)
    # On logout (or forced sign-out) this is set to "now"; any access token issued at
    # or before this instant is rejected, so logout truly ends the session server-side
    # even if a token copy survives in the browser (stateless JWTs are otherwise valid
    # until expiry).
    session_invalidated_at = Column(DateTime(timezone=True), nullable=True)
    # Account-deletion second factor: a short-lived 6-digit OTP (hashed) emailed to
    # the user. The DELETE endpoint requires it as a secondary confirmation.
    account_deletion_otp = Column(String, nullable=True)
    account_deletion_otp_expires = Column(DateTime(timezone=True), nullable=True)
    # Destination-country change second factor: a hashed 6-digit OTP emailed to the user,
    # plus the pending selection they requested (applied only after the code is confirmed).
    country_change_otp = Column(String, nullable=True)
    country_change_otp_expires = Column(DateTime(timezone=True), nullable=True)
    country_change_pending_country = Column(String, nullable=True)
    country_change_pending_visa = Column(String, nullable=True)
    encryption_salt = Column(String, nullable=True)  # Salt for legacy v1 server-side encryption (base64 encoded)
    # --- Client-side end-to-end encryption (E2E) key vault (v2) ---
    # The browser generates a random master key, wraps it with a passphrase-derived key
    # (passphrase NEVER sent to the server) and with a one-time recovery code. Only these
    # opaque wrapped blobs and the public KDF params are stored here; the server can never
    # unwrap them. See app/routers/e2e.py and static/e2e_crypto.js.
    e2e_enabled = Column(Boolean, nullable=False, default=False)
    e2e_kdf = Column(String, nullable=True)  # public KDF params, e.g. "pbkdf2-sha256$600000$<saltB64>"
    e2e_wrapped_master_key = Column(Text, nullable=True)  # master key wrapped by passphrase-derived key (base64)
    e2e_recovery_wrapped_master_key = Column(Text, nullable=True)  # master key wrapped by recovery-code-derived key (base64)
    e2e_setup_at = Column(DateTime(timezone=True), nullable=True)
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
    # Age self-attestation captured at signup: the user confirmed they are 18+ (or a
    # parent/guardian agreed on their behalf). Supports DPDP (under-18) / GDPR
    # (under-16) minor-consent obligations.
    age_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    email_notifications_enabled = Column(Boolean, nullable=False, default=True)
    email_notifications_unsubscribed_at = Column(DateTime(timezone=True), nullable=True)
    email_notifications_unsubscribe_reason = Column(Text, nullable=True)
    # Explicit opt-in consent for marketing emails (product tips, offers, newsletters),
    # captured at signup. Distinct from email_notifications_enabled, which governs
    # transactional/visa notifications. Users can opt out anytime; the timestamp
    # records when consent was last given or withdrawn (proof of consent).
    marketing_emails_consent = Column(Boolean, nullable=False, default=False)
    marketing_emails_consent_at = Column(DateTime(timezone=True), nullable=True)
    # First-touch acquisition attribution (where this signup came from), captured on the
    # landing page and sent at register. acquisition_channel is the normalized bucket used
    # for the admin traffic-source breakdown; the rest keep the raw UTM/referrer detail.
    acquisition_channel = Column(String, nullable=True, index=True)   # google_organic|instagram|chatgpt|direct|referral|...
    acquisition_source = Column(String, nullable=True)                # utm_source or referrer host
    acquisition_medium = Column(String, nullable=True)                # utm_medium (organic|social|cpc|email|...)
    acquisition_campaign = Column(String, nullable=True)              # utm_campaign
    acquisition_referrer = Column(String, nullable=True)              # raw document.referrer (truncated)
    acquisition_landing_page = Column(String, nullable=True)          # first landing path
    # Self-reported "How did you hear about us?" (asked once post-signup, B2C + B2B).
    # Complements the first-party attribution above and covers OAuth/untracked signups.
    heard_about_us = Column(String, nullable=True, index=True)         # option id (google|chatgpt|instagram|...)
    heard_about_us_detail = Column(String, nullable=True)             # free text when "other"
    heard_about_us_at = Column(DateTime(timezone=True), nullable=True)  # answered timestamp (also the "asked" flag)
    # Final visa DECISION (outcome capture) — closes the journey loop past interview prep so we can
    # compute an approval rate (esp. red-flag-scan users vs. not). Self-reported by the student on the
    # dashboard, or set by an admin. NULL = no decision recorded yet. See app/routers/outcomes.py.
    visa_decision = Column(String, nullable=True, index=True)          # approved|refused|withdrawn|deferred
    visa_decision_at = Column(DateTime(timezone=True), nullable=True)  # when the decision was recorded
    visa_decision_source = Column(String, nullable=True)              # self_reported|admin
    # Lets the "did you get your decision?" dashboard card be snoozed so we don't nag; NULL = show if eligible.
    visa_decision_prompt_snoozed_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    documents = relationship("Document", back_populates="uploader", cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="user", uselist=False, cascade="all, delete-orphan")
    # NOT delete-orphan: payment (financial) records must be RETAINED for accounting/tax after
    # account deletion. delete_account de-links them (nulls user_id) instead of deleting them.
    subscription_payments = relationship("SubscriptionPayment", back_populates="user", cascade="save-update, merge")
    notifications = relationship("UserNotification", back_populates="user", cascade="all, delete-orphan")

class USUniversity(Base):
    __tablename__ = "us_universities"
    
    # Use email_domain as primary key since the table doesn't have an id column
    email_domain = Column(String, primary_key=True, nullable=False, index=True)
    university_name = Column(String, nullable=False, index=True)
    location = Column(String, nullable=True)
    # Which country this university belongs to (US loaded externally; AU code-seeded).
    country_code = Column(String, nullable=True, default="US", index=True)

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
    # Company location (the org's own records) — seeds both the portal's DISPLAY currency
    # (_org_display_currency) and the default CHARGE currency for credit top-ups.
    country_code = Column(String, nullable=True)   # ISO-3166 alpha-2, e.g. "US"
    state_region = Column(String, nullable=True)
    # The currency this org is actually billed in for Rilono's own charges (credit
    # top-ups, infra fee). Set from the first checkout so the choice is sticky rather
    # than re-guessed from country on every visit. NULL = not yet chosen; falls back to
    # country, then INR. Note this does NOT affect what they collect from their own
    # students — Razorpay Route is INR-only.
    billing_currency = Column(String, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # Proof the organization accepted the Data Processing Agreement (controller↔processor
    # terms for handling its clients' personal data). Captured at signup.
    dpa_accepted_at = Column(DateTime(timezone=True), nullable=True)
    dpa_accepted_version = Column(String, nullable=True)
    dpa_accepted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
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

    # --- Access control ---------------------------------------------------
    # `role` above is now a maintained MIRROR of role_key (see legacy_role_for in
    # app/enterprise_access.py): three older code paths still read that column, and one of
    # them decides whether bank details are included in a payload, so it can never drift.
    role_key = Column(String, nullable=False, default="viewer", index=True)
    # owner | admin | branch_manager | counsellor | finance | viewer | custom
    custom_role_id = Column(Integer, ForeignKey("enterprise_roles.id"), nullable=True, index=True)
    # NULLABLE WITH NO DEFAULT, on purpose. NULL means "inherit the role's own scope", which is
    # what makes a preset's data_scope (counsellor = only their own clients) take effect at all.
    # A NOT NULL DEFAULT 'all' here would pin every member to workspace-wide access and turn
    # every role's default scope into dead code.
    data_scope = Column(String, nullable=True)             # all | branch | assigned
    capability_grants_json = Column(Text, nullable=True)   # JSON array — added on top of the role
    capability_denies_json = Column(Text, nullable=True)   # JSON array — removed; deny always wins
    primary_branch_id = Column(Integer, ForeignKey("enterprise_branches.id"), nullable=True, index=True)
    job_title = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    # Deactivation keeps the row (history, audit trail, record reassignment). `is_active` above
    # stays the gate; `status` records why it flipped.
    status = Column(String, nullable=False, default="active", index=True)  # active | suspended
    deactivated_at = Column(DateTime(timezone=True), nullable=True)
    deactivated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    invited_at = Column(DateTime(timezone=True), nullable=True)
    invite_accepted_at = Column(DateTime(timezone=True), nullable=True)
    last_active_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_ent_org_member_org_user_unique", "organization_id", "user_id", unique=True),
        Index("ix_ent_member_org_role_key", "organization_id", "role_key"),
    )


class EnterpriseBranch(Base):
    """A physical office of an enterprise organization (multi-office consultancies are the
    norm here: a head office plus city branches, with staff hired per office).

    A branch is two things at once — a label on a client record, and the unit a member's
    data scope can be narrowed to (see EnterpriseMemberBranch).

    Offices are ARCHIVED (is_active=False + archived_at), never deleted: clients, member
    links and audit rows keep pointing at them, so the name has to survive.
    """
    __tablename__ = "enterprise_branches"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    code = Column(String, nullable=True)            # the org's own short code, e.g. "HYD-01"
    city = Column(String, nullable=True)
    state_region = Column(String, nullable=True)
    country_code = Column(String, nullable=True)    # ISO-3166 alpha-2
    address_line = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    timezone = Column(String, nullable=True)
    # Exactly one default per org, maintained in application code. New clients and new
    # members land in the default office when nobody picks one.
    is_default = Column(Boolean, nullable=False, default=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # There is deliberately NO unique index on (organization_id, name). Name uniqueness is
    # enforced in application code on lower(trim(name)) and must include ARCHIVED rows — so a
    # rename can legitimately collide with an office nobody can currently see. A DB constraint
    # would turn that into an unhandled IntegrityError (500) instead of the 409 that tells the
    # user to reactivate the archived office, and a case-sensitive index would let "Kukatpally"
    # and "kukatpally" both through anyway.
    __table_args__ = (
        Index("ix_ent_branch_org_active", "organization_id", "is_active"),
    )


class EnterpriseMemberBranch(Base):
    """Which offices a staff member covers (many-to-many — a branch manager can run several).

    Keyed on `member_id`, not `user_id`: a member row already implies its tenant, so there is
    no way to link a user to an office in an organization they don't belong to. It also keeps
    seat billing honest — enterprise_billing.active_seat_count counts member rows, so granting
    a second office must never read as a second seat.

    ondelete=CASCADE because these rows are pure join data: once the membership is gone the
    office assignments mean nothing.
    """
    __tablename__ = "enterprise_member_branches"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    member_id = Column(
        Integer,
        ForeignKey("enterprise_organization_members.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_id = Column(Integer, ForeignKey("enterprise_branches.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_ent_member_branch_unique", "member_id", "branch_id", unique=True),
        Index("ix_ent_member_branch_org", "organization_id", "branch_id"),
    )


class EnterpriseRole(Base):
    """A custom, per-organization role — a named capability set a customer assembled themselves.

    The built-in roles (owner, admin, branch manager, counsellor, finance, viewer, plus the
    "custom" pseudo-role) live in CODE, not in this table — see app/enterprise_access.py — so a
    preset can gain a capability in a release without a data migration. Only invented roles
    land here.

    Archived (is_active=False), never deleted: members and audit rows reference them.
    """
    __tablename__ = "enterprise_roles"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False)
    description = Column(String, nullable=True)
    capabilities_json = Column(Text, nullable=True)    # JSON array of capability keys
    # NULL = inherit the scope of the preset this role was based on, instead of freezing a
    # scope at creation time (same reasoning as EnterpriseOrganizationMember.data_scope).
    data_scope = Column(String, nullable=True)         # all | branch | assigned
    based_on_role_key = Column(String, nullable=True)  # the preset it was duplicated from
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Slug/name uniqueness is application-enforced for the same reason as EnterpriseBranch:
    # the check is case-insensitive AND spans archived rows, which a DB index cannot express.
    __table_args__ = (
        Index("ix_ent_role_org_active", "organization_id", "is_active"),
        Index("ix_ent_role_org_slug", "organization_id", "slug"),
    )


class EnterpriseAccessAudit(Base):
    """Append-only log of who changed permissions, roles, offices and team membership.

    This is the record a consultancy shows when a student's file was read or moved by someone
    who should not have had access, so rows are never updated or deleted, and actor_name /
    target_name are SNAPSHOTS — the log has to stay readable after a member is removed and
    their user row de-identified.

    target_role_id and target_branch_id deliberately carry NO foreign key: an audit entry
    outlives its subject (roles and offices get archived and may one day be purged), and an FK
    would either block that or cascade the evidence away.
    """
    __tablename__ = "enterprise_access_audit"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    action = Column(String, nullable=False, index=True)   # member_role_changed | branch_archived | ...
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    actor_name = Column(String, nullable=True)            # snapshot
    target_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    target_name = Column(String, nullable=True)           # snapshot
    target_role_id = Column(Integer, nullable=True)       # no FK — see the note above
    target_branch_id = Column(Integer, nullable=True)     # no FK — see the note above
    summary = Column(String, nullable=False)              # one line, always esc()'d in the UI
    detail_json = Column(Text, nullable=True)             # {"before": {...}, "after": {...}}
    ip_address = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_ent_access_audit_org_created", "organization_id", "created_at"),
        Index("ix_ent_access_audit_org_action", "organization_id", "action"),
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
    """A client/applicant managed by an enterprise organization (any visa category)."""
    __tablename__ = "enterprise_clients"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)

    # Identity & contact
    full_name = Column(String, nullable=False)
    email = Column(String, nullable=True, index=True)
    phone = Column(String, nullable=True)
    # Counselling in this market runs on WhatsApp, and students routinely give a parent's
    # or a landline number as the primary contact — so the two are recorded separately.
    whatsapp_number = Column(String, nullable=True)
    current_city = Column(String, nullable=True)
    gender = Column(String, nullable=True)
    nationality = Column(String, nullable=True)
    date_of_birth = Column(Date, nullable=True)
    # Passport number is a government identifier — stored encrypted at rest.
    # (Encrypted values are not substring-searchable; excluded from client search.)
    passport_number = Column(EncryptedString, nullable=True)
    passport_expiry = Column(Date, nullable=True)

    # Parent / guardian — for a student case this is usually the payer, the sponsor on the
    # financial documents, and the number the agency actually calls when a student goes quiet.
    guardian_name = Column(String, nullable=True)
    guardian_relation = Column(String, nullable=True)
    guardian_phone = Column(String, nullable=True)

    # Visa case
    visa_category = Column(String, nullable=False, default="student")  # student|tourist|work|immigration
    destination_country_code = Column(String, nullable=False)
    destination_country_name = Column(String, nullable=False)
    visa_type = Column(String, nullable=False)
    intake = Column(String, nullable=True)
    application_reference = Column(String, nullable=True)
    # What they want to study and how far along the admission is — the questions that decide
    # whether a lead is sellable at all. Option keys come from enterprise_client_fields.
    study_level = Column(String, nullable=True)
    field_of_study = Column(String, nullable=True)
    admission_stage = Column(String, nullable=True)
    # Highest-signal risk field on the intake form: a refusal discovered after the fee has
    # been collected is the most common refund dispute in this business.
    prior_refusal_history = Column(String, nullable=True)
    prior_refusal_notes = Column(Text, nullable=True)

    # Academic profile & tests (lead qualification, and the inputs the AI shortlist needs)
    highest_qualification = Column(String, nullable=True)
    qualification_score = Column(String, nullable=True)   # free-form: "7.2", "76%", "First class"
    qualification_scale = Column(String, nullable=True)   # percentage | cgpa_10 | cgpa_4 | …
    year_of_passing = Column(Integer, nullable=True)
    backlogs_count = Column(Integer, nullable=True)
    work_experience_band = Column(String, nullable=True)
    english_test_status = Column(String, nullable=True)
    english_test_type = Column(String, nullable=True)
    english_test_score = Column(String, nullable=True)    # scales differ wildly (7.5 / 110 / 65)
    english_test_date = Column(Date, nullable=True)
    aptitude_test_type = Column(String, nullable=True)
    aptitude_test_score = Column(String, nullable=True)

    # Funding
    budget_band = Column(String, nullable=True)
    funding_source = Column(String, nullable=True)

    # Where the lead came from & who owns it
    lead_source = Column(String, nullable=True)
    lead_source_detail = Column(String, nullable=True)    # referrer / campaign / partner name
    branch_name = Column(String, nullable=True)
    # The office this case belongs to. branch_id is authoritative and branch_name is its
    # server-written display copy — branch_name predates this table, is full of free-text
    # spellings from live data and is still read by the client search clause, so it stays.
    branch_id = Column(Integer, ForeignKey("enterprise_branches.id"), nullable=True, index=True)
    next_followup_date = Column(Date, nullable=True)

    # Pipeline
    status = Column(String, nullable=False, default="new_lead", index=True)
    # When a case is put On Hold, the stage it was held FROM is kept here so the UI can
    # show the client's real position and offer a one-click "Resume". Cleared on resume.
    held_from_status = Column(String, nullable=True)
    priority = Column(String, nullable=False, default="normal")
    target_date = Column(Date, nullable=True)  # interview / travel / intake deadline
    # Per-stage case record, country-aware. JSON: {"<stage_key>": {"<field_key>": "value", …}}.
    # The field definitions live in enterprise_catalog.ENTERPRISE_STAGE_FIELD_CATALOG (shared +
    # per-destination), so what a counselor records at "Application Submitted" differs for a US
    # (DS-160 / SEVIS) vs a UK (CAS / IHS) case. Stored as JSON text like deep_scan_facts.
    stage_data = Column(Text, nullable=True)

    # Consent: the staff member confirmed this client consented to having their
    # personal data processed by the organization through Rilono (the org is the
    # controller; Rilono the processor). Proof-of-consent for end-client data.
    client_consent_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    client_consent_confirmed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Purpose-specific consents, each recorded separately from the processing consent
    # above because they authorise a different thing: promotional contact (per channel,
    # opt-in) and sharing the profile with universities / partner institutions abroad.
    marketing_consent_channels = Column(String, nullable=True)   # "whatsapp,email"
    marketing_consent_at = Column(DateTime(timezone=True), nullable=True)
    institution_share_consent_at = Column(DateTime(timezone=True), nullable=True)

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
    copilot_invites = relationship(
        "EnterpriseCopilotInvite",
        back_populates="client",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    deep_scans = relationship(
        "EnterpriseClientDeepScan",
        back_populates="client",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    writing_drafts = relationship(
        "EnterpriseClientWritingDraft",
        back_populates="client",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    # Money records are RETAINED (not deleted) when a client is removed: default cascade
    # only, no delete-orphan and no passive_deletes, so SQLAlchemy nulls client_id via
    # UPDATE rather than deleting the financial rows (see EnterpriseStudentPayment).
    student_payments = relationship(
        "EnterpriseStudentPayment",
        back_populates="client",
    )
    finance_entries = relationship(
        "EnterpriseFinanceEntry",
        back_populates="client",
    )

    __table_args__ = (
        Index("ix_ent_clients_org_status", "organization_id", "status"),
        Index("ix_ent_clients_org_created", "organization_id", "created_at"),
        # The three access-scope predicates. Every scoped list/count query filters on
        # organization_id plus exactly one of these, so each pairing gets its own index.
        Index("ix_ent_clients_org_branch", "organization_id", "branch_id"),
        Index("ix_ent_clients_org_assigned", "organization_id", "assigned_to_user_id"),
        Index("ix_ent_clients_org_creator", "organization_id", "created_by_user_id"),
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


class EnterpriseClientUniversity(Base):
    """One university on a client's shortlist, scoped to the consultancy AND the client.

    The B2C equivalent (UniversityShortlistEntry) is keyed to a student's own user_id, so
    it can't be reused here: these rows belong to an organization's client record and are
    managed by staff. Unlike the B2C table we also persist the ranking/difficulty fields the
    AI returns — consultants shortlist against them, so throwing them away would lose the
    most useful part of a recommendation.
    """
    __tablename__ = "enterprise_client_universities"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("enterprise_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    # Destination the shortlist was built for (snapshotted at add time, like the B2C table).
    country_code = Column(String, nullable=True)
    university_name = Column(String, nullable=False)
    program = Column(String, nullable=True)
    location = Column(String, nullable=True)
    status = Column(String, nullable=False, default="considering")  # considering|applied|admitted|rejected
    source = Column(String, nullable=False, default="manual")       # manual|ai
    est_tuition = Column(String, nullable=True)
    rationale = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    qs_world_rank = Column(String, nullable=True)
    country_rank = Column(String, nullable=True)
    admission_difficulty = Column(String, nullable=True)            # reach|match|safety
    key_requirements = Column(Text, nullable=True)                  # JSON-encoded list of short strings
    application_fee = Column(String, nullable=True)                 # one-off fee to apply (≠ tuition)
    website_url = Column(String, nullable=True)                     # official university/program page
    admissions_url = Column(String, nullable=True)                  # entry-requirements / how-to-apply page
    added_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    added_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_enterprise_client_universities_client_created", "client_id", "created_at"),
    )


class EnterpriseClientEmail(Base):
    """Email thread between the org and a client: staff sends from the dashboard
    (direction=outbound) and, when Resend Inbound is configured, client replies
    land here too (direction=inbound, status=received)."""
    __tablename__ = "enterprise_client_emails"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("enterprise_clients.id", ondelete="CASCADE"), nullable=True, index=True)
    sent_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    sent_by_name = Column(String, nullable=True)
    to_email = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)  # always plain text (the email's text/plain part)
    # Rich-text version of `body` as composed in the dashboard editor, already run
    # through app/utils/html_sanitizer. Null for plain-text and inbound messages.
    body_html = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="sent")  # sent|failed|received
    provider_message_id = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    direction = Column(String, nullable=False, default="outbound")  # outbound|inbound
    from_email = Column(String, nullable=True)  # inbound only: the actual sender
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    client = relationship("EnterpriseClient", back_populates="emails")
    attachments = relationship(
        "EnterpriseClientEmailAttachment",
        back_populates="email",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="EnterpriseClientEmailAttachment.id",
    )


class EnterpriseClientEmailAttachment(Base):
    """A file attached to a staff-composed client email.

    Rows are created by the composer's upload endpoint *before* the email exists
    (email_id is null = still a draft attachment) and are bound to the email when
    it sends. Bytes live in the same encrypted private storage as client documents;
    attaching a document already on file copies it, so deleting that document later
    never breaks the record of what was actually sent."""
    __tablename__ = "enterprise_client_email_attachments"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    email_id = Column(
        Integer, ForeignKey("enterprise_client_emails.id", ondelete="CASCADE"), nullable=True, index=True
    )
    client_id = Column(Integer, ForeignKey("enterprise_clients.id", ondelete="CASCADE"), nullable=True, index=True)
    # Provenance when the file came from the client's document locker rather than a upload.
    source_document_id = Column(Integer, nullable=True)
    original_filename = Column(String, nullable=False)
    storage_key = Column(String, nullable=False)  # private object key (not a public URL)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String, nullable=True)
    uploaded_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    email = relationship("EnterpriseClientEmail", back_populates="attachments")


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
    # Deep Scan map-reduce cache: structured audit facts extracted from THIS document
    # (JSON), plus a hash of the source text so the extraction is reused across scans
    # and only re-run when the document's text actually changes.
    deep_scan_facts = Column(Text, nullable=True)
    deep_scan_facts_hash = Column(String, nullable=True)
    # Per-document AI validation, populated by the background worker right after upload.
    # validation_status: "valid" | "invalid" (AI red-flagged: bad/expired doc OR a material
    # conflict with the client profile/other docs — never auto-filled) | "error" | NULL (= still scanning).
    # extracted_fields: JSON — {fields, autofill:{filled,conflicts}, cross_validation_flags}.
    validation_status = Column(String, nullable=True, index=True)
    validation_message = Column(Text, nullable=True)
    extracted_fields = Column(Text, nullable=True)
    validated_at = Column(DateTime(timezone=True), nullable=True)
    # Human override: staff reviewed a document the AI flagged and accepted it themselves.
    # validation_status is flipped to "valid" so downstream logic is unchanged, but these
    # two columns keep the provenance honest — the UI must never call such a document
    # "Validated by Rilono AI".
    manually_accepted_at = Column(DateTime(timezone=True), nullable=True)
    manually_accepted_by = Column(String, nullable=True)
    uploaded_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    uploaded_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    client = relationship("EnterpriseClient", back_populates="documents")


class EnterpriseClientDeepScan(Base):
    """A stored Deep Scan result: one AI audit of a client's ENTIRE dossier (profile,
    stage case records, document contents, notes, emails, universities, interview
    results and payments). Kept as history so counselors can re-open past audits and
    see how the file improved between scans."""
    __tablename__ = "enterprise_client_deep_scans"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("enterprise_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    risk_level = Column(String, nullable=False, default="medium")  # low|medium|high
    summary = Column(Text, nullable=True)          # short plain-English overview
    findings = Column(Text, nullable=True)         # JSON list of structured findings
    checks_passed = Column(Text, nullable=True)    # JSON list of clean checks (strings)
    stats = Column(Text, nullable=True)            # JSON: severity counts + document coverage
    model_used = Column(String, nullable=True)     # internal only — never sent to the frontend
    credits_charged = Column(Integer, nullable=False, default=0)  # 0 = free first scan
    triggered_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    triggered_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    client = relationship("EnterpriseClient", back_populates="deep_scans")

    __table_args__ = (
        Index("ix_ent_deep_scans_client_created", "client_id", "created_at"),
    )


class EnterpriseAiConversation(Base):
    """One saved thread with the Rilono AI Assistant (the org-scoped dashboard copilot).

    Threads are PER MEMBER, not per org — a consultant's chat history is their own
    scratchpad, and making it org-readable would be a surveillance surface nobody asked
    for. The transcript is the authoritative conversation state: /ai/chat replays it
    server-side, so a client can no longer hand the model a fabricated prior turn.
    Rows are hard-deleted (thread delete, retention sweep, member offboarding) — they
    carry client PII, so there is no soft-delete/archive state to leak from.
    """
    __tablename__ = "enterprise_ai_conversations"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, nullable=True)  # first user message, truncated — never a model call
    message_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_message_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        Index("ix_ent_ai_convs_org_user_last", "organization_id", "user_id", "last_message_at"),
    )


class EnterpriseAiMessage(Base):
    """One turn of a saved assistant thread ({role: user|model}). Deleted explicitly with
    its conversation — deletion never relies on DB-level FK cascade (SQLite dev DBs don't
    enforce it)."""
    __tablename__ = "enterprise_ai_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("enterprise_ai_conversations.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    role = Column(String, nullable=False)  # user | model
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_ent_ai_msgs_conv_id", "conversation_id", "id"),
    )


class EnterpriseClientWritingDraft(Base):
    """One AI-drafted admissions document for a client — a Statement of Purpose or a
    Letter of Recommendation — from the enterprise Writing Studio.

    Versions are immutable: a refinement inserts a NEW row sharing the first version's
    `root_id`, so a counselor can compare "make it more technical" against the original
    and re-export any version's Word file. The `recommender_*` columns only apply to
    LORs: a letter is written in the recommender's voice, and who they are changes what
    they can credibly attest to, so their identity is part of the document's inputs.
    """
    __tablename__ = "enterprise_client_writing_drafts"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("enterprise_clients.id", ondelete="CASCADE"), nullable=False, index=True)

    doc_type = Column(String, nullable=False, default="sop")  # sop | lor
    # First version's id — the whole chain shares it (set right after the first flush).
    root_id = Column(Integer, nullable=True, index=True)
    version = Column(Integer, nullable=False, default=1)

    # What the document is aimed at (snapshotted, so later profile edits don't rewrite history).
    country_code = Column(String, nullable=True)
    university = Column(String, nullable=True)
    program = Column(String, nullable=True)
    study_level = Column(String, nullable=True)
    intake = Column(String, nullable=True)

    # LOR only — whose voice the letter speaks in.
    recommender_type = Column(String, nullable=True)  # professor|supervisor|manager|mentor|community
    recommender_name = Column(String, nullable=True)
    recommender_title = Column(String, nullable=True)
    recommender_org = Column(String, nullable=True)
    recommender_email = Column(String, nullable=True)
    relationship_context = Column(Text, nullable=True)  # how they know the student, in staff's words

    brief = Column(Text, nullable=True)        # the counselor's emphasis brief (generation input)
    instruction = Column(Text, nullable=True)  # the revision instruction that produced THIS version

    title = Column(String, nullable=True)
    content_md = Column(Text, nullable=False)  # the document itself (Markdown)
    # Rilono's coaching notes for the counselor: every [PLACEHOLDER] left in the draft and
    # what to strengthen. Kept OUT of content_md so the exported Word file can put them on
    # a final, deletable page instead of inside the letter.
    notes_md = Column(Text, nullable=True)
    word_count = Column(Integer, nullable=False, default=0)
    model_used = Column(String, nullable=True)  # internal only — never sent to the frontend
    credits_charged = Column(Integer, nullable=False, default=0)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    client = relationship("EnterpriseClient", back_populates="writing_drafts")

    __table_args__ = (
        Index("ix_ent_writing_drafts_client_created", "client_id", "created_at"),
        Index("ix_ent_writing_drafts_root_version", "root_id", "version"),
    )


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
    used_count = Column(Integer, nullable=False, default=0)  # interviews STARTED via the link
    completed_count = Column(Integer, nullable=False, default=0)  # interviews FINISHED (feedback generated)
    last_completed_at = Column(DateTime(timezone=True), nullable=True)
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


class EnterpriseClientPortalShare(Base):
    """A secure email share giving a client read-only access to their own case portal.

    Mirrors the interview-invite / document-request security model: a high-entropy
    capability token (stored hashed) plus a one-time email code (OTP) the client
    must confirm, after which a short-lived signed session token authorizes the
    read-only portal data endpoint. Strictly view-only — no write path exists.
    """
    __tablename__ = "enterprise_client_portal_shares"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("enterprise_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)  # hashed capability token
    email = Column(String, nullable=False)  # client email the link was sent to
    # One-time email verification (OTP) — same scheme as EnterpriseInterviewInvite.
    code_hash = Column(String, nullable=True)
    code_expires_at = Column(DateTime(timezone=True), nullable=True)
    code_attempts = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked = Column(Boolean, nullable=False, default=False)
    # Staff-facing engagement signal: has the client actually opened their portal?
    last_opened_at = Column(DateTime(timezone=True), nullable=True)
    open_count = Column(Integer, nullable=False, default=0)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    client = relationship("EnterpriseClient")

    __table_args__ = (
        Index("ix_ent_portal_shares_client_created", "client_id", "created_at"),
    )


class EnterpriseCopilotInvite(Base):
    """A secure email invite giving a client their own Copilot chat about their case.

    Mirrors the interview-invite / portal-share security model: a high-entropy
    capability token (stored hashed) plus a one-time email code (OTP) the client
    must confirm, after which a short-lived signed session token (scope
    "ent_copilot") authorizes the public chat endpoint. Access is a flat
    per-client unlock: the org wallet is charged once when the client first
    verifies (unlocked_at), and the message counters cap total usage.
    """
    __tablename__ = "enterprise_copilot_invites"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("enterprise_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)  # hashed capability token
    email = Column(String, nullable=False)  # client email the link was sent to
    allowed_messages = Column(Integer, nullable=False, default=100)
    used_messages = Column(Integer, nullable=False, default=0)  # answered chat messages
    last_message_at = Column(DateTime(timezone=True), nullable=True)
    # Flat unlock: set when the client first verifies and the org wallet is charged.
    unlocked_at = Column(DateTime(timezone=True), nullable=True)
    credits_charged = Column(Integer, nullable=False, default=0)
    # One-time email verification (OTP) — same scheme as EnterpriseInterviewInvite.
    code_hash = Column(String, nullable=True)
    code_expires_at = Column(DateTime(timezone=True), nullable=True)
    code_attempts = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked = Column(Boolean, nullable=False, default=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    client = relationship("EnterpriseClient", back_populates="copilot_invites")

    __table_args__ = (
        Index("ix_ent_copilot_invites_client_created", "client_id", "created_at"),
    )


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


class EnterpriseCalendarEventAttachment(Base):
    """A reference file pinned to a calendar event — the appointment letter, the agenda for
    a call, the checklist to run through.

    Files upload immediately rather than on form submit (the calendar form posts JSON, so a
    file input could never ride along). When the event already exists they bind straight to
    it; when the reminder is still being composed they land with `event_id` NULL under a
    per-modal `draft_token` and are bound once it saves — the same draft-then-bind dance the
    email composer does, keyed on a token so a cancelled modal's files cannot leak into the
    next reminder. See app/enterprise_calendar_files.py.

    Deliberately no client_id: the owning event already carries the client link and can be
    re-pointed at a different client on edit, so a copy here would be a second source of
    truth that silently drifts. The delete-client blob sweep joins through the event instead.
    Bytes live in the same encrypted private R2 storage as client documents and are only ever
    served back through the authenticated, org-scoped download endpoint. Internal to staff —
    never surfaced in the client portal or attached to client emails."""
    __tablename__ = "enterprise_calendar_event_attachments"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    event_id = Column(
        Integer, ForeignKey("enterprise_calendar_events.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Set only while unbound; cleared on bind. Owner of a not-yet-saved reminder's uploads.
    draft_token = Column(String, nullable=True, index=True)
    original_filename = Column(String, nullable=False)
    storage_key = Column(String, nullable=False)  # private R2 object key (not a public URL)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String, nullable=True)
    uploaded_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    uploaded_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        Index("ix_ent_cal_att_draft", "organization_id", "draft_token", "event_id"),
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


class EnterpriseNotification(Base):
    """In-portal notification for enterprise staff (the topbar bell).

    One row per recipient (fan-out at write time), so read-state is per member.
    Deliberately high-signal only — client added, pipeline stage moved, mock interview
    completed, requested documents submitted, team changes, low credits — and the actor
    never gets a notification about their own action (communications stay limited).
    """
    __tablename__ = "enterprise_notifications"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    recipient_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)   # None = external event (student)
    type = Column(String, nullable=False)          # client_added | status_changed | interview_completed | docs_submitted | member_added | member_removed | credits_low
    title = Column(String, nullable=False)
    body = Column(Text, nullable=True)
    reference_type = Column(String, nullable=True)  # client | credits | team | ...
    reference_id = Column(Integer, nullable=True)
    is_read = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        Index("ix_ent_notif_recipient_read", "recipient_user_id", "is_read"),
        Index("ix_ent_notif_org_created", "organization_id", "created_at"),
    )


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
    # Attachments are forwarded straight to the support inbox as email attachments (never
    # stored in our bucket). This column keeps only the manifest — [{filename, size}] — so
    # the requester's history can show what they sent.
    attachments_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_ent_support_org_created", "organization_id", "created_at"),
    )


class EnterpriseDemoRequest(Base):
    """A public 'book a demo' lead from the enterprise landing page (no auth). Stored so
    no lead is lost even if the notification email fails."""
    __tablename__ = "enterprise_demo_requests"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    work_email = Column(String, nullable=False, index=True)
    company = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    team_size = Column(String, nullable=True)        # e.g. "1-5", "6-20", "21-50", "50+"
    students_count = Column(String, nullable=True)   # e.g. "<50", "50-200", "200-1000", "1000+"
    message = Column(Text, nullable=True)
    source = Column(String, nullable=True)           # utm/referrer hint (optional)
    ip_address = Column(String, nullable=True)
    status = Column(String, nullable=False, default="new", index=True)  # new|contacted|scheduled|closed
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class EnterpriseSignupOtp(Base):
    """Email-verification code for enterprise workspace signup. The workspace is only
    created after the owner proves the inbox (stops junk workspaces + subdomain squatting).
    One row per email (upserted on resend); deleted once the signup completes."""
    __tablename__ = "enterprise_signup_otps"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    code_hash = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EnterpriseStepUpOtp(Base):
    """One-time code that re-proves the ACTOR's own inbox before an irreversible workspace
    action (today: transferring ownership).

    A capability check proves the session is *authorised*; it does not prove the session is
    still the person it was issued to. `context_key` binds the code to the exact action, so a
    code emailed to hand the workspace to Alice can never be replayed to hand it to Bob. One
    live row per (user, organization, purpose) — a re-request overwrites the previous code,
    which is also what makes an older intercepted code useless."""
    __tablename__ = "enterprise_step_up_otps"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    purpose = Column(String, nullable=False, index=True)     # e.g. "owner_transfer"
    context_key = Column(String, nullable=True)              # e.g. "target:42"
    code_hash = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # The "one live code per scope" rule above is what makes a re-request invalidate the
    # previous code; it is enforced by the database, not by the issuing code path.
    __table_args__ = (
        Index(
            "uq_enterprise_step_up_otps_scope",
            "user_id", "organization_id", "purpose", unique=True,
        ),
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
    # Rilono AI assistant (copilot) metering: a free daily allowance, then credits are
    # debited per bundle of messages (see app/enterprise_credits.py). `copilot_usage_date`
    # is the 'YYYY-MM-DD' the daily counter applies to; `copilot_msgs_today` is that day's
    # message count (for the free allowance); `copilot_unbilled_msgs` is billable messages
    # accrued toward the next credit debit (rolls over, not reset daily).
    copilot_usage_date = Column(String, nullable=True)
    copilot_msgs_today = Column(Integer, nullable=False, default=0)
    copilot_unbilled_msgs = Column(Integer, nullable=False, default=0)
    # Free staff-run mock interview "previews" consumed (the self-serve link is the
    # real product; staff can run a few in-browser test interviews free, then it costs
    # the normal mock_interview price). See app/enterprise_credits.py.
    interview_staff_previews_used = Column(Integer, nullable=False, default=0)
    # Deep Scan freebie guard: each CLIENT's first scan is free, but the org's total
    # free scans are ALSO capped per month — otherwise create-scan-delete client churn
    # could farm unlimited free Gemini audits. 'YYYY-MM' window + count used in it.
    deep_scan_free_month = Column(String, nullable=True)
    deep_scan_free_used = Column(Integer, nullable=False, default=0)
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
    # Minor unit of `currency` — paise for INR, cents for USD. Never sum across currencies.
    amount_paise = Column(Integer, nullable=False)
    currency = Column(String, nullable=False, default="INR")
    # --- Settlement (see SubscriptionPayment for the full rationale) ------------------
    base_amount_paise = Column(Integer, nullable=True)     # Razorpay's INR settlement figure
    base_currency = Column(String, nullable=False, default="INR")
    fx_rate_used = Column(Numeric(18, 6), nullable=True)
    is_international = Column(Boolean, nullable=False, default=False)
    price_book_version = Column(String, nullable=True)
    razorpay_order_id = Column(String, nullable=False, unique=True, index=True)
    razorpay_payment_id = Column(String, nullable=True, unique=True, index=True)
    status = Column(String, nullable=False, default="created")  # created | verified | failed
    # Per-account discount applied at checkout (admin-managed; see EnterpriseCoupon).
    coupon_code = Column(String, nullable=True, index=True)
    coupon_percent_off = Column(Numeric(5, 2), nullable=True)
    original_amount_paise = Column(Integer, nullable=True)  # pre-discount amount
    verified_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    # Running total of money refunded against this payment (paise). When >0 the
    # status becomes 'partially_refunded'; when it reaches amount_paise, 'refunded'.
    refunded_amount_paise = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class EnterpriseRefund(Base):
    """An audit record of a refund issued to an enterprise account by a platform admin.

    Two kinds:
      * 'credits' — a goodwill credit grant added back to the wallet (no money moves).
      * 'money'   — a real Razorpay refund against a specific credit/infra payment,
                    optionally clawing back the corresponding credits."""
    __tablename__ = "enterprise_refunds"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    payment_id = Column(Integer, ForeignKey("enterprise_credit_payments.id"), nullable=True, index=True)
    kind = Column(String, nullable=False, default="credits", index=True)  # credits | money
    amount_paise = Column(Integer, nullable=False, default=0)        # money refunded (paise)
    currency = Column(String, nullable=False, default="INR")
    credits_delta = Column(Integer, nullable=False, default=0)       # +credits granted / -credits clawed back
    provider = Column(String, nullable=True)                         # razorpay (money) / null (credits)
    razorpay_payment_id = Column(String, nullable=True, index=True)
    razorpay_refund_id = Column(String, nullable=True, unique=True, index=True)
    status = Column(String, nullable=False, default="completed")     # completed | processed | pending | failed
    reason = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


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


class EnterpriseLinkedAccount(Base):
    """A consultancy's Razorpay Route "Linked Account" (sub-merchant).

    This is the compliant marketplace primitive: student payments are collected into
    *Razorpay's* PA escrow (never a Rilono bank account) and settled by Razorpay directly
    to this linked account's own verified bank. Rilono only issues split instructions and
    keeps a commission — it never takes custody of the consultancy's funds. One linked
    account per organization. We store only the Razorpay ids + display-safe fields; full
    bank numbers and stakeholder KYC live with Razorpay, not here.
    """
    __tablename__ = "enterprise_linked_accounts"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, unique=True, index=True)

    # Razorpay Route ids (v2 Accounts API).
    razorpay_account_id = Column(String, nullable=True, unique=True, index=True)      # acc_...
    razorpay_product_id = Column(String, nullable=True)                              # acc_prd_... (route config)
    razorpay_stakeholder_id = Column(String, nullable=True)                          # sth_...

    # Business identity (sent to Razorpay for KYC; PAN encrypted at rest).
    legal_business_name = Column(String, nullable=True)
    business_type = Column(String, nullable=True)   # proprietorship|partnership|llp|private_limited|...
    contact_name = Column(String, nullable=True)
    contact_email = Column(String, nullable=True)
    contact_phone = Column(String, nullable=True)
    business_pan = Column(EncryptedString, nullable=True)
    # GSTIN embeds the PAN (chars 3-12), so it gets the same at-rest encryption.
    gst_number = Column(EncryptedString, nullable=True)

    # Settlement bank — display only. The full account number is NOT stored (Razorpay is
    # the record); we keep last4 + IFSC + beneficiary for the UI and reconciliation.
    bank_account_last4 = Column(String, nullable=True)
    bank_ifsc = Column(String, nullable=True)
    beneficiary_name = Column(String, nullable=True)

    # Route onboarding/activation state machine (mirrors Razorpay account/product status).
    activation_status = Column(String, nullable=False, default="not_started", index=True)
    # not_started|created|stakeholder_added|product_requested|settlement_submitted|
    # under_review|needs_clarification|activated|suspended
    requirements_json = Column(Text, nullable=True)   # last requirements[] for remediation UI
    is_payable = Column(Boolean, nullable=False, default=False)  # derived: activated + bank verified

    # Eligibility attestation (RBI/Route: split payee must itself deliver the service to the
    # student and meet the turnover threshold). Captured with timestamp + IP as proof.
    attested_service_delivery = Column(Boolean, nullable=False, default=False)
    attested_turnover_ok = Column(Boolean, nullable=False, default=False)
    attested_at = Column(DateTime(timezone=True), nullable=True)
    attested_ip = Column(String, nullable=True)
    # Which version of the attestation wording was agreed to (FINANCE_ATTESTATION_VERSION
    # in app/legal.py) — proof survives future copy changes.
    attested_version = Column(String, nullable=True)

    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class EnterpriseStudentPayment(Base):
    """A payment request / invoice a consultancy raises against one of its students.

    Collected via Razorpay Route: an order is created on Rilono's platform account with an
    inline transfer that splits the money — the consultancy's `payout_paise` goes to their
    linked account, and Rilono's `commission_paise` is retained. Reconciliation is driven by
    webhooks (see EnterprisePaymentEvent), not the browser callback. Money is stored in
    integer paise (INR only for now).

    `client_id` is nullable and nulls out on client delete (NOT cascade) so the financial
    record is retained even if the student is removed — `client_name_snapshot` preserves who
    it was for (mirrors SubscriptionPayment retention).
    """
    __tablename__ = "enterprise_student_payments"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("enterprise_clients.id", ondelete="SET NULL"), nullable=True, index=True)
    client_name_snapshot = Column(String, nullable=True)   # denormalized for retention
    linked_account_id = Column(Integer, ForeignKey("enterprise_linked_accounts.id"), nullable=True, index=True)

    invoice_number = Column(String, nullable=True, index=True)
    description = Column(String, nullable=True)

    amount_paise = Column(Integer, nullable=False)          # total the student pays
    commission_paise = Column(Integer, nullable=False, default=0)  # Rilono's gross take (retained)
    payout_paise = Column(Integer, nullable=False, default=0)      # to consultancy = amount - commission
    # Razorpay Route transfers are INR-ONLY, so gateway-collected rows here are always INR
    # and `amount_paise` is genuinely paise. Manual (off-platform) rows may carry a foreign
    # currency — the consultancy really did collect foreign cash and the books should say so.
    currency = Column(String, nullable=False, default="INR")
    provider = Column(String, nullable=False, default="razorpay")   # razorpay | manual
    # True when an INR invoice here was paid with a foreign-issued card. The order stays INR
    # (Route requires it), but the cost of collection does not: international cards run
    # ~3% + GST vs ~2% domestic, so margin/"Rilono savings" figures overstate unless this is
    # known. Also the signal for export-of-services treatment at filing time.
    is_international = Column(Boolean, nullable=False, default=False)
    # For off-platform ("manual") payments recorded by staff — money the consultancy collected
    # OUTSIDE Rilono (cash/bank transfer/UPI/cheque/card/other). NULL for Razorpay rows.
    manual_method = Column(String, nullable=True)

    razorpay_order_id = Column(String, nullable=True, unique=True, index=True)
    razorpay_payment_id = Column(String, nullable=True, unique=True, index=True)
    razorpay_transfer_id = Column(String, nullable=True, unique=True, index=True)  # trf_...

    status = Column(String, nullable=False, default="created", index=True)
    # created|paid|transferred|on_hold|settled|failed|refunded|partially_refunded|cancelled
    settlement_status = Column(String, nullable=True)       # pending|on_hold|settled (from Route)
    on_hold = Column(Boolean, nullable=False, default=False)
    on_hold_until = Column(DateTime(timezone=True), nullable=True)
    utr = Column(String, nullable=True)                     # bank UTR for reconciliation
    refunded_amount_paise = Column(Integer, nullable=False, default=0)

    due_date = Column(Date, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    settled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Secure pay-link sent to the student by email (raw token never stored — only its
    # hash, mirroring EnterpriseInterviewInvite.token_hash). The public /pay/<token>
    # page resolves the request through this hash.
    pay_token_hash = Column(String, nullable=True, unique=True, index=True)
    payer_email_snapshot = Column(String, nullable=True)   # where the link was sent
    # The student's phone at request time. Needed because Razorpay hard-fails an
    # international card payment when the email/phone sent to Checkout are placeholders.
    payer_phone_snapshot = Column(String, nullable=True)
    email_sent_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    # Chargeback/dispute state from payment.dispute.* webhooks:
    # None|open|under_review|action_required|won|lost|closed
    dispute_status = Column(String, nullable=True, index=True)
    disputed_at = Column(DateTime(timezone=True), nullable=True)

    # Retention: null the FK on client delete (no cascade, no passive_deletes) so SQLAlchemy
    # issues UPDATE ... SET client_id=NULL rather than deleting these money rows.
    client = relationship("EnterpriseClient", back_populates="student_payments")

    __table_args__ = (
        Index("ix_ent_student_pay_org_created", "organization_id", "created_at"),
        Index("ix_ent_student_pay_org_status", "organization_id", "status"),
    )


class EnterprisePaymentEvent(Base):
    """Append-only reconciliation ledger for Route webhook events.

    Doubles as the idempotency guard: a real UNIQUE constraint on `razorpay_event_id`
    (the `x-razorpay-event-id` header) makes at-least-once webhook delivery safe, and
    upserts keyed on the entity id tolerate out-of-order events.
    """
    __tablename__ = "enterprise_payment_events"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=True, index=True)
    student_payment_id = Column(Integer, ForeignKey("enterprise_student_payments.id"), nullable=True, index=True)
    razorpay_event_id = Column(String, nullable=True, unique=True, index=True)  # dedupe key
    event_type = Column(String, nullable=True, index=True)   # payment.captured|transfer.processed|...
    entity_type = Column(String, nullable=True)              # payment|transfer|settlement|refund
    entity_id = Column(String, nullable=True, index=True)    # pay_/trf_/setl_/rfnd_
    amount_paise = Column(Integer, nullable=True)
    payload_json = Column(Text, nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_ent_pay_evt_org_created", "organization_id", "created_at"),
    )


class EnterprisePaymentDispute(Base):
    """Audit ledger for chargebacks/disputes raised against a student payment
    (payment.dispute.* webhooks). Liability for disputed amounts rests with the
    organization (Terms §6.7 Payment Collection); this table tracks the lifecycle so
    staff can respond before the evidence deadline."""
    __tablename__ = "enterprise_payment_disputes"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=True, index=True)
    student_payment_id = Column(Integer, ForeignKey("enterprise_student_payments.id"), nullable=True, index=True)
    razorpay_dispute_id = Column(String, nullable=True, unique=True, index=True)
    razorpay_payment_id = Column(String, nullable=True, index=True)
    amount_paise = Column(Integer, nullable=False, default=0)
    currency = Column(String, nullable=False, default="INR")
    phase = Column(String, nullable=True)          # e.g. chargeback|retrieval|fraud|pre_arbitration
    status = Column(String, nullable=False, default="open")  # open|under_review|action_required|won|lost|closed
    reason_code = Column(String, nullable=True)
    respond_by = Column(DateTime(timezone=True), nullable=True)   # evidence deadline from Razorpay
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class EnterprisePaymentRefund(Base):
    """Audit record of a refund/reversal issued against a student payment (mirrors
    EnterpriseRefund). Refunds always return to the student's original instrument; a
    transfer reversal claws back the consultancy's share where still possible."""
    __tablename__ = "enterprise_payment_refunds"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    student_payment_id = Column(Integer, ForeignKey("enterprise_student_payments.id"), nullable=True, index=True)
    kind = Column(String, nullable=False, default="money")
    amount_paise = Column(Integer, nullable=False, default=0)
    currency = Column(String, nullable=False, default="INR")
    provider = Column(String, nullable=False, default="razorpay")
    razorpay_refund_id = Column(String, nullable=True, unique=True, index=True)
    razorpay_reversal_id = Column(String, nullable=True, index=True)
    reverse_all = Column(Boolean, nullable=False, default=False)
    status = Column(String, nullable=False, default="created")
    reason = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class EnterpriseFinanceEntry(Base):
    """One hand-recorded income or expense in a consultancy's own books.

    This table holds ONLY money the platform cannot already see. Collected student
    payments, the Rilono commission on them, credit top-ups, the infrastructure fee,
    refunds and lost chargebacks are derived at read time from their own authoritative
    rows (see app/enterprise_finance.py) — copying them here would invite double
    counting the moment a webhook lands. So: fees taken in cash, university commissions
    received, salaries, rent, ads and agent payouts live here; anything Razorpay knows
    about does not.

    `repeat_monthly` makes a row a monthly TEMPLATE (salary, rent, a subscription):
    occurrences are projected at read time from `occurred_on` up to today (or
    `repeat_until`), so there is no cron job and editing the template retroactively
    fixes every month it produced.

    Money is integer paise, INR (matching enterprise_student_payments). `client_id`
    nulls out on client delete rather than cascading, and `client_name_snapshot`
    preserves who a fee belonged to — a financial record has to outlive the client row.
    """
    __tablename__ = "enterprise_finance_entries"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)

    kind = Column(String, nullable=False, default="expense", index=True)   # income | expense
    category = Column(String, nullable=False, default="other_expense", index=True)
    amount_paise = Column(Integer, nullable=False, default=0)
    tax_paise = Column(Integer, nullable=False, default=0)   # GST/tax portion of the amount
    currency = Column(String, nullable=False, default="INR")
    occurred_on = Column(Date, nullable=False, index=True)

    description = Column(String, nullable=True)
    counterparty = Column(String, nullable=True, index=True)  # vendor, payer or partner
    payment_method = Column(String, nullable=True)            # cash|bank_transfer|upi|card|cheque|other
    reference = Column(String, nullable=True)                 # invoice / bill / voucher number
    notes = Column(Text, nullable=True)

    # Optional case attribution — what makes per-client profitability possible.
    client_id = Column(Integer, ForeignKey("enterprise_clients.id", ondelete="SET NULL"), nullable=True, index=True)
    client_name_snapshot = Column(String, nullable=True)

    # Monthly template (salaries, rent, subscriptions). repeat_until ends the series.
    repeat_monthly = Column(Boolean, nullable=False, default=False)
    repeat_until = Column(Date, nullable=True)

    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Retention: default cascade only (no delete-orphan, no passive_deletes) so a client
    # delete issues UPDATE … SET client_id = NULL instead of deleting the money row.
    client = relationship("EnterpriseClient", back_populates="finance_entries")

    __table_args__ = (
        Index("ix_ent_fin_entries_org_date", "organization_id", "occurred_on"),
        Index("ix_ent_fin_entries_org_kind", "organization_id", "kind"),
    )


class EnterpriseFinanceSettings(Base):
    """Per-organization finance configuration (one row per org).

    `hourly_cost_paise` is the org's own blended staff cost — it turns hours saved by
    the platform into rupees, and because the number is theirs the ROI panel can't be
    accused of using a flattering assumption. `savings_overrides_json` holds their
    edits to the per-task minute baselines ({"deep_scan": 30, …}). `opening_balance_*`
    anchors the cash position, and `fy_start_month` makes "this quarter"/"this FY"
    match their financial year (April in India).
    """
    __tablename__ = "enterprise_finance_settings"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, unique=True, index=True)
    hourly_cost_paise = Column(Integer, nullable=False, default=40000)   # ₹400/hour
    # A BALANCE, not a transaction: integer paise caps at ~₹2.1 crore on Postgres int4,
    # which a real consultancy's bank balance can exceed, so this one column is BIGINT.
    opening_balance_paise = Column(BigInteger, nullable=False, default=0)
    opening_balance_on = Column(Date, nullable=True)
    fy_start_month = Column(Integer, nullable=False, default=4)          # April–March
    savings_overrides_json = Column(Text, nullable=True)                 # {"<activity>": minutes}
    updated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


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
    encrypted_file_key = Column(Text, nullable=True)  # Legacy v1: file key wrapped with the login password (base64)
    # --- Client-side E2E (v2) ---
    # When e2e_scheme is set, the R2 object is a client-encrypted blob (AES-GCM, IV prepended)
    # whose data-encryption key is wrapped by the user's E2E master key. The server stores only
    # the wrapped DEK and never has the plaintext or the DEK. NULL e2e_scheme = legacy v1 row.
    e2e_scheme = Column(String, nullable=True)  # e.g. "v2-aesgcm"; NULL = legacy server-side encryption
    e2e_wrapped_dek = Column(Text, nullable=True)  # per-file DEK wrapped by the E2E master key (base64)
    # Optional E2E-encrypted extracted-text artifact (from consent-based AI validation). The
    # ciphertext lives in object storage at extracted_text_file_url; the server can't read it.
    e2e_extracted_wrapped_dek = Column(Text, nullable=True)  # DEK for the extracted-text blob (base64)
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
    sop_generations_used = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ends_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="subscription")


class SubscriptionPayment(Base):
    __tablename__ = "subscription_payments"

    id = Column(Integer, primary_key=True, index=True)
    # Nullable so a payment (financial record) can be RETAINED and de-identified on account
    # deletion rather than hard-deleted (financial record-retention vs. right-to-erasure).
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    provider = Column(String, nullable=False, default="razorpay")  # razorpay
    plan = Column(String, nullable=False, default="pro")  # pro
    # `amount_paise` is in the MINOR UNIT OF `currency` — paise for INR, cents for USD.
    # It is what the customer was charged and must never be summed across currencies.
    amount_paise = Column(Integer, nullable=False)
    currency = Column(String, nullable=False, default="INR")
    # --- Settlement (the only figures that may be summed for revenue) -----------------
    # Razorpay settles everything to INR and reports the converted amount as `base_amount`
    # (absent on INR payments, where charged == settled). Reporting sums THIS column, never
    # `amount_paise`: adding 1299 (=$12.99) to 99900 (=₹999) yields a plausible-looking
    # number that is neither. See app/money.py::settled_inr_minor.
    base_amount_paise = Column(Integer, nullable=True)
    base_currency = Column(String, nullable=False, default="INR")
    fx_rate_used = Column(Numeric(18, 6), nullable=True)   # base_amount/amount, for audit
    # True when paid with a foreign-issued card. Drives the fee model (international cards
    # cost ~3% + GST vs ~2% domestic) and the GST export-of-services classification, which
    # cannot be derived from the INR amount alone.
    is_international = Column(Boolean, nullable=False, default=False)
    # Which app/money.py PRICE_BOOK_VERSION set this price — without it an in-flight
    # price change is unreconcilable after the fact.
    price_book_version = Column(String, nullable=True)
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


class SopDraft(Base):
    """
    Application Kit — AI-generated Statement of Purpose / Motivation-letter drafts.

    Every generation AND refinement is stored as its own immutable row (a version);
    versions of the same statement share root_id (= id of the first version), so the
    UI lists the latest version per root and can show/restore full history.
    """
    __tablename__ = "sop_drafts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    root_id = Column(Integer, nullable=True, index=True)   # set to own id on the first version
    version = Column(Integer, nullable=False, default=1)
    country_code = Column(String, nullable=True)           # US | UK | CA | AU | DE (at generation time)
    visa_type_key = Column(String, nullable=True)
    university = Column(String, nullable=False)
    program = Column(String, nullable=False)
    study_level = Column(String, nullable=True)            # Bachelor's | Master's | PhD | ...
    intake = Column(String, nullable=True)
    highlights = Column(Text, nullable=True)               # user-provided angles to emphasize
    instruction = Column(Text, nullable=True)              # None/"initial" or the refine instruction
    content_md = Column(Text, nullable=False)
    word_count = Column(Integer, nullable=False, default=0)
    model_used = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_sop_drafts_user_root_version", "user_id", "root_id", "version"),
    )


class CouponCode(Base):
    __tablename__ = "coupon_codes"

    coupon_code = Column(String, primary_key=True, index=True, nullable=False)
    percent_off = Column(Numeric(5, 2), nullable=False)
    max_uses_per_user = Column(Integer, nullable=True)
    # Per-account coupon (admin console "conversion play"): when set, only this user
    # can apply the code at checkout. NULL = a global code anyone can use.
    restricted_to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=True)


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
    # Destination student-visa country this news item is about (US | UK | CA | AU | DE | IE).
    # Lets each user see news for their own journey instead of US F-1 for everyone.
    destination_country_code = Column(String, nullable=True, index=True, default="US")
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
    # Subset of prompt_tokens served from Gemini's context cache (implicit on 2.5 models,
    # or explicit). Billed at a discount, so estimated_cost_usd already reflects it.
    cached_tokens = Column(Integer, nullable=False, default=0)
    estimated_cost_usd = Column(Numeric(12, 6), nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


# ===========================================================================
# Course Finder catalog (shared, cross-tenant)
#
# A real universities/courses database — unlike `us_universities` (an email-domain
# map for signup autofill), these rows carry rankings, fees, intakes and entry
# requirements. Content is written ONLY by the background course-catalog refresh
# agent (app/services/course_catalog_refresh.py), which keeps every row stamped
# with last_verified_at via Google-Search-grounded Gemini runs. The enterprise
# Course Finder reads it; browsing costs no credits because no AI call happens.
# ===========================================================================

class CourseCatalogUniversity(Base):
    __tablename__ = "course_catalog_universities"

    id = Column(Integer, primary_key=True, index=True)
    country_code = Column(String, nullable=False, index=True)  # US|UK|CA|AU|DE (enterprise_catalog codes)
    name = Column(String, nullable=False)
    # Normalized dedup key (lowercased, punctuation stripped) — the AI names the same
    # university differently across runs ("The University of Melbourne" vs
    # "University of Melbourne"), so uniqueness can't hang off the display name.
    name_key = Column(String, nullable=False, index=True)
    # Registrable domain of the official site ("unsw.edu.au"). Names are unreliable
    # identity — the model calls one university "UNSW Sydney" and "The University of
    # New South Wales" on different days and both slip past name_key, creating
    # duplicates. The domain is stable, so it is the real dedup key when known.
    domain_key = Column(String, nullable=True, index=True)
    city = Column(String, nullable=True)
    qs_world_rank = Column(String, nullable=True)      # display string, e.g. "34" or "301-350"
    # Sortable/filterable form of qs_world_rank (best end of a band: "301-350" -> 301).
    # The advanced browse filters page in SQL, so "within the top 200" needs a number.
    qs_rank_numeric = Column(Integer, nullable=True, index=True)
    national_rank = Column(String, nullable=True)
    university_type = Column(String, nullable=True)    # public|private
    website_url = Column(String, nullable=True)
    tuition_note = Column(String, nullable=True)       # typical intl tuition band, free text
    summary = Column(Text, nullable=True)              # 1-2 sentence profile
    scholarships_note = Column(Text, nullable=True)
    seed_rank = Column(Integer, nullable=True)         # order in the discovery top-N (browse sort)
    is_active = Column(Boolean, nullable=False, default=True)
    source_urls = Column(Text, nullable=True)          # JSON list of grounding source URLs
    extra = Column(Text, nullable=True)                # JSON: anything future refreshes want to keep
    # Consecutive failed enrichment attempts — lets the agent deprioritize (and, for
    # never-enriched stubs, deactivate) universities that keep failing, instead of
    # burning the daily batch on them forever. Reset to 0 on any successful refresh.
    consecutive_failures = Column(Integer, nullable=False, default=0)
    last_verified_at = Column(DateTime(timezone=True), nullable=True, index=True)  # NULL = seeded stub
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    courses = relationship(
        "CourseCatalogCourse", back_populates="university",
        cascade="all, delete-orphan", passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("country_code", "name_key", name="uq_course_catalog_uni_country_name"),
        Index("ix_course_catalog_uni_country_verified", "country_code", "last_verified_at"),
    )


class CourseCatalogCourse(Base):
    """One program/course at a catalog university, refreshed by the catalog agent."""
    __tablename__ = "course_catalog_courses"

    id = Column(Integer, primary_key=True, index=True)
    university_id = Column(Integer, ForeignKey("course_catalog_universities.id", ondelete="CASCADE"), nullable=False, index=True)
    country_code = Column(String, nullable=False, index=True)  # denormalized for direct filtering
    course_name = Column(String, nullable=False)
    name_key = Column(String, nullable=False)          # normalized course_name (dedup within a university+level)
    degree_level = Column(String, nullable=False, default="masters", index=True)  # bachelors|masters|phd|diploma|other
    discipline = Column(String, nullable=True, index=True)  # canonical bucket from course_catalog.DISCIPLINES
    duration = Column(String, nullable=True)           # e.g. "2 years"
    annual_tuition = Column(String, nullable=True)     # display string incl. currency
    tuition_amount = Column(Integer, nullable=True)    # numeric annual tuition (destination currency) for sorting/filters
    tuition_currency = Column(String, nullable=True)   # e.g. USD|GBP|CAD|AUD|EUR
    intakes = Column(Text, nullable=True)              # JSON list, e.g. ["Fall","Spring"]
    application_deadline = Column(String, nullable=True)
    # Parsed from application_deadline on write (apply_course_derived_fields). NULL when
    # the text holds no parseable date ("Rolling admissions"). Read paths compare this
    # against today so an expired deadline is never displayed as current — the text
    # column alone can't do that, and 374 live rows once shipped already-past deadlines.
    application_deadline_date = Column(Date, nullable=True)
    application_fee = Column(String, nullable=True)    # one-off fee to apply (≠ tuition)
    ielts_requirement = Column(String, nullable=True)
    toefl_requirement = Column(String, nullable=True)
    gre_gmat_requirement = Column(String, nullable=True)
    # Numeric forms of the three requirement strings above + duration, parsed once on
    # write (course_catalog.apply_course_derived_fields). The advanced browse filters
    # ("student has IELTS 6.5", "no GRE", "finishes within 18 months") run in SQL over a
    # LIMIT/OFFSET page, so they can only compare columns — never re-parsed free text.
    ielts_score = Column(Float, nullable=True)         # overall band, e.g. 6.5
    toefl_score = Column(Integer, nullable=True)       # total iBT, e.g. 90
    gre_gmat_required = Column(Integer, nullable=True)  # 0 no | 1 optional | 2 yes | NULL unstated
    duration_months = Column(Integer, nullable=True)   # lower bound of a range ("3-4 years" -> 36)
    entry_requirements = Column(Text, nullable=True)   # short free text (GPA, prerequisites)
    course_url = Column(String, nullable=True)         # official program page
    is_active = Column(Boolean, nullable=False, default=True)
    last_verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    university = relationship("CourseCatalogUniversity", back_populates="courses")

    __table_args__ = (
        UniqueConstraint("university_id", "name_key", "degree_level", name="uq_course_catalog_course"),
        Index("ix_course_catalog_course_country_level", "country_code", "degree_level"),
    )


class CourseCatalogRefreshRun(Base):
    """One catalog-agent run per day. run_date is UNIQUE so concurrent workers can't
    double-run (same IntegrityError-skip pattern as AIDailyNotificationRun)."""
    __tablename__ = "course_catalog_refresh_runs"

    id = Column(Integer, primary_key=True, index=True)
    run_date = Column(Date, nullable=False, unique=True, index=True)
    status = Column(String, nullable=False, default="running")  # running | completed | failed
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    universities_discovered = Column(Integer, nullable=False, default=0)
    universities_refreshed = Column(Integer, nullable=False, default=0)
    courses_upserted = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    detail = Column(Text, nullable=True)               # JSON per-country breakdown

class EnterpriseCourseFinderRec(Base):
    """A stored Course Finder AI recommendation (org-scoped, optionally per-client).

    Persisted like Deep Scans so a PAID result can never be lost to a tab switch or
    timeout — consultants re-open past shortlists from the history list. client_name
    is snapshotted because client_id rows cascade away when a client is deleted only
    for client-linked recs; unlinked (general) recs keep client_id NULL.
    """
    __tablename__ = "enterprise_course_finder_recs"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("enterprise_clients.id", ondelete="CASCADE"), nullable=True, index=True)
    client_name = Column(String, nullable=True)        # snapshot for history display
    country_code = Column(String, nullable=True)
    degree_level = Column(String, nullable=True)
    discipline = Column(String, nullable=True)
    query = Column(Text, nullable=True)                # JSON of the full request (field, budget, notes…)
    summary = Column(Text, nullable=True)              # AI overview paragraph
    recommendations = Column(Text, nullable=True)      # JSON list of recommendation objects
    catalog_based = Column(Boolean, nullable=False, default=True)   # built from our verified catalog rows
    grounded = Column(Boolean, nullable=False, default=False)       # live web search supplemented
    model_used = Column(String, nullable=True)         # internal only — never sent to the frontend
    credits_charged = Column(Integer, nullable=False, default=0)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        Index("ix_ent_course_finder_recs_org_created", "organization_id", "created_at"),
    )


class EnterpriseLeadForm(Base):
    """An org-branded public lead-collection form (shared as a link / by email).

    public_token is stored RAW (not hashed, unlike portal/pay tokens) on purpose:
    the link is public-by-design — it only reveals the form definition and org
    branding, grants no data access, and the org must be able to re-copy the same
    link from the UI at any time. Pausing (is_active) or rotating the token kills
    the old link. The field schema lives in fields_json as a JSON list of
    {key,label,type,required,placeholder,options} objects (house JSON-in-Text style).
    """
    __tablename__ = "enterprise_lead_forms"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    name = Column(String, nullable=False)              # internal name shown in the console
    title = Column(String, nullable=True)              # public heading (falls back to name)
    intro_text = Column(Text, nullable=True)           # public intro paragraph
    fields_json = Column(Text, nullable=False)         # JSON list of field definitions
    public_token = Column(String, nullable=False, unique=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    submit_label = Column(String, nullable=True)
    success_message = Column(String, nullable=True)
    notify_email = Column(String, nullable=True)       # optional "new lead" alert inbox
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_ent_lead_forms_org_created", "organization_id", "created_at"),
    )


class EnterpriseLead(Base):
    """One public form submission (a lead) in an org's inbox.

    Leads outlive their form (form_id SET NULL + form_name snapshot — collected
    contacts are business data) and link to the client they become on conversion.
    answers_json is a JSON list of {key,label,type,value} preserving the form's
    field order at submission time; name/email/phone are denormalized copies of
    the matching answers so the inbox list and convert-to-client prefill never
    parse JSON in a query loop.
    """
    __tablename__ = "enterprise_leads"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("enterprise_organizations.id"), nullable=False, index=True)
    form_id = Column(Integer, ForeignKey("enterprise_lead_forms.id", ondelete="SET NULL"), nullable=True, index=True)
    form_name = Column(String, nullable=True)          # snapshot for display after form deletion
    full_name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    answers_json = Column(Text, nullable=False)        # JSON list of {key,label,type,value}
    status = Column(String, nullable=False, default="new", index=True)  # new|contacted|converted|closed
    converted_client_id = Column(Integer, ForeignKey("enterprise_clients.id", ondelete="SET NULL"), nullable=True, index=True)
    ip_address = Column(String, nullable=True)
    source = Column(String, nullable=True)             # referrer / utm hint captured by the public page
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_ent_leads_org_created", "organization_id", "created_at"),
        Index("ix_ent_leads_org_status", "organization_id", "status"),
    )
