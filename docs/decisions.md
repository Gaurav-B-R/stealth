# Rilono Decision Log

Last updated: 2026-10-24

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

## D-010 Enterprise Prices: One Currency Per Visitor and Workspace

- Status: Accepted
- Recorded: 2026-10-23
- Context: Since D-009 the INR plan prices are less than half the foreign ladder (₹1,499 against $39 / £29 / A$59), while the foreign ladders are near-parity with each other. Checkout already refused INR outside the INR region, but the public surfaces still showed it: `/for-enterprise` rendered every plan in INR with an "International $39 / £29 / A$59" line underneath for every visitor, the other marketing pages and their JSON-LD quoted INR, `app.js` shipped a client-side ladder with every currency's plan prices, the public and portal APIs returned the full `price_options` ladder (INR included) to everyone, and the assistant's help quoted INR to every workspace.
- Decision (owner-approved): show each visitor and each workspace only their own country's prices, in one currency, the way regionally priced SaaS does (Canva, Microsoft 365, Spotify). The protection is enforcement at checkout; the display rule stops advertising the gap.
  - **Revised 2026-10-24: one currency, not one region.** The first cut showed "one region": INR to the INR region, and the whole near-parity foreign ladder (USD, GBP, EUR, CAD, AUD, AED, SGD) to everyone else, so the portal's Plans & Billing kept a "Billing currency" selector listing £29, A$59 and the rest beside a US office's $39. The owner asked for a visitor to see only their own country's pricing, so there is no currency choice anywhere.
  - **Visitor currency.** `billing.public_price_currency(request)`: INR from the INR region; elsewhere the visitor's country's ladder currency, else USD; an unknown country (Tor, an unlocatable IP, no CDN) gets USD. No hint changes it.
  - **Workspace currency.** `billing.charge_currency_for_org` returns the org's one currency (`billing.own_currency`): the currency its RUNNING plan was bought in (`billing.billed_currency_pin`: the latest verified or partially refunded plan payment, only while the paid period runs or a mandate is live), else its country's, clamped to its region. A refunded or long-lapsed payment pins nothing. The stored `billing_currency` no longer decides it: that was written at checkout creation under the old selector, so an abandoned GBP checkout would have pinned a US office to another country's prices. The subscription quote (the current-plan line, including the free trial's "$0") uses the same rule, and the portal's display currency IS the billing currency (`_org_display_currency` calls `charge_currency_for_org`), so one page never shows two currencies. The assistant gets the currency the router resolved with the request. A checkout or coupon preview that names a different currency is refused with 409 ("This workspace is billed in X. Refresh the page…"), never silently re-priced — that only happens from a page rendered before the rule. `charge_currencies` is that one currency, so the portal renders no currency selector on Plans & Billing or the top-up window.
  - **Pages.** `{{ENT_*}}` money tokens are currency-neutral (`ENT_STARTER_PRICE`, `ENT_FROM_PRICE`, `ENT_TOPUP_PACKS`, `ENT_CURRENCY` …) and rendered per request. Per-currency, `_INR` and "International" tokens are gone, so a page can't name another region's price.
  - **Search snippets name no price.** JSON-LD answers and meta descriptions describe plans by limits only. Google crawls from the US, so any price there would be one currency for every searcher.
  - **APIs and JS.** `price_options` ladders carry only the caller's one currency (public: the visitor's; portal: the org's; default: the card's own). `app.js` holds no Enterprise price and sends no currency hint. The `/pricing` currency selector is students-only.
  - **Assistant.** Help topics and `get_credit_pricing` quote the workspace's billing currency; with none known, no price.
