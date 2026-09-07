# AI cost accounting

The admin **AI Costs** page contains B2C profile search, a feature breakdown, retained lifetime totals, CSV export and a separate Google billing record. Existing charts still cover all recorded application AI activity.

## Local review

Run the explicit read-only import before starting or restarting the review server:

```sh
venv/bin/python scripts/import_ai_cost_review.py
venv/bin/python scripts/preview_ai_costs.py
```

Open `http://127.0.0.1:8768/admin-console` and select **AI Costs**. No sample profiles, synthetic usage, fixed exchange rate or estimated charge is seeded or displayed. The private SQLite file is `data/ai_cost_review.sqlite3`. The importer reads the configured source URL privately, verifies a PostgreSQL read-only transaction, and copies only real user identity/role fields and retained usage counters. It excludes passwords, authentication tokens, prompts, generated content and estimated monetary fields. A failed import leaves the existing local snapshot intact.

The retained-record import completed at **2026-09-07 01:13:12 UTC**, with **47 users and 4,527 usage events**, covering **June 20–September 6, 2026**. These are snapshot counts, not a continuously connected production database. The import status is available at `/api/local-ai-review/status`. Only profiles and AI accounting records are imported; other product records, including subscription transactions, are absent from this local database. The local review opens AI Costs directly and hides other admin tabs and the revenue panel to avoid implying those records were imported.

The review server loads only billing settings from `data/ai_billing.local.env`; it does not load production `.env`, run production startup, migrate the source database or start schedulers. It binds only to loopback. Authentication overrides exist only in the review script. The only permitted write is **Sync billing**, which queries Google and saves the returned snapshot locally. Restart the server after refreshing the local records or changing local billing configuration.

Unavailable amounts display **0**, accompanied by an availability/coverage message. Zero without a provider record means no verified amount is available; it does not establish that Google charged nothing. Profile-level charges remain 0 until a provider-billed amount can be assigned to that profile. Project-level Google charges are shown separately and are never allocated proportionally to profiles.

The real application routes use the existing admin authentication, Cloudflare verification and rate limits. Profile reports and downloads are sent with `Cache-Control: no-store`.

## What is measured

Every instrumented B2C Gemini attempt writes a pending event before dispatch and records the provider response before output parsing. Rejected/truncated responses therefore remain accounted for. Application fallbacks are separate attempts; SDK retries are disabled at the relevant client boundaries. Response identity prevents charging the same provider response twice in the application ledger.

Events retain profile and organization identifiers, product, trigger, model/version, provider/project, timestamps, response identity, usage counters and a pricing version. Only usage metadata is retained in the new raw accounting field; prompts, document content and generated messages are not copied into it.

Input, candidate output, thinking, cached and tool counters are separate. Cached input is a subset of prompt tokens and must not be added again. The provider total remains authoritative for recorded token totals. Legacy output can already contain thinking, so older records cannot promise a separate split. There is no characters-to-token reconstruction.

Cloud Text-to-Speech characters and explicit-cache storage events have separate units. Cache creation records do not claim the requested TTL was the actual billed duration. Shared catalog/news/batch analysis is not arbitrarily charged to a student. Personalized notification analysis is attributed even when the result decides not to send an email.

States distinguish `pending`, `measured`, `unknown`, `not_billed`, `duplicate` and `legacy`. Unknown requests are not represented as accurately free. Definitive Google HTTP 400/500 token errors are recorded as unbilled; local timeouts remain unknown. Duplicate attempts retain an audit record without additive usage.

## Retained history and recovery

Startup adds nullable/new ledger columns without inventing historical profile, project or provider associations. The safe historical correction converts known legacy `gcp-tts/` character counters out of token columns, once. Only unambiguous historical B2C feature sources enter B2C totals; old shared/enterprise-ambiguous records remain unclassified. Records before tracking existed cannot be reconstructed from an aggregate invoice.

Database write failures are retained in a private recovery spool, with atomic writes, filesystem locking and replay. Set **AI_USAGE_SPOOL_DIR** to a directory on a persistent volume before production use. The default local directory is `web_app/data/ai_usage_spool`; an ephemeral host disk does not survive host replacement. If both database and spool fail before dispatch, the AI request is stopped. A process lost during an active request leaves a pending record requiring reconciliation. The maintenance worker replays the spool every minute; health warnings are visible in the profile section.

Deletion of a user follows existing account-deletion policy: spend events are retained while their user association is removed. Retained lifetime means available accounting history, not a claim of complete history from signup.

## Google billing connection

The **standard Cloud Billing export** is enabled for the linked billing account, targeting `project-80f89486-7dde-4d04-a0e.rilono_billing` in `US`. The existing Rilono service account received the approved **BigQuery Data Viewer** role on that dataset and **BigQuery Job User** on the query project. Dataset read access and a minimal query were verified with that service account. Its existing AI role was preserved; no new credential was created.

