# Rilono Decision Log

Last updated: 2026-10-22

This file records durable technical decisions visible in the current codebase.

Status legend:

- `Accepted`: active decision
- `Superseded`: replaced by a newer decision
- `Proposed`: candidate, not yet enforced

## D-001 FastAPI Monolith For API + Web Assets

- Status: Accepted
- Recorded: 2026-03-25
- Context: Product currently ships backend APIs and static frontend in one deployable unit.
- Decision: Keep a single FastAPI service that mounts `static/` and exposes `/api/*`.
- Consequences: Simple deploy and shared auth/session context; limited independent scaling between frontend/backend.

## D-002 SQLAlchemy With SQLite Default, Postgres-Capable

- Status: Accepted
- Recorded: 2026-03-25
- Context: Local development speed and production portability are both needed.
- Decision: Default `DATABASE_URL` to local SQLite; keep models/query logic database-agnostic.
- Consequences: Easy local bootstrapping; some production concerns (locking/concurrency) require PostgreSQL.

## D-003 Cookie-Based JWT Authentication

- Status: Accepted
- Recorded: 2026-03-25
- Context: Browser clients need session continuity and stronger defaults than localStorage token handling.
- Decision: Use JWT tokens with HTTP cookie settings (`AUTH_COOKIE_*`) plus CSRF origin/referer checks.
- Consequences: Better browser security posture; cookie flags and trusted origins must be configured correctly per environment.

## D-004 Startup Schema Safety Patches And Backfills

- Status: Accepted
- Recorded: 2026-03-25
- Context: Schema evolution happened incrementally across features and older environments.
- Decision: Execute `ensure_*` schema patch functions and backfill routines at app startup.
- Consequences: Improves startup self-healing; startup side effects can mask migration discipline if not documented.

## D-005 In-Process Scheduler Threads For Daily Jobs

- Status: Accepted
- Recorded: 2026-03-25
- Context: Daily AI notifications and F1 news ingestion need periodic execution.
- Decision: Start scheduler threads from application startup instead of external worker infrastructure.
- Consequences: Simple operations in single-instance deploys; multi-instance deployments need care to avoid duplicate runs.
- Update, 2026-09-07: Latest-news ingestion and catalog research are retired. Their entrypoints cannot start work, even with forced calls or old enable flags. Other schedulers retain this design. See [catalog and news policy](catalog-and-news-policy.md).

## D-006 Cloudflare R2 As Document/Artifact Store

- Status: Accepted
- Recorded: 2026-03-25
- Context: Uploaded documents and extracted artifacts should not be tied to local disk.
- Decision: Persist files in Cloudflare R2 and store references in DB.
- Consequences: Better durability and portability; availability depends on external object storage credentials/network.

## D-007 Managed Third-Party Integrations By Domain

- Status: Accepted
- Recorded: 2026-03-25
- Context: Product capabilities depend on specialized external systems.
- Decision:
  - Gemini/Vertex for AI chat and analysis
  - Resend for transactional/marketing email operations
  - Razorpay for payment/subscription flows
  - Turnstile for abuse protection
- Consequences: Faster feature delivery; introduces operational dependency and key/secret management burden.

## D-008 Enterprise Mode Within Same Codebase

- Status: Accepted
- Recorded: 2026-03-25
- Context: Enterprise workflows are product-adjacent and share core user/document models.
- Decision: Keep enterprise routes (`/api/enterprise`) and UI (`/enterprise`) in same service, with subdomain-aware behavior.
- Consequences: Shared model/reuse advantages; tighter coupling between consumer and enterprise release cadence.

## D-009 Enterprise Pricing v2: Open-File Plans, Metered AI, One "AI Paused" Gate

