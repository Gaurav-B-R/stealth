# Rilono Architecture

Last updated: 2026-03-25

## System Overview

Rilono is a FastAPI monolith that serves:

- A browser-based frontend from `static/`
- API endpoints under `/api/*`
- Background schedulers for proactive workflows

At runtime, it integrates with:

- SQL database via SQLAlchemy (`sqlite:///./rilono.db` default)
- Cloudflare R2 for document and artifact storage
- Gemini (Google GenAI/Vertex) for AI features
- Resend for email delivery and contacts sync
- Razorpay for subscription payments
- Cloudflare Turnstile for bot protection

## High-Level Flow

1. Browser requests `/` and receives `static/index.html` (or `/enterprise` for enterprise views).
2. Frontend calls API routes in `app/routers/*`.
3. Routers use `SessionLocal` from `app/database.py` for persistence.
4. Services call external providers (R2, Gemini, Resend, Razorpay) as needed.
5. Startup hooks run schema safety patches/backfills and start scheduler threads.

## Main Modules

- `app/main.py`
  - Builds the FastAPI app.
  - Adds CORS and security headers.
  - Mounts `static/` and `uploads/`.
  - Includes routers.
  - Runs startup schema checks and scheduler boot.
- `app/database.py`
  - SQLAlchemy engine/session/base setup.
- `app/models.py`
  - Core entities: users, documents, subscriptions, notifications, enterprise.
- `app/routers/*`
  - Domain-specific API boundaries:
    - `/api/auth`
    - `/api/profile`
    - `/api/documents`
    - `/api/ai-chat`
    - `/api/upload`
    - `/api/subscription`
    - `/api/pricing`
    - `/api/news`
    - `/api/notifications`
    - `/api/admin`
    - `/api/enterprise`
- `app/services/*`
  - Daily AI notifier
  - F1 visa news ingestion
  - Resend contacts sync

## Data Model (Core Tables)

- `users`: identity, auth state, referral fields, notification settings.
- `documents`: uploaded files + AI extraction/validation metadata.
- `document_type_catalog`: stage-aware document taxonomy and gate metadata.
- `subscriptions` and `subscription_payments`: plan usage + payment lifecycle.
- `user_notifications`: bell/in-app notifications.
- `enterprise_*` tables: enterprise credentials, organizations, members, students.
- `f1_visa_news`: cached/generated F1 visa news feed items.

## Startup Lifecycle

`app/main.py` startup currently performs:

1. Schema safety checks (`ensure_*` functions in `app/schema_patch.py`)
2. Catalog seeding (`ensure_default_document_type_catalog`)
3. Backfills:
   - missing subscriptions
   - missing referral codes
   - token hash backfill
4. Enterprise credential sync into `users`
5. Scheduler startup:
   - daily AI notifications

## Background Processing

- Daily AI notifications:
  - Service: `app/services/daily_ai_notifications.py`
  - Purpose: analyze profile + document artifacts and send proactive nudges
  - Default schedule: 06:00 UTC (poll loop)
- Catalog research and latest-news ingestion are retired. They are not started with the app; their compatibility entrypoints perform no AI calls or database writes, even with `force=True` or old enable flags.
- B2C and B2B Course Finder rank saved course records with tool-free Gemini calls. No catalog discovery, refresh, web-search fallback or link probing runs during recommendations.
- Published applicant experiences retain their existing on-demand Google Search and caching behavior.

Other configured background services continue to run. See [catalog and news policy](catalog-and-news-policy.md).

## Security Model (Current)

- JWT auth with cookies (`AUTH_COOKIE_*` configuration).
- CSRF origin/referer checks for cookie-auth flows.
- Turnstile checks on auth and enterprise login paths (config-controlled).
- Request rate limiting via `app/utils/rate_limiter.py`.
- Security headers middleware:
  - CSP (configurable)
  - HSTS on HTTPS
  - frame/content/referrer protections
- Encrypted artifact handling via `app/utils/secure_artifacts.py`.

## Multi-Tenant Enterprise Routing

- Root domain requests serve standard product routes.
- Subdomain requests matching `*.{ENTERPRISE_ROOT_DOMAIN}` are redirected to `/enterprise`.
- Enterprise APIs are under `/api/enterprise`.
