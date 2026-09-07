# Catalog and news policy

Effective in this code revision, 2026-09-07. Production behavior changes only after this revision is deployed and existing application workers restart.

## Course recommendations

B2C and B2B Course Finder select only from saved university/course records. A tool-free Gemini call ranks candidate IDs against the student brief. Names, fees, entry requirements, rankings and links returned to the client come from those saved records, not model-generated replacements. Off-catalog, duplicate and out-of-context selections are rejected. Missing catalog facts stay missing.

A sparse catalog does not enable live research. An empty catalog returns no matches without an AI call, Visa Pass run or CRM credit charge. Failed or unusable model results do not consume a user run or CRM credits, although an attempted Gemini call can still consume provider tokens. Successful course-matching AI calls remain metered to the requesting profile or organization.

Catalog discovery, AI refresh, scheduled refresh and forced/manual refresh are disabled in code. Old grounding or scheduler environment flags cannot re-enable them. The admin refresh endpoint returns HTTP 410, and catalog status identifies database-only/manual operation. Existing catalog records and audit history are retained for manual maintenance.

## Latest news

Latest news is disabled in web and mobile navigation. The authenticated legacy `/api/news/f1-latest` endpoint returns an explicit disabled response with an empty item list. It does not query or update feed records or call Gemini. Scheduler, forced-job and direct-fetch compatibility entrypoints are inert. Stored news history is retained.

## Published applicant experiences

This feature is deliberately unchanged pending separate instructions. Its existing on-demand Google Search grounding, filters, cache and refresh behavior remain available and can still incur Google Search/API costs. The shared news generation helper accepts only the existing `news.f1_interview_experiences` usage source.

## Scope

Chats without catalog access direct new university/course recommendation requests to Course Finder and can still discuss choices already present in the profile or documents. The CRM assistant uses its existing database catalog tools and is instructed not to invent alternatives when they return no matches. These chat instructions do not provide the structural record validation enforced by Course Finder.

Ordinary AI chat, mock interviews, document analysis and personalized notifications continue without newly added search tools. Existing non-AI exchange-rate and UK maintenance source refreshes are outside the retired Gemini grounding/catalog research services. Historical AI usage and costs remain visible; disabling a feature does not erase those records.
