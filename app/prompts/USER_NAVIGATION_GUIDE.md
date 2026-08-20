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
- `Universities` : Shortlist & Recommendations, Course Finder, SOP Studio
- `Documents` : Upload and manage documents, validation status, stage mapping
- `Interview Prep` (sub-tab labels adapt to the student's destination — e.g. a US student
  sees "F-1 Visa Interview Prep", an Australian student sees "Student Visa Interview Prep";
  refer to them by the destination-appropriate name, never the US one for a non-US student) :
  - `<Visa> Interview Prep (Rilono AI)` — guided question-by-question coaching
  - `<Visa> Mock Interview (Rilono AI)` — full mock interview simulation
  - `Recent Interview Experiences` (US) / `Recent Applicant Experiences` (other destinations)
- `Rilono Copilot` : Chrome extension tab
- `News` : Latest visa and student updates for the student's destination
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

## Rilono Copilot (Chrome Extension)
- What it is: a Chrome side-panel assistant that brings Rilono AI beside whatever page the student is filling (visa forms, university portals), personalized to their Rilono account and destination country (US, UK, Canada, Australia).
- Install: Chrome Web Store → search "Rilono Copilot" → `Add to Chrome` → pin it → click the icon to open the side panel.
- Sign-in: there is NO separate login. The extension reuses the student's signed-in `rilono.com` session. A `rilono.com` tab must be open and logged in. Flow: click `Open Rilono Login` → sign in on rilono.com → return to the panel → click `I am logged in`.
- Access: Copilot chat requires an active **Visa Success Pass**. Signed-in users without the pass get an unlock message instead of answers.
- `Inspect Page`: read-only; reads the visible page/form ONLY when the student clicks the Inspect button, then Copilot explains what to enter field by field. It never auto-fills or submits anything. Non-Rilono sites ask a one-time per-site permission.
- Encrypted documents: off by default. If the student's vault is unlocked on rilono.com, an "Include my unlocked encrypted documents" toggle appears; only after enabling it is decrypted text included. The extension never sees the passphrase. If the vault is locked, they must unlock it on rilono.com first.
- If onboarding is incomplete (no destination chosen), Copilot shows neutral copy and asks them to choose a destination on rilono.com.
- Troubleshooting: "Copilot not responding" → check (1) a rilono.com tab is open and signed in, (2) the account has an active Visa Success Pass, (3) onboarding/destination is completed.

## Journey Stage Guidance
- Stage progress is shown in Overview.
- Clicking a stage shows required docs and progress.
- Stage advancement depends on mandatory docs mapped in catalog and validation rules.

## Common User Questions
- "Why can’t I upload more?" → Check plan limits and usage in subscription card.
- "Why can’t I use this feature?" → Free tier quota may be exhausted; suggest the Visa Success Pass.
- "How do I change my subscription?" → Open `/subscription`.
- "Where do I see document issues?" → Documents tab + Overview > Document Health.
- "How do I use Rilono Copilot?" → It is the Chrome extension (see the Rilono Copilot section above): install from the Chrome Web Store, keep a signed-in rilono.com tab open, and hold an active Visa Success Pass. Do NOT confuse it with the in-app Rilono AI chat.
