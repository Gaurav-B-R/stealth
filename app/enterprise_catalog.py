"""
Student-visa & destination-country catalog for the Rilono enterprise platform.

Rilono Enterprise is focused exclusively on STUDENT / education visas for the ten
most popular study destinations. This module is the single source of truth for:
  * The (single) visa category — student
  * Destination countries, their iconic landmark, flag and brand gradient
  * The student visa types available for each country
  * The visa-case pipeline stages a client moves through

The frontend renders bundled SVG landmark art keyed by the country `code`, using
the `gradient_from` / `gradient_to` / `accent` colors supplied here so the look is
fully on-brand and never depends on an external image/CDN.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app import enterprise_client_fields as client_fields


# ---------------------------------------------------------------------------
# Visa category (student only)
# ---------------------------------------------------------------------------

VISA_CATEGORY_STUDENT = "student"

VISA_CATEGORIES = [
    {
        "key": VISA_CATEGORY_STUDENT,
        "label": "Student",
        "short_label": "Student",
        "description": "Study permits and student visas for universities & colleges.",
        "icon": "graduation",
        "accent": "#6366f1",
        "uses_intake": True,
    },
]

VISA_CATEGORY_MAP = {item["key"]: item for item in VISA_CATEGORIES}
VISA_CATEGORY_KEYS = {item["key"] for item in VISA_CATEGORIES}


# ---------------------------------------------------------------------------
# Visa-case pipeline stages
# ---------------------------------------------------------------------------

STAGE_NEW_LEAD = "new_lead"
STAGE_SHORTLISTING = "shortlisting"
STAGE_APPLICATIONS_SENT = "applications_sent"
STAGE_OFFER_ACCEPTED = "offer_accepted"
STAGE_DOCUMENTS = "documents"
STAGE_SUBMITTED = "submitted"
STAGE_APPOINTMENT = "appointment"
STAGE_DECISION = "decision"
STAGE_APPROVED = "approved"
STAGE_REJECTED = "rejected"
STAGE_ON_HOLD = "on_hold"

CLIENT_STAGES = [
    {
        "key": STAGE_NEW_LEAD,
        "label": "New Lead",
        "description": "Enquiry received, not yet started.",
        "order": 1,
        "color": "#64748b",
        "is_open": True,
        "is_terminal": False,
    },
    {
        "key": STAGE_SHORTLISTING,
        "label": "University Shortlisting",
        "description": "Choosing courses and universities, and preparing the application essays.",
        "order": 2,
        "color": "#2dd4bf",
        "is_open": True,
        "is_terminal": False,
    },
    {
        "key": STAGE_APPLICATIONS_SENT,
        "label": "University Applications",
        "description": "Applications sent to the shortlisted universities — awaiting their decisions.",
        "order": 3,
        "color": "#14b8a6",
        "is_open": True,
        "is_terminal": False,
    },
    {
        "key": STAGE_OFFER_ACCEPTED,
        "label": "Offer Accepted & Deposit Paid",
        "description": "One offer accepted and the tuition deposit paid; enrolment document requested.",
        "order": 4,
        "color": "#0d9488",
        "is_open": True,
        "is_terminal": False,
    },
    {
        "key": STAGE_DOCUMENTS,
        "label": "Collecting Documents",
        "description": "Gathering and preparing the applicant's documents.",
        "order": 5,
        "color": "#6366f1",
        "is_open": True,
        "is_terminal": False,
    },
    {
        "key": STAGE_SUBMITTED,
        "label": "Application Submitted",
        "description": "Application filed with the consulate / authority.",
        "order": 6,
        "color": "#0ea5e9",
        "is_open": True,
        "is_terminal": False,
    },
    {
        "key": STAGE_APPOINTMENT,
        "label": "Biometrics / Appointment",
        "description": "Biometrics or VFS appointment booked — plus a visa interview where the destination requires one.",
        "order": 7,
        "color": "#8b5cf6",
        "is_open": True,
        "is_terminal": False,
    },
    {
        "key": STAGE_DECISION,
        "label": "Awaiting Decision",
        "description": "Application under review by the authority.",
        "order": 8,
        "color": "#f59e0b",
        "is_open": True,
        "is_terminal": False,
    },
    {
        "key": STAGE_APPROVED,
        "label": "Approved",
        "description": "Visa granted. 🎉",
        "order": 9,
        "color": "#10b981",
        "is_open": False,
        "is_terminal": True,
    },
    {
        "key": STAGE_REJECTED,
        "label": "Rejected",
        "description": "Application refused.",
        "order": 10,
        "color": "#ef4444",
        "is_open": False,
        "is_terminal": True,
    },
    {
        "key": STAGE_ON_HOLD,
        "label": "On Hold",
        "description": "Paused — waiting on the client or external factors.",
        "order": 11,
        "color": "#9ca3af",
        "is_open": False,
        "is_terminal": False,
    },
]

CLIENT_STAGE_MAP = {item["key"]: item for item in CLIENT_STAGES}
CLIENT_STAGE_KEYS = {item["key"] for item in CLIENT_STAGES}
DEFAULT_CLIENT_STAGE = STAGE_NEW_LEAD


# ---------------------------------------------------------------------------
# Destination-specific stage WORDING
# ---------------------------------------------------------------------------
# The stage KEYS, ORDER and COLORS above are structural: they are stored on the client
# row, and drive the kanban columns, filter chips and analytics across a whole org, so
# they are the same for every destination and must stay that way.
#
# What the stages are CALLED, though, is destination-specific. The generic set is
# US/UK-shaped and misleads elsewhere: a UAE case has no "Application Submitted" to a
# consulate (the university's PRO files an entry permit with ICP/GDRFA), and its
# "Biometrics / Appointment" is an Emirates ID capture and medical fitness test taken
# INSIDE the country after arrival. Ditto the Netherlands, where the recognised sponsor
# — not the student — files with the IND.
#
# So label/description resolve per destination while everything else stays fixed.
# Only the differences are listed; anything omitted keeps the generic wording above.
ENTERPRISE_STAGE_LABELS: dict[str, dict[str, dict]] = {
    "US": {
        "new_lead": {
            "label": "New Lead",
            "description": "Enquiry logged after the first consultation — academic profile, budget "
                           "and the F-1 intake being targeted.",
        },
        "shortlisting": {
            "label": "Shortlisting & SOP",
            "description": "SEVP-certified schools shortlisted on program fit, test scores and "
                           "first-year cost; SOP drafted and recommenders briefed for their LORs.",
        },
        "applications_sent": {
            "label": "Applications Sent",
            "description": "Applications filed on each school's own portal or the Common App with "
                           "transcripts, TOEFL/IELTS and GRE/GMAT scores; admits, waitlists and "
                           "denials tracked per school.",
        },
        "offer_accepted": {
            "label": "Admit Accepted & I-20 Requested",
            "description": "One admit accepted and the enrolment deposit paid; financial evidence "
                           "sent to the DSO so the SEVP school can raise the I-20.",
        },
        "documents": {
            "label": "I-20 & Financial Evidence",
            "description": "Signed I-20 in hand — SEVIS ID, funds figure and program start date "
                           "recorded — with bank statements, sponsor affidavit and academic "
                           "originals assembled for the interview.",
        },
        "submitted": {
            "label": "DS-160 & Fees Paid",
            "description": "DS-160 filed for the chosen consular post, with the SEVIS I-901 and MRV "
                           "visa fees paid and receipts on file.",
        },
        "appointment": {
            "label": "OFC & Visa Interview",
            "description": "Fingerprints and photo taken at the OFC/VAC, and the consular interview "
                           "slot booked at the embassy or consulate.",
        },
        "decision": {
            "label": "Awaiting CEAC Status",
            "description": "Officer's counter outcome logged; CEAC tracked through Administrative "
                           "Processing, plus any 221(g) slip or document request.",
        },
        "approved": {
            "label": "F-1 Visa Stamped",
            "description": "Visa foil printed in the passport and the passport returned — "
                           "issue/expiry dates, entries and annotation recorded.",
        },
        "rejected": {
            "label": "Visa Refused",
            "description": "Refused at the counter — most often 214(b) non-immigrant intent; "
                           "officer's stated reason and reapply plan captured.",
        },
        "on_hold": {
            "label": "On Hold",
            "description": "Paused — waiting on the client, funds, a fresh I-20 or a deferred "
                           "intake before the case moves again.",
        },
    },
    "CA": {
        "new_lead": {
            "label": "New Lead",
            "description": "Enquiry received — log the first consultation and the target province "
                           "or territory before any filing work starts.",
        },
        "shortlisting": {
            "label": "Shortlisting DLIs & SOP",
            "description": "DLIs shortlisted by program, province and PAL/TAL availability; the "
                           "Statement of Purpose / Letter of Explanation drafted and the language "
                           "test booked.",
        },
        "applications_sent": {
            "label": "Applications to DLIs",
            "description": "Applications filed direct with each DLI — OUAC for Ontario undergrad — "
                           "with transcripts and language scores; offers and their conditions "
                           "tracked.",
        },
        "offer_accepted": {
            "label": "LOA Accepted & Deposit Paid",
            "description": "One DLI offer accepted and the tuition deposit paid so the Letter of "
                           "Acceptance is confirmed; PAL/TAL requested from the province — the CAQ "
                           "carries it in Quebec — and the GIC opened.",
        },
        "documents": {
            "label": "PAL, Funds & Forms",
            "description": "LOA and PAL/TAL in hand; proof of funds assembled — GIC or four months "
                           "of bank evidence — plus IMM 1294, the family information form and the "
                           "panel-physician medical.",
        },
        "submitted": {
            "label": "Submitted to IRCC",
            "description": "Study permit application filed online in the IRCC portal — fees paid, "
                           "UCI and application number recorded, IMM 5476 on file.",
        },
        "appointment": {
            "label": "Biometrics & Medical",
            "description": "Biometrics Instruction Letter issued — biometrics given at a VAC within "
                           "the deadline, plus the panel-physician medical exam (IME).",
        },
        "decision": {
            "label": "IRCC Review & PPR",
            "description": "IRCC assessing the file: watch the portal for additional-document "
                           "requests, then the passport request (PPR) and passport handover to the "
                           "VAC.",
        },
        "approved": {
            "label": "POE Letter & TRV/eTA",
            "description": "Approved — student holds the Port of Entry Letter of Introduction plus "
                           "TRV counterfoil or eTA; CBSA issues the study permit on arrival.",
        },
        "rejected": {
            "label": "Refused",
            "description": "IRCC refusal letter received — order GCMS notes, debrief the grounds, "
                           "then choose between reapplying and Federal Court judicial review.",
        },
        "on_hold": {
            "label": "On Hold",
            "description": "Paused — funds or GIC not ready, PAL/LOA pending, intake deferred or "
                           "student undecided; reason logged with a follow-up date.",
        },
    },
    "UK": {
        "new_lead": {
            "label": "New Lead",
            "description": "Enquiry received — first consultation booked, course level, budget and "
                           "English test status captured.",
        },
        "shortlisting": {
            "label": "Shortlisting & Personal Statement",
            "description": "Licensed student sponsors shortlisted on course, entry requirements and "
                           "fees; UCAS or direct route decided and the personal statement drafted.",
        },
        "applications_sent": {
            "label": "UCAS / Direct Applications",
            "description": "Applications sent through UCAS for undergraduate study or the "
                           "university's own portal for postgraduate; references and transcripts "
                           "supplied, offers and their conditions tracked.",
        },
        "offer_accepted": {
            "label": "Offer Firmed & CAS Requested",
            "description": "One unconditional offer accepted, the tuition deposit paid and the "
                           "pre-CAS credibility interview passed so the sponsor will assign a CAS.",
        },
        "documents": {
            "label": "CAS & Financial Evidence",
            "description": "CAS assigned and checked line by line; maintenance funds held the full "
                           "28 days, TB certificate obtained and ATAS clearance where the course "
                           "needs one.",
        },
        "submitted": {
            "label": "Filed with UKVI",
            "description": "Student route form submitted online; visa fee and IHS paid, GWF / UAN "
                           "reference issued.",
        },
        "appointment": {
            "label": "Biometrics Enrolment",
            "description": "Biometrics and documents given at a VFS Global or TLScontact centre — "
                           "UKVCAS only when switching inside the UK — or identity verified in the "
                           "UK Immigration: ID Check app.",
        },
        "decision": {
            "label": "Awaiting UKVI Decision",
            "description": "With UKVI caseworkers — track the standard or priority SLA and any "
                           "interview or further-information request.",
        },
        "approved": {
            "label": "eVisa Granted",
            "description": "Student permission granted — eVisa-only since 15 Jul 2025: confirm the "
                           "UKVI account and share code work; only courses of 6 months or "
                           "less still get a passport vignette.",
        },
        "rejected": {
            "label": "Refused / Admin Review",
            "description": "Refusal notice cites an Immigration Rules paragraph; the administrative "
                           "review window is short, otherwise plan a reapplication.",
        },
        "on_hold": {
            "label": "On Hold",
            "description": "Paused — usually waiting on the CAS, the 28-day funds seasoning, ATAS "
                           "clearance or the client themselves.",
        },
    },
    "AU": {
        "new_lead": {
            "label": "New Lead",
            "description": "First consultation held — capture the AQF level, budget, English test "
                           "status and preferred city before opening the file.",
        },
        "shortlisting": {
            "label": "Shortlisting Providers & Courses",
            "description": "CRICOS-registered providers and courses shortlisted on fit, fees and "
                           "city, with the course-choice rationale the later Genuine Student "
                           "answers rest on.",
        },
        "applications_sent": {
            "label": "Applications to Providers",
            "description": "Applications lodged with each provider, direct or through its education "
                           "agent; transcripts and English scores sent, letters of offer and their "
                           "conditions tracked.",
        },
        "offer_accepted": {
            "label": "Offer Accepted & CoE Requested",
            "description": "One letter of offer accepted, the ESOS written agreement signed and the "
                           "first tuition instalment plus OSHC paid so the provider issues the eCoE "
                           "from PRISMS.",
        },
        "documents": {
            "label": "CoE, OSHC & Documents",
            "description": "eCoE and CRICOS code in hand; Genuine Student answers drafted, OSHC "
                           "policy on file, English score and evidence of funds in AUD assembled "
                           "with NAATI translations.",
        },
        "submitted": {
            "label": "Lodged in ImmiAccount",
            "description": "Subclass 500 lodged online — record the TRN, visa application charge "
                           "receipt, applicant's location at lodgement and any dependants.",
        },
        "appointment": {
            "label": "Medicals & Biometrics",
            "description": "Post-lodgement health exam at a panel clinic against the HAP ID, plus "
                           "biometrics at a collection centre if the Department requests them.",
        },
        "decision": {
            "label": "Awaiting Decision",
            "description": "Case with the Department of Home Affairs — track ImmiAccount status and "
                           "answer any s56 request for more information by its due date.",
        },
        "approved": {
            "label": "Subclass 500 Granted",
            "description": "Electronic grant notification issued — log the grant number, stay-until "
                           "date, first-entry deadline and visa conditions; no visa label.",
        },
        "rejected": {
            "label": "Refused",
            "description": "Refusal received — log the ground; if ART review rights apply, diarise "
                           "the tribunal deadline, otherwise plan a fresh lodgement.",
        },
        "on_hold": {
            "label": "On Hold",
            "description": "Paused — deferred intake, funds or CoE not ready, or waiting on the "
                           "student; record the reason and the resume date.",
        },
    },
    "DE": {
        "new_lead": {
            "label": "New Lead",
            "description": "Enquiry logged — study level, budget and whether this student needs an "
                           "APS certificate for Germany.",
        },
        "shortlisting": {
            "label": "Hochschule Shortlist & Motivation",
            "description": "Hochschulen shortlisted on language of instruction, NC and "
                           "Semesterbeitrag; APS started, TestAS or the language certificate booked "
                           "and the Motivationsschreiben and tabular Lebenslauf drafted.",
        },
        "applications_sent": {
            "label": "uni-assist / Direct Applications",
            "description": "Applications filed through uni-assist or the university's own portal by "
                           "the 15 Jan / 15 Jul deadline; the VPD issued where a university demands "
                           "one, and admission decisions tracked.",
        },
        "offer_accepted": {
            "label": "Zulassung Accepted & Enrolled",
            "description": "One admission taken up — place accepted, any tuition or Semesterbeitrag "
                           "settled and the Zulassungsbescheid (or Studienkolleg place) confirmed "
                           "in writing.",
        },
        "documents": {
            "label": "Documents & Sperrkonto",
            "description": "Blocked account (Sperrkonto) funded to the annual minimum, German "
                           "health insurance arranged, and the APS certificate, transcripts and "
                           "§54 declaration assembled for the mission.",
        },
        "submitted": {
            "label": "Filed with German Mission",
            "description": "Application filed with the Auslandsvertretung via the Consular Services "
                           "Portal / VIDEX form, and the visa fee paid.",
        },
        "appointment": {
            "label": "Embassy Appointment",
            "description": "Personal appearance at the German mission or VFS: originals lodged, "
                           "biometrics captured, passport usually retained by the mission.",
        },
        "decision": {
            "label": "Awaiting Decision",
            "description": "Mission reviews the file, often forwarding it to the local "
                           "Ausländerbehörde for consent; further-information requests are common "
                           "here.",
        },
        "approved": {
            "label": "National D Visa Issued",
            "description": "National (D) visa sticker in the passport for entry — student then "
                           "registers in Germany and converts it to a residence permit.",
        },
        "rejected": {
            "label": "Refused / Klage",
            "description": "Ablehnungsbescheid issued — remonstration was abolished 1 Jul 2025, so "
                           "the routes are a Klage at the Verwaltungsgericht Berlin within one "
                           "month of service, or a stronger fresh application.",
        },
        "on_hold": {
            "label": "On Hold",
            "description": "Paused — waiting on an appointment slot, APS or blocked-account "
                           "funding, or the student deferring to a later semester.",
        },
    },
    "IE": {
        "new_lead": {
            "label": "New Lead",
            "description": "Enquiry logged; check whether the student's nationality needs an Irish "
                           "visa at all, plus the study level and budget.",
        },
        "shortlisting": {
            "label": "Shortlisting ILEP Programmes",
            "description": "Colleges and programmes shortlisted off the ILEP / TrustEd Ireland "
                           "lists on level, fees and learner protection; English test booked and "
                           "the letter of application drafted.",
        },
        "applications_sent": {
            "label": "College Applications",
            "description": "Applications sent through the CAO for undergraduate study or direct to "
                           "the college for postgraduate; transcripts and English scores supplied, "
                           "offers tracked.",
        },
        "offer_accepted": {
            "label": "Offer Accepted & Fees Paid",
            "description": "One offer taken up and tuition paid — EUR 6,000 minimum, by EFT to the "
                           "college's Irish account or via Transfermate — so it issues the Letter "
                           "of Acceptance.",
        },
        "documents": {
            "label": "Funds, FSF & Insurance",
            "description": "Letter of Acceptance in hand; EUR 10,000 living funds evidenced over "
                           "six months, the Financial Summary Form completed and private medical "
                           "insurance taken out.",
        },
        "submitted": {
            "label": "AVATS Form Submitted",
            "description": "AVATS online application completed and the visa fee paid; summary "
                           "sheet, passport and supporting documents then go to the visa office.",
        },
        "appointment": {
            "label": "Lodgement & Biometrics",
            "description": "Passport and original documents lodged at VFS or the embassy; "
                           "fingerprints taken only where that visa office collects biometrics.",
        },
        "decision": {
            "label": "Awaiting Decision",
            "description": "Visa office reviewing the file: track AVATS status and the weekly "
                           "decision lists, and answer any further-documents request before its "
                           "deadline.",
        },
        "approved": {
            "label": "Visa Granted & Stamp 2",
            "description": "Study visa sticker issued in the passport; the student travels, then "
                           "registers in Ireland for the IRP card carrying Stamp 2 permission.",
        },
        "rejected": {
            "label": "Refused / Appeal",
            "description": "Refusal letter issued with reason codes; one free written appeal to the "
                           "Visa Appeals Officer within 2 months, or rebuild the case and re-apply.",
        },
        "on_hold": {
            "label": "On Hold",
            "description": "Paused: intake deferred, funds not yet seasoned, or waiting on the "
                           "student or college to come back.",
        },
    },
    "FR": {
        "new_lead": {
            "label": "New Lead",
            "description": "Enquiry logged — confirm whether Études en France is compulsory and fix "
                           "the route: DAP, Parcoursup or EEF, for a named rentrée.",
        },
        "shortlisting": {
            "label": "Shortlist & Lettres de Motivation",
            "description": "Établissements and programmes shortlisted for the chosen route; "
                           "TCF/TEF booked, CV written and one tailored lettre de motivation per "
                           "programme — the EEF dossier takes up to seven.",
        },
        "applications_sent": {
            "label": "Études en France Dossier",
            "description": "EEF dossier submitted with the programme choices and the Campus France "
                           "procedure fee paid; entretien pédagogique sat and its avis recorded, "
                           "then the établissements' decisions awaited. DAP files close 15 Dec.",
        },
        "offer_accepted": {
            "label": "Acceptation & Inscription",
            "description": "One accord préalable d'inscription accepted in the platform and the "
                           "inscription fee paid; Campus France closes the procedure with the "
                           "end-of-procedure email that unlocks the consular appointment.",
        },
        "documents": {
            "label": "Ressources & Visa Documents",
            "description": "Post-acceptance visa file built: resources for the whole first year at "
                           "the rate in force, 3-month accommodation, apostilled birth certificate "
                           "and sworn translations.",
        },
        "submitted": {
            "label": "France-Visas Filed",
            "description": "France-Visas form validated online for the VLS-TS and the consular fee "
                           "settled — the dossier itself reaches the post at the appointment.",
        },
        "appointment": {
            "label": "Lodgement & Biometrics",
            "description": "File and passport handed in at VFS, TLScontact or Capago; biometrics "
                           "captured, receipt issued, passport retained until the decision.",
        },
        "decision": {
            "label": "Awaiting Decision",
            "description": "Under examination at the post with no public tracker — poll the "
                           "provider portal, answer document requests fast, follow the passport "
                           "back.",
        },
        "approved": {
            "label": "VLS-TS Issued & Validated",
            "description": "Long-stay visa collected, then validated on ANEF within 3 months of "
                           "arrival — the VLS-TS itself serves as the residence permit.",
        },
        "rejected": {
            "label": "Refused / CRRV Appeal",
            "description": "Reasoned refusal, or two months' silence; the mandatory CRRV appeal to "
                           "the visa-refusals commission in Nantes goes by registered post within "
                           "30 days of notification.",
        },
        "on_hold": {
            "label": "On Hold",
            "description": "Paused on a named blocker — Études en France and DAP cut-offs are "
                           "annual, so a stalled file quietly costs a whole rentrée.",
        },
    },
    "ES": {
        "new_lead": {
            "label": "New Lead",
            "description": "Enquiry logged: study route under art. 52, course length, and whether "
                           "the file goes to a consulate abroad or an Oficina de Extranjería.",
        },
        "shortlisting": {
            "label": "Shortlist & Acceso",
            "description": "Recognised centres shortlisted off RUCT / the Registro estatal on "
                           "course length and fees; UNEDasiss and the PCE for undergraduates, or "
                           "the equivalencia de nota media for postgraduates, set in motion.",
        },
        "applications_sent": {
            "label": "Solicitudes de Admisión",
            "description": "Admission applications sent to the shortlisted centres with apostilled, "
                           "sworn-translated transcripts; preinscripción results and admission "
                           "decisions tracked.",
        },
        "offer_accepted": {
            "label": "Admisión & Matrícula",
            "description": "One place taken up and the matrícula paid — a declaración responsable "
                           "stands in where enrolment is not yet open — so the centre issues the "
                           "carta de admisión.",
        },
        "documents": {
            "label": "Fondos, Penales & Docs",
            "description": "Carta de admisión in hand; living funds at 100% of IPREM, health "
                           "insurance, police-clearance (penales) and medical certificates, "
                           "apostilles and sworn translations assembled.",
        },
        "submitted": {
            "label": "Solicitud Lodged",
            "order": 7,
            "description": "Solicitud completed and the fees settled — consular tasa plus the "
                           "790/052 authorisation fee — with the número de solicitud recorded from "
                           "the receipt.",
        },
        "appointment": {
            "label": "Cita Previa & Lodgement",
            "order": 6,
            "description": "Passport and originals handed over at the cita previa, plus a "
                           "comparecencia (personal interview) if summoned; no prints on the D "
                           "route — VIS is for Schengen C.",
        },
        "decision": {
            "label": "Awaiting Resolución",
            "description": "Two waits: the estancia authorisation in 7 days (no answer means "
                           "refused), then the consulate's decision within a month — a subsanación "
                           "asks you to correct the file inside 10 days.",
        },
        "approved": {
            "label": "Visado Tipo D & TIE",
            "description": "Tipo D visa issued with the NIE printed on it — collected in person "
                           "within 2 months, then entry to Spain and, on stays over 6 months, TIE "
                           "huellas within a month of arrival.",
        },
        "rejected": {
            "label": "Refused / Recurso",
            "description": "Resolución denegatoria notified — one month for a recurso de "
                           "reposición, two for the contencioso-administrativo, or refile "
                           "corrected.",
        },
        "on_hold": {
            "label": "On Hold",
            "description": "Paused — admission, funds, cita previa availability or the client; next "
                           "follow-up date set.",
        },
    },
    "NL": {
        "new_lead": {
            "label": "New Lead",
            "description": "Enquiry received — check whether the nationality needs an MVV, and the "
                           "study level and budget.",
        },
        "shortlisting": {
            "label": "Shortlisting Erkend Referenten",
            "description": "Programmes shortlisted only at IND recognised sponsors (erkend "
                           "referent); numerus fixus deadlines diarised, English test booked and "
                           "the motivation letter drafted.",
        },
        "applications_sent": {
            "label": "Studielink Applications",
            "description": "Applications submitted through Studielink — at most four programmes, "
                           "two of them numerus fixus — plus each institution's own portal; "
                           "selection rounds and admission decisions tracked.",
        },
        "offer_accepted": {
            "label": "Admission Accepted & Enrolled",
            "description": "One admission accepted in Studielink and enrolment completed; tuition "
                           "settled with the institution so the recognised sponsor will open the "
                           "IND file.",
        },
        "documents": {
            "label": "Documents & Funding",
            "description": "Living-cost funds transferred to the sponsor, antecedents certificate "
                           "(7601) signed and TB declaration of intent (7603) completed, with "
                           "legalised diplomas handed to the sponsor.",
        },
        "submitted": {
            "label": "Sponsor Filed with IND",
            "description": "The recognised sponsor lodges the TEV application (MVV plus residence "
                           "permit) with the IND; the zaaknummer is issued now, the V-number "
                           "arrives with the decision.",
        },
        "appointment": {
            "label": "MVV Appointment",
            "order": 8,
            "description": "Biometrics and MVV collection at a Dutch mission or VFS — booked only "
                           "once the IND approves; MVV-exempt nationalities skip this step.",
        },
        "decision": {
            "label": "Awaiting IND Decision",
            "order": 7,
            "description": "IND assesses the sponsor's file; the legal limit is 90 days but most "
                           "student cases decide far sooner. Updates come via the sponsor.",
        },
        "approved": {
            "label": "Residence Permit Card",
            "description": "MVV used to enter, residence card collected at the IND desk, BRP "
                           "registration and BSN done, GGD TB screening where required.",
        },
        "rejected": {
            "label": "Refused / Bezwaar",
            "description": "IND refused or withdrew the case — bezwaar (objection) is normally due "
                           "within four weeks, filed by the sponsor or the student.",
        },
        "on_hold": {
            "label": "On Hold",
            "description": "Paused — deferred intake, funding not yet in place, or waiting on the "
                           "client or the sponsor.",
        },
    },
    "AE": {
        "new_lead": {
            "label": "New Lead",
            "description": "Enquiry taken: emirate, budget and sponsorship route (university PRO vs "
                           "other) scoped, plus a UAE ban / absconding check.",
        },
        "shortlisting": {
            "label": "Shortlisting Licensed Institutions",
            "description": "Institutions shortlisted off the CAA / KHDA / ADEK licensed lists on "
                           "emirate, programme accreditation and fees; English test booked and the "
                           "personal statement drafted.",
        },
        "applications_sent": {
            "label": "Applications to Institutions",
            "description": "Applications sent to the shortlisted universities with transcripts; "
                           "equivalency requirements and offer decisions tracked.",
        },
        "offer_accepted": {
            "label": "Offer Accepted & Fees Paid",
            "description": "One offer accepted, with tuition and the refundable visa deposit "
                           "settled, so the institution's PRO can open the sponsorship file.",
        },
        "documents": {
            "label": "Documents & Attestation",
            "description": "Degrees run the legalisation chain to MOFAIC attestation; medical "
                           "insurance arranged and passport copies, photos and the PRO's "
                           "sponsorship paperwork handed over.",
        },
        "submitted": {
            "label": "Entry Permit Filed",
            "description": "The university's PRO (its government-relations officer) files the entry "
                           "permit with ICP or GDRFA; it comes back as an e-visa the student must "
                           "enter on within 60 days.",
        },
        "appointment": {
            "label": "Medical & Emirates ID",
            "description": "Student flies in on the entry permit, then sits the medical fitness "
                           "test and gives Emirates ID biometrics inside the UAE within 60 days.",
        },
        "decision": {
            "label": "Residence File Pending",
            "description": "Residence file sits with ICP / GDRFA after biometrics; the PRO chases "
                           "status and clears any document query before the permit issues.",
        },
        "approved": {
            "label": "Residence & Emirates ID",
            "description": "Residence permit issued and Emirates ID in hand, with UID and health "
                           "insurance active and the refundable visa deposit tracked back.",
        },
        "rejected": {
            "label": "Refused / Blocked",
            "description": "Entry permit or residence refused, or the file blocked by a ban; "
                           "grievance or reconsideration and any reapplication tracked here.",
        },
        "on_hold": {
            "label": "On Hold",
            "description": "Case paused — sponsor, PRO or institution-side blocker, a deferred "
                           "intake, or the student's own delay — with a follow-up date set.",
        },
    },
    "PL": {
        "new_lead": {
            "label": "New Lead",
            "description": "Enquiry logged after the first consultation — study level, budget "
                           "against full-first-year tuition prepayment, and the B2 certificate in "
                           "the language of instruction that admission legally requires since the "
                           "1 June 2025 package.",
        },
        "shortlisting": {
            "label": "Shortlisting Approved Uczelnie",
            "description": "Uczelnie (universities) shortlisted — no central body, each runs its "
                           "own IRK portal; confirm the institution may admit foreigners and mind "
                           "the 50% foreign-student cap, since Ministry approval also carries the "
                           "student work-permit exemption.",
        },
        "applications_sent": {
            "label": "IRK Applications & Exams",
            "description": "Applications filed on each university's own IRK portal — 85 PLN "
                           "standard, 100 PLN exam-based, up to 150 PLN for art programmes — with "
                           "entrance exams or interviews for non-EU credentials since 2025; offers "
                           "tracked per programme.",
        },
        "offer_accepted": {
            "label": "Tuition Paid & Zaświadczenie",
            "description": "Offer accepted and tuition — usually the full first year — prepaid, so "
                           "the university issues the zaświadczenie o przyjęciu in the statutory "
                           "23 Sep 2019 format: the visa anchor document.",
        },
        "documents": {
            "label": "Apostilles, Syrena & Funds",
            "description": "MEA apostilles, NAWA Syrena / kurator recognition of the secondary "
                           "certificate, €30,000 insurance from the MFA-approved list, funds at "
                           "1,010 PLN a month plus 2,500 PLN return travel, and accommodation "
                           "proof stating the monthly fee.",
        },
        "submitted": {
            "label": "File Lodged & €200 Paid",
            "order": 7,
            "description": "The paper file is lodged in person at the booked VFS VAC / consulate "
                           "appointment — nothing is filed before it; €200 paid at the counter, "
                           "biometrics taken, passport retained, and 7 days to cure any formal "
                           "deficiency.",
        },
        "appointment": {
            "label": "e-Konsulat Slot & VFS eForm",
            "order": 6,
            "description": "e-Konsulat form (secure2.e-konsulat.gov.pl) completed, printed and "
                           "signed twice, the VFS eForm done and the slot booked — Delhi lodges "
                           "Mon–Wed 10:00, Mumbai once a fortnight, so book the day the "
                           "zaświadczenie lands.",
        },
        "decision": {
            "label": "Awaiting Consul's Decision",
            "description": "The consul in New Delhi or Mumbai decides — statutory 15 days "
                           "extendable to 30, India committing to 30 calendar days from "
                           "registration — and may summon a credibility interview first; the "
                           "passport stays retained throughout.",
        },
        "approved": {
            "label": "Visa D Issued & MOS 2.0 TRC",
            "description": "Type D 'studies' sticker (symbol 09) issued and passport returned — "
                           "then fly, register the address (PESEL auto-assigned) and file the TRC "
                           "on MOS 2.0 before the visa expires: 340 + 100 PLN, fingerprints at the "
                           "urząd wojewódzki, 15-month karta pobytu.",
        },
        "rejected": {
            "label": "Refused / Ponowne Rozpatrzenie",
            "description": "Standard-form refusal handed back with the passport — wniosek o "
                           "ponowne rozpatrzenie sprawy to the same consul within 14 days, at the "
                           "full €200 again; a corrected refile for the next intake usually beats "
                           "it.",
        },
        "on_hold": {
            "label": "On Hold",
            "description": "Paused — tuition prepayment, apostille or Syrena recognition, "
                           "e-Konsulat slot scarcity (worst June–September) or the client; reason "
                           "logged with a follow-up date set.",
        },
    },
    "NZ": {
        "new_lead": {
            "label": "New Lead",
            "description": "Enquiry logged — prior study, any gap since it, English level and "
                           "whether NZ$20,000 a year plus first-year tuition can realistically be "
                           "evidenced, before the file opens.",
        },
        "shortlisting": {
            "label": "Shortlisting Providers & SOP",
            "description": "Universities, polytechnics and NZQA-approved PTEs shortlisted — "
                           "Pastoral Care Code signatories only; ten polytechnics stand alone "
                           "again since 1 Jan 2026, so verify the legal provider name.",
        },
        "applications_sent": {
            "label": "Applications to Institutions",
            "description": "Applications filed direct on each institution's own portal — New "
                           "Zealand has no central admission portal — free or a small fee at most "
                           "universities; offers and their conditions tracked.",
        },
        "offer_accepted": {
            "label": "Offer of Place Accepted",
            "description": "Offer of Place moved from conditional to unconditional and accepted. "
                           "Tuition is normally NOT paid yet — INZ endorses paying after the AIP; "
                           "some PTEs ask a small deposit.",
        },
        "documents": {
            "label": "Funds, Medicals & PCC",
            "description": "Funds file built (NZ$20,000/yr plus first-year tuition, sources "
                           "proven), SOP drafted, eMedical done at a panel physician (INZ 1096 / "
                           "1007, under 3 months old) and the PCC ordered early — it must be in "
                           "the file at lodgement since Jul 2026.",
        },
        "submitted": {
            "label": "Filed on Immigration Online",
            "description": "Application lodged online in INZ's enhanced Immigration Online — "
                           "paper lodgement ended 18 Sep 2025 — fee from NZ$850 paid by card; 80% "
                           "of Fee Paying files decide within 8.5 weeks.",
        },
        "appointment": {
            "label": "Biometrics (VFS) / Medicals",
            "description": "On INZ's request letter, photo and fingerprints at a VFS centre "
                           "(Delhi, Mumbai, Bengaluru, Chennai — service fee about INR 1,700 "
                           "since 1 Jan 2026); any outstanding medicals completed now.",
        },
        "decision": {
            "label": "AIP, Tuition & Grant",
            "description": "INZ runs the bona fide and funds tests — a PPI letter needs a fast, "
                           "evidenced answer. On the AIP, tuition is paid by the letter's own "
                           "deadline (commonly ~10 days, 15 with FTS); the visa issues only after "
                           "the receipt.",
        },
        "approved": {
            "label": "eVisa Granted",
            "description": "eVisa emailed and electronically linked to the passport — no sticker, "
                           "no card, nothing to collect. Next: enrol in person, open the bank "
                           "account, apply for the IRD number.",
        },
        "rejected": {
            "label": "Declined / Reconsideration",
            "description": "Decline letter cites the immigration instructions not met. Offshore "
                           "has no appeal — reapply better evidenced; onshore only: "
                           "reconsideration within 14 days, NZ$220, one shot.",
        },
        "on_hold": {
            "label": "On Hold",
            "description": "Paused — PCC or medicals pending, funds unsourced, FTS transfer in "
                           "flight, AIP tuition being arranged, or a deferred February / July "
                           "intake; follow-up date set.",
        },
    },
    "SG": {
        "new_lead": {
            "label": "New Lead",
            "description": "Enquiry logged — profile, budget and the single August UG intake "
                           "targeted, plus whether the route is an IHL or an EduTrust PEI, "
                           "which sets the timeline, work rights and insurance downstream.",
        },
        "shortlisting": {
            "label": "Shortlisting & EduTrust Check",
            "description": "No central portal — universities, polytechnics and PEIs picked "
                           "directly; every private institution checked against the SSG "
                           "EduTrust register, since only certified PEIs can sponsor a "
                           "Student's Pass.",
        },
        "applications_sent": {
            "label": "Direct University Applications",
            "description": "Applications filed on each institution's own portal — NUS, NTU, "
                           "SMU and the rest; the UG international window runs roughly Oct–Mar "
                           "for the August intake, with offers landing May–Jul.",
        },
        "offer_accepted": {
            "label": "Offer Accepted & SOLAR Registered",
            "description": "Letter of Offer accepted and the acceptance fee paid; the "
                           "institution issues the Registration Acknowledgement Letter and "
                           "registers the student in SOLAR (IHL) or SOLAR+ (EduTrust PEI, on "
                           "the CPE standard contract).",
        },
        "documents": {
            "label": "eForm 16 Pack & Medicals",
            "description": "Passport bio page, ICA-spec digital photo under 3 months old, "
                           "qualifications and parent/sponsor income details assembled for "
                           "eForm 16, with the HIV and chest X-ray medical planned.",
        },
        "submitted": {
            "label": "eForm 16 Filed in SOLAR",
            "description": "Student files eForm 16 in SOLAR/SOLAR+ — at least 2 and at most 3 "
                           "months before course start on both tracks — and pays the "
                           "non-refundable S$45 processing fee at submission (7 days at most).",
        },
        "appointment": {
            "label": "ICA Completion of Formalities",
            "order": 8,
            "description": "After the IPA and arrival: e-appointment at the ICA Services "
                           "Centre, 2 Crawford Street, or campus Offsite Enrolment — "
                           "biometrics enrolled, medical report handed in, terms signed and "
                           "S$60 (+S$30 MJV) paid.",
        },
        "decision": {
            "label": "Awaiting IPA (ICA Decision)",
            "order": 7,
            "description": "ICA decides on the SOLAR file — about a week for IHLs (two if a "
                           "visa is required), up to a month for PEIs; the In-Principle "
                           "Approval embeds the single-journey entry visa for visa-required "
                           "nationals.",
        },
        "approved": {
            "label": "Digital Student's Pass Issued",
            "description": "Digital-only pass (no card since 27 Feb 2023) lands via FileSG and "
                           "the Singpass app about 3 working days after formalities — FIN, "
                           "validity and the work-rights position recorded.",
        },
        "rejected": {
            "label": "Refused / SOLAR Appeal",
            "description": "Bare refusal in SOLAR — ICA states no reasons; appeal via the "
                           "school and the ICA enquiry form only with genuinely new evidence "
                           "(~4 weeks), or refile any time on a fresh S$45.",
        },
        "on_hold": {
            "label": "On Hold",
            "description": "Paused — usually the school-side SOLAR registration, the "
                           "≥2/≤3-month filing window or the client; reason and follow-up "
                           "date logged.",
        },
    },
    "IT": {
        "new_lead": {
            "label": "New Lead",
            "description": "Enquiry logged — 12-years-schooling check, budget scoped against "
                           "the €10,179.85/yr funds bar and the B2 teaching-language floor "
                           "before the file opens.",
        },
        "shortlisting": {
            "label": "Shortlisting & Entrance Tests",
            "description": "No national portal — universities shortlisted on their own "
                           "admission sites, each one's non-EU seat quota (Art. 46 DPR "
                           "394/1999) checked; IMAT diarised for English-taught medicine "
                           "(29 Sep 2026 — moved twice already, reconfirm on Universitaly).",
        },
        "applications_sent": {
            "label": "Direct University Applications",
            "description": "Applications filed on each university's own apply portal with "
                           "evaluation fees of €0-100; rolling decisions in 2-10 weeks, "
                           "ranking-list dates for test-entry programmes.",
        },
        "offer_accepted": {
            "label": "Lettera di Ammissione Accepted",
            "description": "Acceptance letter in hand — conditional admits show on "
                           "Universitaly as 'accepted with reservations'; many universities "
                           "take the first tuition instalment now to lock the seat.",
        },
        "documents": {
            "label": "Preiscrizione, CIMEA & Funds",
            "description": "Domanda di preiscrizione filed on Universitaly and digitally "
                           "validated by the university (capped at quota +20%); CIMEA "
                           "statements or DoV, apostilles and €10,179.85/yr in traceable "
                           "funds assembled.",
        },
        "submitted": {
            "label": "Lodged at the Consulate",
            "order": 7,
            "description": "The file is with the MAECI consulate the moment the appointment "
                           "ends — €50 fee receipted; a.y. 2026-27 degree files must be "
                           "lodged by 30 November 2026.",
        },
        "appointment": {
            "label": "VAC Appointment & Lodgement",
            "order": 6,
            "description": "Slot at VFS Global (India), BLS-Intiana (Pakistan) or the "
                           "consulate — the appointment IS the lodgement: documents, €50 fee "
                           "and fingerprints (mandatory since 11 Jan 2025) in one visit.",
        },
        "decision": {
            "label": "Awaiting Consular Decision",
            "description": "MAECI mission decides under the 90-day standard term — "
                           "suspendable for further checks — after the DM 850/2011 "
                           "migration-risk assessment; every outcome is logged on "
                           "Universitaly.",
        },
        "approved": {
            "label": "Visa Issued & Permesso Kit",
            "description": "D sticker in the passport — within 8 working days of landing the "
                           "permesso di soggiorno kit giallo goes in at Poste Italiane "
                           "(≈€116.46), then Questura fingerprints; the ricevuta proves "
                           "legal stay.",
        },
        "rejected": {
            "label": "Refused / Ricorso al TAR",
            "description": "Written, reasoned refusal via the VAC — 60 days to the TAR del "
                           "Lazio (150 for residents outside Europe); a corrected refile is "
                           "usually faster, but the freed Universitaly slot must be "
                           "re-secured.",
        },
        "on_hold": {
            "label": "On Hold",
            "description": "Paused — most often the university's Universitaly validation, "
                           "CIMEA lead time or VAC slot scarcity; reason and follow-up date "
                           "logged.",
        },
    },
    "SE": {
        "new_lead": {
            "label": "New Lead",
            "description": "Enquiry logged after the first consultation — academic record, budget "
                           "against SEK 80,000–295,000-a-year tuition, and passport validity, "
                           "since the permit never outruns the passport.",
        },
        "shortlisting": {
            "label": "Ranking the 4 Programme Choices",
            "description": "One national application per round with up to four ranked programmes — "
                           "admitted to the highest eligible choice, lower choices deleted; autumn "
                           "is the real intake, spring carries few English-taught options.",
        },
        "applications_sent": {
            "label": "Universityadmissions.se Filed",
            "description": "Single file on Universityadmissions.se with one document set and the "
                           "SEK 900 fee — autumn closes 15 January with documents and fee due "
                           "2 February; spring closes 17 August, both due 1 September.",
        },
        "offer_accepted": {
            "label": "Admitted & First Tuition Paid",
            "description": "Notification of Selection Results accepted — the university says "
                           "whether a reply is needed — and the first tuition instalment paid: "
                           "Migrationsverket counts the student as finally admitted only once "
                           "tuition is paid.",
        },
        "documents": {
            "label": "Funds & Permit Evidence",
            "description": "Maintenance consolidated in the student's own liquid account — "
                           "SEK 10,656 a month for every month of the permit period, statement "
                           "issued within 4 months of the permit start; locked deposits fail, and "
                           "courses under a year add comprehensive insurance.",
        },
        "submitted": {
            "label": "Migrationsverket E-service Filed",
            "description": "Student files online from home in Migrationsverket's e-service and "
                           "pays SEK 1,500 by card — no consulate, no VFS; case number recorded "
                           "and the e-service inbox watched for komplettering requests.",
        },
        "appointment": {
            "label": "Embassy Biometrics (Walk-in)",
            "description": "Photo and fingerprints at the mission named in the application — "
                           "New Delhi walks in Mon–Fri 08:30–10:30, no appointment. Give them "
                           "straight after filing; the law allows waiting until after the "
                           "decision, at the price of ~4 weeks of card production before travel.",
        },
        "decision": {
            "label": "Awaiting Migrationsverket Decision",
            "description": "Migrationsverket decides on the written file — currently 75% of study "
                           "cases inside 2 months, with a 90-day statutory ceiling from a "
                           "complete application (art 34(1), Directive (EU) 2016/801); the beslut "
                           "lands in the e-service.",
        },
        "approved": {
            "label": "Permit Granted & Card Collection",
            "description": "Residence permit card produced ~4 weeks after grant plus biometrics "
                           "and collected in person at the embassy — the card is what boards the "
                           "flight; then Skatteverket registration and the 30-day address "
                           "notification to Migrationsverket.",
        },
        "rejected": {
            "label": "Refused / Överklagande",
            "description": "Beslut refused — the appeal deadline is stated in the decision "
                           "(typically three weeks): written överklagande to Migrationsverket, "
                           "omprövning, then the Migration Court; a corrected re-file is often "
                           "the faster route.",
        },
        "on_hold": {
            "label": "On Hold",
            "description": "Paused — selection results, the first tuition instalment, funds "
                           "consolidation or the client; reason logged with a follow-up date "
                           "set.",
        },
    },
}


def stages_for(country_code: str | None) -> list[dict]:
    """The pipeline stages worded for `country_code` (generic wording as fallback).

    A destination may also override a stage's `order` where its real chronology differs —
    the Netherlands is the case that forced this: the recognised sponsor files with the IND,
    the IND DECIDES, and only then is the student invited to a mission for biometrics and
    MVV collection, so `appointment` genuinely comes after `decision` there. The keys and
    colors stay fixed (the kanban and analytics are org-wide and share one column order);
    only this per-client journey view re-sequences.

    An override is an ABSOLUTE position in the canonical order, not an offset from the
    stage's own default — so inserting a stage into CLIENT_STAGES means renumbering every
    override that sits below it. The assertions at the bottom of this module catch a miss.
    """
    overrides = ENTERPRISE_STAGE_LABELS.get(str(country_code or "").strip().upper()) or {}
    resolved = []
    for stage in CLIENT_STAGES:
        item = dict(stage)
        override = overrides.get(stage["key"]) or {}
        for field in ("label", "description"):
            value = str(override.get(field) or "").strip()
            if value:
                item[field] = value
        if isinstance(override.get("order"), int):
            item["order"] = override["order"]
        resolved.append(item)
    resolved.sort(key=lambda s: s["order"])
    return resolved


def stages_by_country() -> dict:
    """Resolved stage wording for the frontend: {COUNTRY_CODE: [stage, …]}."""
    return {code: stages_for(code) for code in COUNTRY_MAP}


def stage_brief(country_code: str | None, stage_key: str | None) -> Optional[dict]:
    """One resolved stage (for serializing a client's current status pill)."""
    key = normalize_stage(stage_key)
    for stage in stages_for(country_code):
        if stage["key"] == key:
            return stage
    return None

CLIENT_PRIORITIES = [
    {"key": "low", "label": "Low", "color": "#94a3b8"},
    {"key": "normal", "label": "Normal", "color": "#6366f1"},
    {"key": "high", "label": "High", "color": "#f97316"},
    {"key": "urgent", "label": "Urgent", "color": "#ef4444"},
]
CLIENT_PRIORITY_KEYS = {item["key"] for item in CLIENT_PRIORITIES}
DEFAULT_CLIENT_PRIORITY = "normal"


# ---------------------------------------------------------------------------
# Student document types (for per-client document uploads)
# ---------------------------------------------------------------------------

STUDENT_DOCUMENT_TYPES = [
    "Passport",
    "Passport-size Photograph",
    "Offer / Admission Letter",
    "I-20 / CAS / Confirmation of Enrolment",
    "Financial Proof / Bank Statement",
    "Academic Transcripts & Certificates",
    "English Test Score (IELTS / TOEFL / PTE)",
    "Statement of Purpose (SOP)",
    "Letters of Recommendation",
    "Visa Application Form",
    "Visa Fee Receipt",
    "Medical / Health Insurance",
    "Other",
]
DEFAULT_DOCUMENT_TYPE = "Other"

# ---------------------------------------------------------------------------
# Per-country document catalogs (detailed, destination-specific)
# ---------------------------------------------------------------------------
# The generic STUDENT_DOCUMENT_TYPES above is the legacy/fallback list. Each entry:
#   key       — stable identifier (also used when seeding the DB catalog)
#   label     — what staff see & what is stored on EnterpriseClientDocument.document_type
#   required  — part of the standard checklist for that destination
#   hint      — one-line guidance shown in the picker
# Ordering is the recommended collection order for that destination.

ENTERPRISE_DOCUMENT_CATALOG: dict[str, list[dict]] = {
    "US": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "Valid at least 6 months beyond intended stay."},
        {"key": "photo", "label": "Passport Photo (2×2 inch, US spec)", "required": True, "hint": "White background, taken within 6 months."},
        {"key": "admission-letter", "label": "University Admission / Offer Letter", "required": True, "hint": "From the SEVP-certified school."},
        {"key": "immunization-records", "label": "University Immunization / Vaccination Record", "required": False, "hint": "MMR, TDap and meningococcal on the school's own form — a hold blocks course registration."},
        {"key": "form-i20", "label": "Form I-20 (signed)", "required": True, "hint": "DSO- and student-signed; from 15 Sep 2026 its end date sets the I-94 admit-until date."},
        {"key": "f2-dependent-documents", "label": "F-2 / J-2 Dependent Documents", "required": False, "hint": "Each dependent gets their own I-20 plus marriage or birth certificate; no I-901 fee for F-2."},
        {"key": "ds160-confirmation", "label": "DS-160 Confirmation Page", "required": True, "hint": "Barcode page from CEAC — the 5 years of social-media handles on it must be public accounts."},
        {"key": "sevis-receipt", "label": "SEVIS I-901 Fee Receipt", "required": True, "hint": "$350 F/M, $220 most J — pay on fmjfee.com against the SEVIS ID on the I-20 or DS-2019; reusable within 12 months if refused."},
        {"key": "mrv-fee-receipt", "label": "Visa (MRV) Fee Receipt", "required": True, "hint": "$185 — the CGI receipt number unlocks scheduling and lapses 365 days after payment."},
        {"key": "visa-integrity-fee-receipt", "label": "Visa Integrity Fee Receipt ($250)", "required": False, "hint": "OBBBA fee charged at issuance, not before — rollout is post-by-post, so budget for it."},
        {"key": "interview-appointment", "label": "Interview Appointment Confirmation", "required": True, "hint": "OFC biometrics + interview, booked at the post covering nationality or residence."},
        {"key": "residence-proof", "label": "Proof of Residence for the Consular Post", "required": False, "hint": "Needed when not applying in the country of nationality — posts have demanded it since Sep 2025."},
        {"key": "bank-statements", "label": "Bank Statements / Balance Certificate", "required": True, "hint": "Liquid funds covering I-20 first-year cost."},
        {"key": "loan-sanction", "label": "Education Loan Sanction Letter", "required": False, "hint": "If part of funding — sanctioned, not applied."},
        {"key": "scholarship-letter", "label": "Scholarship / Assistantship Letter", "required": False, "hint": "University or external funding award."},
        {"key": "sponsor-affidavit", "label": "Sponsor Affidavit of Support", "required": False, "hint": "With sponsor's bank proof & income evidence."},
        {"key": "sponsor-income-proof", "label": "Sponsor Income Tax Returns (ITR / Form 16)", "required": False, "hint": "3 years of returns plus salary slips — proves the sponsor earns what the affidavit claims."},
        {"key": "ca-statement", "label": "CA Statement / Asset Valuation", "required": False, "hint": "Chartered-accountant net-worth summary."},
        {"key": "transcripts", "label": "Academic Transcripts & Marksheets", "required": True, "hint": "All semesters, university-attested."},
        {"key": "degree-certificates", "label": "Degree / Provisional Certificates", "required": False, "hint": "Completed programs only."},
        {"key": "english-test", "label": "English Test Score (TOEFL / IELTS / Duolingo)", "required": True, "hint": "As required by the admitting school."},
        {"key": "aptitude-test", "label": "GRE / GMAT / SAT Score Report", "required": False, "hint": "If used in the admission."},
        {"key": "sop", "label": "Statement of Purpose (SOP)", "required": False, "hint": "Programme-specific admission essay — also the spine the counselor preps the interview from."},
        {"key": "resume", "label": "Resume / CV", "required": False, "hint": "Useful for interview & OPT-related questions."},
        {"key": "lor", "label": "Letters of Recommendation (LORs)", "required": False, "hint": "Usually 2-3, submitted by the recommender through the university's own portal."},
        {"key": "work-experience", "label": "Work Experience Letters", "required": False, "hint": "For applicants with employment history."},
        {"key": "gap-justification", "label": "Gap / Study-Break Justification", "required": False, "hint": "Explains gaps after prior education."},
        {"key": "home-ties-evidence", "label": "Evidence of Ties to the Home Country", "required": False, "hint": "Property, family business, job offer on return — the 214(b) presumption is rebutted here."},
        {"key": "prior-visa-refusal", "label": "Previous US Visa / Refusal Documents (221g)", "required": False, "hint": "Any earlier US travel or refusals."},
        {"key": "ds2019", "label": "Form DS-2019 (J-1 only)", "required": False, "hint": "J-1 sponsor's form — check whether it flags the 212(e) two-year home-residence rule."},
        {"key": "i94-record", "label": "I-94 Arrival/Departure Record (CBP)", "required": False, "hint": "Print from i94.cbp.dhs.gov after entry — from 15 Sep 2026 it shows a date, not 'D/S'."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "UK": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "UKVI sets no 6-month rule — it must simply be valid, and it is what the eVisa links to."},
        {"key": "cas", "label": "CAS Statement", "required": True, "hint": "Confirmation of Acceptance for Studies with CAS number."},
        {"key": "offer-letter", "label": "Unconditional Offer Letter", "required": True, "hint": "From the licensed student sponsor."},
        {"key": "pre-cas-interview", "label": "Pre-CAS Interview Outcome", "required": False, "hint": "Most sponsors run a mandatory pre-CAS credibility call — no pass, no CAS."},
        {"key": "cas-deposit-receipt", "label": "Tuition / CAS Deposit Receipt", "required": False, "hint": "Sponsors assign the CAS only once this clears; it must match 'fees paid' on the CAS."},
        {"key": "financial-evidence", "label": "28-Day Bank Statement / Financial Evidence", "required": True, "hint": "£1,529/mo London, £1,171 outside (max 9 mo), held 28 days, closing ≤31 days out."},
        {"key": "ihs-confirmation", "label": "IHS Payment Confirmation", "required": True, "hint": "£776 per year of leave, paid inside the application before the visa fee — keep the number."},
        {"key": "visa-application", "label": "Visa Application Confirmation (GOV.UK)", "required": True, "hint": "Submitted online application summary."},
        {"key": "tb-certificate", "label": "TB Test Certificate", "required": True, "hint": "Approved clinic only (Appendix TB list); expires 6 months after the chest x-ray."},
        {"key": "atas", "label": "ATAS Certificate", "required": False, "hint": "Sensitive-subject PG/research courses flagged on the CAS; valid 6 months for the application."},
        {"key": "selt", "label": "SELT / IELTS-for-UKVI Result", "required": False, "hint": "B2 for degree level, B1 below; UKVI-approved SELT only, valid 2 years — quote the URN."},
        {"key": "ecctis-statement", "label": "Ecctis Statement (Comparability / English Assessment)", "required": False, "hint": "Needed to rely on a degree taught in English outside a majority-English country (ST 6.1)."},
        {"key": "transcripts", "label": "Academic Transcripts", "required": True, "hint": "Documents used to obtain the CAS."},
        {"key": "degree-certificates", "label": "Degree Certificates", "required": False, "hint": "As listed on the CAS."},
        {"key": "sponsor-consent", "label": "Parental / Sponsor Consent + Relationship Proof", "required": False, "hint": "Student's own account, or a parent's/guardian's with consent + relationship proof; a partner's only if applying too or already has permission."},
        {"key": "parental-consent", "label": "Parental Consent & Care Arrangements (under 18)", "required": False, "hint": "Both parents' written consent to the visa, travel and care arrangements, plus birth proof."},
        {"key": "loan-letter", "label": "Education Loan Letter", "required": False, "hint": "Government or regulated education loan; letter dated within 6 months and free of conditions."},
        {"key": "scholarship-letter", "label": "Scholarship / Official Sponsorship Letter", "required": False, "hint": "Official sponsor on letterhead stating the amount, the period covered and contact details."},
        {"key": "official-sponsor-consent", "label": "Official Financial Sponsor Consent Letter", "required": False, "hint": "Needed where an official financial sponsor funded the student in the last 12 months."},
        {"key": "photo", "label": "Passport-size Photograph", "required": False, "hint": "Only if a VAC requests physical photos."},
        {"key": "prior-refusals", "label": "Previous UK Visa / Refusal Documents", "required": False, "hint": "Old passports plus any UK refusal, overstay or removal — the form asks 10 years of travel."},
        {"key": "cv", "label": "CV / Resume", "required": False, "hint": "Occasionally requested for credibility interviews."},
        {"key": "personal-statement", "label": "Personal Statement / Statement of Purpose", "required": False, "hint": "Carries the course-choice story the pre-CAS call and any UKVI interview will test."},
        {"key": "ukvi-account-evisa", "label": "UKVI Account & eVisa Confirmation", "required": False, "hint": "Students get no 90-day vignette since 15 Jul 2025 — the share code is what boards them."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "CA": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "A study permit is never issued beyond passport expiry — renew before filing if it runs short."},
        {"key": "loa", "label": "Letter of Acceptance (LOA)", "required": True, "hint": "From a DLI — IRCC verifies every LOA with the institution before the file is processed."},
        {"key": "pal", "label": "Provincial / Territorial Attestation Letter (PAL/TAL)", "required": True, "hint": "Master's/PhD at a public DLI are PAL-exempt from 1 Jan 2026 — record the exemption ground."},
        {"key": "gic", "label": "GIC Certificate", "required": False, "hint": "Optional since SDS closed on 8 Nov 2024, but still the cleanest proof of the living-cost total."},
        {"key": "tuition-receipt", "label": "First-Year Tuition Payment Receipt", "required": True, "hint": "Proof of tuition paid to the DLI."},
        {"key": "proof-of-funds", "label": "Proof of Funds / Bank Statements (4 months)", "required": True, "hint": "CAD 22,895 living costs for one applicant plus first-year tuition; re-indexed every 1 Sept."},
        {"key": "loan-sanction", "label": "Education Loan Sanction Letter", "required": False, "hint": "Disbursement-ready sanction naming the student — an in-principle letter is discounted."},
        {"key": "sponsor-affidavit", "label": "Sponsor Affidavit / Declaration of Support + Income & Tax Proof", "required": False, "hint": "Who pays, plus their ITRs, payslips and relationship proof — a bare balance reads as parked."},
        {"key": "scholarship-letter", "label": "Scholarship / Assistantship Award Letter", "required": False, "hint": "Funded offer or TA/RA stipend letter — it reduces the living-cost funds still to be shown."},
        {"key": "assets-statement", "label": "Immovable Property & Asset Valuation", "required": False, "hint": "Registered valuations and asset statements — 'personal assets' is a box on the refusal letter."},
        {"key": "imm1294", "label": "Study Permit Application (IMM 1294)", "required": True, "hint": "Filed inside the IRCC secure account, mandatory since 25 Mar 2025 — keep the submission PDF."},
        {"key": "imm5476", "label": "Use of a Representative Form (IMM 5476)", "required": False, "hint": "Signed only where a CICC-licensed RCIC or lawyer is named — ghost consulting is an offence."},
        {"key": "sop-study-plan", "label": "Statement of Purpose / Letter of Explanation (LOE)", "required": True, "hint": "Why this program, why Canada, ties to home country."},
        {"key": "language-test", "label": "Language Test (IELTS / PTE / CELPIP / TEF)", "required": True, "hint": "No IRCC minimum since SDS closed — the DLI sets it; PGWP needs CLB 7 degree / CLB 5 college."},
        {"key": "transcripts", "label": "Academic Transcripts", "required": True, "hint": "All completed education."},
        {"key": "degree-certificates", "label": "Degree / Diploma Certificates", "required": False, "hint": "Completed programs only."},
        {"key": "medical-exam", "label": "Medical Exam (eMedical) Confirmation", "required": False, "hint": "Needed for a 6+ month stay after residence in a designated country; the IME is valid 12 months from the exam."},
        {"key": "police-clearance", "label": "Police Clearance Certificate", "required": False, "hint": "Not standard for a study permit — supply only when the visa office or a fairness letter asks."},
        {"key": "biometrics", "label": "Biometrics Confirmation", "required": False, "hint": "Biometric Instruction Letter / completion slip."},
        {"key": "custodianship", "label": "Custodianship Declaration (minors)", "required": False, "hint": "IMM 5646, notarised both sides — mandatory under 17, officer discretion to the age of majority."},
        {"key": "spouse-dependant", "label": "Marriage Certificate & Dependant Documents", "required": False, "hint": "SOWP since 21 Jan 2025 only for master's 16+ months, doctoral or listed professional degrees."},
        {"key": "family-forms", "label": "Family Information Form (IMM 5645/5707)", "required": True, "hint": "IMM 5707 for every applicant 18+ — list all family, accompanying or not; omissions risk A40."},
        {"key": "birth-certificate", "label": "Birth Certificate / Proof of Relationship", "required": False, "hint": "Links the student to the sponsor shown in the funds file; required for every minor applicant."},
        {"key": "caq", "label": "Quebec Acceptance Certificate (CAQ)", "required": False, "hint": "Apply on Arrima before IRCC; from 1 Jan 2026 shows CAD 24,617 funds, fee CAD 135."},
        {"key": "in-canada-status", "label": "Current Canadian Status Documents (in-Canada filings)", "required": False, "hint": "Existing permit, transcripts and enrolment proof — a DLI change needs a whole new study permit."},
        {"key": "prior-refusals", "label": "Previous Refusal Letters (Any Country)", "required": False, "hint": "Declare every refusal by any country — an undeclared one becomes A40 misrepresentation."},
        {"key": "travel-history", "label": "Previous Passports & Travel History", "required": False, "hint": "Old passports, visas and stamps — travel history is a named ground on the IRCC refusal letter."},
        {"key": "digital-photo", "label": "Digital Photo (IRCC spec)", "required": False, "hint": "Per IRCC photo specifications."},
        {"key": "work-experience", "label": "Work Experience Letters", "required": False, "hint": "If employment history supports the study plan."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "AU": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "The visa binds to this passport — a renewal mid-case needs a Form 929 update in ImmiAccount."},
        {"key": "birth-certificate", "label": "Birth Certificate / National Identity Document", "required": False, "hint": "Chased for under-18s, dependants and any name mismatch across passport, CoE and transcripts."},
        {"key": "coe", "label": "Confirmation of Enrolment (CoE)", "required": True, "hint": "eCoE from PRISMS once fees are paid — a letter of offer has not been accepted since 1 Jan 2025."},
        {"key": "offer-letter", "label": "Offer Letter", "required": True, "hint": "Kept for the file and the ESOS written agreement's refund terms; not accepted at lodgement."},
        {"key": "release-letter", "label": "Provider Release / Transfer Approval (onshore)", "required": False, "hint": "Needed to move provider inside the first 6 months of the principal course."},
        {"key": "gs-statement", "label": "Genuine Student (GS) Statement & Answers", "required": True, "hint": "Four questions, 150 words each, answered in the form — not an attached statement."},
        {"key": "oshc", "label": "OSHC Policy Certificate", "required": True, "hint": "Approved insurers only: Allianz Care, ahm, Bupa, Medibank, nib. Prepaid for the visa period."},
        {"key": "financial-capacity", "label": "Financial Capacity Evidence", "required": True, "hint": "AUD 29,710 living costs + first-year tuition + travel; funds held ~3 months, explain spikes."},
        {"key": "loan-sanction-letter", "label": "Education Loan Sanction / Disbursement Letter", "required": False, "hint": "Must be sanctioned and disbursement-ready — an in-principle approval is not evidence of funds."},
        {"key": "sponsor-income-evidence", "label": "Sponsor Income & Relationship Evidence", "required": False, "hint": "Income route: a parent's or partner's income (ITRs, payslips) plus proof of the relationship."},
        {"key": "english-test", "label": "English Test (IELTS / PTE / TOEFL)", "required": True, "hint": "IELTS 6.0 (5.5 with 10wk ELICOS); in-centre sitting under 2 years old — online is void."},
        {"key": "transcripts", "label": "Academic Transcripts", "required": True, "hint": "All prior study."},
        {"key": "degree-certificates", "label": "Degree / Award Certificates", "required": False, "hint": "Completed qualifications."},
        {"key": "naati-translations", "label": "NAATI-Certified English Translations", "required": False, "hint": "Anything not in English — upload the original and the translation with the NAATI number on it."},
        {"key": "health-exam", "label": "Health Examination (HAP ID / eMedical)", "required": False, "hint": "Book with Bupa MVS on the HAP ID; My Health Declarations can raise one pre-lodgement."},
        {"key": "health-undertaking-815", "label": "Health Undertaking (Form 815)", "required": False, "hint": "Signed where latent TB is found — student must contact Bupa MVS within 28 days of arrival."},
        {"key": "biometrics-letter", "label": "Biometrics Request Letter (s.40 Personal Identifiers)", "required": False, "hint": "Post-lodgement — 14 calendar days to attend an ABCC/AVAC or submit via the Immi app."},
        {"key": "photo", "label": "Passport-size Photograph", "required": False, "hint": "One recent colour passport-size photo — Australia issues no label, so this is ID evidence."},
        {"key": "form-956a", "label": "Form 956A — Authorised Recipient (or Form 956 for a MARN agent)", "required": False, "hint": "956A only routes correspondence; advising or lodging needs a registered agent on Form 956."},
        {"key": "character-documents", "label": "Character Documents (Form 80 / 1221, Police Certificates)", "required": False, "hint": "Requested on higher-scrutiny files — 10 years of addresses, travel and work, plus any PCC."},
        {"key": "guardian-forms", "label": "Under-18 Welfare Forms (CAAW / 157N / 1229)", "required": False, "hint": "CAAW from the provider, or Form 157N + a 590 guardian; Form 1229 from the other parent."},
        {"key": "relationship-docs", "label": "Marriage / Relationship Certificates (dependents)", "required": False, "hint": "Marriage or de facto and birth certificates; school-age children add schooling costs."},
        {"key": "employment-evidence", "label": "Employment Evidence / CV", "required": False, "hint": "Payslips, service letters and a written gap explanation — study gaps are a standard GS probe."},
        {"key": "prior-refusals", "label": "Previous Visa / Refusal Documents", "required": False, "hint": "All prior Australian and other-country visas, refusals and cancellations — PIC 4020 risk."},
        {"key": "grant-notification", "label": "Visa Grant Notification & VEVO Record", "required": False, "hint": "The grant letter is the only 'visa' — confirm the conditions independently in VEVO."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "DE": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "Issued within 10 years, 2 blank pages."},
        {"key": "biometric-photos", "label": "Biometric Photos (35×45 mm)", "required": True, "hint": "3 current identical photos to the German biometric spec; the mission keeps them."},
        {"key": "admission", "label": "Admission Letter (Zulassungsbescheid) / Conditional Admission", "required": True, "hint": "Studienkolleg place or course registration on those files; must state the language of instruction and whether a German degree is awarded."},
        {"key": "uni-assist-vpd", "label": "uni-assist VPD / Application Confirmation", "required": False, "hint": "Vorprüfungsdokumentation some universities demand before they will look at an application."},
        {"key": "phd-supervision", "label": "PhD Supervision Confirmation (Betreuungszusage)", "required": False, "hint": "PhD files: supervisor's acceptance or institute contract, in place of a Zulassungsbescheid."},
        {"key": "aps", "label": "APS Certificate (DigZert)", "required": True, "hint": "India/China/Vietnam only. Waived for PhD, German/EU public scholarships, non-Indian degrees."},
        {"key": "dmat", "label": "dMAT Score Report (Digital Master Test)", "required": False, "hint": "New APS India element for selected master's applicants, Summer Semester 2027 intake onward."},
        {"key": "anabin-zab", "label": "Degree Recognition Proof (anabin / ZAB Zeugnisbewertung)", "required": False, "hint": "For APS-exempt files: anabin H+ printout, or a ZAB Zeugnisbewertung (~€208, 2-3 months)."},
        {"key": "sperrkonto", "label": "Blocked Account (Sperrkonto) Confirmation", "required": True, "hint": "€11,904 / €992 a month — €13,092 for §17 study applicants, Studienkolleg and non-preparatory §16f(1) language courses."},
        {"key": "tuition-payment-proof", "label": "Proof of Tuition / Study Fee Payment", "required": False, "hint": "Required wherever the institution charges fees — private universities and language courses."},
        {"key": "scholarship-letter", "label": "Scholarship Award Letter", "required": False, "hint": "Only a German or EU public-fund award replaces the Sperrkonto — and it also waives APS."},
        {"key": "verpflichtung", "label": "Formal Obligation Letter (Verpflichtungserklärung)", "required": False, "hint": "Sponsor must live in Germany and obtain it from their local authority under §§66-68 AufenthG."},
        {"key": "videx", "label": "National Visa Application Form (Consular Services Portal)", "required": True, "hint": "Filed online at digital.diplo.de; a VIDEX printout only where CSP is not yet available."},
        {"key": "declaration", "label": "Declaration under Section 54 of the Residence Act", "required": True, "hint": "Signed acknowledgement of the consequences of false statements — two identical copies."},
        {"key": "legal-representation-declaration", "label": "Declaration of Additional Contact & Legal Representation", "required": True, "hint": "Mission's own form naming an authorised representative — two signed copies at the appointment."},
        {"key": "health-insurance", "label": "Health / Travel Insurance Proof", "required": True, "hint": "Travel cover for the first 90 days from the intended entry date, then German statutory/private."},
        {"key": "language-cert", "label": "Language Certificate (TestDaF / DSH / Goethe or IELTS/TOEFL)", "required": True, "hint": "Not older than 1 year at the appointment; skip only if the admission letter confirms the level."},
        {"key": "testas", "label": "TestAS Certificate", "required": False, "hint": "g.a.s.t. aptitude test — asked for on many bachelor and Studienkolleg files, never on master's."},
        {"key": "transcripts", "label": "Academic Transcripts", "required": True, "hint": "Bachelor files need 10th and 12th mark sheets too; master's, the full degree record."},
        {"key": "degree-certificates", "label": "Degree Certificates", "required": False, "hint": "Bachelor's certificate for Master's applicants."},
        {"key": "cv", "label": "CV (Tabular / Lebenslauf)", "required": True, "hint": "German-style tabular CV."},
        {"key": "motivation-letter", "label": "Motivation Letter (Motivationsschreiben)", "required": True, "hint": "Duly signed — why this subject, why Germany, why this university, in German or English."},
        {"key": "appointment", "label": "Visa Appointment Confirmation", "required": False, "hint": "VFS or mission slot — the booking link only appears once the CSP pre-check is complete."},
        {"key": "fee-receipt", "label": "Visa Fee Receipt", "required": False, "hint": "€75 adult, €37.50 under-18, non-refundable on refusal; VFS adds its own service charge."},
        {"key": "accommodation", "label": "Accommodation Proof", "required": False, "hint": "If arranged — the landlord's Wohnungsgeberbestätigung is what unlocks Anmeldung on arrival."},
        {"key": "prior-refusals", "label": "Previous Refusal Documents", "required": False, "hint": "Any Schengen/German refusals."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "IE": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "Valid 12+ months beyond arrival."},
        {"key": "previous-passports", "label": "Photocopies of All Previous Passports", "required": False, "hint": "Photocopy every page of all previous passports — ISD says omitting them delays the file."},
        {"key": "acceptance-letter", "label": "Letter of Acceptance", "required": True, "hint": "Must confirm 15+ hours organised daytime tuition a week, fees payable, fees paid and learner protection."},
        {"key": "programme-eligibility-listing", "label": "ILEP / TrustEd Ireland Programme Listing", "required": True, "hint": "Print the ILEP or TrustEd Ireland list entry — a programme sits on one list, never both."},
        {"key": "learner-protection-certificate", "label": "Learner Protection Certificate", "required": False, "hint": "Insurance-scheme route only, in the student's own name — publicly funded universities and awarding bodies are exempt."},
        {"key": "fee-receipt", "label": "Tuition Fee Payment Receipt", "required": True, "hint": "EFT to the college's Irish account, or a Transfermate (ex-Pay to Study) receipt — €6,000 min since 30 Jun 2025."},
        {"key": "proof-of-funds", "label": "Proof of Funds / 6-Month Bank Statements", "required": True, "hint": "€10,000 for year one plus six months of transactions on headed paper — Ireland has no 28-day seasoning rule."},
        {"key": "financial-summary-form", "label": "Financial Summary Form (FSF)", "required": True, "hint": "ISD Financial Summary Form — mandatory for every long-stay study visa applicant."},
        {"key": "bank-access-letter", "label": "Bank Letter — Deposit / Savings Access", "required": False, "hint": "Bank letter confirming funds in a deposit or savings account can actually be withdrawn."},
        {"key": "funds-source-evidence", "label": "Source-of-Funds Evidence for Large Lodgements", "required": False, "hint": "Loan sanction, property sale or gift papers behind every large or irregular lodgement."},
        {"key": "education-bond", "label": "Education Bond (Alternative Evidence of Finance)", "required": False, "hint": "Degree students only (NFQ 7-10): €10,000+ lodged with Transfermate and held until you register in Ireland."},
        {"key": "scholarship-letter", "label": "Scholarship / Government Funding Letter", "required": False, "hint": "College or government award letter stating the amount — it feeds box C of the FSF."},
        {"key": "medical-insurance", "label": "Medical / Travel Insurance", "required": True, "hint": "College group scheme or an Irish policy; travel cover year one only, min €25,000 accident and €25,000 disease."},
        {"key": "english-test", "label": "English Test (IELTS / TOEFL / Duolingo)", "required": True, "hint": "ISD visa floor is IELTS Academic 5.0 / TOEFL iBT 61 / Duolingo 75; cert must be under 2 years at course start."},
        {"key": "preparatory-course-study-plan", "label": "Preparatory English Course Study Plan", "required": False, "hint": "Prep-English route only: dates of both courses, max 6 months, both fees paid in full."},
        {"key": "transcripts", "label": "Academic Transcripts", "required": True, "hint": "Previous exam results & study history."},
        {"key": "degree-certificates", "label": "Degree Certificates", "required": False, "hint": "Completed qualifications."},
        {"key": "avats-summary", "label": "AVATS Application Summary", "required": True, "hint": "Print, sign and date it — the signed form, passport and documents must reach the office within 30 days."},
        {"key": "photos", "label": "Passport Photographs", "required": True, "hint": "Two colour photos under 6 months old, each signed on the back with the Visa Application Transaction Number."},
        {"key": "application-letter", "label": "Letter of Application / SOP", "required": True, "hint": "Must state arrival/departure dates, family in Ireland or the EU, and the three ISD commitments."},
        {"key": "sponsor-docs", "label": "Sponsor Documents + Relationship Proof", "required": False, "hint": "Sponsor's 6-month statements, employer letter + 3 payslips, relationship proof and signed FSF consent."},
        {"key": "work-experience", "label": "Work Experience / Gap Evidence", "required": False, "hint": "Accounts for time since last study."},
        {"key": "prior-refusals", "label": "Previous Visa Refusals (any country)", "required": False, "hint": "Any country, with the ORIGINAL refusal letter — non-disclosure is itself a ground for refusal."},
        {"key": "certified-translations", "label": "Certified Translations (+ Apostille)", "required": False, "hint": "Certified English or Irish translation; one made outside the EEA must itself be apostilled."},
        {"key": "birth-certificate", "label": "Birth Certificate (Applicants Under 18)", "required": False, "hint": "Under-18 applicants; a non-EEA original needs the issuing state's MFA apostille."},
        {"key": "parental-consent", "label": "Notarised Parental Consent & Guardianship (Under 18)", "required": False, "hint": "Notarised consent from BOTH parents naming the Irish guardian, plus their signed ID pages."},
        {"key": "accommodation", "label": "Accommodation Details", "required": False, "hint": "If already arranged in Ireland."},
        {"key": "garda-vetting-clearance", "label": "Garda Vetting Clearance for the Host Address (Unaccompanied Under 18)", "required": False, "hint": "Unaccompanied under-18s: the school obtains Garda clearance for the host address."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "FR": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "Issued within the last 10 years, 2 blank pages, valid 3+ months beyond the visa end date."},
        {"key": "photos", "label": "Photographs (2, 35×45 mm)", "required": True, "hint": "Identical, plain light background, taken within the last 6 months."},
        {"key": "transcripts", "label": "Academic Transcripts (relevés de notes)", "required": True, "hint": "All years of study, with a sworn (assermentée) French translation where required."},
        {"key": "degree-certificates", "label": "Diplomas / Degree Certificates", "required": False, "hint": "Completed qualifications only; sworn French translation where required."},
        {"key": "cv", "label": "CV", "required": True, "hint": "Uploaded into the Études en France dossier, in the programme's language."},
        {"key": "lettre-de-motivation", "label": "Lettre de Motivation (one per programme)", "required": True, "hint": "A separate, tailored letter for each programme selected — up to 7."},
        {"key": "language-certificate", "label": "Language Certificate (TCF / TEF / DELF-DALF or IELTS/TOEFL)", "required": True, "hint": "B2 typical for French-taught courses; TCF-DAP is campaign-specific."},
        {"key": "dap-dossier", "label": "DAP Dossier (blanc / vert / jaune)", "required": False, "hint": "Blanc = L1 from abroad, vert = already in France, jaune = ENSA 1re–5e année. Closes 15 December."},
        {"key": "campus-france-fee", "label": "Campus France Procedure Fee Receipt", "required": True, "hint": "Non-refundable EEF fee paid inside the platform in local currency — not the visa fee."},
        {"key": "acceptance-attestation", "label": "Accord Préalable d'Inscription / Attestation d'Acceptation", "required": True, "hint": "France's admission proof, recorded in the platform — there is no CAS or I-20."},
        {"key": "convocation-concours", "label": "Convocation to the Concours / Entretien d'Admission", "required": False, "hint": "Institution's summons — required for the court séjour « étudiant-concours »."},
        {"key": "eef-completion", "label": "Campus France End-of-Procedure Email", "required": True, "hint": "No consular appointment can be booked before this go-ahead lands."},
        {"key": "france-visas-form", "label": "France-Visas Application Form & Receipt (signed)", "required": True, "hint": "Printed from france-visas.gouv.fr with the application number, signed by the applicant."},
        {"key": "appointment", "label": "Appointment Confirmation (VFS / TLScontact / Capago)", "required": True, "hint": "Whichever provider serves that post; lodge at most 3 months before departure."},
        {"key": "proof-of-resources", "label": "Proof of Resources (bank statements)", "required": True, "hint": "Whole first year at the monthly rate in force on the filing date."},
        {"key": "prise-en-charge", "label": "Attestation de Prise en Charge + Guarantor's Proof", "required": False, "hint": "Worthless without the guarantor's own ID, proof of address and income evidence."},
        {"key": "avi", "label": "AVI (Attestation de Virement Irrévocable)", "required": False, "hint": "Blocked-transfer certificate — expected at many Maghreb and West-African posts."},
        {"key": "scholarship-letter", "label": "Scholarship Award Letter (Eiffel / Charpak / AUF)", "required": False, "hint": "French-government award holders are also exempt from the consular visa fee."},
        {"key": "accommodation", "label": "Accommodation Proof (CROUS / lease / hébergement)", "required": True, "hint": "Covers at least the first 3 months; host's ID and proof of address attached."},
        {"key": "birth-certificate", "label": "Birth Certificate & Minor's Parental Authorisation", "required": True, "hint": "Recent extract, apostilled or legalised; under-18s add both parents' consent."},
        {"key": "insurance", "label": "Private Medical / Travel Insurance", "required": False, "hint": "Required for VLS-T and short-stay C; VLS-TS holders join Assurance Maladie."},
        {"key": "visa-fee-receipt", "label": "Visa Fee Receipt", "required": False, "hint": "€50 student rate under Études en France, €99 standard long-stay, €90 short-stay C."},
        {"key": "prior-refusals", "label": "Previous Schengen / French Visa & Refusal Documents", "required": False, "hint": "Any earlier refusal, its décision motivée, and any CRRV appeal already filed."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "ES": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "Valid 12+ months at application, 2 blank pages, under 10 years old."},
        {"key": "photo", "label": "Passport Photo (ICAO Doc 9303 spec)", "required": True, "hint": "Recent colour photo, plain light background, last 6 months."},
        {"key": "admission-letter", "label": "Carta de Admisión (Final Admission Letter)", "required": True, "hint": "Final admission, not a place reservation — exact dates and timetable."},
        {"key": "minor-authorisation", "label": "Parental Authorisation + Birth Certificate (under-18s)", "required": False, "hint": "Notarised consent to study in Spain, apostilled and sworn-translated."},
        {"key": "centre-recognition", "label": "Centre Recognition (RUCT / Registro estatal / Cervantes)", "required": True, "hint": "Proof the centre and title are officially recognised in Spain."},
        {"key": "access-credential", "label": "UNEDasiss Accreditation / Equivalencia de Nota Media", "required": False, "hint": "Undergrad: UNEDasiss + PCE. Postgrad: equivalencia or homologación."},
        {"key": "matricula-receipt", "label": "Matrícula / Inscription Fee Receipt", "required": True, "hint": "Fee paid, or a declaración responsable if enrolment is not yet open."},
        {"key": "transcripts", "label": "Academic Transcripts", "required": True, "hint": "All prior study, apostilled and sworn-translated where required."},
        {"key": "degree-certificates", "label": "Degree Certificates (apostilled)", "required": False, "hint": "Needed for the equivalencia de nota media or full homologación."},
        {"key": "language-evidence", "label": "Spanish / English Proficiency Evidence (DELE, SIELE, IELTS)", "required": False, "hint": "Level enough to follow teaching in the language of instruction."},
        {"key": "motivation-letter", "label": "Carta de Motivación (Letter of Motivation)", "required": False, "hint": "Admissions document — it is not on any consular checklist."},
        {"key": "bank-statements", "label": "Bank Statements / Proof of Funds (100% IPREM)", "required": True, "hint": "€600/month (IPREM, re-check yearly) × the real course length."},
        {"key": "family-funds", "label": "Family Funds: Relative's Statements + Proof of Relationship", "required": False, "hint": "Proof of the family link plus the relative's own bank movements."},
        {"key": "funding-evidence", "label": "Scholarship, Mobility or Work-Contract Evidence", "required": False, "hint": "A mobility body's responsibility certificate replaces IPREM proof."},
        {"key": "accommodation", "label": "Accommodation Evidence (whole stay)", "required": True, "hint": "Tenancy, residence booking or host-family letter for the full period."},
        {"key": "health-insurance", "label": "Health Insurance Policy (insurer authorised in Spain)", "required": True, "hint": "No co-pays, no carencias, no ceilings — travel cover is refused."},
        {"key": "criminal-record", "label": "Criminal Record Certificate (Antecedentes Penales)", "required": True, "hint": "Stays over 6 months; every country lived in for 5 years; valid 3 months."},
        {"key": "medical-certificate", "label": "Medical Certificate (WHO IHR 2005)", "required": True, "hint": "Stays over 6 months; doctor's licence number; valid 3 months."},
        {"key": "apostille-translations", "label": "Apostilles & Sworn Translations (Traductor Jurado)", "required": True, "hint": "Photocopy taken after the apostille is affixed."},
        {"key": "visa-form", "label": "Solicitud de Visado Nacional (signed)", "required": True, "hint": "Unsigned is not submitted; EX-00 instead when filing inside Spain."},
        {"key": "appointment-confirmation", "label": "Cita Previa / BLS–VFS Appointment Confirmation", "required": False, "hint": "Lodge in person at least 2 months before the course starts."},
        {"key": "visa-fee-receipt", "label": "Visa / Autorización Fee Receipt (tasa)", "required": True, "hint": "Consular route pays two tasas: €80 visa plus the autorización tasa 790 código 052. Filed inside Spain, only the 052."},
        {"key": "prior-refusals", "label": "Previous Schengen / Spanish Visa Refusals", "required": False, "hint": "Must be declared — a common trigger for a personal interview."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "NL": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "Valid 6+ months at the MVV appointment, 2 blank pages — the permit is never issued beyond passport expiry."},
        {"key": "sponsor-register", "label": "IND Recognised-Sponsor Register Check (erkend referent)", "required": True, "hint": "Print of the IND 'study' register entry + Code of Conduct listing. No sponsor, no permit."},
        {"key": "studielink", "label": "Studielink Enrolment Confirmation", "required": True, "hint": "Studielink application number plus the institution's own student number."},
        {"key": "admission-letter", "label": "Letter of Admission (Toelatingsbrief / Bewijs van Toelating)", "required": True, "hint": "Conditional, then unconditional — proof of enrolment (bewijs van inschrijving) only exists after matriculation."},
        {"key": "transcripts", "label": "Academic Transcripts & Marksheets", "required": True, "hint": "All prior study, certified for the institution's admissions office."},
        {"key": "degree-certificates", "label": "Degree / Diploma Certificates", "required": False, "hint": "Bachelor's certificate for a master's applicant; for a zoekjaar file, top-200 or Erasmus Mundus proof under 3 years old."},
        {"key": "idw-evaluation", "label": "Nuffic / IDW Credential Evaluation", "required": False, "hint": "Diploma evaluation where the institution or the gemeente asks for one — allow ~10 working weeks."},
        {"key": "english-test", "label": "English Test Score (IELTS Academic / TOEFL iBT)", "required": True, "hint": "Code of Conduct floor is IELTS 6.0 (TOEFL iBT 80); most master's ask 6.5 — must still be valid at enrolment."},
        {"key": "cv", "label": "CV / Curriculum Vitae", "required": False, "hint": "Standard in master's and HBO admission files."},
        {"key": "motivation-letter", "label": "Motivation Letter (Motivatiebrief)", "required": True, "hint": "Programme-specific — it carries the case, because the IND never interviews a study applicant."},
        {"key": "tuition-invoice", "label": "Tuition Fee Invoice / Receipt (Instellingscollegegeld)", "required": True, "hint": "Non-EU institutional fee — deposit or first instalment, per the offer. Sits on top of the study norm."},
        {"key": "living-cost-transfer", "label": "Living-Cost Transfer Receipt to the University (Study Norm)", "required": True, "hint": "Most universities require 12 months at the IND study norm in their OWN account before the sponsor files."},
        {"key": "scholarship-letter", "label": "Scholarship Award Letter", "required": False, "hint": "A full-cost award replaces the transfer; a partial one still needs the shortfall wired."},
        {"key": "financier-declaration", "label": "Third-Party Financier Declaration + Income Proof", "required": False, "hint": "Parent or sponsor income must meet the IND norm — re-indexed 1 January and 1 July, so re-check before filing."},
        {"key": "antecedents-certificate", "label": "Antecedents Certificate (Antecedentenverklaring, Appendix 7601)", "required": True, "hint": "Signed by every applicant aged 12+; re-declare within 4 weeks of any change."},
        {"key": "prior-refusals", "label": "Previous Refusal / Entry-Ban / Prior-Stay Documents", "required": False, "hint": "Papers behind an adverse answer on appendix 7601 — Schengen refusal, EU entry ban, prior stay — plus the written explanation."},
        {"key": "tb-declaration", "label": "TB Test Declaration of Intent (Appendix 7603)", "required": True, "hint": "A declaration only — the GGD screening happens after arrival. Skip if the nationality is exempt (appendix 7644)."},
        {"key": "ind-form-7504", "label": "IND Application Form 7504 / 7505 (Sponsor-Filed)", "required": True, "hint": "Sponsor files it: 7504 (code 392, WO/HBO) or 7505 (code 393, secondary/MBO). Keep the copy."},
        {"key": "health-insurance", "label": "Health Insurance Policy", "required": True, "hint": "Cover from the date of entry; switches to Dutch basisverzekering once paid work starts."},
        {"key": "birth-certificate", "label": "Birth Certificate (Legalised / Apostilled + Translated)", "required": True, "hint": "For the gemeente and the BSN, not the IND — legalisation plus translation takes months, so start it at offer stage."},
        {"key": "photo", "label": "Passport Photo (Dutch specification, 35×45 mm)", "required": False, "hint": "Handed in at the MVV appointment; MVV-exempt students are photographed at the IND desk instead."},
        {"key": "mvv-appointment", "label": "MVV Appointment Confirmation (VFS / Dutch Mission)", "required": False, "hint": "Booked after approval — the MVV must be collected within 3 months of the IND decision."},
        {"key": "housing-proof", "label": "Proof of Dutch Address / Housing Contract", "required": False, "hint": "A real, registrable Dutch address is what unlocks BRP registration and the BSN."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "AE": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "Valid 6+ months when the entry permit is filed; spelling must match the certificates."},
        {"key": "photo", "label": "Digital Photograph (ICP spec, 4.3×5.5 cm)", "required": True, "hint": "True-white background, taken within 6 months; digital JPEG, no prints."},
        {"key": "admission-letter", "label": "Offer / Acceptance Letter (MoHESR-licensed)", "required": True, "hint": "From a MoHESR/CAA-licensed institution; many files also need an Arabic copy."},
        {"key": "english-test", "label": "English Test Score (IELTS Academic / TOEFL iBT)", "required": True, "hint": "Meet the score on the offer letter — universities set their own bar since the Grade-12 EmSAT was scrapped in 2024."},
        {"key": "attested-certificates", "label": "Attested Academic Certificates & Transcripts", "required": True, "hint": "Home ministry → UAE Embassy → MOFAIC chain (AED 150 per document); an apostille alone is not accepted."},
        {"key": "moe-equivalency", "label": "MOE Grade-12 Equivalency (Muadala)", "required": False, "hint": "Ministry of Education equivalency for a foreign Grade-12 certificate — school level only."},
        {"key": "mohesr-recognition", "label": "MoHESR University Certificate Recognition", "required": False, "hint": "Degree-level recognition on mohesr.gov.ae — needed for a foreign bachelor's before Master's entry."},
        {"key": "legal-translation", "label": "Legal Translation (MoJ-licensed)", "required": False, "hint": "Anything not in Arabic or English needs a UAE Ministry of Justice-licensed translator."},
        {"key": "tuition-receipt", "label": "Tuition / First-Semester Fee Receipt", "required": True, "hint": "The PRO usually will not file the entry permit until the first instalment is paid."},
        {"key": "security-deposit", "label": "Refundable Visa Security Deposit Receipt", "required": False, "hint": "Institution-held, commonly AED 3,000–5,000 — refunded when the file closes cleanly."},
        {"key": "financial-capability", "label": "Bank Statement / Sponsor Financial Undertaking", "required": False, "hint": "Only where the institution or the sponsor route asks — immigration sets no funds threshold here."},
        {"key": "visa-request-form", "label": "University Student Visa Request Form", "required": True, "hint": "The institution's own form — most PRO offices want it at least two months before the intake start date."},
        {"key": "sponsor-establishment-card", "label": "Sponsor Establishment Card / Immigration File", "required": False, "hint": "Sponsor's immigration file or free-zone card; quota or fines on it stall every file."},
        {"key": "entry-permit", "label": "Entry Permit (e-Visa) PDF", "required": True, "hint": "PDF e-permit: single entry, valid 60 days from issue, carries the student's UID."},
        {"key": "health-insurance", "label": "UAE Health Insurance Policy", "required": True, "hint": "UAE-licensed cover for the whole permit period; a lapse blocks issuance and renewal."},
        {"key": "medical-fitness", "label": "Medical Fitness Certificate (DHA / EHS / SEHA)", "required": True, "hint": "Taken inside the UAE — HIV blood screen and TB chest X-ray; certificate valid 90 days."},
        {"key": "emirates-id-receipt", "label": "Emirates ID Application Receipt (biometrics)", "required": False, "hint": "Issued at fingerprint enrolment; tracks card printing and Emirates Post delivery."},
        {"key": "emirates-id-card", "label": "Emirates ID Card / e-Residence Confirmation", "required": True, "hint": "The Emirates ID is the residence document — no passport sticker since April 2022."},
        {"key": "parent-sponsor-docs", "label": "Parent Sponsor & Relationship Documents", "required": False, "hint": "Sponsor's Emirates ID, salary certificate (AED 4,000/mo), tenancy and the attested birth certificate."},
        {"key": "minor-consent", "label": "Parental Consent / Guardian Undertaking (under 18)", "required": False, "hint": "Notarised and attested parental NOC for applicants under 18; under-18s are exempt from the medical."},
        {"key": "prior-uae-records", "label": "Previous UAE Visa / Cancellation Papers", "required": False, "hint": "Earlier residence, cancellation or exit papers — an undisclosed ban stops the file at clearance."},
        {"key": "golden-visa-evidence", "label": "Golden Residence Evidence (Nomination / GPA)", "required": False, "hint": "Golden route: 95%+ secondary result, or GPA 3.5+ (Class A) / 3.8+ (Class B) within 2 years of graduating."},
        {"key": "work-permit-noc", "label": "University No Objection Certificate (part-time work)", "required": False, "hint": "Institution NOC required before MOHRE will issue a part-time student work permit."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "PL": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "Issued within 10 years, valid 3+ months beyond departure from Schengen, 2 blank pages."},
        {"key": "photos", "label": "Photographs (2, 35×45 mm)", "required": True, "hint": "Colour, white background, taken within the last 6 months."},
        {"key": "admission-certificate", "label": "Certificate of Admission (Zaświadczenie o Przyjęciu)", "required": True, "hint": "Statutory format of the Regulation of 23 Sep 2019, rector-signed original — the visa anchor; informal offer letters are rejected."},
        {"key": "tuition-payment-proof", "label": "Tuition Payment Proof", "required": True, "hint": "Full-first-year prepayment is the norm before the certificate issues; free programmes need a university confirmation letter instead."},
        {"key": "irk-application", "label": "University Application (IRK)", "required": True, "hint": "Each university's own IRK portal — 85 PLN standard, 100 PLN exam-based, up to 150 PLN for art programmes; per programme."},
        {"key": "language-certificate", "label": "Language Certificate (B2)", "required": True, "hint": "Legally required for admission since the 1 Jun 2025 law (list in Dz.U. 2025 poz. 1045); the consulate recommends IELTS 6.5 / TOEFL iBT 79 / CAE 176 — formally optional in the visa file but always enclose it."},
        {"key": "secondary-certificate-apostilled", "label": "Secondary Certificate + MEA Apostille", "required": True, "hint": "State RAC authentication first, then the MEA apostille; the Syrena / kurator recognition attaches to this document."},
        {"key": "degree-apostilled", "label": "Degree Certificate + MEA Apostille", "required": False, "hint": "Master's / PhD files — apostilled like the secondary certificate."},
        {"key": "transcripts", "label": "Academic Transcripts", "required": True, "hint": "All semesters, consistent with the certificates — explain any gap in the cover letter."},
        {"key": "nawa-syrena-recognition", "label": "NAWA Syrena / Kurator Recognition", "required": True, "hint": "Free at syrena.nawa.gov.pl; first-cycle admits also need the kurator oświaty decision on eligibility for higher education."},
        {"key": "e-konsulat-form", "label": "e-Konsulat Visa Form (signed twice)", "required": True, "hint": "Generated on secure2.e-konsulat.gov.pl — print and sign in both places, signature matching the passport."},
        {"key": "vfs-eform", "label": "VFS Supplementary eForm", "required": True, "hint": "Separate from e-Konsulat — mandatory at eforms.vfsglobal.com/pol before visiting the VAC."},
        {"key": "cover-letter", "label": "Applicant's Cover Letter", "required": True, "hint": "Purpose, duration, funding story and annex list, numbers matching the bank evidence — weak or template letters are a cited refusal driver."},
        {"key": "travel-insurance", "label": "Travel Medical Insurance (€30,000)", "required": True, "hint": "MFA-approved insurers only (list at gov.pl/web/diplomacy/visas), whole stay, repatriation covered; handwritten certificates rejected, insured's name in Latin script."},
        {"key": "accommodation-proof", "label": "Accommodation Proof (monthly fee stated)", "required": True, "hint": "Dorm allocation or lease that states the monthly cost — funds must cover it on top of the 1,010 PLN maintenance."},
        {"key": "funds-evidence", "label": "Funds Evidence (closed list)", "required": True, "hint": "1,010 PLN/month single — 823 PLN each when family accompanies — plus 2,500 PLN return travel (waived with a return ticket) and housing; only a Polish-bank certificate, credit-card-limit certificate, scholarship or traveller's cheques count — an Indian savings balance alone fails."},
        {"key": "sponsor-letter", "label": "Notarized Sponsorship Letter", "required": False, "hint": "Sponsor covers ALL travel, living and accommodation costs — add the employment certificate with monthly salary, or any accepted funds document in the sponsor's name."},
        {"key": "scholarship-letter", "label": "Scholarship Award Letter", "required": False, "hint": "NAWA, university or government award — counts as full funds evidence on the closed list."},
        {"key": "flight-itinerary", "label": "Return Flight Reservation", "required": True, "hint": "Reservation only — do NOT buy the outbound; a held return ticket also waives the 2,500 PLN return-travel component."},
        {"key": "passport-copies", "label": "Passport Data-Page Copies", "required": True, "hint": "First and last pages, plus old-passport pages carrying prior Schengen visas."},
        {"key": "prior-visa-copies", "label": "Prior Schengen / Polish Visa Copies", "required": False, "hint": "Strengthens credibility — prior compliant Schengen travel is the cheapest rebuttal of migration-intent doubt."},
        {"key": "minor-consents", "label": "Minor: Parental Consents + Birth Certificate", "required": False, "hint": "Both apostilled; at least one parent must attend the lodgement in person."},
        {"key": "visa-fee-payment", "label": "Visa Fee €200 + VFS Fee", "required": True, "hint": "€200 / ₹21,120 (1 Jan 2026 tariff, non-refundable, cash or card at the VAC counter); VFS service fee ₹1,026 incl. GST paid online at booking, optional courier ₹960."},
        {"key": "trc-post-arrival-pack", "label": "Post-Arrival TRC Pack (MOS 2.0)", "required": False, "hint": "Mandatory e-filing on mos.cudzoziemcy.gov.pl since 27 Apr 2026 — 340 + 100 PLN by bank transfer outside MOS, Polish sworn translations, NFZ ~55.80 PLN/month; first karta pobytu 15 months."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "NZ": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "Valid at least 3 months beyond the intended departure from NZ — renew before filing if it runs short."},
        {"key": "digital-photo", "label": "Digital Photo (Immigration Online spec)", "required": True, "hint": "Recent (under 6 months), plain background, uploaded as a file — no physical prints anywhere in this process."},
        {"key": "offer-of-place", "label": "Offer of Place (unconditional)", "required": True, "hint": "From a Pastoral Care Code signatory; conditional offers cannot support the visa — check the legal provider name post-Te Pūkenga."},
        {"key": "transcripts", "label": "Academic Transcripts & Certificates", "required": True, "hint": "10th, 12th and degree marksheets; NZQA equivalence is rarely needed for university offers."},
        {"key": "english-test", "label": "English Test Result (IELTS / PTE / TOEFL)", "required": True, "hint": "Typical bars: IELTS 6.0 UG (no band below 5.5), 6.5 PG — score under 2 years old."},
        {"key": "cv-resume", "label": "CV / Resume", "required": False, "hint": "PG admission plus the work-in-gap story — every gap over 6 months needs employment evidence behind it."},
        {"key": "sop-genuine-intent", "label": "Statement of Purpose / Genuine Intentions Letter", "required": True, "hint": "The bona fide test lives here: course logic, exact funding figures, honest post-study plan — 1-2 pages."},
        {"key": "study-gap-evidence", "label": "Study / Work Gap Evidence", "required": False, "hint": "Employment letters and payslips covering every gap over 6 months — the top India decline theme."},
        {"key": "bank-statements", "label": "Bank Statements (NZ$20,000/yr + tuition)", "required": True, "hint": "About 6 months of history; INZ probes recent lump sums — pair every spike with its source proof."},
        {"key": "funds-source-evidence", "label": "Source-of-Funds Proof", "required": True, "hint": "FD receipts, sale deeds, 2-3 years of ITRs — INZ verifies directly with banks, so provenance beats balance."},
        {"key": "education-loan-letter", "label": "Education Loan Sanction Letter", "required": False, "hint": "A sanction letter, not an eligibility letter — Indian bank sanctions are widely accepted."},
        {"key": "sponsor-undertaking-1014", "label": "Financial Undertaking for a Student (INZ 1014)", "required": False, "hint": "Family sponsor route: the current (June 2025) form plus sponsor ITRs, income proof and relationship evidence."},
        {"key": "scholarship-letter", "label": "Scholarship Award Letter", "required": False, "hint": "Amount and duration stated; a government award may move the file to a different visa category."},
        {"key": "fts-anz-setup", "label": "Funds Transfer Scheme (ANZ) Confirmation", "required": False, "hint": "If INZ directs FTS (India is a scheme country): ANZ account opened and NZ$20,000 moved — on FTS files the AIP letter's deadline commonly stretches to about 15 days; the letter's own date governs."},
        {"key": "chest-xray-1096", "label": "Chest X-ray Certificate (INZ 1096)", "required": True, "hint": "Study over 6 months + high-TB country (incl. India) or 3+ months in one in the last 5 years; under 3 months old at lodgement."},
        {"key": "medical-1007", "label": "General Medical Certificate (INZ 1007)", "required": True, "hint": "Stay over 12 months — same panel-physician eMedical visit; roughly INR 5,000-8,000 combined in India."},
        {"key": "police-clearance", "label": "Police Clearance Certificate(s)", "required": False, "hint": "17+ and staying 24+ months: upload AT lodgement since Jul 2026 — order the Passport Seva PCC early; under 6 months old."},
        {"key": "insurance-policy", "label": "Medical & Travel Insurance", "required": True, "hint": "Whole visa period — usually the provider's Studentsafe plan; PhD students are exempt per INZ (providers may still require cover)."},
        {"key": "accommodation-evidence", "label": "Accommodation Arrangement", "required": False, "hint": "Prepaid accommodation is deducted from the NZ$20,000 requirement; under-18s need approved accommodation or a caregiver."},
        {"key": "birth-certificate", "label": "Birth Certificate", "required": False, "hint": "Minor applicants and dependent-child files."},
        {"key": "translations", "label": "Certified English Translations", "required": False, "hint": "Accredited translator on letterhead with a declaration — INZ takes plain scans but verifies with issuers."},
        {"key": "immigration-online-summary", "label": "Immigration Online Application Summary", "required": True, "hint": "Online only since 18 Sep 2025; fee from NZ$850 by card — keep the application number."},
        {"key": "biometrics-vfs", "label": "VFS Biometrics Confirmation", "required": False, "hint": "Only on INZ's request letter, after lodgement — service fee about INR 1,700 since 1 Jan 2026 (confirm on the VFS page)."},
        {"key": "ppi-response", "label": "PPI Letter Response", "required": False, "hint": "Potentially Prejudicial Information — answer inside the stated deadline with evidence, not assertions."},
        {"key": "aip-letter", "label": "Approval in Principle (AIP) Letter", "required": True, "hint": "Pay tuition by the deadline IN the letter — commonly ~10 days, 15 with FTS; ask for an extension the moment it looks tight."},
        {"key": "tuition-receipt", "label": "Tuition Fee Receipt", "required": True, "hint": "Provider receipt uploaded to INZ (plus the ANZ confirmation on FTS files) — the visa is granted only after this."},
        {"key": "evisa-letter", "label": "eVisa Grant Letter", "required": True, "hint": "Check the conditions — provider name, 25 hrs/week work limit — and carry a printed copy when travelling."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "SG": [
        {"key": "passport-bio", "label": "Passport Bio-Data Page", "required": True, "hint": "Validity must outlast the intended pass — a mid-process renewal forces a SOLAR update."},
        {"key": "digital-photo", "label": "Digital Photo (ICA spec, 400×514 px)", "required": True, "hint": "White background, taken within the last 3 months — ICA rejects scans of print photos."},
        {"key": "transcripts", "label": "Academic Transcripts & Certificates", "required": True, "hint": "10th, 12th and degree for Indian files; English or a translation from an approved source."},
        {"key": "english-test", "label": "English Test Score (IELTS / TOEFL)", "required": False, "hint": "Only if the university demanded it — ICA itself never asks."},
        {"key": "offer-letter", "label": "Letter of Offer", "required": True, "hint": "The admissions document — keep the PDF; eForm 16 must match its programme name and dates exactly."},
        {"key": "acceptance-proof", "label": "Acceptance Proof / PEI Standard Student Contract", "required": True, "hint": "A PEI contract must be the CPE standard student contract with the Fee Protection Scheme."},
        {"key": "registration-ack-letter", "label": "Registration Acknowledgement Letter", "required": True, "hint": "Issued by the IHL after acceptance — this, not the offer, triggers the SOLAR registration."},
        {"key": "solar-registration", "label": "SOLAR / SOLAR+ Registration (institution-filed)", "required": True, "hint": "The school registers the student first; the login for eservices.ica.gov.sg/solar follows."},
        {"key": "eform16", "label": "eForm 16 (completed)", "required": True, "hint": "Filed by the student inside SOLAR/SOLAR+ — at least 2 and at most 3 months before course start, both tracks."},
        {"key": "processing-fee-receipt", "label": "S$45 Processing Fee Receipt", "required": True, "hint": "Non-refundable; pay at submission — SOLAR allows at most 7 days before the application lapses."},
        {"key": "bank-statements", "label": "Bank Statements / Balance Certificate", "required": True, "hint": "~6 months covering year-1 tuition plus S$12,000–15,000 living — a planning bar, not an ICA rule."},
        {"key": "sponsor-income", "label": "Parent / Sponsor Income Proof (payslips / ITR)", "required": True, "hint": "eForm 16 declares the parents' occupation and income — the evidence must match the declaration."},
        {"key": "education-loan", "label": "Education Loan Sanction Letter", "required": False, "hint": "Accepted alongside statements on Indian files; sanctioned, not merely applied for."},
        {"key": "gap-explanation", "label": "Study-Gap / Career-Gap Letter", "required": False, "hint": "The top South-Asian refusal trigger — account for every month of any gap over 6 months."},
        {"key": "birth-certificate", "label": "Birth Certificate", "required": False, "hint": "Chased for minors and some profiles; translate via an approved source if not in English."},
        {"key": "vaccination-records", "label": "Child Vaccination Records (12 and under)", "required": False, "hint": "Diphtheria and measles records verified by the Communicable Diseases Agency (CDA) before issuance."},
        {"key": "ipa-letter", "label": "In-Principle Approval (IPA) Letter", "required": True, "hint": "Arrives in SOLAR and by email; embeds the single-journey entry visa for visa-required nationals."},
        {"key": "medical-exam-report", "label": "ICA Medical Examination Report", "required": True, "hint": "ICA's own form plus HIV and chest X-ray lab reports ≤3 months old — done abroad or in Singapore."},
        {"key": "insurance-policy", "label": "Medical Insurance Certificate", "required": True, "hint": "IHLs auto-enrol in the university group scheme; EduTrust PEIs: S$20,000/yr minimum, B2 ward."},
        {"key": "sg-arrival-card", "label": "SG Arrival Card (electronic)", "required": True, "hint": "Free, submitted within 3 days before arrival on the ICA website or app — it is not a visa."},
        {"key": "terms-conditions-form", "label": "Student's Pass Terms & Conditions Form", "required": True, "hint": "Download, sign and carry to the formalities appointment."},
        {"key": "eappointment", "label": "ICA e-Appointment Confirmation", "required": True, "hint": "ICA Services Centre, 2 Crawford Street Level 3 — strictly by appointment — or campus Offsite Enrolment."},
        {"key": "issuance-fee-receipt", "label": "S$60 Issuance (+S$30 MJV) Receipt", "required": True, "hint": "Paid at formalities; the S$30 Multiple Journey Visa applies to visa-required nationals only."},
        {"key": "digital-pass", "label": "Digital Student's Pass (FileSG / Singpass)", "required": True, "hint": "No card since 27 Feb 2023 — verify the FIN and validity on the PDF ~3 working days after enrolment."},
        {"key": "tuition-grant-agreement", "label": "MOE Tuition Grant Agreement", "required": False, "hint": "Only if taking the grant — it signs a 3-year bond to work for a Singapore-registered company."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "IT": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "Valid 3+ months beyond the visa expiry with 2 blank pages — renew first if under 18 months remain."},
        {"key": "passport-photos", "label": "Passport Photos (35×40 mm)", "required": True, "hint": "Two recent white-background ICAO photos; VFS India also captures a biometric photo at the counter."},
        {"key": "secondary-diploma", "label": "Secondary School Diploma (12 Years)", "required": True, "hint": "Original plus apostille — bachelor access needs at least 12 years of schooling under the MUR circular."},
        {"key": "transcripts", "label": "Academic Transcripts", "required": True, "hint": "All years, apostilled; traduzione giurata (sworn Italian translation) where the university or consulate asks."},
        {"key": "degree-certificate", "label": "Bachelor Degree Certificate (Master's Files)", "required": False, "hint": "Provisional certificates count only when officially issued by the competent authority — self-declarations are refused."},
        {"key": "entrance-exam-cert", "label": "National College-Entrance Exam Certificate", "required": False, "hint": "Only where the home country runs one — the circular requires it wherever it exists."},
        {"key": "cimea-comparability", "label": "CIMEA Statement of Comparability", "required": True, "hint": "Via the cimea-diplome.it DiploMe wallet — €150, about 30 working days (€250 total expedited); start 3 months out."},
        {"key": "cimea-verification", "label": "CIMEA Statement of Verification", "required": True, "hint": "Confirms authenticity of the qualification; skip only where a DoV covering authenticity is used instead."},
        {"key": "dov", "label": "Declaration of Value (Dichiarazione di Valore)", "required": False, "hint": "Free at the consulate but slow and unevenly offered; the Questura may not demand one (Council of State 4613/2007)."},
        {"key": "apostille", "label": "Apostille / Legalisation on Originals", "required": True, "hint": "India: MEA apostille, always BEFORE translations — India, Pakistan and Bangladesh are all Hague members."},
        {"key": "sworn-translations", "label": "Sworn Italian Translations (Traduzione Giurata)", "required": False, "hint": "Diplomas and transcripts, only where the consulate or university requires them — photocopy after apostille."},
        {"key": "language-cert", "label": "Language Certificate (B2 CEFR)", "required": True, "hint": "IELTS/TOEFL ≈B2 for English-taught, CILS/CELI B2 for Italian-taught — or the university's own assessment letter."},
        {"key": "admission-letter", "label": "University Admission Letter (Lettera di Ammissione)", "required": True, "hint": "Conditional admits show on Universitaly as 'accepted with reservations' until the final diploma lands."},
        {"key": "universitaly-summary", "label": "Validated Universitaly Pre-enrolment", "required": True, "hint": "PDF of the validated domanda di preiscrizione — no visa filing without it; a.y. 2026-27 deadline 30 Nov 2026."},
        {"key": "visa-form", "label": "National Visa Application Form (Form D)", "required": True, "hint": "Signed; downloaded from vistoperitalia.esteri.it or the consulate's own site — there is no form number."},
        {"key": "funds-proof", "label": "Proof of Funds (€10,179.85/Year)", "required": True, "hint": "Student's own or ≤4th-degree-kin funds from lawful, traceable sources — the 2026-28 figure, up 46.5% on 2025-26."},
        {"key": "bank-statements", "label": "6-Month Bank Statements", "required": True, "hint": "Movement must sit consistently with family income — explain every lump-sum deposit in writing."},
        {"key": "sponsor-income-proof", "label": "Sponsor Income / ITR + Kinship Proof", "required": True, "hint": "Three years of ITRs, salary slips or business papers, plus the birth certificate linking sponsor to student."},
        {"key": "education-loan", "label": "Education Loan Sanction Letter", "required": False, "hint": "A recognised-bank sanction letter counts toward the traceable-funds picture at Indian posts."},
        {"key": "scholarship-letter", "label": "Scholarship Award Letter", "required": False, "hint": "Only an explicit award certificate counts — DSU eligibility or a pending application is worth nothing."},
        {"key": "tuition-payment-proof", "label": "First Tuition Instalment Receipt", "required": False, "hint": "Not a visa requirement, but several universities demand it to confirm the seat and it strengthens intent."},
        {"key": "accommodation-proof", "label": "Accommodation in Italy", "required": True, "hint": "Rental contract, residence booking or host declaration — a mere university-housing application is NOT valid."},
        {"key": "health-insurance", "label": "Health Insurance Policy", "required": True, "hint": "Valid in Italy with no limits or exceptions on urgent hospitalisation, bridging until SSN enrolment (€700/calendar year)."},
        {"key": "flight-itinerary", "label": "Flight Reservation", "required": False, "hint": "Itinerary only, not a purchased ticket, matching the course start date."},
        {"key": "cover-letter", "label": "Cover Letter / Study Plan (Consulate)", "required": False, "hint": "One page pre-empting the migration-risk probes: study-path coherence, funding provenance, post-study intent."},
        {"key": "cv", "label": "CV (Europass)", "required": False, "hint": "Some posts ask; it is where study gaps get explained — gaps are a standing refusal trigger."},
        {"key": "minor-consent", "label": "Parental Consent (Under 18)", "required": False, "hint": "Notarised consent plus both parents' identity documents."},
        {"key": "pcc", "label": "Police Clearance Certificate", "required": False, "hint": "Not on the standard Italy study checklist — produce one only if the consulate individually asks."},
        {"key": "permesso-kit", "label": "Permesso di Soggiorno Kit (Kit Giallo)", "required": True, "hint": "Within 8 working days of arrival at a Poste Sportello Amico — ≈€116.46 all-in; the ricevuta proves legal stay."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
    "SE": [
        {"key": "passport", "label": "Passport", "required": True, "hint": "The permit is clipped to passport expiry — renew first if under ~2.5 years remain, since 2-year grants are common."},
        {"key": "academic-transcripts", "label": "Academic Transcripts (all semesters)", "required": True, "hint": "Uploaded once on Universityadmissions.se and reused across all 4 ranked choices; institution-issued English versions."},
        {"key": "degree-certificates", "label": "Degree / Provisional Certificate", "required": True, "hint": "Provisional accepted at application; the final certificate is needed before enrolment."},
        {"key": "english-test", "label": "English Test (IELTS / TOEFL / PTE)", "required": True, "hint": "Typical master's bar IELTS 6.5 overall / TOEFL iBT 90 — medium-of-instruction letters are rarely accepted."},
        {"key": "cv", "label": "CV / Résumé", "required": False, "hint": "Programme-specific — 1-2 pages, factual, no photo needed."},
        {"key": "motivation-letter", "label": "Motivation Letter", "required": False, "hint": "Only where the programme demands one — follow its own template and word cap, naming specific courses."},
        {"key": "recommendation-letters", "label": "Recommendation Letters", "required": False, "hint": "Often optional in Sweden — 1-2 short factual academic letters on letterhead when the programme asks."},
        {"key": "gmat-gre", "label": "GMAT / GRE Score Report", "required": False, "hint": "Only some business and engineering programmes (SSE among them) ask for it."},
        {"key": "ua-fee-receipt", "label": "Application Fee Receipt (SEK 900)", "required": True, "hint": "Paid once per round however many choices — autumn fee deadline 2 February, spring 1 September; unpaid means not processed."},
        {"key": "selection-results", "label": "Notification of Selection Results", "required": True, "hint": "Portal PDF — autumn results 26 March (master's) / 31 March (bachelor's), spring 30 September (bachelor's) / 7 October (master's); the university contacts you if a reply is required."},
        {"key": "admission-letter", "label": "University Admission / Offer Letter", "required": True, "hint": "The university's own letter plus its tuition invoice — both sit in the permit file beside the portal notification."},
        {"key": "tuition-payment-receipt", "label": "First Tuition Instalment Receipt", "required": True, "hint": "The permit gate — Migrationsverket counts the student as finally admitted only once tuition is paid."},
        {"key": "bank-statement", "label": "Own Bank Statement (SEK 10,656/month)", "required": True, "hint": "SEK 10,656 × every month of the permit period (2026 rate) — liquid, in the student's own account, issued within 4 months of the permit start."},
        {"key": "education-loan-sanction", "label": "Education Loan Sanction Letter", "required": False, "hint": "Must show disbursable, unconditional funds — a locked or conditional sanction is discounted; pair with bank proof."},
        {"key": "scholarship-letter", "label": "Scholarship Award Letter", "required": False, "hint": "SI or university awards covering living costs cut the funds to show — and some waive the SEK 1,500 permit fee."},
        {"key": "sponsor-letter", "label": "Sponsor Undertaking + Sponsor Bank Proof", "required": False, "hint": "Accepted, but best practice is moving the money into the student's own account well before the statement date."},
        {"key": "health-insurance", "label": "Comprehensive Health Insurance", "required": False, "hint": "Courses under 1 year only — cover for care, hospitalisation and repatriation; Kammarkollegiet's Student IN via the university often suffices."},
        {"key": "translations", "label": "Authorised Translations (SV / EN)", "required": False, "hint": "Any document not in Swedish or English: authorised translator plus the original-language copy — no apostille, scans suffice."},
        {"key": "permit-application-receipt", "label": "E-service Submission + SEK 1,500 Receipt", "required": True, "hint": "Online only, paid by Visa/Mastercard — keep the case number for komplettering follow-up."},
        {"key": "embassy-biometric-form", "label": "Embassy Biometric Form", "required": False, "hint": "New Delhi walk-in Mon–Fri 08:30–10:30, registration closes 10:20 sharp — verify hours on swedenabroad.se before visiting."},
        {"key": "marriage-certificate", "label": "Marriage Certificate", "required": False, "hint": "Accompanying-partner files only — add cohabitation evidence for unmarried partners; funds rise SEK 4,440 a month."},
        {"key": "child-birth-certificates", "label": "Children's Birth Certificates", "required": False, "hint": "Must name both parents; consent letter where one parent stays behind — funds rise SEK 2,664 a month per child."},
        {"key": "accommodation-proof", "label": "Accommodation Booking", "required": False, "hint": "Not demanded by Migrationsverket but helps at intention checks — Swedish student-housing queues are brutal, start early."},
        {"key": "gap-justification", "label": "Study-Gap / Career-Linkage Note", "required": False, "hint": "Pre-empts intention-to-study doubt — tie every gap and pivot to the chosen programme."},
        {"key": "previous-refusal-docs", "label": "Prior Refusal Decisions (any country)", "required": False, "hint": "Prior refusals are a listed doubt indicator — disclose and explain, never hide."},
        {"key": "residence-permit-card", "label": "Residence Permit Card (post-decision)", "required": True, "hint": "Produced ~4 weeks after grant + biometrics; collected in person (New Delhi 11:00–12:00) — required to board and enter Sweden."},
        {"key": "other", "label": "Other", "required": False, "hint": "Anything not covered above."},
    ],
}


def document_types_for_country(country_code: str | None) -> list[dict]:
    """Detailed picker list for one destination (falls back to the generic list)."""
    items = ENTERPRISE_DOCUMENT_CATALOG.get(str(country_code or "").strip().upper())
    if items:
        return [dict(item) for item in items]
    return [{"key": t.lower().replace(" ", "-")[:40], "label": t, "required": False, "hint": ""}
            for t in STUDENT_DOCUMENT_TYPES]


def normalize_document_type(raw: str | None) -> str:
    value = str(raw or "").strip()
    if not value:
        return DEFAULT_DOCUMENT_TYPE
    for option in STUDENT_DOCUMENT_TYPES:
        if option.lower() == value.lower():
            return option
    # Accept a free-form custom type (trimmed) so staff aren't boxed in.
    return value[:80]


# ---------------------------------------------------------------------------
# Destination countries (student visas only)
# ---------------------------------------------------------------------------
# Ten most popular study destinations. The `gradient_*` and `accent` colors feed
# the bundled SVG landmark art on the frontend.

COUNTRIES = [
    {
        "code": "US",
        "name": "United States",
        "flag_emoji": "🇺🇸",
        "landmark": "Statue of Liberty",
        "gradient_from": "#1d4ed8",
        "gradient_to": "#0ea5e9",
        "accent": "#f8fafc",
        "student_intakes": ["Spring", "Summer", "Fall"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["F-1 Student Visa", "J-1 Exchange Visitor", "M-1 Vocational Student"],
        },
    },
    {
        "code": "CA",
        "name": "Canada",
        "flag_emoji": "🇨🇦",
        "landmark": "Niagara Falls",
        "gradient_from": "#dc2626",
        "gradient_to": "#f87171",
        "accent": "#fff5f5",
        "student_intakes": ["January", "May", "September"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["Study Permit"],
        },
    },
    {
        "code": "UK",
        "name": "United Kingdom",
        "flag_emoji": "🇬🇧",
        "landmark": "Big Ben",
        "gradient_from": "#1e3a8a",
        "gradient_to": "#7c3aed",
        "accent": "#eef2ff",
        "student_intakes": ["January", "September"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["Student Visa", "Child Student Visa", "Short-Term Study Visa"],
        },
    },
    {
        "code": "AU",
        "name": "Australia",
        "flag_emoji": "🇦🇺",
        "landmark": "Sydney Opera House",
        "gradient_from": "#0e7490",
        "gradient_to": "#14b8a6",
        "accent": "#ecfeff",
        "student_intakes": ["February", "July", "November"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["Subclass 500 Student Visa", "Subclass 590 Student Guardian"],
        },
    },
    {
        "code": "DE",
        "name": "Germany",
        "flag_emoji": "🇩🇪",
        "landmark": "Brandenburg Gate",
        "gradient_from": "#111827",
        "gradient_to": "#b91c1c",
        "accent": "#fef3c7",
        "student_intakes": ["Summer Semester", "Winter Semester"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["National Visa (Type D) – Study", "Student Applicant Visa", "Language Course Visa"],
        },
    },
    {
        "code": "IE",
        "name": "Ireland",
        "flag_emoji": "🇮🇪",
        "landmark": "Cliffs of Moher",
        "gradient_from": "#15803d",
        "gradient_to": "#65a30d",
        "accent": "#f0fdf4",
        "student_intakes": ["January", "September"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["D Study Visa", "Short Stay 'C' Study Visa"],
        },
    },
    {
        "code": "FR",
        "name": "France",
        "flag_emoji": "🇫🇷",
        "landmark": "Eiffel Tower",
        "gradient_from": "#1e40af",
        "gradient_to": "#e11d48",
        "accent": "#eff6ff",
        "student_intakes": ["January", "September"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["Long-Stay Student Visa (VLS-TS « Étudiant »)", "Temporary Long-Stay Student Visa (VLS-T)", "Entrance-Exam Visa (Court Séjour « Étudiant-Concours »)", "Short-Stay Study Visa (Schengen Type C)"],
        },
    },
    {
        "code": "ES",
        "name": "Spain",
        "flag_emoji": "🇪🇸",
        "landmark": "Sagrada Família",
        "gradient_from": "#b91c1c",
        "gradient_to": "#f59e0b",
        "accent": "#fff7ed",
        "student_intakes": ["January", "February", "September", "October"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["Long-Stay Study Visa (Type D) – Higher Education", "Long-Stay Study Visa (Type D) – Language / Training Activity", "Long-Stay Study Visa (Type D) – Secondary / Student Mobility", "Short-Stay Study Visa (Schengen Type C)"],
        },
    },
    {
        "code": "NL",
        "name": "Netherlands",
        "flag_emoji": "🇳🇱",
        "landmark": "Kinderdijk Windmills",
        "gradient_from": "#075985",
        "gradient_to": "#38bdf8",
        "accent": "#f0f9ff",
        "student_intakes": ["September", "February"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["Study Residence Permit (MVV/TEV) – Higher Education", "Study Residence Permit – Secondary / MBO", "Exchange Student Residence Permit", "Orientation Year (Zoekjaar) Permit"],
        },
    },
    {
        "code": "AE",
        "name": "United Arab Emirates",
        "flag_emoji": "🇦🇪",
        "landmark": "Burj Khalifa",
        "gradient_from": "#78350f",
        "gradient_to": "#fbbf24",
        "accent": "#fffbeb",
        "student_intakes": ["January", "May", "September"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["Student Residence Visa", "Study / Training Visit Visa", "Golden Residence – Outstanding Student", "Parent-Sponsored Student Residence"],
        },
    },
    {
        "code": "PL",
        "name": "Poland",
        "flag_emoji": "🇵🇱",
        "landmark": "Wawel Royal Castle",
        "gradient_from": "#7f1d1d",
        "gradient_to": "#ef4444",
        "accent": "#fef2f2",
        "student_intakes": ["October", "February"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["National Visa (Type D) – Studies", "Temporary Residence Permit for Studies (Karta Pobytu)", "Schengen Visa (Type C) – Short Study", "Temporary Residence Permit – Graduate Job Search"],
        },
    },
    {
        "code": "NZ",
        "name": "New Zealand",
        "flag_emoji": "🇳🇿",
        "landmark": "Milford Sound",
        "gradient_from": "#064e3b",
        "gradient_to": "#34d399",
        "accent": "#ecfdf5",
        "student_intakes": ["February", "July"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["Fee Paying Student Visa", "Pathway Student Visa", "Exchange Student Visa", "Foreign Government Supported Student Visa"],
        },
    },
    {
        "code": "SG",
        "name": "Singapore",
        "flag_emoji": "🇸🇬",
        "landmark": "Marina Bay Sands",
        "gradient_from": "#9d174d",
        "gradient_to": "#f472b6",
        "accent": "#fdf2f8",
        "student_intakes": ["January", "April", "July", "August", "October"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["Student's Pass (IHL Track)", "Student's Pass (PEI / EduTrust Track)", "Short-Term Visit Pass – Short Course"],
        },
    },
    {
        "code": "IT",
        "name": "Italy",
        "flag_emoji": "🇮🇹",
        "landmark": "Colosseum",
        "gradient_from": "#9a3412",
        "gradient_to": "#f97316",
        "accent": "#fff7ed",
        "student_intakes": ["January", "February", "June", "September", "October", "November"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["National Study Visa (Type D) – Immatricolazione Università", "National Study Visa (Type D) – PhD / AFAM / Non-Degree", "Short-Stay Study Visa (Schengen Type C)"],
        },
    },
    {
        "code": "SE",
        "name": "Sweden",
        "flag_emoji": "🇸🇪",
        "landmark": "Stockholm City Hall",
        "gradient_from": "#0c4a6e",
        "gradient_to": "#eab308",
        "accent": "#fefce8",
        "student_intakes": ["January", "August"],
        "visa_types": {
            VISA_CATEGORY_STUDENT: ["Residence Permit for Studies at Higher Education", "Residence Permit for Doctoral Studies", "Post-Study Job-Seeking Residence Permit", "Short-Stay Study Visa (Schengen Type C)"],
        },
    },
]

COUNTRY_MAP = {item["code"]: item for item in COUNTRIES}
COUNTRY_CODES = {item["code"] for item in COUNTRIES}


# ---------------------------------------------------------------------------
# Intake helpers (for student cases)
# ---------------------------------------------------------------------------

_INTAKE_START_MONTH_HINTS = {
    "spring": 1, "summer": 5, "fall": 8, "autumn": 8, "winter": 11,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "summer semester": 4, "winter semester": 10,
}


def _resolve_intake_start_month(intake_label: str) -> int:
    normalized = str(intake_label or "").strip().lower()
    if not normalized:
        return 9
    if normalized in _INTAKE_START_MONTH_HINTS:
        return int(_INTAKE_START_MONTH_HINTS[normalized])
    for key, month in _INTAKE_START_MONTH_HINTS.items():
        if key in normalized:
            return int(month)
    return 9


def materialize_future_intakes(intake_labels: list[str]) -> list[str]:
    """Turn base intake labels (e.g. "Fall") into the next upcoming dated intakes."""
    now_utc = datetime.utcnow()
    current_month = int(now_utc.month)
    current_year = int(now_utc.year)
    sortable: list[tuple[int, int, str, str]] = []
    seen: set[str] = set()
    for raw_label in intake_labels:
        base_label = str(raw_label or "").strip()
        if not base_label:
            continue
        start_month = _resolve_intake_start_month(base_label)
        year = current_year if start_month >= current_month else (current_year + 1)
        future_label = f"{base_label} {year}"
        key = future_label.lower()
        if key in seen:
            continue
        seen.add(key)
        sortable.append((year, start_month, base_label.lower(), future_label))
    sortable.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in sortable]


# ---------------------------------------------------------------------------
# Public payloads & validation
# ---------------------------------------------------------------------------

def _document_types_by_country_from_db(db) -> dict[str, list[dict]]:
    """Load the enterprise document catalog from the DB (scope visa_type_key='enterprise').

    The DB is the runtime source of truth (seeded from ENTERPRISE_DOCUMENT_CATALOG at
    startup, editable later without a deploy); any country with no rows falls back to
    the in-code list so the picker never comes up empty."""
    from app import models  # local import — this module is imported by models-adjacent code
    out: dict[str, list[dict]] = {}
    try:
        rows = (
            db.query(models.DocumentTypeCatalog)
            .filter(
                models.DocumentTypeCatalog.visa_type_key == "enterprise",
                models.DocumentTypeCatalog.is_active.is_(True),
            )
            .order_by(models.DocumentTypeCatalog.country_code.asc(), models.DocumentTypeCatalog.sort_order.asc())
            .all()
        )
        for row in rows:
            out.setdefault(row.country_code, []).append({
                "key": row.document_type,
                "label": row.label,
                "required": bool(row.is_required),
                "hint": row.description or "",
            })
    except Exception:
        out = {}
    for code in ENTERPRISE_DOCUMENT_CATALOG:
        if not out.get(code):
            out[code] = document_types_for_country(code)
    return out


def build_catalog_payload(db=None) -> dict:
    """Full catalog the frontend uses to drive dropdowns and graphics."""
    countries_payload = []
    for country in COUNTRIES:
        visa_types_by_category = {
            category: list(country["visa_types"].get(category, []))
            for category in VISA_CATEGORY_KEYS
        }
        countries_payload.append({
            "code": country["code"],
            "name": country["name"],
            "flag_emoji": country["flag_emoji"],
            "landmark": country["landmark"],
            "gradient_from": country["gradient_from"],
            "gradient_to": country["gradient_to"],
            "accent": country["accent"],
            "student_intakes": materialize_future_intakes(country.get("student_intakes", [])),
            "visa_types": visa_types_by_category,
        })
    doc_types_by_country = (
        _document_types_by_country_from_db(db) if db is not None
        else {code: document_types_for_country(code) for code in ENTERPRISE_DOCUMENT_CATALOG}
    )
    return {
        "categories": [dict(item) for item in VISA_CATEGORIES],
        # Generic wording — for org-wide surfaces (kanban columns, filter chips) where one
        # list has to cover clients of every destination.
        "stages": [dict(item) for item in CLIENT_STAGES],
        # Same stages, worded per destination — for anything scoped to ONE client.
        "stages_by_country": stages_by_country(),
        "priorities": [dict(item) for item in CLIENT_PRIORITIES],
        # Legacy flat list (kept for back-compat); the per-country map below is what
        # the client-profile pickers use.
        "document_types": list(STUDENT_DOCUMENT_TYPES),
        "document_types_by_country": doc_types_by_country,
        # Case-record fields to capture at each pipeline stage, resolved per destination.
        "stage_fields_by_country": stage_fields_by_country(),
        # Option lists for the client intake record (Add/Edit client). Defined server-side
        # so the dropdowns and the server-side validation can never drift apart.
        "client_profile_options": {
            field: [dict(item) for item in options]
            for field, options in client_fields.CLIENT_PROFILE_OPTIONS.items()
        },
        "marketing_consent_channels": [dict(item) for item in client_fields.MARKETING_CONSENT_CHANNELS],
        "city_suggestions": list(client_fields.CITY_SUGGESTIONS),
        "field_of_study_suggestions": list(client_fields.FIELD_OF_STUDY_SUGGESTIONS),
        "countries": countries_payload,
    }


# ---------------------------------------------------------------------------
# Per-stage CASE RECORD fields (destination-aware)
# ---------------------------------------------------------------------------
# What a counselor RECORDS on the client at each pipeline stage — the numbers, dates and
# references that make up the case file. Documents themselves are handled separately by
# ENTERPRISE_DOCUMENT_CATALOG; these are the data points, and they differ per destination
# (US SEVIS/DS-160 vs UK CAS/IHS vs Canada IRCC/GIC …).
#
# Each field: key (stable, unique within a destination), label, type
# (text | date | number | select | textarea), hint, required — plus options for select.
#
# SHARED fields apply to every destination. The per-country map ADDS destination-specific
# fields; a country field reusing a shared key overrides it.
# The field data lives in its own module (it is large); this file owns the resolution rules.
from app.enterprise_stage_fields import (  # noqa: E402
    ENTERPRISE_STAGE_SHARED_FIELDS,
    ENTERPRISE_STAGE_FIELD_CATALOG,
)


# Lead-qualification questions that USED to be recorded here and are now first-class
# columns on the client (captured in the Add-client form — see enterprise_client_fields).
# They stay suppressed rather than deleted from the data file so that anything an org
# already stored under these keys survives in stage_data; schema_patch copies it into the
# new columns on startup.
RETIRED_STAGE_FIELDS: dict[str, set[str]] = {
    "new_lead": {
        "enquiry_source",
        "prior_refusal_history",
        "admission_stage",
        "funding_source",
        "english_test_status",
        "language_test_status",
        "study_level",
    },
}


def stage_fields_for(country_code: str | None, stage_key: str | None) -> list[dict]:
    """Fields to record at `stage_key` for `country_code`: the shared set plus that
    destination's own fields.

    A country entry that reuses a shared key can do one of two things:
      * REDEFINE it — the entry names a `label`, and replaces the shared field outright
        (the UK's "Course Start Date (per CAS)" instead of the generic label).
      * PATCH it — the entry leaves `label` blank, meaning "keep the shared field, just
        refine it for this destination". Only its own non-empty values are applied, so
        the shared label, type and options survive. Without this, a destination that
        merely wanted to sharpen a hint would flatten a labelled `select` into an
        unlabelled free-text box and lose its options.
    """
    stage = str(stage_key or "").strip().lower()
    if stage not in CLIENT_STAGE_KEYS:
        return []
    merged: dict[str, dict] = {f["key"]: dict(f) for f in ENTERPRISE_STAGE_SHARED_FIELDS.get(stage, [])}
    country = (ENTERPRISE_STAGE_FIELD_CATALOG.get(str(country_code or "").strip().upper()) or {}).get(stage, [])
    for field in country:
        # applicable=False means "this shared field doesn't exist for this destination"
        # (e.g. the UK issues an eVisa, so there is no passport sticker number to record).
        if field.get("applicable") is False:
            merged.pop(field["key"], None)
            continue
        entry = {k: v for k, v in field.items() if k != "applicable"}
        shared = merged.get(field["key"])
        if shared is not None and not str(entry.get("label", "")).strip():
            patched = dict(shared)
            for key, value in entry.items():
                # `type` is part of the shared field's identity — changing it requires a
                # full redefinition (i.e. naming a label), not a patch.
                if key in ("label", "type") or value in ("", None):
                    continue
                patched[key] = value
            merged[field["key"]] = patched
            continue
        merged[field["key"]] = entry
    for retired in RETIRED_STAGE_FIELDS.get(stage, ()):
        merged.pop(retired, None)
    return list(merged.values())


def stage_fields_by_country() -> dict:
    """Resolved catalog for the frontend: {COUNTRY_CODE: {stage_key: [field, …]}}."""
    stage_keys = [item["key"] for item in CLIENT_STAGES]
    return {
        code: {stage: stage_fields_for(code, stage) for stage in stage_keys}
        for code in COUNTRY_MAP
    }


def normalize_category(raw_category: str | None) -> Optional[str]:
    """Student-only catalog: everything resolves to student (or None if clearly invalid)."""
    value = str(raw_category or "").strip().lower()
    if not value:
        return VISA_CATEGORY_STUDENT
    if value in VISA_CATEGORY_KEYS:
        return value
    if value in {"students", "study", "education", "educational", "student visa"}:
        return VISA_CATEGORY_STUDENT
    return None


def normalize_stage(raw_stage: str | None) -> str:
    value = str(raw_stage or "").strip().lower()
    if value in CLIENT_STAGE_KEYS:
        return value
    return DEFAULT_CLIENT_STAGE


def normalize_priority(raw_priority: str | None) -> str:
    value = str(raw_priority or "").strip().lower()
    if value in CLIENT_PRIORITY_KEYS:
        return value
    return DEFAULT_CLIENT_PRIORITY


def get_country(country_code: str | None) -> Optional[dict]:
    return COUNTRY_MAP.get(str(country_code or "").strip().upper())


def resolve_visa_case(
    *,
    category: str | None,
    country_code: str | None,
    visa_type: str | None,
    intake: str | None = None,
) -> dict:
    """
    Validate & canonicalize a (country, visa type, intake) selection. The category
    is always student in this catalog.

    Returns a dict with canonical values, or raises ValueError with a friendly
    message describing the first problem encountered.
    """
    canonical_category = normalize_category(category) or VISA_CATEGORY_STUDENT

    country = get_country(country_code)
    if not country:
        raise ValueError("Please choose a valid study destination country.")

    available_visa_types = country["visa_types"].get(canonical_category, [])
    if not available_visa_types:
        raise ValueError(f"{country['name']} does not have student visas configured.")

    visa_input = str(visa_type or "").strip()
    canonical_visa_type = ""
    for option in available_visa_types:
        if str(option).strip().lower() == visa_input.lower():
            canonical_visa_type = str(option).strip()
            break
    if not canonical_visa_type:
        raise ValueError("The selected visa type is not valid for that country.")

    canonical_intake: Optional[str] = None
    intake_input = str(intake or "").strip()
    if intake_input:
        allowed = materialize_future_intakes(country.get("student_intakes", []))
        for option in allowed:
            if option.strip().lower() == intake_input.lower():
                canonical_intake = option.strip()
                break
        if canonical_intake is None:
            # Accept a free-form intake the user typed, just trim it.
            canonical_intake = intake_input[:120]

    return {
        "category": canonical_category,
        "country_code": country["code"],
        "country_name": country["name"],
        "visa_type": canonical_visa_type,
        "intake": canonical_intake,
    }


# ---------------------------------------------------------------------------
# Stage-catalog invariants (checked at import)
# ---------------------------------------------------------------------------
# The pipeline order lives in two places — the canonical `order` on CLIENT_STAGES and the
# absolute per-destination overrides in ENTERPRISE_STAGE_LABELS — and nothing at runtime
# reads the two together, so a drift between them shows up only as a silently mis-sequenced
# journey for one country. These run once, at import, so the process refuses to start.

def _assert_stage_catalog_invariants() -> None:
    seen: dict[int, str] = {}
    for stage in CLIENT_STAGES:
        clash = seen.get(stage["order"])
        if clash:
            raise ValueError(
                f"CLIENT_STAGES: stages '{clash}' and '{stage['key']}' share order "
                f"{stage['order']} — pipeline orders must be unique."
            )
        seen[stage["order"]] = stage["key"]
    expected = list(range(1, len(CLIENT_STAGES) + 1))
    if sorted(seen) != expected:
        raise ValueError(
            f"CLIENT_STAGES: orders {sorted(seen)} are not contiguous from 1 — "
            f"expected {expected}."
        )

    for code, overrides in ENTERPRISE_STAGE_LABELS.items():
        for key in overrides:
            if key not in CLIENT_STAGE_KEYS:
                raise ValueError(
                    f"ENTERPRISE_STAGE_LABELS['{code}']: '{key}' is not a pipeline stage — "
                    f"known keys are {sorted(CLIENT_STAGE_KEYS)}."
                )
        resolved: dict[int, str] = {}
        for stage in stages_for(code):
            clash = resolved.get(stage["order"])
            if clash:
                raise ValueError(
                    f"ENTERPRISE_STAGE_LABELS['{code}']: stages '{clash}' and "
                    f"'{stage['key']}' both resolve to order {stage['order']} — an absolute "
                    f"`order` override was left behind when the canonical order changed."
                )
            resolved[stage["order"]] = stage["key"]


_assert_stage_catalog_invariants()
