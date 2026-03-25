# Rilono Memory Bank

Last updated: 2026-03-25

This folder is the durable project memory for the team. It captures context
that should survive sprint changes, handoffs, and growth.

## Core Docs

- [architecture.md](./architecture.md): Current system shape, modules, and data flow.
- [decisions.md](./decisions.md): Durable architecture/product decisions and tradeoffs.
- [runbook.md](./runbook.md): Operational procedures, startup, and incident handling.
- [domain-glossary.md](./domain-glossary.md): Shared product/domain vocabulary.
- [workflows/docs-update-checklist.md](./workflows/docs-update-checklist.md): Definition of done for memory-bank updates.

## Setup Guides

- [../README.md](../README.md): Setup and product overview.
- [guides/EMAIL_VERIFICATION_SETUP.md](./guides/EMAIL_VERIFICATION_SETUP.md): Resend setup.
- [guides/TURNSTILE_SETUP.md](./guides/TURNSTILE_SETUP.md): Cloudflare Turnstile setup.
- [guides/DEVELOPER_EMAILS_GUIDE.md](./guides/DEVELOPER_EMAILS_GUIDE.md): Developer email allowlist.
- [guides/AI_THEME_INTEGRATION.md](./guides/AI_THEME_INTEGRATION.md): UI animation/theme references.

## Documentation Rules

- Update `architecture.md` when modules, flows, or integrations change.
- Update `decisions.md` when a non-trivial technical decision is made.
- Update `runbook.md` whenever run/deploy/ops steps change.
- Update `domain-glossary.md` when product terminology changes.
- Prefer appending context instead of deleting history.
- Run [workflows/docs-update-checklist.md](./workflows/docs-update-checklist.md) before closing feature work.
