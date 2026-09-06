# Gemini Google Cloud account switch

This release routes Gemini through the selected provider without changing model
candidates, prompts, generation limits, grounding, background jobs, or product
features. The default remains `developer` until the Cloud configuration is saved
and deployed.

## Production environment contract

Create the Render secret file `vertex-service-account.json` containing the
dedicated service account JSON. Set these environment variables on every service
that executes Gemini requests:

```dotenv
GEMINI_PROVIDER=vertex
GOOGLE_CLOUD_PROJECT=YOUR_CREDITED_PROJECT_ID
GOOGLE_CLOUD_LOCATION=global
GEMINI_VERTEX_CREDENTIALS=/etc/secrets/vertex-service-account.json
```

The project must be linked to the billing account containing the credit, have
`aiplatform.googleapis.com` enabled, and grant the service account
`roles/aiplatform.user`. Model availability and credit eligibility must be
verified in that account before routing production traffic.

The dedicated `GEMINI_VERTEX_CREDENTIALS` path is intentional. Do not replace it
with a global `GOOGLE_APPLICATION_CREDENTIALS` setting for this migration.

## Existing text-to-speech credential

Retain the existing `GEMINI_API_KEY`. Mock-interview speech uses Google Cloud
Text-to-Speech and can use that key independently of Gemini. Leaving the key in
place preserves its current behavior and billing account. This migration moves
Gemini model calls only; existing Text-to-Speech charges can continue on the old
account.

In `vertex` mode, all Gemini clients receive explicit service-account credentials,
project, and location. They ignore the retained API key, including grounded news
and course requests and enterprise tool calls.

## Stage and deploy

1. Confirm the reviewed migration commit is the intended release and the new
   service account can access the required models in the credited project.
2. Add the secret file and four variables in Render. Choose **Save only** while
   staging if Render offers that action; do not select a save-and-deploy action
   until the migration release and complete configuration are ready together.
3. Deploy the reviewed release with the staged environment. Keep existing model,
   job, and other service settings unchanged.
4. Confirm the startup log reports `Gemini provider: Google Cloud` with the
   intended project and location. Verify chat, an image/PDF, interview history,
   enterprise tools, and grounding with small requests. Verify billing attribution
   against the credited project; an empty immediate billing report is not proof
   that no usage was billed.

## Failure and deliberate rollback

Cloud mode never falls back to the retained paid API key. Missing local Cloud
credentials disable AI requests; API authorization, quota, or model failures stay
on Cloud across the existing model-candidate retries. Other application features
remain available. An unsupported `GEMINI_PROVIDER` value rejects application
startup.

To deliberately restore the previous Gemini provider, set
`GEMINI_PROVIDER=developer` and deploy. This resumes Gemini charges on the old
API-key account. The dedicated Cloud secret and other Cloud variables are ignored
in this mode. Do not use this rollback implicitly in response to a Cloud error.

## Offline verification

The migration has 24 focused tests and 50 existing relevant regression tests. The
test environment uses SQLite and fake non-production configuration; no API calls
are needed. With pytest and dependencies installed:

```sh
DATABASE_URL=sqlite:// GEMINI_API_KEY= GEMINI_PROVIDER=developer \
SECRET_KEY=gemini-migration-tests-only-not-a-secret \
R2_ACCOUNT_ID=gemini-migration-tests R2_ACCESS_KEY_ID=test R2_SECRET_ACCESS_KEY=test \
AWS_EC2_METADATA_DISABLED=true PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q \
  tests/test_gemini_cloud.py tests/test_gemini_cloud_consumers.py \
  tests/test_enterprise_ai_client_profile.py \
  tests/test_enterprise_copilot_profile.py \
  tests/test_enterprise_deep_scan_profile.py \
  tests/test_course_finder_subject_rule.py \
  tests/test_ai_identity_guardrails.py
```
