"""
Gemini AI service for document text extraction
Supports both standard Gemini API (with API key) and Vertex AI (with service account)
"""
import os
from typing import Optional
import io
from PIL import Image
from pathlib import Path
from datetime import datetime

# Try to import Vertex AI libraries
try:
    from google.cloud import aiplatform
    from vertexai.generative_models import GenerativeModel, Part
    VERTEX_AI_AVAILABLE = True
except ImportError:
    VERTEX_AI_AVAILABLE = False
    print("⚠ Warning: google-cloud-aiplatform not installed. Install with: pip install google-cloud-aiplatform")

# Also import standard Gemini API as fallback
GENAI_AVAILABLE = False
genai = None
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    print("⚠ Warning: google-generativeai not installed. Install with: pip install google-generativeai")

# Configure authentication - Check for service account first
SERVICE_ACCOUNT_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
USE_VERTEX_AI = False

# Check if service account file exists in current directory
if not os.path.exists(SERVICE_ACCOUNT_PATH):
    # Try project root directory
    current_dir_service_account = Path(__file__).parent.parent.parent / "service_account.json"
    if current_dir_service_account.exists():
        SERVICE_ACCOUNT_PATH = str(current_dir_service_account)

# Configure authentication
if os.path.exists(SERVICE_ACCOUNT_PATH) and VERTEX_AI_AVAILABLE:
    # Use Vertex AI with service account
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = SERVICE_ACCOUNT_PATH
    USE_VERTEX_AI = True
    # Initialize Vertex AI
    try:
        # Get project ID from service account JSON
        import json
        with open(SERVICE_ACCOUNT_PATH, 'r') as f:
            service_account_info = json.load(f)
            project_id = service_account_info.get('project_id', '')
            location = os.getenv("GCP_LOCATION", "us-central1")
        
        if project_id:
            aiplatform.init(project=project_id, location=location)
            print(f"✓ Using Vertex AI with service account: {SERVICE_ACCOUNT_PATH}")
            print(f"  Project: {project_id}, Location: {location}")
        else:
            print("⚠ Warning: Could not find project_id in service account JSON")
            USE_VERTEX_AI = False
    except Exception as e:
        print(f"⚠ Warning: Failed to initialize Vertex AI: {str(e)}")
        USE_VERTEX_AI = False

if not USE_VERTEX_AI:
    # Validate API key format (should start with AIza for Gemini)
    if GEMINI_API_KEY and not GEMINI_API_KEY.startswith("AIza"):
        # Invalid API key format (likely a Resend key or other service key)
        print(f"⚠ Warning: GEMINI_API_KEY doesn't appear to be a valid Gemini API key (should start with 'AIza'). Ignoring it.")
        GEMINI_API_KEY = ""
    
    if GEMINI_API_KEY and GENAI_AVAILABLE:
        # Use standard Gemini API with API key
        genai.configure(api_key=GEMINI_API_KEY)
        print("✓ Using Gemini API key for authentication")
    else:
        print("⚠ Warning: Neither service account JSON nor valid GEMINI_API_KEY found. Document text extraction will be disabled.")


def is_ai_configured() -> bool:
    """True when Gemini is usable via either the Vertex AI service account path
    or a valid Gemini API key. Callers use this to fail fast with a clean
    'temporarily unavailable' message instead of a 500 when AI isn't configured."""
    if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
        return True
    key = (GEMINI_API_KEY or "").strip()
    return bool(GENAI_AVAILABLE and key and key.startswith("AIza"))

