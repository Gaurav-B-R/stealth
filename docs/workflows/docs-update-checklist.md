# Docs Update Checklist

Last updated: 2026-10-22

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
9. If an ENTERPRISE screen, flow, permission, plan, or price changed, update the
   assistant's in-product help guide
   [app/prompts/ENTERPRISE_HELP_GUIDE.md](../../app/prompts/ENTERPRISE_HELP_GUIDE.md)
   (the Rilono AI assistant answers "how do I…" questions from it). Registry-driven
   facts inject themselves via `{{PLACEHOLDER}}` blocks generated in
   `app/enterprise_help.py`. These cover permissions, roles, scopes, plans and their
   limits, prices and "+ GST" (only while tax applies), yearly billing (only while
   enabled), open files and grace, AI reads, the AI-paused rule, Team features, credit
   prices and client-link terms. Only hand-written walkthrough prose needs editing, and
   it must not restate a price, limit, allowance or "GST". A new billing fact gets a
   generator, not a sentence. Then run `python -m pytest tests/test_enterprise_help.py`.
   It fails when the guide drifts from the code's registries or the portal's screen
   names, or when the prose hand-writes a billing number.
10. If an `ENTERPRISE_*` (or other) environment variable was added or its default
    changed, add it to the table in [runbook.md § 7](../runbook.md#7-enterprise-pricing-v2-configuration)
    with its default and meaning.

## Definition Of Done

- Memory-bank docs reflect current behavior.
- No stale root-level guide links remain.
- A teammate can onboard or operate the service from docs without guessing.
