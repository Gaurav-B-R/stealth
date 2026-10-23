# Rilono Architecture

Last updated: 2026-10-23

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
  - Daily AI notifier (skips enterprise accounts: `users.is_enterprise_account` or any active enterprise membership)
  - F1 visa news ingestion
  - Resend contacts sync

### Enterprise (B2B) pricing and metering modules

These modules were introduced or reshaped by pricing v2 on 2026-10-22; see [decisions.md](decisions.md) D-009.

- `app/money.py`: the single source of truth for money. `PRICE_BOOK` holds the ex-tax plan prices and top-up packs per currency. Other helpers: yearly price (`yearly_minor`, 10x monthly), GST (`tax_percent_for`, `quote_with_tax`, and `tax_note()`, which is the only producer of "+ GST" and returns "" at 0%), and `format_money`.
- `app/enterprise_billing.py`: the plan catalog (`PLANS`, which holds limits but no prices) and `effective_limits` (plan, then admin overrides, then Branch Packs). It also covers:
  - open-file counting and the over-limit grace (`open_client_count`, `enforce_client_limit_or_402`, also called on reopen)
  - Team-feature gating (`has_feature` / `enforce_feature_or_402`)
  - the shared AI-paused gate (`ai_access_state` / `enforce_ai_access_or_402`)
  - the currency-region rule (`charge_currency_for_org`)
  - yearly gating (`yearly_enabled`, `normalize_billing_cycle`)
  - `checkout_quote`, `public_plans_payload`, and `build_subscription_state` (what the portal renders)
- `app/enterprise_credits.py`: the credit wallet and ledger. It holds the action price list (`ACTIONS`, `action_cost(key, units)`, and `actions_payload()` with a `price_label` such as "4 credits per 15 pages"), the per-period plan allowance (`sync_plan_credits`, which also syncs reads), and the monthly reading allowance (`reads_state`, `consume_reads`, `release_reads`). It also has the assistant's per-turn cost budget (`copilot_turn_budget`) and the demo-call bonus. Every enforce, charge or precheck function calls the AI-paused gate first.
- `app/enterprise_catalog.py`: the client stages. `is_open` decides what counts as an open file; `closed` is the terminal "no visa outcome" stage; `is_reopen` defines a reopen.
- `app/enterprise_coupons.py`: discount codes, capped at `ENTERPRISE_COUPON_MAX_PERCENT`.
- `app/email_domains.py`: decides whether an email is at a company domain or a public mailbox, for the one-trial-per-company rule applied at enterprise signup.
- `app/enterprise_public_pricing.py`: the server-side renderer for `{{ENT_*}}` price, limit and tax tokens, and `{{ENT_IF_FLAG}}…{{ENT_END_IF_FLAG}}` blocks, in static marketing pages. `app/main.py` `_render_static_page` calls it for every page served through `_read_static_html`, including the homepage, so prices are in the initial HTML. Its values come from `public_plans_payload`, `trial_facts`, `credits.actions_payload` and `money.tax_note`. Prices are written in the visitor's own region currency (`billing.public_price_currency` on the request's CDN geo header): INR from the INR region, the visitor's ladder currency or USD from anywhere else, including an unknown country. There are no per-currency or "International" tokens, JSON-LD answers and meta descriptions carry no price, and a priced page is served `Cache-Control: private, no-cache` with `Vary` on the geo headers.
- `app/enterprise_help.py` and `app/prompts/ENTERPRISE_HELP_GUIDE.md`: the assistant's product-help knowledge base. Placeholders in the guide are generated live from the registries above, and `tests/test_enterprise_help.py` fails when the guide drifts from them.
- `app/utils/gemini_service.py`: model routing. `CHEAP_MODEL_CANDIDATES` (`gemini-3.1-flash-lite` → `gemini-3.5-flash` → `gemini-3.1-pro-preview`) is the default for the enterprise assistant, Deep Scan, the Chrome-extension copilot and upload reading. Reading helpers: `count_document_pages`, `read_blocks_for`, `enterprise_read_units`, and `extract_text_from_document(..., model_candidates, max_blocks)`, which reads PDFs in 15-page blocks with `pypdf`.

## Data Model (Core Tables)

- `users`: identity, auth state, referral fields, notification settings.
- `documents`: uploaded files + AI extraction/validation metadata.
- `document_type_catalog`: stage-aware document taxonomy and gate metadata.
- `subscriptions` and `subscription_payments`: plan usage + payment lifecycle.
- `user_notifications`: bell/in-app notifications.
- `enterprise_*` tables: enterprise credentials, organizations, members, students.
  - `enterprise_subscriptions`: plan, status, period, trial end. Pricing v2 added `files_over_limit_since`, `branch_packs`, the `override_*` limits, `demo_bonus_granted_at` and `trial_domain_blocked`.
  - `enterprise_subscription_payments`: plan payments from checkout, plus offline payments recorded by Rilono staff (`razorpay_order_id = "offline:<reference>"`).
  - `enterprise_credit_wallets`: balance and plan-credit period. Pricing v2 added the reads allowance: `reads_period`, `reads_granted`, `reads_used`.
  - `enterprise_client_documents.read_status` / `read_blocks`: whether free AI reading ran.
  - `enterprise_interview_sessions`: server-side mock interviews, with `status`, `questions_asked`, `credits_charged`, `invite_id` and `run_token_hash`.
