"""Single source of truth for the version of the legal documents users consent to.

Bump ``LEGAL_TERMS_PRIVACY_VERSION`` whenever the Terms & Conditions or Privacy
Policy change materially, and keep it in sync with the "Last Updated" dates rendered
on the legal pages (see ``LEGAL_LAST_UPDATED`` in ``static/app.js``). Every
proof-of-consent record (B2C signup, OAuth signup, enterprise signup) stores this
value so we can prove exactly which version of the documents a user agreed to, and
so we can later detect users who consented to an older version and re-prompt them.
"""

# Matches the Privacy Policy / Terms "Last Updated" date shown to users.
LEGAL_TERMS_PRIVACY_VERSION = "2026-06-20"

# Version of the enterprise Data Processing Agreement (DPA) accepted by organizations
# that handle their own clients' personal data through Rilono Enterprise.
LEGAL_DPA_VERSION = "2026-06-20"
