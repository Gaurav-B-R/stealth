# Rilono Enterprise — product help guide

This file is the Rilono AI assistant's knowledge base about the enterprise portal itself.
It is split into topics by `## [topic-key] Title` headings; `app/enterprise_help.py` serves
one topic at a time to the assistant and replaces `{{PLACEHOLDER}}` lines with blocks
generated live from the product's own registries (permissions, roles, plans, prices, tax,
limits, credit prices, client stages).

Editing rules:
- The FIRST line of each topic is its one-sentence summary (shown in the topic index).
- UI labels in quotes are the exact strings the portal renders — keep them in sync with
  `static/enterprise.js`. When a screen or flow changes, update its topic here in the same
  change (docs/workflows/docs-update-checklist.md).
- Never hand-write capability keys, role contents, plan names, prices, "+ GST", seat / open-file /
  credit / read / message numbers, trial length or free allowances in prose — those come from
  the `{{...}}` placeholders so they can never go stale (and so "+ GST", yearly billing and
  free Deep Scans only appear while they are actually true). Refer to "the plans list" or
  "the credits topic" instead.
- tests/test_enterprise_help.py fails when this guide drifts from the code's registries.

## [getting-started] Getting started & finding your way around

The portal's layout: what each sidebar item opens and where the everyday actions live.

Each consultancy gets its own workspace at its own portal address (e.g. `https://yourcompany.rilono.com`). Staff sign in there with their email and password ("Welcome back" → "Sign in"). A new workspace is created from the public site via "Create free workspace" and starts on the free trial (what it includes is in the credits-billing topic).

The sidebar has two groups. Under **Workspace**:
- **Dashboard** — KPI cards ("Total clients", "Active cases", "Approved", "New this month") plus "Needs attention", "Client pipeline", "Recent clients", "Upcoming deadlines" and "Payments" cards.
- **Clients** — the client table with stage-filter chips, country and office filters, and "+ Add Client".
- **Leads** — the lead inbox and public lead-capture forms ("📥 Lead Inbox" / "🧾 Forms" tabs).
- **Course Finder** — Rilono's shared universities & courses catalog ("📚 Browse Catalog" free, "✨ AI Shortlists" paid).
- **Rilono AI Assistant** — this assistant's full-page chat (it is also available on every screen as the floating "Ask Rilono AI" button, bottom-right).
- **Team** — members, roles & permissions, offices, the access log, and "My access".
- **Calendar** — month view of events, reminders and auto-derived client key dates ("+ Add reminder").
- **Finance** — tabs "📊 Overview", "↘ Income", "↗ Costs", "⚡ Saved with Rilono", "🏦 Payout account".

Under **Account**:
- **Plans & Billing** — the subscription: current plan, usage bars (staff seats, open files, AI document reads), plan cards, checkout.
- **Credits** (screen title "Credits & Billing") — the AI-credit wallet: balance, AI document reads left, "Top up credits", pricing and usage analytics.
- **Help & Support** — contact Rilono support ("🛟 Get help") or send a feature idea ("💡 Feature idea").
- **Settings** — company name and logo, company location, workspace facts, your account.

The top bar always has the search box ("Search clients…", on Dashboard/Clients), the notifications bell, and "+ Add Client". The user chip at the bottom of the sidebar shows who is signed in and their role, with a "Sign out" button.

## [team-access] Team: inviting members, roles, permissions & data scopes

How to invite a teammate and give them exactly the access you want — roles, permission fine-tuning, data scopes, offices, and the rules that protect the workspace.

**To invite a teammate:** open **Team → Members** and click **"+ Invite member"** (needs the "Manage team" permission). In the "Invite a team member" dialog fill in their **Email** (required; name, job title and phone optional), pick a **Role**, choose **"What client data can they see?"** (the data scope), and — for office-scoped members — **"Which offices?"**. Click **"Send invite"**. The teammate receives an email with the portal address and a one-time password-setup link valid 72 hours; once they set a password they can sign in. They occupy a seat immediately (if the plan's seats are full you'll be asked to upgrade). If the link expires, use the member row's **⋯ → "Resend invite"**.

**Roles.** A role is a bundle of permissions plus a default data scope. Built-in roles:
{{ROLE_PRESETS}}

**Data scopes** control WHICH client records the member can see (their permissions control WHAT they can do with them):
{{RECORD_SCOPES}}