- Alternatives rejected:
  - *One global USD price.* Rejected: the pipeline is mostly small Indian offices, for whom $39 is out of reach.
  - *Keep the selector on Enterprise but drop INR from it* (the first cut, in the portal). Rejected by the owner: a list of other countries' prices is what they asked to hide, near-parity or not.
  - *Silently charge the org's currency when a checkout names another.* Rejected: the buyer would meet a different currency at the payment sheet than the page showed; a 409 asks them to refresh instead.
  - *Unknown country quoted INR* (checkout's domestic default). Rejected for display: behind Cloudflare an unknown country is not an Indian office.
- Consequences:
  - Local development shows USD unless a geo header is sent (see [runbook.md](runbook.md)).
  - A workspace whose latest verified plan payment is in a currency other than its country's (possible under the old selector) keeps that currency while it is the one it is billed in.
  - Credit values (an INR unit of account) are shown converted to the workspace's display currency, never as a raw ₹ string: signed-in wallet, usage and analytics JSON carries no ₹ string outside INR (`credits.without_rupee_strings`), the CSV export's value column is in the display currency, and the assistant's wallet and spend tools drop rupee figures. The numeric unit fields (`credit_value_inr`, `value_inr` …) stay, because the portal converts them.
  - Because display currency follows the billing currency, an INR-claiming workspace browsing from outside the INR region (billed in the geo country's currency under `INR_REQUIRE_GEO_MATCH`) also sees its Finance figures converted into that currency for that visit.
  - The price is still discoverable through a VPN; enforcement stays at checkout (`INR_REQUIRE_GEO_MATCH`, the owner-locked company country). [D-011](#d-011-rupee-prices-are-paid-with-indian-payment-methods) adds the stronger fence: INR is accepted only through Indian payment methods.
  - The student Visa Success Pass keeps its currency selector: its ladder is near-parity by design.

## D-011 Rupee Prices Are Paid With Indian Payment Methods

- Status: Accepted. The owner chose `refund` on 2026-10-23, and it is the default.
- Recorded: 2026-10-23
- Context: D-010 stops showing the INR ladder outside the INR region. Checkout still decides the currency from two inputs a buyer controls: the company country (editable until the first payment) and the CDN geo country (a VPN changes it). A foreign office that reaches an INR checkout can pay ₹1,499 for a $39 plan with its own card. Razorpay has no checkout or order option that refuses foreign cards. Its only international switch is account-wide, and turning it off would also block every USD, GBP and AUD sale. The docs were read on 2026-10-23 with `?preferred-country=IN`.
- Decision:
  - **Scope.**
    - An INR plan or credit charge to an org billed in India is sold "domestic-only" (`billing.domestic_only_charge`). An org whose country is unknown counts as billed in India.
    - The payment row records this in `domestic_only`.
    - Other INR-region members (NP, BD, LK, NG, GH, KE) are outside the rule, because they hold no Indian payment methods.
    - Foreign-currency orders are unchanged.
    - Orders and mandates created before this change are not domestic-only, so they keep renewing as they were sold.
  - **One-off orders are checked before capture.** This covers credit top-ups, yearly plans, and monthly plans when auto-renew is off.
    - A domestic-only order is created with manual capture (`"payment": {"capture": "manual"}`).
    - `/billing/verify`, `/credits/topup/verify` and the `payment.authorized` webhook read the payment entity, and capture only what the policy accepts.
    - A refused foreign card is never captured. Razorpay releases the authorisation when it expires.
  - **Mandates are checked after capture.** A Razorpay Subscription has no manual capture, so its first charge and every renewal are checked once captured. A refused charge is refunded in full and the mandate is cancelled.
  - **Detection** uses the payment's `international` or `card.international` flag. Razorpay reports no card country.
  - **Policy** (`ENTERPRISE_INR_FOREIGN_CARD_POLICY`, owner-approved: `refund`):
    - `refund` (default): refuse the payment. It is not captured, or it is refunded. Nothing is granted, and the trial or current plan carries on. Every case logs `inr-card-rule:` at ERROR level.
    - `review`: accept the payment and only log it. Kept as an escape hatch in case refusals misfire; it fences nothing.
    - `reprice`: accept the payment and set `enterprise_organizations.inr_barred_at`. From then on every quote and checkout uses the foreign ladder (the geo country's currency, else USD). An INR mandate is cancelled at the end of the period just paid for.
    - An unrecognised value falls back to `refund`, so a typo can't switch the fence off.
  - **Refused statuses.** `foreign_card_refused` and `foreign_card_refund_due` are not revenue statuses. They never count as coverage, as "has paid" (the billing-country lock) or as revenue. A failed refund stays `foreign_card_refund_due` and is retried on the next webhook delivery.
  - **Portal.**
    - When INR is the charge currency, one line under the plan grid and in the top-up modal states the rule.
    - A refused payment gets a 402 with code `inr_foreign_card`, which the portal shows in an in-app notice.
    - Checkout `config` hides PayPal on domestic-only orders. This is cosmetic.
- Alternatives rejected:
  - *Accept the foreign card once and move the org to the foreign ladder at its next renewal* (`reprice`). Rejected by the owner: it still sells the first period at the rupee price. It stays available as a setting.
  - *Turn off international cards on the Razorpay account.* Rejected: it also blocks every foreign-currency sale.
  - *Hide cards on INR checkouts, or allow-list Indian card issuers.* Rejected: most Indian offices pay by card, and an issuer list turns away any bank left off it. Checkout options also run in the buyer's browser, so they enforce nothing.
  - *Refund after capture on orders too.* Rejected wherever manual capture is possible: the foreign card would be charged, and Razorpay keeps its fee on a refund.
  - *Apply the rule to the whole INR region.* Rejected: offices in Nepal, Bangladesh and the other members have no Indian payment method.
- Consequences:
  - The enterprise credits webhook must also subscribe to `payment.authorized` (see [runbook.md](runbook.md#rupee-prices-indian-payment-methods-only-d-011)). Without it, a domestic buyer who closes the tab before the callback is not captured. Razorpay auto-refunds that payment when it expires.
  - Still not enforceable:
    - A foreign office that claims a non-Indian INR-region country and browses from it, or hides its geo, can pay the rupee price with a foreign card.
    - An Indian business that pays with a foreign-issued card is treated as foreign.
  - Razorpay keeps its fee on a refunded mandate charge.
  - Only Rilono staff can lift the INR bar, in the database. There is no admin console control yet.

## D-012 Resend Delivery Failures Flag The User; Only Non-Transactional Sends Stop

- Status: Accepted
- Recorded: 2026-10-24
- Context: A send counts as "accepted" when Resend returns an id. Suppression, bounces and spam complaints are reported later, by webhook, and the app had no webhook for them. Addresses on Resend's suppression list got a "reset link sent" screen, received nothing, and the daily AI nudge kept paying Gemini to write emails they could not receive.
- Decision:
  - A Svix-signed webhook, `POST /api/webhooks/resend/email-events`, has its own secret, `RESEND_DELIVERABILITY_WEBHOOK_SECRET`. It records `email.bounced` (permanent only), `email.complained`, `email.suppressed` and `suppression.added` as a per-user flag, `users.email_undeliverable_*`. `suppression.removed` clears the flag. Code: `app/email_deliverability.py`.
  - Non-transactional sends skip a flagged user. These are the daily AI nudge (excluded in the candidate SQL, before the snapshot, R2 or Gemini work), the enterprise calendar digest, discount promos and the marketing-audience sync.
  - Transactional sends (password reset, OTPs, verification) are still attempted. The forgot-password response stays generic, so it never reveals the flag or whether the account exists.
  - The admin console's account view shows the flag, the reason and Resend's message. Support clears it there after removing the address in Resend. An email change also clears it.
  - Out-of-order retries are handled. The flag stores the latest bad-event time, and every clear records `email_undeliverable_cleared_at`. A bad event from before the last clear is ignored, and a removal older than the current flag does not clear it.
  - Enterprise CRM clients get the same flag, in `enterprise_clients.email_undeliverable_*`. These rows are not users, so the webhook matches them separately.
    - Every org's client row with the address is flagged, because the suppression list covers Rilono's whole Resend account.
    - A client row stores only Resend's structured codes (for example `Permanent / NoEmail`). It never stores the subject or Resend's free-text message of the send that triggered it. The CRM payload (`email_delivery`) has no timestamp. One org's send must not tell another org anything.
    - The consultant sees a warning chip on the client's profile and in the Emails composer. It asks them to get another address. Saving a new email clears the flag.
    - The automatic client calendar reminder skips a flagged client. Sends a consultant starts (emails, payment links, portal shares, invites) are still attempted.
- Consequences:
  - A flagged student also stops getting the daily nudge's in-app bell notification, because that comes from the same Gemini scan.
  - A client flag clears only on `suppression.removed` or an email change. There is no "clear" button for consultants: they cannot take an address off Rilono's suppression list.
  - Nothing is recorded until the Resend webhook exists (see [runbook.md](runbook.md)). Addresses that were already suppressed are flagged the next time Resend suppresses a send to them.
