# Rilono Runbook

Last updated: 2026-10-23

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
- AI: `GEMINI_API_KEY` and/or Vertex settings; model chains via `*_MODEL` / `*_MODEL_CANDIDATES` (see section 7 — no Gemini 2.5/2.0 ids since their 2026-10-20 retirement)
- Payments: `RAZORPAY_*`, plan amount/currency vars
- Enterprise plans, credits, reads, tax and currency: `ENTERPRISE_*` (full list with defaults in section 7)
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
- Check records in `subscription_payments` (B2C) and `enterprise_subscription_payments` (B2B; offline payments recorded in the admin console have `razorpay_order_id = "offline:<reference>"`)

Enterprise customer says AI "stopped working" or every AI button answers 402:

- Their trial ended or their paid plan lapsed — the shared AI-paused gate (`enterprise_billing.ai_access_state`). The admin console's enterprise account shows the AI-paused state, trial end and plan period. Fix by recording the payment (offline payment), extending `trial_ends_at` (overrides), or, for a platform-wide misfire, `ENTERPRISE_AI_PAUSE_ON_EXPIRY=false`.
- A 402 that names credits rather than the plan is an empty wallet, not a pause.

Enterprise customer can't add a client:

- Open files over the plan limit after the grace period (`ENTERPRISE_FILE_LIMIT_GRACE_DAYS`), or the trial has ended. The 402 detail says which. Closing finished files (stage "Closed") frees slots; an admin override of `max_clients` or a Branch Pack raises the limit.

Uploaded documents show "Not read yet":

- The org's monthly AI document reads are used up (or AI is paused). Expected behaviour: the file is stored, and "Read now" reads it once reads are available. Raise `monthly_reads` with an admin override if agreed with the customer.

## 6) Verification Checklist After Deploy

1. `GET /health` returns healthy.
2. Frontend loads from `/`.
3. Login/register flow works with expected Turnstile behavior.
4. Document upload and listing work for a test user.
5. `/api/meta` reports expected app version/name.
6. Background schedulers log normal startup messages.
7. Enterprise pricing: the "After deploy" step of section 7 (public price list, marketing-page tokens, admin billing controls).

## 7) Enterprise Pricing v2 Configuration

