# Gemini Google Cloud account switch

This release routes Gemini and the existing Cloud Text-to-Speech voice through
the selected Cloud identity and billing project. Model candidates, prompts,
generation limits, grounding, background jobs, Neural2 voice, and product features
remain unchanged. The default remains `developer` until the Cloud configuration
is saved and deployed.

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
`aiplatform.googleapis.com` and `texttospeech.googleapis.com` enabled, and grant
the service account `roles/aiplatform.user`. The existing role was sufficient for
the verified Neural2 request in this project; no additional identity or role was
needed. Model availability, speech synthesis, and credit eligibility must be
verified in that account before routing production traffic.

The dedicated `GEMINI_VERTEX_CREDENTIALS` path is intentional. Do not replace it
with a global `GOOGLE_APPLICATION_CREDENTIALS` setting for this migration.

## Text-to-speech and the old API key

In `vertex` mode, mock-interview speech uses the same dedicated service-account
identity as Gemini and sends `x-goog-user-project` with the credited project ID.
Its existing `en-US-Neural2-D` voice and audio settings are preserved. The speech
client caches a separate short-lived token for that identity, so it does not
change the Gemini SDK's token state or need another credential file.

Neither Gemini nor speech falls back to `GEMINI_API_KEY` or `GOOGLE_TTS_API_KEY`
in Cloud mode. After a production speech request and the Gemini checks succeed,
the old key can be removed from this service. Revoke it in its original project
only after confirming no other application still depends on it. Local Developer
mode retains its previous credential behavior.

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
   enterprise tools, grounding, and one short Neural2 speech request. Verify
   billing attribution against the credited project; an empty immediate billing
   report is not proof that no usage was billed.

## Failure and deliberate rollback

Cloud mode never falls back to the retained paid API key. Missing local Cloud
credentials disable AI requests; API authorization, quota, or model failures stay
on Cloud across the existing model-candidate retries. Other application features
remain available. An unsupported `GEMINI_PROVIDER` value rejects application
startup. Speech authentication or synthesis failures retain the browser speech
fallback, without attempting either old API key.

To deliberately restore the previous provider, restore the previous API key if
it has been removed, set `GEMINI_PROVIDER=developer`, and deploy. This resumes
Gemini and applicable speech charges on the old API-key account. The dedicated
Cloud secret and other Cloud variables are ignored in this mode. Do not use this
rollback implicitly in response to a Cloud error.

## Offline verification

The migration has 24 focused Gemini tests, 13 speech authentication tests, and 50
existing relevant regression tests. The test environment uses SQLite and fake
non-production configuration; no API calls
are needed. With pytest and dependencies installed:

```sh
DATABASE_URL=sqlite:// GEMINI_API_KEY= GEMINI_PROVIDER=developer \
SECRET_KEY=gemini-migration-tests-only-not-a-secret \
R2_ACCOUNT_ID=gemini-migration-tests R2_ACCESS_KEY_ID=test R2_SECRET_ACCESS_KEY=test \
AWS_EC2_METADATA_DISABLED=true PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q \
  tests/test_gemini_cloud.py tests/test_gemini_cloud_consumers.py \
  tests/test_officer_tts_cloud.py \
  tests/test_enterprise_ai_client_profile.py \
  tests/test_enterprise_copilot_profile.py \
  tests/test_enterprise_deep_scan_profile.py \
  tests/test_course_finder_subject_rule.py \
  tests/test_ai_identity_guardrails.py
```