The first local sync reached Google successfully, but the export dataset had no tables yet. The dashboard therefore shows 0 with an awaiting-export status; no successful billing snapshot or sync timestamp was invented. The configured table follows Google's standard name, `gcp_billing_export_v1_0115DB_4FCB5F_12B9D3`. **Sync billing** can fetch the real records once Google creates the table. Initial exports/backfill can take time; see Google's [export availability documentation](https://docs.cloud.google.com/billing/docs/how-to/export-data-bigquery-tables/standard-usage). No production application or deployment settings were changed.

Configure the application environment, or the ignored `data/ai_billing.local.env` file for local review:

| Variable | Purpose |
| --- | --- |
| `AI_BILLING_BIGQUERY_TABLE` | Fully qualified `project.dataset.gcp_billing_export_v1_...` table |
| `AI_BILLING_USAGE_PROJECT` | Exact Google project whose AI expenditure is compared |
| `AI_BILLING_QUERY_PROJECT` | Project running the query; defaults to the table project |
| `AI_BILLING_LOCATION` | Actual dataset location; defaults to `US` |
| `AI_BILLING_CREDENTIALS` | Optional dedicated service-account file; otherwise Application Default Credentials |
| `AI_BILLING_SERVICE_NAMES` | Comma-separated exact service descriptions; defaults cover Gemini/Vertex and Cloud TTS |
| `AI_BILLING_MAX_BYTES` | Maximum bytes billed per query; defaults to 1,000,000,000 |
| `AI_BILLING_SYNC_ENABLED` | `true` to enable the daily worker; defaults to `false` |
| `GEMINI_DEVELOPER_PROJECT_ID` | Project association for Developer API events, explicitly supplied because an API key alone does not reveal it |
| `GOOGLE_TTS_BILLING_PROJECT_ID` | Explicit TTS project when not already supplied by the Vertex configuration |

The integration identity needs BigQuery Data Viewer on the export dataset and BigQuery Job User on the query project. It does not need billing-account administration. Do not put credential values in the admin page, source tree or this document. Local billing configuration is private and excluded from git; its query limit is 100,000,000 bytes per query.

The **Sync billing** action retrieves the selected range, bounded to 366 days and the configured project/services. Google client pagination is consumed fully. Snapshot replacement is atomic, so repeating a sync does not duplicate charges and later corrections replace the prior view. Failed fetches keep the previous successful snapshot. A missing export table returns HTTP 202 with `awaiting_export`; it preserves any prior snapshot and does not mark a successful sync. An optional daily worker with a database lease refreshes the current month, previous month and last 30 days in the full application. The local review uses manual sync. Older/custom windows can be refreshed manually. Multi-worker runs share the daily lease.

Provider quantities remain grouped by day, service, SKU, unit, currency and invoice month. Currency amounts, credits and net charges are separate. Amounts come from Google billing rows. Any USD conversion uses Google's exported currency rate. No application price estimate is used in the visible cost reports. Credits do not alter a student's recorded tokens. Unknown historical scope and missing metadata keep coverage marked incomplete. No mismatch is silently redistributed to profiles. This is usage-date reconciliation; final invoice matching may require invoice-month adjustment review.

## Actual charges and limits

The admin reports and exports show provider-recorded counters and imported Google charges. Legacy estimated monetary fields remain internal compatibility fields and are not shown as actual spending. The local import explicitly excludes those estimates. Missing counters or billed values display 0 with their coverage state, rather than being reconstructed from price lists, character ratios, revenue or totals from another scope.

An aggregate Google project invoice cannot identify which student incurred a charge. Tokens also do not determine exact invoiced cost because storage, grounding, discounts, credits, modality and rounding use different billing rules. Profile cost attribution therefore remains unavailable until supported by actual provider records at that scope.

First-time BigQuery export history is limited by Google's backfill rules; enabling it cannot recover unlimited historical profile mappings. A project switch also requires checking the old project/account's retained exports separately. The local integration supports one configured reconciliation project at a time; the application ledger retains multiple projects without combining them into a false matching bill.

## Verification

Run tests with dotenv disabled and an isolated database:

```sh
PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' GEMINI_PROVIDER=developer GEMINI_API_KEY='' RESEND_API_KEY='' GOOGLE_APPLICATION_CREDENTIALS=/tmp/rilono-no-credentials.json AWS_EC2_METADATA_DISABLED=true venv/bin/python -m pytest tests -q
node --test tests/test_ai_costs_ui.js tests/test_admin_users_export_ui.js
```

Tests cover attempt persistence, fallback usage, duplicate responses, recovery/migration, TTS units, profile and product boundaries, date/lifetime totals, full CSV export, admin access, currency/credits/corrections, failed billing sync and UI stale-request handling. Provider calls are stubbed; local verification does not incur Gemini usage or send email. Deployed PostgreSQL migration remains a rollout check. The separate local importer is tested for preservation of source data, exclusion of credentials and estimates, private file permissions, and retention of the previous snapshot on failure.

Official references: [Gemini usage metadata](https://ai.google.dev/api/generate-content#UsageMetadata), [Cloud Billing export fields](https://docs.cloud.google.com/billing/docs/how-to/export-data-bigquery-tables/standard-usage), [export setup and historical limits](https://docs.cloud.google.com/billing/docs/how-to/export-data-bigquery), [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing).