The 2026-10-22 B2B pricing model ([decision D-009](decisions.md#d-009-enterprise-pricing-v2-open-file-plans-metered-ai-one-ai-paused-gate)) is configured entirely by environment variables with safe defaults: **an unset variable means the shipped default**. Every number below is read at process start, so a change needs a restart (on Render, saving an environment change redeploys the service). Customer-facing copy — the price cards, the marketing pages' `{{ENT_*}}` tokens, emails and the assistant's product help — is generated from these values, never typed by hand, so changing a value changes every surface at once.

### Production checklist (before and after the pricing-v2 deploy)

1. **Remove stale price and limit overrides.** Any of these set on the Render service will silently override the new defaults. List the service's environment (Render dashboard → Environment) and delete each one unless it is a deliberate override:
   - plan prices: `ENTERPRISE_STARTER_MONTHLY_PAISE`, `ENTERPRISE_GROWTH_MONTHLY_PAISE`, `ENTERPRISE_SCALE_MONTHLY_PAISE` (old ₹2,999 / ₹6,999 / ₹14,999)
   - plan limits: `ENTERPRISE_{SANDBOX,STARTER,GROWTH,SCALE}_{MAX_SEATS,MAX_CLIENTS,CREDITS}`
   - action prices: `ENTERPRISE_CREDIT_COST_DOCUMENT_SCAN` (old 1), `ENTERPRISE_CREDIT_COST_WRITING_STUDIO` (old 1), `ENTERPRISE_CREDIT_COST_DEEP_SCAN` (old 20), `ENTERPRISE_CREDIT_COST_COPILOT_CLIENT` (old 20)
   - metering: `ENTERPRISE_COPILOT_MSGS_PER_CREDIT` (old 5), `ENTERPRISE_COPILOT_INVITE_MESSAGES` (old 100), `ENTERPRISE_DEEP_SCAN_FREE_SCANS_PER_CLIENT` (old 1), `DEEP_SCAN_MAX_DOCUMENTS` (old 40)
2. **Model environment variables.** Gemini 2.5 was retired on Vertex on 2026-10-20. Make sure none of these name a `gemini-2.5-*` or `gemini-2.0-*` id (a retired id is a failing round-trip on every call, after which the chain falls through to the most expensive model): `GEMINI_MODEL`, `GEMINI_DOCUMENT_MODEL(_CANDIDATES)`, `RILONO_AI_CHAT_MODEL(_CANDIDATES)`, `RILONO_INTERVIEW_MODEL(_CANDIDATES)`, `DAILY_AI_NOTIFIER_MODEL(_CANDIDATES)`, `SOP_GENERATOR_MODEL(_CANDIDATES)`, `COURSE_CATALOG_MODEL(_CANDIDATES)`, `ADMIN_GROWTH_AGENT_MODEL(_CANDIDATES)`, `ENTERPRISE_AI_MODEL(_CANDIDATES)`, `ENTERPRISE_WRITING_MODEL(_CANDIDATES)`, `ENTERPRISE_READ_MODEL(_CANDIDATES)`, `ENTERPRISE_COPILOT_MODEL(_CANDIDATES)`. In particular **leave `ENTERPRISE_AI_MODEL` unset** unless you mean to: it replaces the cheap chain for the assistant and Deep Scan, and also steers mock interviews and Writing Studio's fallback. The README's old `gemini-2.5-flash` examples are retired — if production copied them, replace them.
3. **`ENTERPRISE_GST_PERCENT`.** Rilono is not GST-registered, so the code default is **0** (`money.DEFAULT_GST_PERCENT`): no tax charged and no "+ GST" anywhere, with nothing to set on Render. Once registered, set `ENTERPRISE_GST_PERCENT=18` on the service (or change `DEFAULT_GST_PERCENT` in `app/money.py`). A typo is logged and falls back to the code default.
4. **`ENTERPRISE_YEARLY_ENABLED`.** Leave unset/false until the reading quality check (item 7) passes. Turning it on shows yearly prices on every surface and enables yearly checkout.
5. **Coupons.** Deactivate any 100% (or otherwise large) discount codes in the admin console (Enterprise Accounts → an account → "Discount codes"). Codes above `ENTERPRISE_COUPON_MAX_PERCENT` (15) are applied at the cap at checkout, so a customer promised more will be charged more than they expect — tell them, or pause the code.
6. **Existing paying customers.** Plan keys were reused, not migrated, so an org on `starter` moves to the new Starter limits (5 seats / 40 open files) the moment this deploys, and its credit allowance drops to the new number from its next period. The overrides endpoint and its `override_*` columns ship in this same deploy, so overrides can only be **applied after** it:
   - **Before deploy:** list the paid orgs (plan `starter` / `growth` / `scale` with a current paid period) whose active seats or open files exceed the new limits — Starter 5 / 40, Team 25 / 150, Multi-branch 50 / 500. A read-only query against `enterprise_subscriptions` joined to active `enterprise_organization_members` and open `enterprise_clients` is enough; the old schema already has these. Have the owner decide which of them to honour.
   - **Immediately after deploy** (once the step 8 checks pass): apply those overrides with `PUT /api/admin/enterprise/accounts/{id}/overrides`, or in the admin console (an enterprise account → Billing controls → Limits & trial).
   - **The window in between:** seats are a hard cap, so those orgs get a 402 on every staff invite until their override lands. Over-limit file adds are still allowed, but the first one starts the 14-day open-file grace clock; it clears once an override puts the org back within its limit. If no window at all is acceptable, temporarily set `ENTERPRISE_<PLAN>_MAX_SEATS` (and `_MAX_CLIENTS`) to the old numbers for the deploy and remove them once the per-org overrides are in — these apply to every org on that plan.
   - Live Razorpay mandates keep charging the amount of the Razorpay plan they were created with (old price + GST) — the owner must decide whether to cancel and re-subscribe them at the new price.
7. **Flash-Lite reading quality check (~50 documents).** Upload reading now defaults to `gemini-3.1-flash-lite`. Before enabling yearly billing (and ideally before launch), compare it with 3.1 Pro on about 50 real enterprise documents covering passports, bank statements, transcripts, offer letters / I-20 / CAS, scanned photos and PDFs over 15 pages. From a shell with production AI credentials:
   ```python
   from app.utils import gemini_service as g
   data = open("sample.pdf", "rb").read()
   cheap = g.extract_text_from_document(data, "sample.pdf", "application/pdf", model_candidates=["gemini-3.1-flash-lite"])
   pro = g.extract_text_from_document(data, "sample.pdf", "application/pdf", model_candidates=["gemini-3.1-pro-preview"])
   ```
   Check names, dates of birth, document numbers, expiry dates, amounts and balances, institution names and grades against the original. If Flash-Lite misses facts that matter, pin a stronger chain with `ENTERPRISE_READ_MODEL_CANDIDATES` and re-check the margin. These calls are billed (usage source `enterprise_document_read`).
8. **After deploy:** `GET /api/enterprise/public/plans` from India (or with `cf-ipcountry: IN`) returns the new INR prices, and from anywhere else never any INR price, `tax.note` is `"+ GST"` only when GST is above 0, and `yearly_enabled` matches the flag; the for-enterprise marketing page and the homepage contain no literal `{{ENT_` text; the admin console's enterprise account shows Billing controls (offline payment, credits, limits & trial).

### Environment variables added or changed by pricing v2

Plans and limits (`app/enterprise_billing.py`; prices in `app/money.py`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `ENTERPRISE_STARTER_MONTHLY_PAISE` / `ENTERPRISE_GROWTH_MONTHLY_PAISE` / `ENTERPRISE_SCALE_MONTHLY_PAISE` | 149900 / 399900 / 999900 | Ex-tax INR monthly price of Starter / Team / Multi-branch (was 299900 / 699900 / 1499900). The other-currency `*_USD_MINOR` … `*_SGD_MINOR` ladders are unchanged. |
| `ENTERPRISE_SANDBOX_MAX_SEATS` / `_MAX_CLIENTS` / `_CREDITS` / `_READS` | 3 / 15 / 50 / 50 | Free trial: staff seats, open files, one-time credits, reads for the whole trial. |
| `ENTERPRISE_STARTER_MAX_SEATS` / `_MAX_CLIENTS` / `_CREDITS` / `_READS` | 5 / 40 / 150 / 150 | Starter: seats, open files, credits a month, reads a month. |
| `ENTERPRISE_GROWTH_MAX_SEATS` / `_MAX_CLIENTS` / `_CREDITS` / `_READS` | 25 / 150 / 450 / 500 | Team (internal key `growth`). |
| `ENTERPRISE_SCALE_MAX_SEATS` / `_MAX_CLIENTS` / `_CREDITS` / `_READS` | 50 / 500 / 1200 / 1000 | Multi-branch (internal key `scale`). |
| `ENTERPRISE_TRIAL_DEMO_BONUS_CREDITS` | 50 | Credits Rilono staff can grant once per org after a demo call (admin console). 0 disables the bonus. |
| `ENTERPRISE_BRANCH_PACK_FILES` / `_SEATS` / `_CREDITS` / `_READS` | 100 / 10 / 200 / 200 | What one Branch Pack adds on top of a paid plan (packs are set per org by an admin). |
| `ENTERPRISE_FILE_LIMIT_GRACE_DAYS` | 14 | Days an org may stay over its open-file limit (from the first over-limit add) before adds are refused. 0 = hard cap. |
| `ENTERPRISE_AI_PAUSE_ON_EXPIRY` | true | Pause every AI path (402) when the trial has expired or a paid plan lapsed. `false` is the kill switch; it does not reopen adding clients or seats. |
| `ENTERPRISE_YEARLY_ENABLED` | false | Sell yearly plans (one-off order, no mandate). |
| `ENTERPRISE_YEARLY_PRICE_MONTHS` | 10 | Yearly price = this many months of the monthly price, in every currency. |
| `ENTERPRISE_YEARLY_PERIOD_DAYS` | 365 | Coverage of one yearly payment; allowances are still granted per `ENTERPRISE_PLAN_PERIOD_DAYS` (30). |
| `ENTERPRISE_INR_REGION_COUNTRIES` | `IN,NP,BD,LK,NG,GH,KE` | Countries charged INR only (IN is always included). Everywhere else is never charged INR. The country is the org's `country_code`, else the request's CDN geo country; unknown → INR allowed. |
| `ENTERPRISE_INR_REQUIRE_GEO_MATCH` | true | The org's country is owner-editable, so INR is charged (and quoted) only if the request's geo country is unknown or also in the INR region. An org that says `IN` but checks out from London is charged GBP (the geo country's ladder currency, else USD). Owners also can't change the country in Settings once the org has a verified plan payment; staff change it with `country_code` on `PUT /api/admin/enterprise/accounts/{id}/overrides`. `false` trusts the stored country alone. |
| `ENTERPRISE_GST_PERCENT` | 0 | GST on INR plan prices. Default 0 because Rilono is not GST-registered (no tax, no "+ GST" anywhere); set 18 once registered. An invalid value is logged and falls back to the default (`money.DEFAULT_GST_PERCENT`). |
| `ENTERPRISE_COUPON_MAX_PERCENT` | 15 | Highest discount an admin can create; existing codes above it apply at the cap. |
| `ENTERPRISE_ONE_TRIAL_PER_DOMAIN` | true | A new workspace whose owner is at a company domain that already has a workspace starts with its trial ended. A teammate counts only once they have signed in — an invited address alone never uses up a company's trial. |
| `ENTERPRISE_FREE_MAIL_DOMAINS_EXTRA` | (empty) | Extra comma-separated public-mailbox domains the one-trial rule must ignore (`app/email_domains.py`). |

Credits and AI action prices (`app/enterprise_credits.py`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `ENTERPRISE_CREDIT_COST_DOCUMENT_SCAN` | 4 | Credits per 15-page block of a paid document check (was 1 per document). |
| `ENTERPRISE_CREDIT_COST_WRITING_STUDIO` | 5 | SOP/LOR draft or refinement (was 1). |
| `ENTERPRISE_CREDIT_COST_DEEP_SCAN` | 40 | One Deep Scan (was 20). |
| `ENTERPRISE_CREDIT_COST_COPILOT_CLIENT` | 30 | One client Copilot link, charged at first open (was 20). |
| `ENTERPRISE_COPILOT_MSGS_PER_CREDIT` | 2 | Assistant message units per credit after the free daily units (was 5). |
| `ENTERPRISE_COPILOT_INVITE_MESSAGES` / `ENTERPRISE_COPILOT_INVITE_EXPIRES_DAYS` | 5 / 30 | Messages and lifetime of a new client Copilot link (was 100 messages). Read only through `enterprise_credits`. |
| `ENTERPRISE_DEEP_SCAN_FREE_SCANS_PER_CLIENT` | 0 | Free Deep Scans per client (was 1). Raising it re-enables the free-scan copy everywhere. |
| `DEEP_SCAN_MAX_DOCUMENTS` | 20 | Documents one Deep Scan reads — the newest ones when a client has more (was 40). |
| `ENTERPRISE_INTERVIEW_MAX_QUESTIONS` | 12 | Officer questions per mock-interview session (hard-capped at 20 by the interview engine). |
| `ENTERPRISE_INTERVIEW_ABANDON_HOURS` | 3 | Idle hours after which an unfinished interview session is marked abandoned (it was charged; no report). |
| `ENTERPRISE_CREDITS_LOW_THRESHOLD` | most expensive action price (40) | Balance below which the low-credit banner and notification fire. |
| `ENTERPRISE_COPILOT_BUDGET_MAX_OUTPUT_TOKENS` | 4096 | Output cap for a Chrome-extension copilot turn the wallet can only partly cover. |
| `ENTERPRISE_COPILOT_LEGACY_MSGS_PER_CREDIT` / `ENTERPRISE_COPILOT_RATE_CHANGED_AT` | 5 / 2026-10-22 | Reporting only: the assistant rate before the re-price and when it changed, so the finance "Saved with Rilono" panel converts old credit debits back into message counts at the rate in force at the time. |

AI document reading (`app/utils/gemini_service.py`, `app/routers/enterprise.py`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `ENTERPRISE_READ_MODEL` / `ENTERPRISE_READ_MODEL_CANDIDATES` | cheap chain | Model chain for free upload reading. Unset = `gemini-3.1-flash-lite` → `gemini-3.5-flash` → `gemini-3.1-pro-preview`. |
| `ENTERPRISE_READ_MAX_BLOCKS` | 10 | Most 15-page blocks read (and reads charged) per document — the first 150 pages. |
| `ENTERPRISE_READ_MAX_OUTPUT_TOKENS` | 2048 | Output cap per block request. |
| `ENTERPRISE_READ_UPLOAD_TIMEOUT_SECONDS` | 120 | Developer-API file-processing wait for a block (Vertex unaffected). |
| `ENTERPRISE_DOC_READ_RATE_LIMIT` / `ENTERPRISE_DOC_READ_RATE_WINDOW_SECONDS` | 30 / 3600 | "Read now" requests per user per window. |
| `ENTERPRISE_DOC_READ_STALE_MINUTES` | 30 | A "pending" read older than this (orphaned by a restart) may be claimed again by "Read now". |

Model routing for the Chrome-extension copilot (`app/enterprise_copilot.py`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `ENTERPRISE_COPILOT_MODEL` / `ENTERPRISE_COPILOT_MODEL_CANDIDATES` | cheap chain | Staff Chrome-extension copilot. It no longer follows the B2C `RILONO_AI_CHAT_MODEL`. |

Public price list (`GET /api/enterprise/public/plans`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `ENTERPRISE_PUBLIC_PLANS_RATE_LIMIT` / `ENTERPRISE_PUBLIC_PLANS_RATE_WINDOW` | 60 / 60 s | Per-IP rate limit. |
| `ENTERPRISE_PUBLIC_PLANS_MAX_AGE` | 300 | `Cache-Control: public, max-age` in seconds (the path is exempt from the global `/api/` no-store rewrite in `app/main.py`). |

Each visitor is quoted one region's prices: INR from the INR region (`ENTERPRISE_INR_REGION_COUNTRIES`), the local ladder currency or USD from anywhere else. The geo country comes from the CDN header (`CF-IPCountry` behind Cloudflare). Locally there is no such header, so pages show USD; send `cf-ipcountry: IN` (or `x-country-code: IN`) to see the INR version, e.g. `curl -H 'cf-ipcountry: IN' http://127.0.0.1:8097/for-enterprise`.

Admin console typo guards (`app/routers/admin.py`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `ENTERPRISE_ADMIN_OFFLINE_PAYMENT_MAX_MINOR` | 100000000 | Largest offline plan payment an admin can record, in minor units (₹10,00,000). |
| `ENTERPRISE_ADMIN_CREDIT_ADJUST_MAX` | `ENTERPRISE_MAX_CREDIT_REFUND` (100000) | Largest single credit adjustment, and the cap on an `included_credits` override. |
| `ENTERPRISE_ADMIN_MAX_BRANCH_PACKS` | 100 | Most Branch Packs per org. |
| `ENTERPRISE_ADMIN_OVERRIDE_MAX` | 1000000 | Largest seat / open-file / reads override. |
| `ENTERPRISE_ADMIN_MAX_TRIAL_DAYS` | 365 | How far ahead an admin can set a trial end. |

Unchanged but relevant: `ENTERPRISE_TRIAL_DAYS` (14), `ENTERPRISE_PLAN_PERIOD_DAYS` (30), `ENTERPRISE_PLAN_GRACE_DAYS` (3), `ENTERPRISE_FREE` (false; billing kill switch), `ENTERPRISE_CREDITS_ENFORCE` (true), `ENTERPRISE_COPILOT_FREE_DAILY` (5), `ENTERPRISE_CREDIT_COST_MOCK_INTERVIEW` (20), `ENTERPRISE_INTERVIEW_FREE_STAFF_PREVIEWS` (3), `ENTERPRISE_AI_MODEL` / `_CANDIDATES` (unset = cheap chain for the assistant and Deep Scan).

To list every `ENTERPRISE_*` variable the code reads:

```bash
rg -o '"ENTERPRISE_[A-Z0-9_]+"' app | sed -E 's/.*"(ENTERPRISE_[A-Z0-9_]+)"/\1/' | sort -u
```

### Rupee prices: Indian payment methods only (D-011)

An INR plan or credit charge to an org billed in India must be paid with an Indian payment method: UPI, netbanking, or an India-issued card or wallet ([decision D-011](decisions.md#d-011-rupee-prices-are-paid-with-indian-payment-methods)).

- **One-off orders** use manual capture: the server captures only what the policy accepts.
- **Mandates** are checked after each charge.
- **Not covered:** the other INR-region countries (NP, BD, LK, NG, GH, KE) and foreign-currency orders.

| Variable | Default | Meaning |
| --- | --- | --- |
| `ENTERPRISE_INR_DOMESTIC_ONLY` | true | The rule itself. `false` turns it off: no manual capture, no check, no portal line. |
| `ENTERPRISE_INR_MANUAL_CAPTURE` | true | Create domestic-only one-off orders with manual capture. With `false`, those orders are auto-captured, and a refused foreign card is refunded after capture instead. |
| `ENTERPRISE_INR_MANUAL_CAPTURE_EXPIRY_MINUTES` | unset | How long an uncaptured authorisation lives before Razorpay releases it (auto-refund). Unset means nothing is sent and Razorpay's default applies: 7200 minutes, i.e. 5 days, which is the maximum. A refused foreign card's hold can therefore last up to 5 days. Values from 12 to 7200 are sent. Razorpay's docs require it to be at least `automatic_expiry_period`, and don't say what that is on a manual-capture order. Try a shorter value in Razorpay test mode first: a rejected order would break every Indian checkout. |
| `ENTERPRISE_INR_FOREIGN_CARD_POLICY` | `refund` | What happens to a card issued outside India on a domestic-only charge. `refund` (the owner's choice): refuse; the order is never captured, a mandate charge is refunded and the mandate cancelled, and nothing is granted. `review`: accept and only log; an escape hatch if refusals misfire. `reprice`: accept, set `enterprise_organizations.inr_barred_at` (foreign ladder from then on), and stop an INR mandate at the end of its paid period. Any other value is logged and treated as `refund`. |

**Before deploying:**

1. In the Razorpay Dashboard, go to Webhooks and open the enterprise credits webhook (`/api/enterprise/webhook/razorpay-credits`).
2. Add the `payment.authorized` event. Keep `payment.captured` and the `subscription.*` events.
3. Check the setup works. Without `payment.authorized`, a domestic buyer who closes the tab before the browser callback is never captured. Razorpay releases that payment when the authorisation expires, and the buyer has to pay again.
4. Leave `ENTERPRISE_INR_FOREIGN_CARD_POLICY` unset: the default is `refund`, which the owner chose. Set it only to switch the fence off temporarily (`review`).
5. The deploy adds `domestic_only` to `enterprise_subscription_payments` and `enterprise_credit_payments`, and `inr_barred_at` to `enterprise_organizations`. `ensure_enterprise_pricing_v2_columns` does this; the change is additive and existing rows read false or NULL.

**Operating it:**

- Every foreign card on a domestic-only charge logs an ERROR line starting `inr-card-rule:`, whatever the policy.
- List refused payments:

  ```sql
  SELECT 'plan' AS kind, id, organization_id, razorpay_payment_id, amount_paise, status, error_message
    FROM enterprise_subscription_payments WHERE status LIKE 'foreign_card_%'
  UNION ALL
  SELECT 'credits', id, organization_id, razorpay_payment_id, amount_paise, status, error_message
    FROM enterprise_credit_payments WHERE status LIKE 'foreign_card_%';
  ```

- **`foreign_card_refund_due`:** the automatic refund failed, and the log line says `REFUND IT BY HAND`. Razorpay redelivers the webhook and the refund is retried each time. If the refund still hasn't gone through:
  1. Refund the payment in the Razorpay Dashboard.
  2. Set the row to `foreign_card_refused`, with `refunded_amount_paise = amount_paise`.
- **Lifting a `reprice` bar** (for example, an Indian business that paid with a foreign card): `UPDATE enterprise_organizations SET inr_barred_at = NULL WHERE id = …;`. There is no admin console control yet.
- **Local check:** `tests/test_enterprise_inr_domestic_only.py`. Never test against live Razorpay: a real foreign-card order would be captured or refunded for real.

## 8) Current Gaps

- Automated tests live in `tests/` (pytest, plus node-run `tests/*.js` UI tests), but no CI workflow is checked in — run both suites before deploying.
- Scheduler jobs are in-process; multi-instance deployment requires duplication controls.
