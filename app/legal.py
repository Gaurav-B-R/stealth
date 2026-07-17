"""Single source of truth for the version of the legal documents users consent to.

Bump ``LEGAL_TERMS_PRIVACY_VERSION`` whenever the Terms & Conditions or Privacy
Policy change materially, and keep it in sync with the "Last Updated" dates rendered
on the legal pages (see ``LEGAL_LAST_UPDATED`` in ``static/app.js``). Every
proof-of-consent record (B2C signup, OAuth signup, enterprise signup) stores this
value so we can prove exactly which version of the documents a user agreed to, and
so we can later detect users who consented to an older version and re-prompt them.
"""

# Matches the most recent Privacy Policy / Terms "Last Updated" date shown to users.
LEGAL_TERMS_PRIVACY_VERSION = "2026-07-16"

# Version of the enterprise Data Processing Agreement (DPA) accepted by organizations
# that handle their own clients' personal data through Rilono Enterprise.
LEGAL_DPA_VERSION = "2026-06-20"

# Version of the Rilono Finance bank-connect eligibility attestations. Bump whenever the
# checkbox wording in the Finance onboarding form (static/enterprise.js) changes, so the
# stored proof records exactly which wording was attested to.
# v2026-07-16 wording:
#   1. "My organization directly provides the visa/education service the student is
#      paying for."
#   2. "The details above are accurate and my business is eligible to receive these
#      payments."
FINANCE_ATTESTATION_VERSION = "2026-07-16"