**To change someone's access later:** Team → Members → the member's **⋯ menu → "Edit access"** (needs "Manage roles & permissions"). There you can switch their role, change their data scope and offices, and open **"Fine-tune individual permissions"** — a per-permission matrix where each permission is "Inherit" (whatever the role says), "Allow" (grant on top of the role) or "Block" (deny even if the role grants it). Save with **"Save access"**. A "Block" always wins over any grant.

**Custom roles:** Team → **"Roles & permissions"** tab. Duplicate a preset ("Duplicate to customise") or click **"+ Create role"**, name it, pick its data scope and set each permission to Allowed / Not allowed. Custom roles can be edited, duplicated and archived (archiving asks where to move members still holding the role). Roles are archived, never deleted. Custom roles and offices depend on the plan — see "Plans and the Team features" below.

**Safety rules the portal enforces (the assistant should state these when relevant):**
- Nobody can change their **own** access — a colleague with the right permission must do it.
- The **owner's** access can't be edited; ownership moves only via ⋯ → "Transfer ownership", which emails the current owner a 6-digit confirmation code. The old owner becomes an Admin. Exactly one owner per workspace.
- You can only hand out permissions **you yourself hold**, and a data scope no wider than your own.
- The workspace must always keep at least one active Owner/Admin.
- "Owner-only" permissions (refunds, payout bank account, ownership transfer) can never be granted to anyone else.
- Every access change is recorded in Team → **"Access log"** (visible with the "View access log" permission).

**Offices:** Team → **"Offices"** tab → **"+ Add office"** (name, code, city, time zone…). Members are attached to offices in the invite/edit-access dialogs; clients get a "Branch / office" in their form. Office-scoped members see only their offices' clients. Archiving an office asks you to move its clients and members first; the default office can't be archived.

**Plans and the Team features:**
{{TEAM_FEATURES}}

**Deactivating / removing a member:** member ⋯ menu → **"Deactivate"** (or "Remove from workspace"). If they still have assigned clients or open reminders, the portal asks who takes them over — nothing is orphaned. Deactivation signs them out immediately and frees their seat; their private AI-assistant chats are permanently deleted. "Reactivate" restores access (re-checking the seat limit).

**Everyone can check their own access** under Team → **"My access"** — no permission needed.

**Every permission** — its label, key and what it allows — is listed in the permissions topic (the same list the fine-tune matrix and role editor show).

Workspace limits:
{{WORKSPACE_LIMITS}}

## [permissions] The full permission list

Every permission a role or member can hold, grouped as the Roles & Permissions matrix groups them, with what each one allows.

Permissions are granted through a role (Team → "Roles & permissions") and fine-tuned per member (member ⋯ menu → "Edit access" → "Fine-tune individual permissions"); see the team-access topic for how. The list, exactly as the matrix and role editor show it:
{{CAPABILITY_MATRIX}}

## [clients-pipeline] Clients, leads, the case pipeline & open-file limits

Adding clients, assigning counsellors, moving cases through stages (including Closed), how leads become clients, and which files count toward the plan's open-file limit.

**Add a client:** the **"+ Add Client"** button (always in the top bar, also on the Clients screen) opens "Add new client". Required: full name, destination country and visa type. The form also captures contact details, target intake, admission stage, prior visa/refusal history, "How did they hear about us?", **"Branch / office"**, **"Assigned counselor"**, next follow-up, key date, pipeline stage, priority, academic/test/funding profile, and consent checkboxes. Save with **"Add client"**.

**Duplicates:** if the email, phone, passport number, or name+date-of-birth matches an existing client, the portal warns you and the save button flips to "Add anyway" — duplicates are allowed but take an open-file slot like any other open file.

**Assign or reassign a counsellor:** the "Assigned counselor" select in the Add/Edit client form (needs "Assign clients" to change an existing assignment). Unassigned clients show "Unassigned" in the list.

**The client page (dossier):** click any client row. Tabs: Overview, 🎓 Universities, ✍️ SOP & LOR, Documents, 🛡️ Deep Scan, 🎤 Interview, ✨ Copilot, Emails, Notes, 💳 Payments. The action bar has "🔗 Share with client" and "Edit details".

**Change the pipeline stage:** open the client → **"Edit details"** → click the new stage in the "Pipeline stage" card (the tracker is read-only outside edit mode) and confirm. Stages can also be set when creating the client. Marking a shortlisted university as applied offers to move the case to "Applications submitted" automatically. The stage list is ordered per destination country; "Approved"/"Rejected" mean the **visa** decision only — a university turning someone down is recorded on the shortlist, not the pipeline. A file that ends without a visa decision goes to "Closed", which sits off the journey like "Rejected".

