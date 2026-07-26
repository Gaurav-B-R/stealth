"""Single source of truth for the version of the legal documents users consent to.

Bump ``LEGAL_TERMS_PRIVACY_VERSION`` whenever the Terms & Conditions or Privacy
Policy change materially, and keep it in sync with the "Last Updated" dates rendered
on the legal pages (see ``LEGAL_LAST_UPDATED`` in ``static/app.js``). Every
proof-of-consent record (B2C signup, OAuth signup, enterprise signup) stores this
value so we can prove exactly which version of the documents a user agreed to, and
so we can later detect users who consented to an older version and re-prompt them.
"""

# Matches the most recent Privacy Policy / Terms "Last Updated" date shown to users.
#
# v2026-07-25 changed the published Grievance Officer contact in the Privacy Policy from
# grievance@rilono.com to contact@rilono.com — Rilono operates a single monitored mailbox,
# and a published grievance address that bounces is worse than none. The same address is
# now used in the DPA and in the B2C data-export notice (app/routers/profile.py).
LEGAL_TERMS_PRIVACY_VERSION = "2026-07-25"

# Version of the enterprise Data Processing Agreement (DPA) accepted by organizations
# that handle their own clients' personal data through Rilono Enterprise.
#
# v2026-07-24 covers the rewritten DPA, which replaced the placeholder text with what the
# platform actually does:
#   * a real sub-processor register (the named third parties that process client data),
#   * an accurate description of the technical and organizational security measures,
#   * Rilono Finance (payment collection on behalf of the organization),
#   * the direct interactions Rilono has with an organization's own clients
#     (client portal shares, document requests, notification email),
#   * stated retention periods (kept in sync with the defaults in
#     app/services/document_retention.py), and
#   * Annexes I-III (processing details, security measures, sub-processors).
#
# Bumping this value makes every organization that accepted an EARLIER version show as
# requiring re-acceptance: enterprise_organizations.dpa_accepted_version no longer matches
# LEGAL_DPA_VERSION, so those orgs are re-prompted to accept the current DPA.
LEGAL_DPA_VERSION = "2026-07-25"

# Version of the Rilono Finance bank-connect eligibility attestations. Bump whenever the
# checkbox wording in the Finance onboarding form (static/enterprise.js) changes, so the
# stored proof records exactly which wording was attested to.
# v2026-07-16 wording:
#   1. "My organization directly provides the visa/education service the student is
#      paying for."
#   2. "The details above are accurate and my business is eligible to receive these
#      payments."
FINANCE_ATTESTATION_VERSION = "2026-07-16"
