# Docs Update Checklist

Last updated: 2026-03-25

Use this checklist before merging any feature, fix, or operational change.

## When To Run

Run this checklist if your change touches any of:

- API routes, auth, permissions, or security behavior
- Database schema, model fields, background jobs, or integrations
- Environment variables, startup/deploy steps, or incident handling
- Product terminology, user-facing statuses, or workflow stages

## Checklist

1. Update `Last updated` date on any edited doc.
2. Update [architecture.md](../architecture.md) for module/flow/integration changes.
3. Add or amend a record in [decisions.md](../decisions.md) if a durable technical choice changed.
4. Update [runbook.md](../runbook.md) if startup, deploy, env, or incident steps changed.
5. Update [domain-glossary.md](../domain-glossary.md) if terminology changed.
6. Confirm setup guide links still resolve from [docs/README.md](../README.md).
7. Run link sanity check:
   - `rg -n "EMAIL_VERIFICATION_SETUP\\.md|TURNSTILE_SETUP\\.md|DEVELOPER_EMAILS_GUIDE\\.md|AI_THEME_INTEGRATION\\.md" README.md docs`
8. If new docs were added, list them in [docs/README.md](../README.md).

## Definition Of Done

- Memory-bank docs reflect current behavior.
- No stale root-level guide links remain.
- A teammate can onboard or operate the service from docs without guessing.