**Delete a client:** at the bottom of "Edit details" in the type-to-confirm "Danger zone" (needs the "Delete clients" permission). Deletion is permanent and removes everything attached.

**Leads:** the **Leads** screen has a "📥 Lead Inbox" (statuses, filters, search) and "🧾 Forms" — public lead-capture forms you can share; submissions land in the inbox and can be converted into client records. A converted lead enters the pipeline at the "New Lead" stage and, like any new client, takes an open-file slot. Leads themselves never count toward the plan.

**Open files and the plan limit:**
{{OPEN_FILES}}

## [documents] Client documents: upload, AI reading, AI scan, requests & approval

Uploading client documents, the free AI reading and its monthly allowance ("Not read yet" / "Read now"), the optional paid AI scan, requesting documents from clients by email, and who can see or download what.

**Upload:** client page → **Documents** tab → "Upload a document": pick the document type (searchable, tailored to the client's destination), choose the file (PDF, images, Word/Excel, CSV or text, up to 25 MB) and click **"Upload document"**. Uploading and storing is always free, and files are encrypted at rest.

**AI reading (free, from the plan's reads):** the document shows "Reading…" while Rilono AI reads it in the background.
{{AI_READS}}

**AI scan (optional, paid):** tick **"Scan & validate with Rilono AI"** when uploading (or scan later from the document's card). The scan checks the document is the right type, genuine and in date, cross-validates it against the client's profile and already-validated documents, and auto-fills empty profile fields it can prove. It is priced by the document's length (see the credits topic); the portal names the exact cost before you confirm, and a scan that fails to return a verdict isn't charged. Badges show the outcome: "✓ Validated by Rilono AI", "⚠ Needs review", "✓ Manually approved", "Not scanned", "Scan failed". Accepting a document (the "Accept documents" permission) writes its extracted fields onto the client record.

**Request documents from the client:** Documents tab → **"✉ Request documents"** emails the client a secure upload link; you can revoke it any time ("Revoke document request?"). Submitted files appear in the same tab and notify the team.

**Permissions that matter here:** "View documents" shows the list and AI verdicts; "Download documents" is separate (raw passports and bank letters are sensitive); "Upload", "Accept", "Delete" and "Request" are each their own permission — see the Team topic for how to grant them.

## [client-links] Sharing with the client: portal, copilot, interview & upload links

The four client-facing links staff can send — what each shows the client, what it costs, how long it lives, and how to revoke it.

All client links work the same way: they go to the **client's email on record**, one live link per client per feature (sending a new one replaces the old), and the link alone is never enough — the client must verify a **6-digit code** emailed to them (valid 15 minutes). Staff can revoke any link instantly from the same place it was sent.

- **Client portal** ("🔗 Share with client" on the dossier → "✉ Share portal with …" (the button shows the client's name)): a read-only view of their own case — stages, details, documents, universities, payments. Notes are never shown. Free; the link lives 180 days; each verified visit lasts 24 hours. Needs the "Share client portal" permission. The dialog shows "Opened n times", "Resend new link", "Copy link" and "Revoke access".
- **Client Copilot** (dossier → ✨ Copilot tab → "Send copilot access to …" (the button shows the client's name)): the client's own AI chat about their application, grounded in their case. Flat price in credits, charged **once, when the client first opens it** — an ignored link costs nothing. Price, message allowance and lifetime are below. Needs "Share client copilot". Revoking is immediate (no refund once activated).
- **Mock interview invite** (🎤 Interview tab or "🎤 Send … a mock interview" (the button shows the client's name)): a self-serve AI mock visa interview the client takes on their own; the completed session, transcript and coaching report appear in the Interview tab (unfinished sessions don't). Charged per interview — see below. Needs "Send interview invites".
- **Document request** (Documents tab → "✉ Request documents"): a secure upload link — see the documents topic.

What the paid links cost and allow:
{{CLIENT_LINK_TERMS}}

If a client says their link "doesn't work", the usual causes are: the link was superseded by a newer one, it expired, it was revoked, or the one-time code was mistyped too many times (after too many failed codes the link locks and a fresh one must be sent).

## [ai-features] Rilono AI features & what they do

Every AI feature in the portal — what it does, where it lives, and its free allowance.

- **Rilono AI Assistant** (sidebar "Rilono AI Assistant", or the floating "Ask Rilono AI" button on any screen): answers questions from your live workspace data — clients, pipeline, documents, calendar, team, credits, finance — and product how-to questions like this one. Chats are saved per member ("History" / "New chat") and kept 90 days; your chats are private to you and are deleted if your access is deactivated. Requires the "Rilono AI Assistant" and "Spend credits" permissions.
- **Deep Scan** (client page → 🛡️ Deep Scan): strictly audits the client's ENTIRE dossier — profile, stage records, the documents' contents, notes, emails, universities, interviews, payments — and flags anything irregular. Its price and how many documents one scan covers are in the credits topic.
- **Document scan & validate** (Documents tab, at upload or later): one document checked, cross-validated and auto-filled, priced by its length — see the documents topic. (Plain AI reading of every upload is separate and comes from the plan's AI document reads.)
- **Writing Studio** (client page → ✍️ SOP & LOR): drafts a submission-ready SOP or LOR grounded in the client's real dossier, exported as a formatted Word file. Every refinement is saved as a new version so you can compare and re-export. A generated LOR is a draft **for the recommender** — they must verify, edit and sign it.
- **AI university shortlist** (client page → 🎓 Universities): AI-recommended universities matched to the client's destination, budget, grades and intake.
- **Course Finder AI shortlist** (Course Finder → "✨ AI Shortlists", or the client's Universities tab): a personalized course shortlist from Rilono's verified catalog. Browsing the catalog is always free.
- **AI mock visa interview** (client page → 🎤 Interview): role-plays the visa officer for the client's destination, grounded in their profile and documents, then produces a readiness report. Each interview is one session with a fixed number of officer questions and one feedback report (numbers in the credits topic); when the officer closes the interview, generate the report — a finished session can't take more answers. Staff can run one live or email the client a self-serve invite.
- **Client Copilot** (client page → ✨ Copilot): the client's own AI chat — see the client-links topic.

What each action costs and every free allowance is in the credits-billing topic (ask about "credits" for exact numbers). Every plan includes every AI feature. All AI features also require the member to hold "Spend credits" — an owner/admin can block a member from spending by denying that one permission. If AI features are paused because the trial ended or a plan lapsed, the credits-billing topic explains what still works and how to turn AI back on.

## [credits-billing] Plans, free trial, credits & billing

The subscription plans and what they include, the free trial and what happens when it ends, what every AI action costs in credits, free allowances, top-up packs and how billing behaves.

**Plans** (managed under **Plans & Billing**; needs the "Plans & subscription" permission to change):
{{PLANS}}

Checkout runs through Razorpay. Renewal is a manual re-purchase unless auto-renewal is on ("Turn off auto-renewal" on the Current plan card). What counts as an open file, and what happens when you go over, is in the clients-pipeline topic; how AI document reads work is in the documents topic.

**Free trial, lapsed plans and paused AI:**
{{TRIAL_AND_AI_PAUSE}}

**Credits** (the **Credits** screen, title "Credits & Billing"): Rilono Credits are the wallet that pays for AI actions. The wallet card shows the balance; **"Top up credits"** buys a pack.

**What things cost:**
{{CREDIT_PRICING}}

If the wallet can't cover an action, the portal blocks it up front with a clear message — a failed AI run is never charged. When the balance runs low, whoever can top up gets a notification. Buying credits needs the "Buy credits" permission; spending them needs "Spend credits". Percentage coupon codes can be applied at checkout when Rilono has issued one to your workspace.

## [finance] Finance: student payments, books & the payout account

Collecting student payments online, recording offline income, the company books, refunds and the ROI panel.

The **Finance** screen (Beta) has five tabs:
- **"📊 Overview"** — the period's income, costs, receivables and cash position at a glance.
- **"↘ Income"** — money in: online student payments (collected via Razorpay after you "Connect bank" on the banner), manually recorded offline payments (cash / bank transfer / UPI / card / cheque), and other income entries. Online payments generate invoices numbered `INV-…`, manual ones `MAN-…`. Rilono's commission on online collection is 2% (minimum ₹49) per payment; recording offline payments is free. Online collection is INR-only, up to ₹5,00,000 per payment.
- **"↗ Costs"** — expenses: salaries, rent, marketing, agent commissions, and automatic entries for what you pay Rilono (plan, credit top-ups, commission). Monthly recurring entries (like rent) can be templated.
- **"⚡ Saved with Rilono"** — the ROI panel: real completed AI work (scans, interviews, drafts, emails…) × editable minutes-per-task × your hourly cost, minus what you paid Rilono. Every assumption is on screen and editable.
- **"🏦 Payout account"** — where settled student payments land. Owner-only.

Per-client payment history lives on the client page's 💳 Payments tab ("View payments" permission). Raising invoices and recording payments needs "Manage payments"; the company books need the separate "Company books" permission (P&L is more sensitive than per-client receipts); **refunds and the payout bank account are owner-only**. Money answers in Finance follow the org's financial-year quarters and the default office's timezone.

## [calendar] Calendar, reminders & notifications

The team calendar, event reference files, auto-derived client key dates, and how the notification bell decides what to tell you.

**Calendar** (sidebar): a month grid of the workspace's events in your record scope. Click a day or **"+ Add reminder"** to open "Event details" — title, date/time, linked client, assignee, notes, and up to 6 attached reference files (agendas, appointment letters; 15 MB each). Events linked to a client also appear on that client's page. Editing needs "Manage calendar"; viewing needs "View calendar".

The calendar and the assistant also surface **auto-derived key dates** — client interview/travel dates, passport expiries, next follow-ups — without anyone creating an event.

**Notifications** (the bell, top bar): high-signal events only — a client added, a stage moved, a mock interview completed, requested documents submitted, team membership changes, credits running low. Routine actions (notes, edits, scans) deliberately don't notify. You are never notified about your own action, and notifications respect each member's record scope. "Mark all read" clears the badge.

All dates and "today"/"overdue" decisions use the workspace's operating timezone, which comes from the default office's time zone setting (Team → Offices).

## [course-finder] Course Finder & university shortlists

Browsing Rilono's shared universities & courses catalog, running AI shortlists, and how the per-client Universities tab works.

**Course Finder** (sidebar) is Rilono's shared catalog across all supported destinations — universities, courses, fees, intakes and score requirements, with per-country coverage stats shown in the hero. **"📚 Browse Catalog"** is free and unlimited: filter by destination, level, discipline, tuition, and "Advanced filters" (fees & funding, tests & entry, program). **"✨ AI Shortlists"** generates a personalized shortlist for a client (priced in credits; past shortlists are kept).

On a client's page, the **🎓 Universities** tab is their own shortlist: add candidates manually, from catalog browse ("Add selected to shortlist"), or via the embedded AI shortlist pinned to the client's destination. Track each university's status there (applied, admit, declined…); marking one applied offers to move the pipeline stage to "Applications submitted". A university declining the client is recorded here — it does NOT make the client "rejected" (that's the visa decision).

Catalog answers cover Rilono's whole shared catalog, not your workspace's own records. Application deadlines in the catalog are not reliably current — always confirm deadlines on the university's official page.

## [support] Help & Support: contacting Rilono

Raising a support ticket or feature idea with Rilono, and tracking what you've sent.

Open **Help & Support** in the sidebar. Two tabs: **"🛟 Get help"** (something's wrong or confusing) and **"💡 Feature idea"**. Fill the subject and description, optionally attach up to 5 files / 10 MB total (screenshots can be pasted directly), and click **"Send to support"** / **"Send feature idea"**. Requests go to Rilono's support inbox (shown on the page, with a copy button) and your submissions are listed below under "Your requests" with a status pill (open / in progress / closed). Anyone with "Contact Rilono support" can raise tickets and see their own; "Manage support tickets" additionally shows every ticket the workspace has raised. The page's "Quick answers" rail covers the most common questions — and you can always ask this assistant first.

## [security-privacy] Security, privacy & data protection

How workspace data is isolated, encrypted and access-controlled, and what clients can and cannot see.

- **Tenant isolation:** every record belongs to your organization; nothing is ever visible to another workspace, and this assistant can only read your own organization's data.
- **Access control:** everything staff can see or do is governed by their role's permissions and record scope (see the team-access topic). Sensitive identity fields (passport numbers) and raw document downloads are separate permissions. Permission changes are audited in Team → "Access log".
- **Documents & files** are stored encrypted at rest under unguessable keys and served only through authenticated, organization-scoped downloads — never public URLs.
- **Client-facing links** never rely on the link alone: a one-time emailed code is always required, links expire, and staff can revoke them instantly. The client portal never shows internal notes, and the client copilot masks identity numbers.
- **Consent:** the client form records DPA processing consent and per-channel marketing consent (unchecked by default), timestamped.
- **Sessions:** deactivating a member signs them out immediately; their private assistant chats are permanently deleted. Assistant conversations are retained 90 days.
- **Payments** are processed by Razorpay; Rilono never stores card numbers.

For a formal data-processing or security question, raise it via Help & Support so Rilono can answer in writing.