- Status: Accepted
- Recorded: 2026-10-22
- Supersedes: the 2026-08-02 tier catalog (Starter ₹2,999 / 10 seats / 100 clients / 1,000 credits, Growth ₹6,999, Scale ₹14,999). That catalog is described in the `HISTORY` notes of `app/enterprise_billing.py` and `app/enterprise_credits.py`. No earlier record in this log covers it.
- Context: The 2026-08 tiers included 1,000 to 10,000 credits a month. Each credit earned ₹1.50 to ₹3.00 against AI actions that cost more than that to run. A document scan or SOP draft sold for 1 credit, and every client's first Deep Scan was free. The tiers were also sized by every client ever entered, so keeping finished files on record used up plan capacity. On 2026-10-20 Vertex retired Gemini 2.5. The enterprise assistant's default chain led with 2.5 Flash, so every turn silently fell through to 3.1 Pro at about 6x the token price. The real sales pipeline is mostly 1 to 5 person Indian offices. The INR column of the price book did not fit them, while the foreign ladders did fit their markets.
- Decision (owner-approved). The full specification lives in the code: `app/enterprise_billing.py`, `app/enterprise_credits.py` and `app/money.py` hold the numbers, and every one of them is env-overridable (see [runbook.md](runbook.md#7-enterprise-pricing-v2-configuration)).
  - **Plans.** The trial keeps the internal key `sandbox`; the paid keys `starter|growth|scale` are unchanged because DB rows and Razorpay notes carry them. Customers see "14-day free trial", "Starter", "Team" and "Multi-branch".

    | Plan (key) | INR per month, ex-tax | Seats | Open files | AI credits | AI reads |
    | --- | --- | --- | --- | --- | --- |
    | 14-day free trial (`sandbox`) | free | 3 | 15 | 50 once, plus a 50-credit demo-call bonus once | 50 for the trial |
    | Starter (`starter`) | ₹1,499 | 5 | 40 | 150 a month | 150 a month |
    | Team (`growth`) | ₹3,999 | 25 | 150 | 450 a month | 500 a month |
    | Multi-branch (`scale`) | ₹9,999 | 50 | 500 | 1,200 a month | 1,000 a month |

    Only the INR column was cut; the foreign price ladders are unchanged. Every plan gets every AI feature. Branch Packs (sold by invoice, set by admin) each add 100 open files, 10 seats, 200 credits and 200 reads. Per-org admin overrides replace a plan number, and packs add on top.
  - **Offices, custom roles and per-branch reporting are Team and Multi-branch only.** Starter gets the default (head) office and the built-in role presets. Only creating or editing is gated (HTTP 402 naming the Team plan). Existing offices, roles and data keep working on a lower plan and are never deleted.
  - **A live trial gets the Team features.** The trial is an evaluation of Team. When it expires the features close with it.
  - **Plans count open student files.** Only clients whose stage has `is_open=True` count toward the limit. A new terminal stage, `closed` ("Closed"), finishes a file without a visa outcome. Approved, Rejected, Closed and On Hold files don't count.
  - **14-day open-file grace** (`ENTERPRISE_FILE_LIMIT_GRACE_DAYS`, 0 = hard cap). An add that would go over the limit is still allowed while the org has been over for less than the grace period. The add can be a new client, a converted lead, or a reopen from a non-open stage; a reopen counts as an add, which closes the close, add, reopen loophole. The first over-limit add stamps `enterprise_subscriptions.files_over_limit_since`. The stamp is ignored, and cleared on the next add, once open files are back at or below the limit. A later overage therefore gets a fresh grace period. The stamp is flushed, not committed, so an add that fails does not start the clock. Seats stay a hard cap.
  - **One "AI paused" gate.** AI pauses when the trial has expired, or when a paid plan has lapsed with no paid period in force. While paused, every AI path refuses with a 402 before any model call or charge, including free assistant messages, free upload reading, and public interview and client Copilot links. Uploads still succeed and are stored "not read". Credit top-ups are refused while paused, because a top-up adds to an active plan or trial. Data is never deleted. `ENTERPRISE_AI_PAUSE_ON_EXPIRY=false` is the kill switch.
  - **One trial per company email domain.** A second workspace whose owner is at a company domain (not a public mailbox) already used by another workspace is created with its trial already ended and no trial credits or reads.
  - **Currency regions.** IN, NP, BD, LK, NG, GH and KE are charged INR only. Everywhere else can never be charged INR. This applies to plan checkout, credit top-ups and every displayed quote.
  - **GST decision deferred, but 0% is supported end to end.** Rilono is not GST-registered, so since 2026-10-22 the code default is 0 (`money.DEFAULT_GST_PERCENT`); set `ENTERPRISE_GST_PERCENT=18`, or change that constant, once registered. At 0, no surface prints "+ GST", charges tax or shows a tax label. That covers the price cards, server copy, emails, the assistant's help and the marketing pages, and all of them ask `money.tax_note()`. At 0%, a Multi-branch renewal is ₹9,999, below the RBI ₹15,000 e-mandate limit.
  - **Cheap model routing after the Gemini 2.5 retirement.** Every Gemini 2.5 and 2.0 id was removed from every default candidate chain; they stay in the cost tables so historical rows still price. `CHEAP_MODEL_CANDIDATES = [gemini-3.1-flash-lite, gemini-3.5-flash, gemini-3.1-pro-preview]` is defined once in `app/utils/gemini_service.py`. It is the default for the enterprise assistant, the Chrome-extension copilot, Deep Scan and enterprise upload reading. The app-wide default chain leads with 3.1 Pro.
  - **Yearly billing is behind a flag.** `ENTERPRISE_YEARLY_ENABLED` defaults to false. When enabled, yearly costs exactly 10x the monthly price in every currency ("2 months free"). It is a one-off Razorpay order with no mandate, covering 365 days. Credits and reads are still granted in monthly sub-periods. The owner gated yearly on the Flash-Lite reading quality check: a year paid up front locks in an allowance whose AI cost is not yet proven.
  - **Metered AI prices.** All prices are env-overridable, and 1 credit is ₹10 nominal.

    | Action | Price |
    | --- | --- |
    | Document check | 4 credits per 15-page block |
    | SOP / LOR draft or refinement | 5 credits |
    | Mock interview | 20 credits per server-side session: up to 12 officer questions and one feedback report |
    | Deep Scan | 40 credits, no free scans, at most 20 documents |
    | Assistant | 1 credit per 2 message units, after 5 free units per org per day |
    | Client Copilot link | 30 credits for 5 messages over 30 days (interim, not promoted) |

    A plan change inside a live period only tops the allowance up to the new tier.
  - **Monthly AI reading allowance.** Free upload reading uses one read per 15 pages, from a per-plan allowance stored on the wallet. If the allowance is used up, the document is stored "not read", with a "Read now" action for later. A paid document check never uses reads.
  - **Coupons are capped** at `ENTERPRISE_COUPON_MAX_PERCENT` (15). Admins can't create a code above the cap, and a legacy code above it is applied at the cap.
  - **One source of truth for public prices.** `GET /api/enterprise/public/plans` and server-rendered `{{ENT_*}}` tokens in the static marketing pages both come from `money.PRICE_BOOK` and `billing.PLANS`.
- Alternatives rejected:
  - *Keep the 2026-08 allowances and only raise action prices.* Rejected: the included credits were still worth less than they cost to serve. The allowance was the loss, not the action price.
  - *Count every client toward the limit.* Rejected: it punishes keeping finished files on record and pushes customers to delete history.
  - *A hard open-file cap with no grace.* Rejected: a busy intake week would wall a paying customer mid-sale. *Unlimited overage* was also rejected, because it makes the limit meaningless.
  - *Reopening a file is free.* Rejected: close, add, reopen walks straight past any limit.
  - *Gate AI features by plan.* Rejected: credits already meter AI cost, and a Starter office that can't try Deep Scan never upgrades to use it more.
  - *Offices and custom roles on every plan.* Rejected by the owner: they are the clearest reason for a growing office to move to Team. *Deleting or locking existing offices and roles on downgrade* was also rejected, because a downgrade must never break a working workspace.
  - *Delete, lock or hide data when a trial or plan ends.* Rejected: an evaluation that lapses must never destroy data, and read access costs nothing.
  - *Pause only the paid AI actions after expiry.* Rejected: free assistant messages and free reading are real model spend, and they were the expired trials' main use.
  - *Hardcode 18% GST.* Rejected: an unregistered supplier may not collect GST, and the owner has not decided on registration.
  - *Let any buyer pick INR, or FX-convert INR prices.* Rejected: after the INR-only cut, INR is a 60% discount on the foreign ladder.
  - *Keep a free first Deep Scan per client.* Rejected: at 40 credits, four new clients would give away more than a Starter month's whole allowance. The setting remains as a promotion knob.
  - *Keep Pro as the assistant default, or pin a 2.5 id until it stopped answering.* Rejected: Pro costs about 6x more per message under a flat credit price, and a retired id wastes a failing round trip on every call.
  - *Meter reading with credits.* Rejected: an upload must never be refused or charged. A separate counter lets the file be stored "not read" instead.
  - *Charge mock interviews per turn, or trust the client's transcript.* Rejected: the cost would be unbounded and the transcript could be tampered with. Sessions now live on the server with a question cap.
  - *Sell yearly from day one.* Rejected until the cheap reading model passes the quality check.
- Consequences:
  - Existing paid orgs move to the new limits for their key at once, because keys are reused, not migrated. Live Razorpay mandates keep charging the plan amount they were created with. The pre-deploy checklist in [runbook.md](runbook.md#7-enterprise-pricing-v2-configuration) covers both.
  - Old price and limit env vars set on the host override the new defaults silently.
  - The cheap-model rates in the cost catalog come from public price lists and are reported as `partial` until they are checked against a Google invoice ([ai-cost-accounting.md](ai-cost-accounting.md)).
  - Assistant message counts derived from historical credit debits must use the rate in force when each debit was written: 1 credit per 5 messages before this change.