# Supported file types for Gemini
SUPPORTED_IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
SUPPORTED_DOCUMENT_TYPES = {".pdf", ".txt"}
UPLOAD_VALIDATION_PROMPT_CONTEXT_CHARS = int(
    os.getenv("UPLOAD_VALIDATION_PROMPT_CONTEXT_CHARS", "120000") or "120000"
)
# Primary model everywhere: Gemini 3.1 Pro (strongest reasoning). Fallbacks stay on
# LIVE model ids only — gemini-2.0-flash / gemini-1.5-* are retired and now 404 on
# the v1beta API, so they must never appear in a candidate chain.
#
# 2026-07-26: the bare `gemini-3.1-pro` id is NOT served by the v1beta API (verified
# against list_models — only `gemini-3.1-pro-preview` exists). It sat at the head of
# every chain, so each call paid a wasted 404 round-trip before falling through, and
# single-shot grounded callers (course_catalog) silently degraded to ungrounded. The
# preview id is the primary until the GA id actually ships; keep the dead id OUT.
DEFAULT_GEMINI_MODEL = (os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview").strip() or "gemini-3.1-pro-preview")
DEFAULT_GEMINI_MODEL_CANDIDATES = [
    DEFAULT_GEMINI_MODEL,
    "gemini-3.1-pro-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
]


def _dedupe_model_names(model_names: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for model_name in model_names:
        value = str(model_name or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def get_model_candidates(
    primary_env: Optional[str] = None,
    candidates_env: Optional[str] = None,
    defaults: Optional[list[str]] = None,
) -> list[str]:
    primary = os.getenv(primary_env or "", "").strip() if primary_env else ""
    configured_candidates = []
    if candidates_env:
        configured_candidates = [
            item.strip()
            for item in os.getenv(candidates_env, "").split(",")
            if item.strip()
        ]
    return _dedupe_model_names(
        [primary] + configured_candidates + list(defaults or DEFAULT_GEMINI_MODEL_CANDIDATES)
    )


def _instrument_usage(model, model_name: str, usage_source: str = "document_ai"):
    """Wrap generate_content so every document-AI call logs its token usage/cost."""
    try:
        original = model.generate_content
    except Exception:
        return

    def _wrapped(*args, **kwargs):
        resp = original(*args, **kwargs)
        try:
            from app import ai_usage
            ai_usage.record_gemini_usage(usage_source, model_name, resp)
        except Exception:
            pass
        return resp

    try:
        model.generate_content = _wrapped
    except Exception:
        pass


def build_generative_model(model_name: str, usage_source: str = "document_ai"):
    model = None
    if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
        model = GenerativeModel(model_name)
    elif GENAI_AVAILABLE:
        model = genai.GenerativeModel(model_name)
    if model is not None:
        _instrument_usage(model, model_name, usage_source)
    return model


def _generate_content_with_fallback(
    model_names: list[str],
    content,
    usage_source: str = "document_ai",
):
    """Generate with each configured model until one succeeds."""
    last_error = None
    for model_name in _dedupe_model_names(model_names):
        try:
            model = build_generative_model(model_name, usage_source=usage_source)
            if model is None:
                continue
            return model.generate_content(content)
        except Exception as exc:
            last_error = exc
            print(
                f"AI model candidate '{model_name}' failed during {usage_source}; "
                "trying the next configured candidate."
            )

    if last_error is not None:
        raise last_error
    raise RuntimeError("No configured AI model is available")

# Destination-specific date/validity rules injected into the upload-validation prompt so
# a UK/CA/AU/DE/FR/ES/NL/AE student's documents are judged by THEIR authority's rules
# (not US ones).
_DESTINATION_TIMELINE_RULES = {
    "US": (
        "- I-20 / DS-2019: flag if the program start or reporting date is already in the past. From 15 Sep 2026 the I-20 program end date also fixes the I-94 admit-until date (capped at 4 years), so flag an I-20 whose program runs longer than one admission can cover.\n"
        "- Transfer or change-of-level I-20: from 15 Sep 2026 an F-1 must normally complete the first academic year at the school that first enrolled them, and a graduate-level student may not change program, major or education level at any point — flag a transfer or change-of-level I-20 dated inside the first academic year without an SEVP exception.\n"
        "- Passport: must be valid at least 6 months beyond the intended period of stay, unless the applicant's nationality is on the State Department's six-month-club list, in which case validity through the period of stay is enough.\n"
        "- DS-160 confirmation: must belong to the current application cycle and carry the same SEVIS ID and school as the I-20 — flag a confirmation page for a superseded DS-160, or one whose social-media disclosure does not match the accounts the student actually holds.\n"
        "- MRV fee receipt: valid 365 days from the date of payment for scheduling — flag receipts older than that; the $185 is not refundable and must be paid again.\n"
        "- I-901 SEVIS fee receipt: must quote the exact SEVIS ID printed on the I-20 or DS-2019 — flag a receipt for a different SEVIS ID. A receipt from a refused application may be reused only within 12 months of that refusal.\n"
        "- Financial proof: US consulates expect bank statements no older than ~3-6 months at the interview date, and the evidenced amount must cover at least the first-year cost printed on the I-20. Flag a single large deposit shortly before the interview as unseasoned funds.\n"
        "- English test scores: TOEFL, IELTS, PTE and Duolingo results are valid 2 years from the test date — flag older results, and check them against the admitting school's own minimum rather than a generic one.\n"
        "- Interview appointment: flag a slot booked at a post outside the applicant's country of nationality or residence (State Department guidance of 6 Sep 2025), and treat any interview-waiver or dropbox evidence for F, M or J as obsolete — in-person interviews have been required since 2 Sep 2025.\n"
        "- Visa foil: the 'Expiration Date' governs entry only, never the permitted stay — flag any reasoning that treats the foil expiry as the study period, or that treats an I-94 marked 'D/S' as still being issued after 15 Sep 2026."
    ),
    "UK": (
        "- Passport: UKVI applies no 6-month validity rule and, since entry vignettes were withdrawn for Student applicants on 15 July 2025, no blank-page rule either — flag only a passport that is expired or otherwise invalid on the application date.\n"
        "- CAS statement: flag if the course start date is in the past, if the CAS was assigned more than 6 months before the application (ST 1.2), or if the application is being made more than 6 months before the course start (3 months for an in-UK application).\n"
        "- Financial evidence (UKVI 28-day rule): funds must be held for 28 CONSECUTIVE days, and the statement's closing date must be within 31 days of the visa application date — flag statements older than ~31 days or that do not show a 28-day history. Since 11 November 2025 the maintenance rates are £1,529/month in London and £1,171/month outside London, both capped at 9 months, PLUS any course fees still unpaid on the CAS — flag evidence below that total, and flag overdrafts, shares, pensions or crypto, which are not accepted at all.\n"
        "- Loan letters and official financial sponsor letters: must be dated no more than 6 months before the application — flag older letters, and flag a loan letter that does not confirm the money is available before the course begins or is issued by anything other than a government or a regulated education-loan scheme.\n"
        "- SELT / IELTS for UKVI: results are valid 2 years from the test date — flag older results, and flag a certificate that is not a UKVI-approved SELT (IELTS Life Skills, or a plain Academic IELTS taken at a non-SELT centre, does not count).\n"
        "- IHS payment confirmation: must correspond to the current application.\n"
        "- TB test certificate: valid 6 months from the date of the chest x-ray at an approved clinic — flag if older.\n"
        "- ATAS certificate (if present): valid 6 months from issue for the visa application — flag if older.\n"
        "- UKVI eVisa/share-code evidence: flag if the passport/travel-document details do not match the student's profile or decision notice. Do NOT flag the absence of a 90-day entry vignette: Student grants for courses over 6 months have been eVisa-only since 15 July 2025.\n"
        "- Student route visa brake: an entry-clearance application made on or after 26 March 2026 by a national of Afghanistan, Cameroon, Myanmar or Sudan is refused regardless of the CAS — raise it against the case, not the document."
    ),
    "CA": (
        "- Letter of Acceptance (LOA): flag if the program start date is already in the past, and flag an LOA the DLI has not confirmed in IRCC's portal — since 1 December 2023 an unverified LOA stops the application.\n"
        "- PAL/TAL: 2026 cap-year letters are valid to 31 December 2026 unless a shorter expiry is printed, and must be valid on the date IRCC RECEIVES the application, not the date it is processed. Flag a PAL reused after a decision was made on an earlier application, or after a change of school or level of study — a new one is required. Do NOT flag a missing PAL for a master's or doctoral applicant at a public DLI, for K-12, for a formal exchange, or for an extension at the same DLI and level: those are PAL-exempt from 1 January 2026, and a Quebec file's CAQ letter carries the attestation.\n"
        "- Proof of funds: outside Quebec the living-cost floor is CAD 22,895 for a single applicant (in force from 1 September 2025, re-indexed every 1 September), on top of first-year tuition and travel; for Quebec it is CAD 24,617 from 1 January 2026. Flag totals below the applicable floor, statements older than ~6 months or covering fewer than 4 months, and a large unexplained deposit shortly before filing.\n"
        "- GIC: optional since the Student Direct Stream closed on 8 November 2024 — do NOT flag its absence as a defect where other evidence meets the floor.\n"
        "- Immigration medical exam: an IME is valid 12 months from the exam date — flag an older one. Biometrics are reusable for 10 years from enrolment, so do not flag an in-date prior enrolment.\n"
        "- Language test: IELTS, PTE, TOEFL and CELPIP results are valid 2 years from the test date — flag older results. IRCC itself sets no minimum since SDS closed; judge the score against the DLI's offer, and against CLB 7 (degree) or CLB 5 (college) if a PGWP is intended.\n"
        "- Passport: a study permit is never issued beyond passport expiry — flag a passport expiring before the program end date, because it silently truncates both the permit and the PGWP window.\n"
        "- CAQ (Quebec only): must still be valid when the study permit is decided and must cover the program — flag an expired CAQ, or one issued for a different program or institution."
    ),
    "AU": (
        "- CoE (Confirmation of Enrolment): flag if the course start date is already in the past. Since 1 January 2025 a letter of offer is no longer accepted as evidence of enrolment — flag a file carrying only an offer letter (narrow exceptions: Foreign Affairs/Defence-sponsored students, AASES secondary exchange students, and postgraduate research students awaiting thesis assessment).\n"
        "- OSHC: must be from an approved fund (Allianz Care, ahm, Bupa, Medibank, nib — CBHS left the scheme in 2025), prepaid, starting on or before arrival and running to the VISA expiry rather than the course end date — flag any gap, and flag cover bought from a non-approved insurer.\n"
        "- Financial capacity evidence: statements must be recent (within about a month of lodgement) AND show the funds held for roughly 3 months — flag a large unexplained credit shortly before lodgement as manufactured funds. The benchmark is 12 months' living costs (AUD 29,710 for the student, AUD 10,394 for a partner, AUD 4,449 per child) plus first-year tuition and return travel; the figure is indexed, so treat it as current-at-filing rather than fixed. On the annual-income route the income must be a parent's or partner's — currently AUD 87,856 alone, AUD 102,500 with family, for the 12 months before lodgement.\n"
        "- Education loan evidence: flag an in-principle or conditional sanction — the loan must be sanctioned by an approved lender and disbursement-ready.\n"
        "- English test: flag any result 2 years or older at the application date, and flag online or at-home formats (IELTS Online, TOEFL iBT Home Edition) outright — only supervised in-centre sittings are accepted for a Subclass 500.\n"
        "- Health: panel-clinic clearances lapse after about 12 months — flag an eMedical clearance likely to be stale at decision, and flag a Form 815 health undertaking with no evidence it was actioned.\n"
        "- Biometrics: the s.40 'requirement to provide personal identifiers' letter runs 14 CALENDAR days — flag a request whose window has closed.\n"
        "- Passport: an Australian visa is bound electronically to the passport in the application — flag a passport renewed after lodgement with no Form 929 update, and one whose validity does not run to the end of the intended stay.\n"
        "- Refusal and s56 correspondence: deadlines run from the DEEMED notification date (the date the Department sent it, not the date it was read); the ART review deadline cannot be extended, while an s56 extension must be requested before the due date — flag a refusal letter or information request whose stated deadline has already passed."
    ),
    "DE": (
        "- Passport: German missions apply their own rule, not the generic 6-month one — flag a passport issued more than 10 years before the application date, or one with fewer than 2 blank pages.\n"
        "- Blocked account (Sperrkonto) confirmation: must show the full year's sum AND a maximum monthly release. For a §16b study file that is €11,904 and €992/month; for a §17(2) study applicant, a Studienkolleg entrant, or a §16f(1) language course that does not serve study preparation it is 10% higher — €13,092 and €1,091/month (§2(3) AufenthG). Figures are indexed to the BAföG rate and re-checked each year, so treat them as the amount in force on the filing date, never as fixed. Flag a confirmation below the applicable threshold, one that names no monthly release cap, or one issued by a provider no longer operating (Deutsche Bank closed 2022, ICICI suspended July 2024, Coracle paused August 2025).\n"
        "- Language certificate: German missions require it to be NOT OLDER THAN 1 YEAR at the appointment — flag anything older, even though the test body itself may still call it valid. Do not flag it at all if the admission letter certifies sufficient proficiency.\n"
        "- Admission letter (Zulassungsbescheid, Studienkolleg place or language-course registration): flag if the programme start date has already passed, and flag if it fails to state the language of instruction or whether a German degree is awarded — German missions reject on both omissions.\n"
        "- APS certificate: since April 2023 APS India issues only the digitally signed DigZert — flag a scanned paper certificate or one without the qualified electronic seal. Do not flag its absence where an exemption applies (PhD/post-doc, German or EU public-fund scholarship, a degree earned in Germany, or a non-Indian qualifying certificate/degree); in those files expect an anabin printout or a ZAB Statement of Comparability instead, neither of which expires.\n"
        "- Travel health insurance: must cover the first 90 days starting with and including the intended date of entry — flag cover that starts after the entry date or ends inside that window. German statutory or private cover takes over from enrolment.\n"
        "- Scholarship letter: only a German or EU public-fund award substitutes for the blocked account — flag a private or home-country award offered in its place.\n"
        "- Verpflichtungserklärung: valid only if issued to a sponsor resident in Germany by their local authority under §§66-68 AufenthG — flag one signed abroad, and flag one older than 6 months.\n"
        "- Visa fee receipt: €75 for an adult, €37.50 under 18 — flag an amount that cannot be reconciled to those, allowing for the VFS service charge shown separately.\n"
        "- Refusal letter: the remonstration procedure was abolished worldwide on 1 July 2025. Do not treat a remonstration deadline as live; the only remaining deadline is one month from service for a Klage at the Verwaltungsgericht Berlin (§74 VwGO)."
    ),
    "FR": (
        "- Passport: French posts apply Schengen-style checks, not the generic 6-month rule — flag a passport issued more than 10 years before the application date, one whose validity does not run at least 3 months beyond the visa end date, or one with fewer than 2 blank pages.\n"
        "- Accord préalable d'inscription / attestation d'acceptation: flag if it is not for the academic year being applied for, or if the enrolment date has already passed — a deferral voids it and the Études en France procedure must be run again for the new campaign. A convocation for a concours must place the results inside the 3-month court-séjour validity.\n"
        "- France-Visas long-stay application and provider appointment: flag anything lodged more than 3 months before the intended departure date — it is turned away at the counter.\n"
        "- Proof of resources: statements must be dated within 3 months of the appointment (ideally 30 days) and cover the whole first year at the monthly rate in force ON THE FILING DATE (€615/month up to 31 July 2026; €877.50/month — 47% of the gross SMIC, décret 2026-526 — for files lodged from 1 August 2026, and re-indexed at every SMIC revaluation, so treat the figure as indexed, never fixed). Flag a single large deposit shortly before the appointment as manufactured funds.\n"
        "- Attestation de prise en charge: flag if older than 3 months, if it does not state the monthly amount committed at the current threshold, or if the guarantor's own ID, proof of address and income/bank evidence are missing.\n"
        "- Accommodation proof: must cover at least the first 3 months from arrival with no gaps; an attestation d'hébergement must be within 3 months and carry the host's ID and proof of address.\n"
        "- Language certificate: TCF and TEF results are valid 2 years from the test date; TCF-DAP is valid only for the DAP campaign it was sat for; DELF/DALF diplomas do not expire; IELTS/TOEFL 2 years."
    ),
    "ES": (
        "- Passport: Spain requires validity of at least 1 YEAR at the date of application (RD 1155/2024) — flag anything under 12 months, plus fewer than 2 blank pages or issuance more than 10 years ago.\n"
        "- Carta de Admisión: flag if the course start date has already passed, if it is only a reservation of a place or a conditional offer, or if the course is not full-time and attended in person.\n"
        "- Criminal record certificate (antecedentes penales): required only for stays over 6 months, and valid 3 months from issue — flag if older, if the apostille/legalisation or the sworn Spanish translation is missing, or if a country lived in during the last 5 years has no matching certificate.\n"
        "- Medical certificate (WHO IHR 2005): required only for stays over 6 months (180 days), and valid 3 months from issue — flag if older, or if it does not state the applicant is free of diseases with serious public-health repercussions and carry the doctor's signature, stamp and licence number.\n"
        "- Health insurance: must be a HEALTH policy from an insurer authorised in Spain spanning the whole authorised stay (many posts require cover from one month before the course to 15 days after it ends) — flag travel-only cover and any co-payment, waiting period (carencia), deductible or cover ceiling.\n"
        "- Proof of funds: 100% of monthly IPREM (€600 in 2026, re-fixed each year in the Presupuestos Generales del Estado) for EVERY month of the real course length, never a flat annual figure — flag totals below that, unexplained lump-sum deposits, statements that are not recent, and any reliance on property valuations, vehicles or a bare third-party support letter with no financial documentation behind it.\n"
        "- Where the funds sit in a relative's account, flag a missing apostilled proof of the family link, the relative's own statements or their notarised commitment to maintain the student."
    ),
    "NL": (
        "- Passport: flag if it expires within 6 months of the MVV appointment, has fewer than 2 blank pages, or expires before the programme end date — the permit is never issued beyond passport validity.\n"
        "- Letter of admission (toelatingsbrief): flag if the programme start date is already in the past, or no CROHO/ISAT number identifies an NVAO-accredited programme.\n"
        "- Living-cost transfer receipt: flag if the amount is under 12 months at the IND study norm for the intake year (re-indexed 1 January and 1 July), or the funds sit in the student's own account instead of being credited to the university. There is NO seasoning rule — never flag a statement for its age.\n"
        "- IND approval letter: flag if it is more than ~2 months old with no MVV appointment booked — the MVV must be collected within 3 months of the decision date.\n"
        "- MVV sticker (type D): flag if the 90-day window from the issue date closes before the intended entry date.\n"
        "- English test report (IELTS Academic / TOEFL iBT): valid 2 years from the test date — flag results that expire before ENROLMENT, not merely before the application.\n"
        "- Health insurance: flag if cover starts after the declared entry date or ends before the permit does.\n"
        "- Document language: flag any document not in Dutch, English, French or German with no translation by a translator sworn before a Dutch court (Rbtv) — a translation made abroad must itself be legalised.\n"
        "- Birth certificate: needed by the gemeente for BRP/BSN, not by the IND — flag a missing apostille/legalisation or a missing translation; it blocks the BSN, the bank account and the deposit refund.\n"
        "- TB: only the declaration of intent (appendix 7603) belongs in the application — do NOT flag a missing TB certificate, and expect none at all for nationalities exempt under appendix 7644."
    ),
    "AE": (
        "- Entry permit (e-visa): valid 60 days from the date of issue and single entry — flag travel planned outside that window, a permit already used to enter, or any plan to exit and re-enter on it.\n"
        "- Medical fitness certificate: valid 90 days and taken inside the UAE at a DHA / EHS-MOHAP / SEHA approved centre — flag a home-country medical or a certificate older than 90 days. The screens that decide fitness are HIV and a TB chest X-ray; applicants under 18 are exempt.\n"
        "- Attested academic certificates: the chain is home education authority → home MoFA → UAE Embassy/Consulate → MOFAIC inside the UAE. The UAE is NOT a Hague Apostille state — flag any certificate carrying only an apostille.\n"
        "- Attestation detail: flag a missing MOFAIC stamp on a foreign certificate, and flag any name spelling that differs from the passport. Nothing needs legalising where the certificate was issued in the UAE.\n"
        "- Health insurance policy: from a UAE-licensed insurer and covering the whole residence period — flag any policy expiring before the permit, since a lapse blocks issuance and renewal in ICP, GDRFA and MOHRE at once.\n"
        "- Offer / enrolment letter: flag a programme start date already past, or an issuing body that is not MoHESR/CAA-licensed (KHDA/UQAIB-validated in Dubai's free zones, ADEK-regulated in Abu Dhabi). Renewals need a fresh enrolment certificate each cycle, so flag a stale letter reused at renewal.\n"
        "- English test score: IELTS and TOEFL results are accepted within 2 years — flag older results, and flag any score below the requirement printed on the offer letter. Since the Grade-12 EmSAT was cancelled in November 2024 each university sets its own bar, commonly IELTS 5.5 / TOEFL iBT 71 and 6.0–6.5 at branch campuses."
    ),
    "IE": (
        "- Passport: Ireland requires validity of at least 12 MONTHS after the intended date of arrival, not the generic 6 months — flag anything shorter, and flag a file with no photocopies of previous passports.\n"
        "- Letter of Acceptance: flag a course start date already in the past, an offer that is conditional rather than an acceptance, fewer than 15 hours of organised daytime tuition per week, no statement of the learner protection arrangements, or a programme that appears on neither the ILEP nor the TrustEd Ireland eligible programmes list.\n"
        "- Proof of fee payment: since 30 June 2025 the full fee must be paid where it is under €6,000, otherwise at least €6,000, by electronic transfer to the college's Irish bank account or through an approved student fees payment service (Transfermate, formerly Pay to Study) — flag a shortfall, a cash receipt, and a transfer that does not show both the college's and the applicant's bank details.\n"
        "- Financial evidence: €10,000 for a one-year course, or €833 per month capped at €6,665 for a stay of 8 months or less, plus the same again for each subsequent year. Statements must be on headed paper and show SIX MONTHS of transactions — Ireland applies NO 28-day seasoning rule, so never flag a statement for failing one. Flag unexplained large or irregular lodgements, credit cards offered as evidence, a deposit or savings statement with no bank letter confirming the funds can be withdrawn, and an education bond under €10,000, held for a non-degree student, or already released before registration.\n"
        "- English test certificate: must have been ISSUED within 2 years of the expected COURSE START date, not the application date — flag older certificates, and flag scores below the ISD visa floor of IELTS Academic 5.0 / TOEFL iBT 61 / PTE Academic 30 / Duolingo 75 (4.0 / 47 / 30 / 55 for second-level, foundation and preparatory English courses). Do NOT flag a missing certificate for an English language course applicant — none is required.\n"
        "- Private medical insurance: must cover accident, disease and any period of hospitalisation for the whole stay. Travel insurance is acceptable only for a newly arrived first-year student and only at €25,000 accident and €25,000 disease — flag travel cover presented at second or subsequent registration, and flag any policy not evidenced in English.\n"
        "- Translations and civil documents: flag any document not in English or Irish without a full certified translation, and flag a birth, marriage or similar state-issued certificate from outside the EEA or Switzerland that carries no apostille from that state's Ministry of Foreign Affairs — a translation made outside the EEA must itself be apostilled."
    ),
}


def validate_and_extract_document(
    file_contents: bytes,
    filename: str,
    mime_type: str,
    document_type: Optional[str] = None,
    current_date_for_evaluation: Optional[str] = None,
    student_profile_context: Optional[str] = None,
    related_documents_context: Optional[str] = None,
    destination_country_code: Optional[str] = None,
    destination_summary: Optional[str] = None,
) -> Optional[dict]:
    """
    Validate document type and extract information using Gemini AI.
    Returns a JSON dict with validation result and extracted information, or None if extraction fails.
    
    Response format:
    {
        "Document Validation": "Yes" or "No",
        "Message": "Validation message",
        "Name": "extracted name",
        "Extracted Information": {...}
    }
    """
    # Check if we have authentication configured
    has_service_account = os.path.exists(SERVICE_ACCOUNT_PATH)
    has_valid_api_key = GEMINI_API_KEY and GEMINI_API_KEY.startswith("AIza")
    
    if not has_service_account and not has_valid_api_key:
        return None
    
    try:
        file_extension = os.path.splitext(filename)[1].lower()
        
        # Try configured candidates in order so a retired model does not break uploads.
        document_model_candidates = get_model_candidates(
            primary_env="GEMINI_DOCUMENT_MODEL",
            candidates_env="GEMINI_DOCUMENT_MODEL_CANDIDATES",
        )
        
        evaluation_date_value = (current_date_for_evaluation or "").strip() or datetime.now().isoformat()
        profile_context_value = (student_profile_context or "").strip()
        related_docs_context_value = (related_documents_context or "").strip()
        if len(profile_context_value) > UPLOAD_VALIDATION_PROMPT_CONTEXT_CHARS:
            profile_context_value = (
                profile_context_value[:UPLOAD_VALIDATION_PROMPT_CONTEXT_CHARS]
                + "\n... [student profile context truncated]"
            )
        if len(related_docs_context_value) > UPLOAD_VALIDATION_PROMPT_CONTEXT_CHARS:
            related_docs_context_value = (
                related_docs_context_value[:UPLOAD_VALIDATION_PROMPT_CONTEXT_CHARS]
                + "\n... [related documents context truncated]"
            )

        cross_validation_block = f"""
ADDITIONAL CROSS-VALIDATION CONTEXT:
Use the following context to cross-check the uploaded document against the user's profile and previously uploaded documents.

=== ATTACHED STUDENT PROFILE SNAPSHOT ===
{profile_context_value or "Not available"}
=== END ATTACHED STUDENT PROFILE SNAPSHOT ===

=== ATTACHED PREVIOUS DOCUMENTS SNAPSHOT ===
{related_docs_context_value or "Not available"}
=== END ATTACHED PREVIOUS DOCUMENTS SNAPSHOT ===

CROSS-VALIDATION REQUIREMENTS (MANDATORY):
1. Compare this uploaded document with profile + previous documents for consistency.
2. Check identity consistency across documents:
   - Name, Date of Birth, passport/document numbers, country, issue/expiry dates.
3. Check study-plan consistency:
   - University name, intake term/year, and timeline against other available evidence.
4. If there is a material conflict, set "Document Validation" to "No".
5. Clearly state each detected inconsistency in "Message", and include structured details under "Cross Validation Flags".
6. If evidence is insufficient, do not invent facts; explicitly state uncertainty.
"""

        destination_code_value = str(destination_country_code or "US").strip().upper() or "US"
        destination_summary_value = (destination_summary or "").strip()
        destination_rules = _DESTINATION_TIMELINE_RULES.get(
            destination_code_value, _DESTINATION_TIMELINE_RULES["US"]
        )
        destination_line = (
            f"This student is applying for: {destination_summary_value}. Judge every document by THAT "
            "destination's immigration rules and terminology — do not apply another country's rules."
            if destination_summary_value else
            "Judge the document by the student's destination immigration rules."
        )

        timeline_rules_block = f"""
Current Date for Evaluation: {evaluation_date_value}
{destination_line}

STRICT DATE/TIMELINE COMPLIANCE RULES (MANDATORY):
1. Cross-reference all document dates against the Current Date for Evaluation.
2. Bank statements / financial liquid-funds proofs:
   - Unless the destination-specific rules below say otherwise, flag as invalid if the statement date is older than 6 months from the Current Date for Evaluation.
   - Include the detected age in the reason.
3. Passport:
   - Flag as invalid if passport expiry is less than 6 months from expected travel/program-start date.
   - If expected travel/program-start date is unavailable, compare expiry against Current Date for Evaluation and state that assumption explicitly.
4. University offer / admission / enrolment confirmations:
   - Flag as invalid if intake term, program start date, or reporting date is already in the past relative to Current Date for Evaluation.
5. Destination-specific rules for {destination_code_value}:
{destination_rules}
6. Other date-sensitive documents:
   - Apply the same timeline-compliance logic; if expiry/validity is past, mark invalid.
7. If any date check fails:
   - Set "Document Validation" to "No"
   - Put a clear failure explanation in "Message" (this is the review reason field shown to the user), citing the destination's own rule (e.g. UKVI's 28-day rule for the UK, consulate recency expectations for the US).
8. If the document does not contain enough date evidence, do NOT invent dates; mention the assumption/limitation clearly.
"""

        # Build validation prompt based on document type
        validation_prompt = ""
        if document_type:
            validation_prompt = f"""You are a document validation system. The user claims this document is a {document_type.upper()}.

TASK:
1. Carefully examine the document
2. Determine if it actually matches a {document_type.upper()}
3. If YES: Set "Document Validation" to "Yes" and extract all information
4. If NO: Set "Document Validation" to "No", identify what document type it actually is, and provide a helpful message asking the user to upload the correct document

{timeline_rules_block}
{cross_validation_block}

REQUIREMENTS:
- You MUST respond with ONLY valid JSON, no markdown, no code blocks, no explanations
- Start your response directly with {{ and end with }}
- Do NOT include ```json or ``` markers
- Do NOT include any text before or after the JSON

REQUIRED JSON FORMAT:
{{
    "Document Validation": "Yes" or "No",
    "Message": "If 'No': Explain what the document actually looks like (e.g., 'This does not look like your passport page, it looks like your resume. Please cross check and upload the right passport'). If 'Yes': 'Document validated successfully'",
    "Name": "extracted name or null",
    "Date of Birth": "extracted date of birth or null",
    "Document Number": "extracted document number/ID or null",
    "Expiration Date": "extracted expiration date or null",
    "Issue Date": "extracted issue date or null",
    "Country": "extracted country or null",
    "Other Information": "any other relevant extracted information or null",
    "Cross Validation Flags": [
        {{
            "field": "name/date/document_number/university/intake/timeline/other",
            "status": "match/conflict/unknown",
            "current_document_value": "value from current doc or null",
            "reference_value": "value from profile/other docs or null",
            "note": "short explanation"
        }}
    ]
}}

Remember: Output ONLY the JSON object, nothing else."""
        else:
            validation_prompt = f"""Extract all information from this document.

IMPORTANT DATE CONTEXT:
Use the following Current Date for Evaluation while extracting and validating date relevance.
Current Date for Evaluation: {evaluation_date_value}

For date-sensitive docs, explicitly check expiration and timeline compliance:
- Bank statements older than 6 months should be treated as invalid.
- Passport with less than 6 months remaining validity should be treated as invalid.
- I-20/Offer/Admission date in the past should be treated as invalid.
- For other visa docs, flag stale/expired dates as invalid.

{cross_validation_block}

REQUIREMENTS:
- You MUST respond with ONLY valid JSON, no markdown, no code blocks, no explanations
- Start your response directly with {{ and end with }}
- Do NOT include ```json or ``` markers
- Do NOT include any text before or after the JSON

REQUIRED JSON FORMAT:
{{
    "Document Validation": "Yes",
    "Message": "Document information extracted successfully",
    "Name": "extracted name or null",
    "Date of Birth": "extracted date of birth or null",
    "Document Number": "extracted document number/ID or null",
    "Expiration Date": "extracted expiration date or null",
    "Issue Date": "extracted issue date or null",
    "Country": "extracted country or null",
    "Other Information": "any other relevant extracted information or null",
    "Cross Validation Flags": [
        {{
            "field": "name/date/document_number/university/intake/timeline/other",
            "status": "match/conflict/unknown",
            "current_document_value": "value from current doc or null",
            "reference_value": "value from profile/other docs or null",
            "note": "short explanation"
        }}
    ]
}}

Remember: Output ONLY the JSON object, nothing else."""
        
        # Handle different file types
        if file_extension in SUPPORTED_IMAGE_TYPES:
            # For images, use vision model
            image = Image.open(io.BytesIO(file_contents))
            
            print("\n" + "="*80)
            print(f"🔵 GEMINI API CALL: validate_and_extract_document() - IMAGE")
            print(f"📄 File: {filename} ({file_extension})")
            print(f"📝 Document Type: {document_type or 'Not specified'}")
            print("-"*80)
            print("📤 SENDING PROMPT TO GEMINI:")
            print("-"*80)
            pass  # prompt content not logged (privacy)
            print("-"*80)
            print("⏳ Waiting for Gemini response...")
            
            if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                img_bytes = io.BytesIO()
                image.save(img_bytes, format='JPEG')
                img_bytes.seek(0)
                image_part = Part.from_data(img_bytes.read(), mime_type="image/jpeg")
                response = _generate_content_with_fallback(
                    document_model_candidates, [validation_prompt, image_part]
                )
            else:
                response = _generate_content_with_fallback(
                    document_model_candidates, [validation_prompt, image]
                )
            
            response_text = response.text.strip()
            
            print("✅ RECEIVED RESPONSE FROM GEMINI:")
            print("-"*80)
            pass  # response content not logged (privacy)
            print("="*80 + "\n")
        
        elif file_extension == ".pdf":
            # For PDFs
            import tempfile
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                tmp_file.write(file_contents)
                tmp_path = tmp_file.name
            
            try:
                print("\n" + "="*80)
                print(f"🔵 GEMINI API CALL: validate_and_extract_document() - PDF")
                print(f"📄 File: {filename}")
                print(f"📝 Document Type: {document_type or 'Not specified'}")
                print("-"*80)
                print("📤 SENDING PROMPT TO GEMINI:")
                print("-"*80)
                pass  # prompt content not logged (privacy)
                print("-"*80)
                print("⏳ Waiting for Gemini response...")
                
                if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                    with open(tmp_path, 'rb') as f:
                        pdf_data = f.read()
                    pdf_part = Part.from_data(pdf_data, mime_type="application/pdf")
                    response = _generate_content_with_fallback(
                        document_model_candidates, [validation_prompt, pdf_part]
                    )
                else:
                    pdf_file = genai.upload_file(
                        path=tmp_path,
                        mime_type="application/pdf"
                    )
                    import time
                    print("📤 Uploading PDF to Gemini...")
                    while pdf_file.state.name == "PROCESSING":
                        print("   ⏳ PDF still processing...")
                        time.sleep(2)
                        pdf_file = genai.get_file(pdf_file.name)
                    
                    if pdf_file.state.name == "FAILED":
                        raise Exception(f"File processing failed: {pdf_file.state}")
                    
                    print("✅ PDF uploaded, generating content...")
                    response = _generate_content_with_fallback(
                        document_model_candidates, [validation_prompt, pdf_file]
                    )
                    
                    try:
                        genai.delete_file(pdf_file.name)
                    except:
                        pass
                
                response_text = response.text.strip()
                
                print("✅ RECEIVED RESPONSE FROM GEMINI:")
                print("-"*80)
                pass  # response content not logged (privacy)
                print("="*80 + "\n")
            finally:
                try:
                    os.unlink(tmp_path)
                except:
                    pass
        
        elif file_extension == ".txt":
            text_content = file_contents.decode('utf-8', errors='ignore')
            prompt = validation_prompt + f"\n\nDocument content:\n{text_content[:50000]}"
            
            print("\n" + "="*80)
            print(f"🔵 GEMINI API CALL: validate_and_extract_document() - TEXT")
            print(f"📄 File: {filename}")
            print(f"📝 Document Type: {document_type or 'Not specified'}")
            print("-"*80)
            print("📤 SENDING PROMPT TO GEMINI:")
            print("-"*80)
            pass  # prompt content not logged (privacy)
            print("-"*80)
            print("⏳ Waiting for Gemini response...")
            
            response = _generate_content_with_fallback(document_model_candidates, prompt)
            response_text = response.text.strip()
            
            print("✅ RECEIVED RESPONSE FROM GEMINI:")
            print("-"*80)
            pass  # response content not logged (privacy)
            print("="*80 + "\n")
        
        else:
            # Try to process as image
            try:
                image = Image.open(io.BytesIO(file_contents))
                
                print("\n" + "="*80)
                print(f"🔵 GEMINI API CALL: validate_and_extract_document() - UNKNOWN TYPE (trying as image)")
                print(f"📄 File: {filename} ({file_extension})")
                print(f"📝 Document Type: {document_type or 'Not specified'}")
                print("-"*80)
                print("📤 SENDING PROMPT TO GEMINI:")
                print("-"*80)
                pass  # prompt content not logged (privacy)
                print("-"*80)
                print("⏳ Waiting for Gemini response...")
                
                if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                    img_bytes = io.BytesIO()
                    image.save(img_bytes, format='JPEG')
                    img_bytes.seek(0)
                    image_part = Part.from_data(img_bytes.read(), mime_type="image/jpeg")
                    response = _generate_content_with_fallback(
                        document_model_candidates, [validation_prompt, image_part]
                    )
                else:
                    response = _generate_content_with_fallback(
                        document_model_candidates, [validation_prompt, image]
                    )
                response_text = response.text.strip()
                
                print("✅ RECEIVED RESPONSE FROM GEMINI:")
                print("-"*80)
                pass  # response content not logged (privacy)
                print("="*80 + "\n")
            except:
                return None
        
        # Parse JSON response
        try:
            # Clean up response text - remove markdown code blocks if present
            response_text = response_text.strip()
            
            # Remove markdown code blocks
            if response_text.startswith("```json"):
                response_text = response_text[7:].strip()
            elif response_text.startswith("```"):
                response_text = response_text[3:].strip()
            
            if response_text.endswith("```"):
                response_text = response_text[:-3].strip()
            
            # Find first { and last } to extract JSON
            first_brace = response_text.find('{')
            last_brace = response_text.rfind('}')
            
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                response_text = response_text[first_brace:last_brace + 1]
            
            import json
            result = json.loads(response_text)
            
            # Ensure required fields exist. NEVER default a missing verdict to "Yes":
            # the AI is the sole validation gatekeeper, so a garbled/incomplete response
            # must land in "needs review"/"error" downstream (only an explicit "Yes"
            # counts as validated) — not show a green "Validated" badge.
            if "Document Validation" not in result:
                result["Document Validation"] = "Unknown"
                if "Message" not in result:
                    result["Message"] = ("The document was processed but Rilono AI did not return a "
                                         "clear validation verdict. Please verify this document manually.")
            if "Message" not in result:
                result["Message"] = "Document processed successfully"

            return result
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON response from Gemini: {str(e)}")
            # Privacy: do not log the response content.
            # Return a fallback response ("Unknown" verdict — see note above).
            return {
                "Document Validation": "Unknown",
                "Message": "Document processed but the validation response format was invalid. Please verify this document manually.",
                "Name": None,
                "Date of Birth": None,
                "Document Number": None,
                "Expiration Date": None,
                "Issue Date": None,
                "Country": None,
                "Other Information": response_text[:500] if response_text else None
            }
    
    except Exception as e:
        print(f"Error validating and extracting document with Gemini: {str(e)}")
        return None

def extract_text_from_document(file_contents: bytes, filename: str, mime_type: str) -> Optional[str]:
    """
    Extract main information from a document using Gemini AI.
    Returns extracted text as a string, or None if extraction fails.
    """
    # Check if we have authentication configured
    has_service_account = os.path.exists(SERVICE_ACCOUNT_PATH)
    has_valid_api_key = GEMINI_API_KEY and GEMINI_API_KEY.startswith("AIza")
    
    if not has_service_account and not has_valid_api_key:
        return None
    
    try:
        file_extension = os.path.splitext(filename)[1].lower()
        
        # Try configured candidates in order so a retired model does not break extraction.
        document_model_candidates = get_model_candidates(
            primary_env="GEMINI_DOCUMENT_MODEL",
            candidates_env="GEMINI_DOCUMENT_MODEL_CANDIDATES",
        )
        
        # Handle different file types
        if file_extension in SUPPORTED_IMAGE_TYPES:
            # For images, use vision model
            image = Image.open(io.BytesIO(file_contents))
            
            prompt = """Please extract and summarize the main information from this document image. 
            Include all important details such as:
            - Document type (passport, visa, transcript, certificate, etc.)
            - Names, dates, identification numbers
            - Key dates and expiration dates
            - Important numbers and codes
            - Any other relevant information
            
            Format the output as clear, structured text that captures all essential information from the document."""
            
            print("\n" + "="*80)
            print(f"🔵 GEMINI API CALL: extract_text_from_document() - IMAGE")
            print(f"📄 File: {filename}")
            print("-"*80)
            print("📤 SENDING PROMPT TO GEMINI:")
            print("-"*80)
            pass  # prompt content not logged (privacy)
            print("-"*80)
            print("⏳ Waiting for Gemini response...")
            
            if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                # Vertex AI format - convert image to bytes
                img_bytes = io.BytesIO()
                image.save(img_bytes, format='JPEG')
                img_bytes.seek(0)
                image_part = Part.from_data(img_bytes.read(), mime_type="image/jpeg")
                response = _generate_content_with_fallback(
                    document_model_candidates, [prompt, image_part]
                )
            else:
                # Standard API format
                response = _generate_content_with_fallback(
                    document_model_candidates, [prompt, image]
                )
            
            print("✅ RECEIVED RESPONSE FROM GEMINI:")
            print("-"*80)
            pass  # response content not logged (privacy)
            print("="*80 + "\n")
            
            return response.text
        
        elif file_extension == ".pdf":
            # For PDFs, we need to save temporarily and upload
            # Gemini requires file uploads for PDFs
            import tempfile
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                tmp_file.write(file_contents)
                tmp_path = tmp_file.name
            
            try:
                prompt = """Please extract and summarize the main information from this PDF document. 
                Include all important details such as:
                - Document type and purpose
                - Names, dates, identification numbers
                - Key dates and expiration dates
                - Important numbers, codes, and references
                - Academic information (if applicable): grades, courses, GPA, etc.
                - Any other relevant information
                
                Format the output as clear, structured text that captures all essential information from the document."""
                
                print("\n" + "="*80)
                print(f"🔵 GEMINI API CALL: extract_text_from_document() - PDF")
                print(f"📄 File: {filename}")
                print("-"*80)
                print("📤 SENDING PROMPT TO GEMINI:")
                print("-"*80)
                pass  # prompt content not logged (privacy)
                print("-"*80)
                print("⏳ Waiting for Gemini response...")
                
                if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                    # Vertex AI - read PDF directly
                    with open(tmp_path, 'rb') as f:
                        pdf_data = f.read()
                    pdf_part = Part.from_data(pdf_data, mime_type="application/pdf")
                    response = _generate_content_with_fallback(
                        document_model_candidates, [prompt, pdf_part]
                    )
                else:
                    # Standard API - upload file first
                    print("📤 Uploading PDF to Gemini...")
                    pdf_file = genai.upload_file(
                        path=tmp_path,
                        mime_type="application/pdf"
                    )
                    
                    # Wait for file to be processed
                    import time
                    while pdf_file.state.name == "PROCESSING":
                        print("   ⏳ PDF still processing...")
                        time.sleep(2)
                        pdf_file = genai.get_file(pdf_file.name)
                    
                    if pdf_file.state.name == "FAILED":
                        raise Exception(f"File processing failed: {pdf_file.state}")
                    
                    print("✅ PDF uploaded, generating content...")
                    response = _generate_content_with_fallback(
                        document_model_candidates, [prompt, pdf_file]
                    )
                    
                    # Clean up uploaded file
                    try:
                        genai.delete_file(pdf_file.name)
                    except:
                        pass
                
                print("✅ RECEIVED RESPONSE FROM GEMINI:")
                print("-"*80)
                pass  # response content not logged (privacy)
                print("="*80 + "\n")
                
                return response.text
            finally:
                # Clean up temporary file
                try:
                    os.unlink(tmp_path)
                except:
                    pass
        
        elif file_extension == ".txt":
            # For text files, read and summarize
            text_content = file_contents.decode('utf-8', errors='ignore')
            
            prompt = f"""Please extract and summarize the main information from this text document. 
            Include all important details such as:
            - Document type and purpose
            - Names, dates, identification numbers
            - Key dates and expiration dates
            - Important numbers, codes, and references
            - Any other relevant information
            
            Format the output as clear, structured text that captures all essential information.
            
            Document content:
            {text_content[:50000]}"""  # Limit to 50k chars to avoid token limits
            
            print("\n" + "="*80)
            print(f"🔵 GEMINI API CALL: extract_text_from_document() - TEXT")
            print(f"📄 File: {filename}")
            print("-"*80)
            print("📤 SENDING PROMPT TO GEMINI:")
            print("-"*80)
            pass  # prompt content not logged (privacy)
            print("-"*80)
            print("⏳ Waiting for Gemini response...")
            
            response = _generate_content_with_fallback(document_model_candidates, prompt)
            
            print("✅ RECEIVED RESPONSE FROM GEMINI:")
            print("-"*80)
            pass  # response content not logged (privacy)
            print("="*80 + "\n")
            
            return response.text
        
        else:
            # For other file types, try to process as image if possible
            try:
                image = Image.open(io.BytesIO(file_contents))
                prompt = """Please extract and summarize the main information from this document. 
                Include all important details such as:
                - Document type (passport, visa, transcript, certificate, etc.)
                - Names, dates, identification numbers
                - Key dates and expiration dates
                - Important numbers and codes
                - Any other relevant information
                
                Format the output as clear, structured text that captures all essential information from the document."""
                
                print("\n" + "="*80)
                print(f"🔵 GEMINI API CALL: extract_text_from_document() - UNKNOWN TYPE (trying as image)")
                print(f"📄 File: {filename} ({file_extension})")
                print("-"*80)
                print("📤 SENDING PROMPT TO GEMINI:")
                print("-"*80)
                pass  # prompt content not logged (privacy)
                print("-"*80)
                print("⏳ Waiting for Gemini response...")
                
                if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                    # Vertex AI format - convert image to bytes
                    img_bytes = io.BytesIO()
                    image.save(img_bytes, format='JPEG')
                    img_bytes.seek(0)
                    image_part = Part.from_data(img_bytes.read(), mime_type="image/jpeg")
                    response = _generate_content_with_fallback(
                        document_model_candidates, [prompt, image_part]
                    )
                else:
                    # Standard API format
                    response = _generate_content_with_fallback(
                        document_model_candidates, [prompt, image]
                    )
                
                print("✅ RECEIVED RESPONSE FROM GEMINI:")
                print("-"*80)
                pass  # response content not logged (privacy)
                print("="*80 + "\n")
                
                return response.text
            except:
                # If it's not an image, return None
                return None
    
    except Exception as e:
        print(f"Error extracting text from document with Gemini: {str(e)}")
        return None

RED_FLAG_PROMPT = """You are an expert study-visa document auditor for Rilono's supported destinations
(US, UK, Canada, Australia, Germany and future student-visa destinations). Inspect this document and
find "red flags" — concrete errors or risks that could cause a visa refusal (expired/stale dates,
name/DOB/passport-number mismatches, insufficient or unexplained funds, missing signatures/stamps,
wrong document for the claimed purpose, sponsor/financial gaps).

Respond with ONLY valid JSON (no markdown, no code fences), starting with {{ and ending with }}:
{{
  "summary": "one-sentence overall read of this document",
  "flags": [
    {{"title": "short label", "detail": "what is wrong and why it matters", "severity": "high|medium|low"}}
  ]
}}
Order flags most-severe first. If the document looks clean, return an empty "flags" list.
Current date for evaluation: {eval_date}"""


def scan_document_red_flags(file_contents: bytes, filename: str, mime_type: str) -> Optional[dict]:
    """
    Run a focused "red flag" audit over a single document for the B2C Visa Success Pass.
    Returns {"summary": str, "flags": [{"title","detail","severity"}]} or None if AI is
    unavailable. Usage is logged under the "red_flag_scan" source for B2C economics.
    """
    has_service_account = os.path.exists(SERVICE_ACCOUNT_PATH)
    has_valid_api_key = GEMINI_API_KEY and GEMINI_API_KEY.startswith("AIza")
    if not has_service_account and not has_valid_api_key:
        return None

    try:
        model_candidates = get_model_candidates(
            primary_env="GEMINI_DOCUMENT_MODEL",
            candidates_env="GEMINI_DOCUMENT_MODEL_CANDIDATES",
        )

        prompt = RED_FLAG_PROMPT.format(eval_date=datetime.now().date().isoformat())
        file_extension = os.path.splitext(filename)[1].lower()

        if file_extension in SUPPORTED_IMAGE_TYPES:
            image = Image.open(io.BytesIO(file_contents))
            if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                buf = io.BytesIO(); image.save(buf, format="JPEG"); buf.seek(0)
                response = _generate_content_with_fallback(
                    model_candidates,
                    [prompt, Part.from_data(buf.read(), mime_type="image/jpeg")],
                    usage_source="red_flag_scan",
                )
            else:
                response = _generate_content_with_fallback(
                    model_candidates, [prompt, image], usage_source="red_flag_scan"
                )
        elif file_extension == ".pdf":
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(file_contents); tmp_path = tmp.name
            try:
                if USE_VERTEX_AI and VERTEX_AI_AVAILABLE:
                    with open(tmp_path, "rb") as f:
                        response = _generate_content_with_fallback(
                            model_candidates,
                            [prompt, Part.from_data(f.read(), mime_type="application/pdf")],
                            usage_source="red_flag_scan",
                        )
                else:
                    import time
                    pdf_file = genai.upload_file(path=tmp_path, mime_type="application/pdf")
                    while pdf_file.state.name == "PROCESSING":
                        time.sleep(2); pdf_file = genai.get_file(pdf_file.name)
                    if pdf_file.state.name == "FAILED":
                        raise Exception("PDF processing failed")
                    response = _generate_content_with_fallback(
                        model_candidates,
                        [prompt, pdf_file],
                        usage_source="red_flag_scan",
                    )
                    try: genai.delete_file(pdf_file.name)
                    except Exception: pass
            finally:
                try: os.unlink(tmp_path)
                except Exception: pass
        else:
            text_content = file_contents.decode("utf-8", errors="ignore")
            response = _generate_content_with_fallback(
                model_candidates,
                prompt + f"\n\nDocument content:\n{text_content[:50000]}",
                usage_source="red_flag_scan",
            )

        import json
        raw = (response.text or "").strip()
        if raw.startswith("```json"): raw = raw[7:].strip()
        elif raw.startswith("```"): raw = raw[3:].strip()
        if raw.endswith("```"): raw = raw[:-3].strip()
        fb, lb = raw.find("{"), raw.rfind("}")
        if fb != -1 and lb != -1 and lb > fb:
            raw = raw[fb:lb + 1]
        data = json.loads(raw)
        flags = data.get("flags") if isinstance(data, dict) else None
        if not isinstance(flags, list):
            flags = []
        normalized = []
        for f in flags:
            if not isinstance(f, dict):
                continue
            normalized.append({
                "title": str(f.get("title") or "Issue").strip()[:140],
                "detail": str(f.get("detail") or "").strip()[:600],
                "severity": str(f.get("severity") or "medium").strip().lower(),
            })
        return {"summary": str((data or {}).get("summary") or "").strip()[:400], "flags": normalized}
    except Exception as e:
        print(f"Error running red-flag scan with Gemini: {str(e)}")
        return None


def create_extracted_text_file(extracted_text: str, original_filename: str) -> bytes:
    """
    Create a .txt file from extracted text.
    Returns the file contents as bytes.
    """
    if not extracted_text:
        return b""
    
    # Add header with original filename
    header = f"Extracted information from: {original_filename}\n"
    header += "=" * 80 + "\n\n"
    
    full_text = header + extracted_text
    return full_text.encode('utf-8')
