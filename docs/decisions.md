# Rilono Decision Log

Last updated: 2026-03-25

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