- `f1_visa_news`: cached/generated F1 visa news feed items.

## Startup Lifecycle

`app/main.py` startup currently performs:

1. Schema safety checks (`ensure_*` functions in `app/schema_patch.py`, including `ensure_enterprise_pricing_v2_columns`: additive and idempotent)
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

## Enterprise Pricing Flows (pricing v2, 2026-10-22)

**Public price list.** `GET /api/enterprise/public/plans` needs no login and is rate-limited per IP (`ENTERPRISE_PUBLIC_PLANS_RATE_*`). It returns plan cards, action prices, top-up packs, trial facts, Branch Pack facts, `tax` {percent, label, note} and `yearly_enabled`. The visitor's CDN geo country picks the currency (`billing.public_price_currency`): INR-region visitors always get INR; everyone else, including an unknown country, never does. One region's prices per visitor: `price_options` ladders are limited to `currencies` (the visitor's region), and outside INR the rupee fields (`price_inr`, `price_display`, `value_inr`) are dropped. An optional `?currency=` hint is honoured only within the region. The portal's `/billing/plans` and `/credits/wallet` limit their ladders to the org's `charge_currencies` the same way, and the assistant's help and credit-price tools quote the org's own billing currency. The response sets `Cache-Control: public, max-age=…` and `Vary` on the geo headers. `app/main.py` exempts this one path from the global `/api/` no-store rewrite, and only for a 200 that declares itself public. The `/pricing` card (`static/app.js`) loads prices from it. The signed-in portal gets the same cards from `/billing/plans`, and the marketing pages get the same numbers server-side through `app/enterprise_public_pricing.py`.

**AI-paused gate.** Every enterprise AI entry point calls `enterprise_billing.enforce_ai_access_or_402` before any model call or charge, either directly or through the `enterprise_credits` enforce and charge functions. That covers the assistant and Chrome extension, Deep Scan, document check, Writing Studio, Course Finder, staff and public mock interviews, client Copilot links, and "Read now". Public client links use the `client_facing=True` wording. Free upload reading does not raise: `consume_reads` returns False and the file is stored `not_read`. Credit top-up checkout is gated the same way. Top-up verify and webhooks are not, so captured money is always credited.

**Upload reading (reads allowance).**

1. A staff upload, client secure-link upload, lead conversion, or re-scan stores the file (R2) and sets `read_status = "pending"`.
2. A background worker takes `gemini_service.enterprise_read_units(contents, …, max_blocks=ENTERPRISE_READ_MAX_BLOCKS)` reads with `enterprise_credits.consume_reads`.
3. If the reads can't be taken (allowance used up, or AI paused), the document becomes `not_read` and no model is called.
4. Otherwise `extract_text_from_document(..., model_candidates=enterprise_read_model_candidates(), max_blocks=…)` reads it in 15-page blocks on the cheap chain. Usage is recorded under source `enterprise_document_read`, and success sets `read` and `read_blocks`.
5. On failure the document becomes `failed`, and `release_reads` returns the reads for the period captured before consuming.

"Read now" (`POST /api/enterprise/clients/{id}/documents/{doc_id}/read`) takes the reads synchronously, so an insufficient allowance is a 402, and then queues the same worker. A paid document check (`document_scan`, charged as `action_cost(key, document_scan_units(pages))`) reads the file itself and never consumes reads.

**Plan allowance sync.** `sync_plan_credits` grants credits and reads once per period key (`<plan>:<period start>`, or `<plan>:once` for the trial). A yearly coverage is cut into monthly sub-periods. A plan change inside a live period grants only `max(0, new allowance − already granted)`.

**Rupee prices need an Indian payment method ([D-011](decisions.md#d-011-rupee-prices-are-paid-with-indian-payment-methods)).** An INR plan or credit checkout for an org billed in India is "domestic-only". `billing.domestic_only_charge` decides this, and the row stores it in `domestic_only`.

- **One-off orders** are created with manual capture (`billing.domestic_only_order_options`). `/billing/verify`, `/credits/topup/verify` and the credits webhook's `payment.authorized` branch run `_inr_card_rule` on the payment entity (`international` / `card.international`). They then capture (`POST /payments/:id/capture`) only what `ENTERPRISE_INR_FOREIGN_CARD_POLICY` accepts.
- **Mandates** are checked in `/billing/verify` and `_handle_subscription_charged` after capture.
- **On a refusal**, the row becomes `foreign_card_refused` or `foreign_card_refund_due`. Neither is a revenue status. A captured charge is refunded, and a mandate is cancelled.
- **Under `reprice`**, the org gets `inr_barred_at`, which `billing.org_billing_country` reads to keep it off INR.

Every honouring path checks the refused statuses under the same row lock as its existing idempotency check, so a replayed verify or a redelivered webhook never grants or refunds twice.

**Admin billing controls.** These live in the admin console's enterprise account, under `/api/admin/enterprise/accounts/{id}/…`:

- `offline-payment`: records a Payment Link, bank transfer or invoice payment, activates the plan and extends the period. It is idempotent on the reference.
- `credits/adjust`: signed adjustments, or the once-only demo-call bonus.
- `overrides`: Branch Packs, limit overrides and the trial-end extension.

Offline payments and overrides re-run `sync_plan_credits`, so raised allowances and packs land immediately.
