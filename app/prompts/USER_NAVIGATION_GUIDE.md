# Rilono User Navigation Guide

This guide helps users navigate the Rilono web app UI quickly.

## Main Routes
- `/` : Home page
- `/dashboard` : Main dashboard
- `/subscription` : Subscription Management view
- `/unsubscribe-email?token=...` : Email notifications unsubscribe flow
- `/pricing` : Pricing page
- `/about-us` : About page
- `/contact` : Contact form
- `/privacy` : Privacy policy
- `/terms` : Terms and conditions
- `/refund-policy` : Refund policy
- `/delivery-policy` : Delivery policy

## Dashboard Left Menu
- `Overview` : Journey status, document health summary, and embedded AI chat
- `Documents` : Upload and manage documents, validation status, stage mapping
- `F1-Visa (Interviews)` :
  - `F-1 Visa Interview Prep (Rilono AI)`
  - `F1 Mock Interview (Rilono AI)`
  - `Recent F1 Interview Experiences`
- `News` : Latest F1 visa-related updates
- `Rilono AI` : Full chat workspace

## Top-Right User Menu
- `Dashboard` : Opens dashboard
- `Profile` : Opens profile tab inside dashboard
- `Manage Subscription` : Opens `/subscription`
- `Feature Request` : Opens feature request modal
- `Logout` : Signs out

## Email Notification Controls
- Unsubscribe link is present in email footer (small and low-visibility) for notification emails.
- Unsubscribe page asks for reason before confirmation.
- In-app bell notifications continue even after email unsubscribe.
- Re-enable location:
  - Dashboard → `Profile` tab → `Email Notifications` card.
  - `Enable Email Notifications` button is shown only when email notifications are currently disabled.

## Subscription Management (`/subscription`)
- Shows:
  - Current plan and status
  - Auto-renew state
  - Access end/renewal dates
  - Latest payment
  - Usage counters (AI, uploads, prep, mock)
- Actions:
  - Upgrade/Renew subscription
  - Cancel auto-renew (when applicable)

## Documents Tab
- Upload order:
  1. Select Document
  2. Document Type
  3. Description (Optional)
  4. Password
- Supported file types:
  - PDF, DOC, DOCX, TXT, Images
- Max file size:
  - 5 MB per file
- Validation:
  - Each uploaded document can be marked valid/needs review with reason.

## Journey Stage Guidance
- Stage progress is shown in Overview.
- Clicking a stage shows required docs and progress.
- Stage advancement depends on mandatory docs mapped in catalog and validation rules.

## Common User Questions
- "Why can’t I upload more?" → Check plan limits and usage in subscription card.
- "Why can’t I use this feature?" → Free tier quota may be exhausted; suggest Pro.
- "How do I change my subscription?" → Open `/subscription`.
- "Where do I see document issues?" → Documents tab + Overview > Document Health.
