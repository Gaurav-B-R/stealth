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

Force F1 news ingestion manually:

```bash
python -c "from app.services.f1_visa_news_ingestion import run_f1_news_ingestion_job; print(run_f1_news_ingestion_job(force=True))"
```

Admin-triggered daily notification run (authenticated admin session required):

- `POST /api/notifications/daily/run-now?force=true`

## 4) Schema And Data Maintenance

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
