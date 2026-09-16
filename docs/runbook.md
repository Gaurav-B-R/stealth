# Rilono Runbook

Last updated: 2026-03-25

## 1) Local Development Startup

From repository root:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Alternative helper script:

```bash
./run.sh
```

Primary local URLs:

- App: `http://localhost:8000`
- OpenAPI: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`
- App metadata: `http://localhost:8000/api/meta`

## 2) Environment Configuration Baseline

Minimum core:

- `SECRET_KEY`
- `DATABASE_URL` (optional for local; defaults to `sqlite:///./rilono.db`)

Common production/security:

- `ENVIRONMENT=production`
- `CORS_ALLOW_ORIGINS`
- `AUTH_COOKIE_SECURE=true`
- `AUTH_COOKIE_SAMESITE`
- `AUTH_COOKIE_DOMAIN` (when needed)
- `CSRF_TRUSTED_ORIGINS`
- `ENABLE_CSP` and optional `CONTENT_SECURITY_POLICY`

Feature groups:

- Email: `RESEND_*`, `BASE_URL`, `USE_TEST_EMAIL`
- Turnstile: `TURNSTILE`, `TURNSTILE_ENABLED`, `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`
- Storage: `R2_*`
- AI: `GEMINI_API_KEY` and/or Vertex settings
- Payments: `RAZORPAY_*`, plan amount/currency vars
- Background jobs: `DAILY_AI_NOTIFIER_*`, `F1_NEWS_INGESTION_*`

To inspect current env usage in code:

```bash
rg -o 'os\.getenv\("[A-Z0-9_]+"' app/*.py app/**/*.py | sed -E 's/.*"([A-Z0-9_]+)"/\1/' | sort -u
```

## 3) Routine Operational Tasks

Run contacts sync with Resend:

```bash
python -m app.services.resend_contacts_sync --dry-run
python -m app.services.resend_contacts_sync
```

Notification unsubscribes are app-level only. Do not provider-unsubscribe users in Resend for notification opt-outs, because password resets, email verification, and enterprise invite emails are transactional and must still be delivered.

Force daily notification job manually:

```bash
python -c "from app.services.daily_ai_notifications import run_daily_ai_notification_job; print(run_daily_ai_notification_job(force=True))"
```

Latest-news ingestion and automated university/course research are retired. Their scheduler, manual and forced job entrypoints are inert, including when old environment flags are enabled. The admin catalog refresh endpoint returns HTTP 410. Maintain catalog records manually; stored records and earlier research history are retained.

The published applicant-experiences feature retains its existing on-demand Google Search behavior and cache. It is the sole remaining allowed Gemini Search grounding path. See [catalog and news policy](catalog-and-news-policy.md).

Admin-triggered daily notification run (authenticated admin session required):

- `POST /api/notifications/daily/run-now?force=true`

## 4) Schema And Data Maintenance

### Admin console Team access

Use **Team** in the admin console to grant an existing personal Rilono account
access by email. This does not create an account or send an invitation. Enterprise-only accounts keep
their separate workspace login and cannot be added through this flow.

When adding or editing a manageable Team member, an Admin with Team access can
set a separate **Console password** and confirm it. Leaving the fields blank
preserves the member's current sign-in method. Until a console password is set,
the member signs in at `/admin_console` with their existing Rilono password.
After setup, that page requires their email and console password. Share the
password and console link directly with the member; no password email is sent.
The account must be active and email-verified to sign in.

Console passwords use the existing password-strength policy and are stored only
as hashes. They are never returned in member lists or password-update responses.
Setting a new console password invalidates the member's console sessions. It
does not change their personal or Enterprise password, encrypted documents, or
normal app sessions. Existing platform administrators remain protected from
password changes through Team.

| Role | Access within assigned sections |
| --- | --- |
| Admin | Read, make changes, and delete; manage Team when Team is assigned |
| Editor | Read and make changes; no deletion, refunds, or Team management |
| Viewer | Read and export; no changes |

Section grants cover Student Accounts, Enterprise Accounts, Analytics & Agent,
Investment Analytics, AI Costs, and Team. Each section includes the data already
shown within that page and its exports. Team can be assigned only to an Admin;
an Admin cannot grant sections they do not have, change their own access, or
manage a teammate with broader access. Existing platform admins/developers retain
their full access and are protected from changes through Team. Enterprise
credential provisioning remains restricted to those existing platform accounts.

Roles and sections are stored in `admin_console_access` in the application SQL
database, separate from the legacy `users.is_admin` and `users.is_developer`
flags. Every admin API request checks the stored grant; revocation takes effect
on the next request. Removing Team access preserves the person's Rilono account.
Credentials and sessions are stored separately in `admin_console_credentials`
and `admin_console_sessions`. The console uses a dedicated HttpOnly cookie and
stores session tokens only as hashes. Console login/logout do not sign the person
into or out of the student or Enterprise app. Once a dedicated console password
exists, a personal app session alone cannot enter that member's console.
The normal startup table creation creates these new tables. No root migration
script or manual role backfill is needed.

### Existing schema maintenance

Current startup behavior already runs:

- schema patch helpers in `app/schema_patch.py`
- catalog/default data seeding
- backfills for subscriptions/referrals/auth tokens

Legacy one-off migration scripts exist at repository root (`migrate_*.py` and similar).
Use them carefully and only after validating target environment/schema.

## 5) Incident Triage Quick Map

Login or auth failures:

- Check cookie security/env mismatch (`AUTH_COOKIE_*`, `ENVIRONMENT`)
- Check Turnstile key config and Cloudflare verification path
- Check rate limits in `app/utils/rate_limiter.py`

Document upload or extraction failures:

- Verify `R2_*` credentials/bucket config
- Confirm object accessibility and artifact encryption key configuration

Email delivery failures:

- Verify `RESEND_API_KEY`, sender domain settings, `BASE_URL`, and `USE_TEST_EMAIL`
- Check logs from `app/email_service.py`

Subscription/payment failures:

- Validate `RAZORPAY_*` keys and webhook secret
- Check records in `subscription_payments`

## 6) Verification Checklist After Deploy

1. `GET /health` returns healthy.
2. Frontend loads from `/`.
3. Login/register flow works with expected Turnstile behavior.
4. Document upload and listing work for a test user.
5. `/api/meta` reports expected app version/name.
6. Background schedulers log normal startup messages.

## 7) Current Gaps

- No automated test suite is currently checked in.
- Scheduler jobs are in-process; multi-instance deployment requires duplication controls.
