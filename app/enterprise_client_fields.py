"""Client INTAKE fields — the lead record a consultancy keeps on every client.

These are the generic, cross-destination facts a counselor captures the moment a lead
walks in: who they are, what they want to study, how strong the profile is, how it will
be funded, and where the lead came from. They live as real columns on EnterpriseClient
so they can be searched, filtered and reported on — unlike the per-stage case record
(enterprise_stage_fields.py), which is destination-specific and filled in later as the
case actually moves through the pipeline.

The option lists are defined ONCE here and shipped to the frontend inside the /catalog
payload, so the selects in the Add-client modal and the server-side validation can never
drift apart. Values stored in the DB are the option `key` (a stable slug); labels are
presentation only and may be reworded without a migration.
"""

from __future__ import annotations


def _opts(*pairs) -> list[dict]:
    return [{"key": key, "label": label} for key, label in pairs]


# ---------------------------------------------------------------------------
# Option lists, keyed by the EnterpriseClient column they populate
# ---------------------------------------------------------------------------
CLIENT_PROFILE_OPTIONS: dict[str, list[dict]] = {
    "gender": _opts(
        ("male", "Male"),
        ("female", "Female"),
        ("other", "Other"),
        ("undisclosed", "Prefer not to say"),
    ),
    # What level they intend to study at — drives eligibility, budget and the shortlist.
    "study_level": _opts(
        ("bachelors", "Bachelor's"),
        ("masters", "Master's"),
        ("mba", "MBA"),
        ("phd", "PhD / Doctorate"),
        ("pg_diploma", "PG Diploma"),
        ("diploma", "Diploma / Advanced Diploma"),
        ("foundation", "Foundation / Pathway"),
        ("certificate", "Certificate / Short course"),
        ("language", "Language / Pre-sessional English"),
    ),
    # The triage question: a lead holding their enrolment confirmation is a paying client
    # today, "just exploring" is a nurture-list entry. Captured by staff, and advanced for
    # them when the case is moved to a university stage — see DERIVED_PROFILE_FIELDS below.
    # Destination-neutral wording on purpose — this field sits on the Add-client form, which
    # is filled in before (or while) the destination is chosen, and it is asked identically
    # of all ten destinations. The artifact is an I-20 in the US, a CAS in the UK, an LOA in
    # Canada, a CoE in Australia, a Zulassungsbescheid in Germany, an accord préalable in
    # France, a Carta de Admisión in Spain, a Bewijs van Toelating in the Netherlands and an
    # offer from a licensed institution in the UAE; naming only the first three read as a
    # bug to everyone else. The per-destination detail is captured at the documents stage.
    "admission_stage": _opts(
        ("exploring", "Just exploring"),
        ("shortlisting", "Shortlisting universities"),
        ("applied", "Applications submitted"),
        ("admitted", "Admit received, offer not accepted"),
        ("offer_accepted", "Offer accepted — enrolment doc pending"),
        ("doc_in_hand", "Enrolment confirmation in hand"),
        ("deferred", "Deferred to a later intake"),
    ),
    # Highest-signal risk field on the intake form. A refusal discovered after the fee is
    # collected is the single most common refund dispute in this industry.
    "prior_refusal_history": _opts(
        ("none", "No prior application"),
        ("prior_no_refusal", "Prior application — no refusal"),
        ("refused_this_destination", "Refused by this destination"),
        ("refused_other_country", "Refused by another country"),
        ("overstay_violation", "Overstay / status violation / removal"),
        ("other_adverse", "Other adverse history"),
        ("not_confirmed", "Not yet confirmed"),
    ),
    "lead_source": _opts(
        ("walk_in", "Walk-in"),
        ("referral", "Referral (client / friend)"),
        ("website", "Website / web form"),
        ("whatsapp", "WhatsApp"),
        ("social", "Instagram / Facebook"),
        ("google_ads", "Google Ads / search"),
        ("education_fair", "Education fair / seminar"),
        ("partner_agent", "Partner / sub-agent"),
        ("institution_referral", "University / institution referral"),
        ("cold_call", "Cold call / database"),
        ("repeat_client", "Existing client (repeat)"),
        ("other", "Other"),
    ),
    "highest_qualification": _opts(
        ("class_10", "Class 10"),
        ("class_12", "Class 12 / Intermediate"),
        ("diploma_3yr", "Diploma (3-year)"),
        ("bachelors_3yr", "Bachelor's — 3 year"),
        ("bachelors_4yr", "Bachelor's — 4 year"),
        ("masters", "Master's"),
        ("phd", "PhD"),
        ("professional", "Professional (CA / CS / MBBS…)"),
    ),
    "qualification_scale": _opts(
        ("percentage", "Percentage (out of 100)"),
        ("cgpa_10", "CGPA out of 10"),
        ("cgpa_4", "CGPA out of 4"),
        ("gpa_4", "GPA out of 4"),
        ("grade", "Grade / Division"),
    ),
    "work_experience_band": _opts(
        ("none", "None"),
        ("lt_1", "Less than 1 year"),
        ("1_2", "1–2 years"),
        ("2_5", "2–5 years"),
        ("5_10", "5–10 years"),
        ("gt_10", "10+ years"),
    ),
    "english_test_status": _opts(
        ("score_available", "Score available"),
        ("booked", "Booked — awaiting test"),
        ("result_awaited", "Result awaited"),
        ("preparing", "Preparing"),
        ("not_taken", "Not taken"),
        ("exempt_moi", "Exempt (MOI letter)"),
        ("exempt_provider", "Exempt (provider assessed)"),
        ("not_required", "Not required for this route"),
    ),
    "english_test_type": _opts(
        ("ielts_academic", "IELTS Academic"),
        ("ielts_ukvi", "IELTS for UKVI"),
        ("ielts_general", "IELTS General"),
        ("toefl_ibt", "TOEFL iBT"),
        ("pte_academic", "PTE Academic"),
        ("duolingo", "Duolingo (DET)"),
        ("celpip", "CELPIP"),
        ("tef_tcf", "TEF / TCF (French)"),
        ("cambridge", "Cambridge C1 / C2"),
        ("oet", "OET"),
        ("languagecert", "LanguageCert"),
        ("other", "Other"),
    ),
    "aptitude_test_type": _opts(
        ("none", "Not required / not taken"),
        ("gre", "GRE"),
        ("gmat", "GMAT"),
        ("sat", "SAT"),
        ("act", "ACT"),
        ("other", "Other"),
    ),
    # A band is answerable on a first phone call where an exact figure is not, and it
    # separates a Germany/Ireland lead from a US-private-university lead immediately.
    "budget_band": _opts(
        ("under_10l", "Under ₹10 L / year"),
        ("10_15l", "₹10–15 L / year"),
        ("15_25l", "₹15–25 L / year"),
        ("25_40l", "₹25–40 L / year"),
        ("above_40l", "₹40 L+ / year"),
        ("not_sure", "Not sure yet"),
    ),
    "funding_source": _opts(
        ("self_family", "Self / family savings"),
        ("loan_planning", "Education loan — exploring"),
        ("loan_applied", "Education loan — applied"),
        ("loan_sanctioned", "Education loan — sanctioned"),
        ("scholarship", "Scholarship / assistantship"),
        ("sponsor_relative", "Sponsor (relative)"),
        ("employer", "Employer sponsored"),
        ("mixed", "Mixed"),
    ),
    "guardian_relation": _opts(
        ("father", "Father"),
        ("mother", "Mother"),
        ("guardian", "Guardian"),
        ("spouse", "Spouse"),
        ("sibling", "Sibling"),
        ("other", "Other"),
    ),
}

# Promotional-contact opt-in. Legally distinct from the DPA processing consent: India's
# DPDP Act needs purpose-specific consent and TRAI governs promotional calls/SMS, so this
# is per-channel, unchecked by default, and timestamped when it is first given.
MARKETING_CONSENT_CHANNELS: list[dict] = _opts(
    ("whatsapp", "WhatsApp"),
    ("sms", "SMS"),
    ("email", "Email"),
    ("phone", "Phone calls"),
)
_MARKETING_CHANNEL_KEYS = {item["key"] for item in MARKETING_CONSENT_CHANNELS}

# Free-text suggestions (datalist). Not a closed list — anything may be typed.
CITY_SUGGESTIONS: list[str] = [
    "Ahmedabad", "Bengaluru", "Chandigarh", "Chennai", "Coimbatore", "Delhi NCR",
    "Hyderabad", "Indore", "Jaipur", "Kochi", "Kolkata", "Kozhikode", "Lucknow",
    "Ludhiana", "Mumbai", "Nagpur", "Patna", "Pune", "Rajkot", "Surat",
    "Thiruvananthapuram", "Vadodara", "Vijayawada", "Visakhapatnam",
]
FIELD_OF_STUDY_SUGGESTIONS: list[str] = [
    "Computer Science / IT", "Data Science & AI", "Engineering (other)",
    "Business & Management", "Finance & Accounting", "Health, Nursing & Allied",
    "Hospitality & Tourism", "Law", "Arts, Design & Media",
    "Agriculture & Life Sciences", "Social Sciences & Education", "Undecided",
]

CLIENT_PROFILE_OPTION_KEYS: dict[str, set[str]] = {
    field: {item["key"] for item in options}
    for field, options in CLIENT_PROFILE_OPTIONS.items()
}

# ---------------------------------------------------------------------------
# Profile fields the pipeline also writes
# ---------------------------------------------------------------------------
# `admission_stage` describes the university phase of a case, which is also a set of PIPELINE
# stages (shortlisting / applications_sent / offer_accepted). Moving the case to one of those
# is a statement that the phase was reached, so a stage CHANGE advances this column too
# (routers/enterprise._apply_status_change) and the counselor is not asked the same thing
# twice. It stays a captured field, though: it is the only place a walk-in who already holds
# an admit can be recorded, months before their visa case opens.
#
# The values listed against a field are the states no pipeline stage implies. They are set by
# hand and derivation must leave them alone. `deferred` is that state — a case parked for a
# later intake sits at whatever stage it had reached, so no stage can mean it.
DERIVED_PROFILE_FIELDS: dict[str, set[str]] = {
    "admission_stage": {"deferred"},
}

# A typo here would make a manual-only value overwritable, which does not show up as an
# error at runtime.
for _field, _manual_keys in DERIVED_PROFILE_FIELDS.items():
    if _field not in CLIENT_PROFILE_OPTION_KEYS:
        raise ValueError(f"DERIVED_PROFILE_FIELDS: '{_field}' is not a client profile field.")
    _unknown = _manual_keys - CLIENT_PROFILE_OPTION_KEYS[_field]
    if _unknown:
        raise ValueError(f"DERIVED_PROFILE_FIELDS['{_field}']: unknown option(s) {sorted(_unknown)}.")


def is_manual_choice(field: str, value) -> bool:
    """Whether `value` is one of a field's manual-only keys — the values derivation must
    leave alone because no source state implies them."""
    raw = ("" if value is None else str(value)).strip()
    return bool(raw) and raw in DERIVED_PROFILE_FIELDS.get(field, set())


def normalize_choice(field: str, value) -> str | None:
    """Validate a select value against its option list. Returns the stored key, or None
    for an empty value. Raises ValueError if the value isn't in the catalog."""
    raw = ("" if value is None else str(value)).strip()
    if not raw:
        return None
    allowed = CLIENT_PROFILE_OPTION_KEYS.get(field)
    if allowed is None:
        return raw
    if raw not in allowed:
        raise ValueError(f"'{raw}' is not a valid value for {field.replace('_', ' ')}.")
    return raw


def choice_label(field: str, value) -> str | None:
    """Human label for a stored key (falls back to the raw value)."""
    raw = ("" if value is None else str(value)).strip()
    if not raw:
        return None
    for item in CLIENT_PROFILE_OPTIONS.get(field, []):
        if item["key"] == raw:
            return item["label"]
    return raw


def normalize_marketing_channels(value) -> str | None:
    """Accepts a list or comma string of channel keys; returns a canonical comma string."""
    if value is None:
        return None
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        raise ValueError("Marketing consent channels must be a list or comma-separated string.")
    picked = []
    for part in parts:
        key = str(part or "").strip().lower()
        if not key:
            continue
        if key not in _MARKETING_CHANNEL_KEYS:
            raise ValueError(f"'{key}' is not a valid contact channel.")
        if key not in picked:
            picked.append(key)
    if not picked:
        return None
    # Stable order so the stored string is comparable.
    order = [item["key"] for item in MARKETING_CONSENT_CHANNELS]
    picked.sort(key=order.index)
    return ",".join(picked)


def marketing_channel_labels(value) -> list[str]:
    keys = [k.strip() for k in str(value or "").split(",") if k.strip()]
    by_key = {item["key"]: item["label"] for item in MARKETING_CONSENT_CHANNELS}
    return [by_key.get(k, k) for k in keys]


# ---------------------------------------------------------------------------
# Migration off the retired `new_lead` stage fields
# ---------------------------------------------------------------------------
# Six lead-qualification questions used to live in the per-stage case record, where they
# were destination-specific, unsearchable, and only reachable after the client had already
# been created. They are columns above now, and the stage catalog no longer offers them
# (enterprise_catalog.RETIRED_STAGE_FIELDS) so nobody is asked the same question twice.
#
# This map moves what orgs already recorded into the new columns. The stage record stored
# display LABELS, and each destination relabelled the question its own way, so every
# variant that was ever offered is listed here. A value we can't map (DE recorded prior
# refusals as free text) goes to `fallback` — and in every case the original stage_data
# JSON is left untouched, so nothing is destroyed by a mapping miss.
RETIRED_STAGE_FIELD_BACKFILL: dict[str, dict] = {
    "enquiry_source": {
        "fallback": "lead_source_detail",
        "values": {
            "Walk-in": {"lead_source": "walk_in"},
            "Referral": {"lead_source": "referral"},
            "Website / Web form": {"lead_source": "website"},
            "WhatsApp": {"lead_source": "whatsapp"},
            "Instagram / Facebook": {"lead_source": "social"},
            "Google Ads": {"lead_source": "google_ads"},
            "Education fair": {"lead_source": "education_fair"},
            "Partner agent": {"lead_source": "partner_agent"},
            "Institution / University referral": {"lead_source": "institution_referral"},
            "Cold call": {"lead_source": "cold_call"},
            "Other": {"lead_source": "other"},
        },
    },
    "prior_refusal_history": {
        "fallback": "prior_refusal_notes",
        "values": {
            # Shared wording.
            "No prior application": {"prior_refusal_history": "none"},
            "Prior application — no refusal": {"prior_refusal_history": "prior_no_refusal"},
            "Refused by this destination": {"prior_refusal_history": "refused_this_destination"},
            "Refused by another country": {"prior_refusal_history": "refused_other_country"},
            "Overstay / status violation / removal": {"prior_refusal_history": "overstay_violation"},
            "Other adverse history": {"prior_refusal_history": "other_adverse"},
            "Not yet confirmed": {"prior_refusal_history": "not_confirmed"},
            # US wording.
            "No prior US visa": {"prior_refusal_history": "none"},
            "Previously issued, no refusal": {"prior_refusal_history": "prior_no_refusal"},
            "Previously refused (214(b))": {"prior_refusal_history": "refused_this_destination"},
            "Previously refused (other ground)": {"prior_refusal_history": "refused_this_destination"},
            "Prior overstay / status violation": {"prior_refusal_history": "overstay_violation"},
            "Not disclosed yet": {"prior_refusal_history": "not_confirmed"},
            # UK wording.
            "None": {"prior_refusal_history": "none"},
            "Previous UK refusal": {"prior_refusal_history": "refused_this_destination"},
            "Previous overstay / removal": {"prior_refusal_history": "overstay_violation"},
            # CA wording.
            "Yes — study permit refused": {"prior_refusal_history": "refused_this_destination"},
            "Yes — visitor visa refused": {"prior_refusal_history": "refused_this_destination"},
            "Yes — work permit refused": {"prior_refusal_history": "refused_this_destination"},
            "Yes — other refusal": {"prior_refusal_history": "other_adverse"},
            "Unknown": {"prior_refusal_history": "not_confirmed"},
            # AU wording.
            "Australia — refused": {"prior_refusal_history": "refused_this_destination"},
            "Australia — cancelled": {"prior_refusal_history": "other_adverse"},
            "Other country — refused": {"prior_refusal_history": "refused_other_country"},
            "Unsure": {"prior_refusal_history": "not_confirmed"},
        },
    },
    # NB: these keys are the literal strings already stored in stage_data by the retired US
    # stage field — they are match targets for migration, not display copy, so they keep the
    # old I-20 wording even though the option labels above are now destination-neutral.
    "admission_stage": {
        "fallback": None,
        "values": {
            "Exploring / shortlisting universities": {"admission_stage": "shortlisting"},
            "Applications submitted": {"admission_stage": "applied"},
            "Admit received, I-20 not issued": {"admission_stage": "admitted"},
            "I-20 received": {"admission_stage": "doc_in_hand"},
            "Deferred to later intake": {"admission_stage": "deferred"},
        },
    },
    "funding_source": {
        "fallback": None,
        "values": {
            "Self / family savings": {"funding_source": "self_family"},
            "Education loan (sanctioned)": {"funding_source": "loan_sanctioned"},
            "Education loan (applied)": {"funding_source": "loan_applied"},
            "Assistantship / scholarship": {"funding_source": "scholarship"},
            "Sponsor (relative)": {"funding_source": "sponsor_relative"},
            "Mixed": {"funding_source": "mixed"},
        },
    },
    # UK / AU wording — status only.
    "english_test_status": {
        "fallback": None,
        "values": {
            "IELTS for UKVI held": {"english_test_status": "score_available", "english_test_type": "ielts_ukvi"},
            "Other approved SELT held": {"english_test_status": "score_available"},
            "Test booked": {"english_test_status": "booked"},
            "Not yet taken": {"english_test_status": "not_taken"},
            "Exempt / sponsor-assessed": {"english_test_status": "exempt_provider"},
            "Not taken": {"english_test_status": "not_taken"},
            "Booked": {"english_test_status": "booked"},
            "Result available": {"english_test_status": "score_available"},
            "Exempt (provider assessed)": {"english_test_status": "exempt_provider"},
            "Exempt (prior study in English)": {"english_test_status": "exempt_moi"},
        },
    },
    # CA wording — the only destination that asked this generically.
    "study_level": {
        "fallback": None,
        "values": {
            "Certificate": {"study_level": "certificate"},
            "Diploma": {"study_level": "diploma"},
            "Advanced Diploma": {"study_level": "diploma"},
            "Bachelor's Degree": {"study_level": "bachelors"},
            "Post-Graduate Diploma (PG Diploma)": {"study_level": "pg_diploma"},
            "Master's Degree": {"study_level": "masters"},
            "PhD": {"study_level": "phd"},
        },
    },
    # CA wording — one control that carried both the status and the test taken.
    "language_test_status": {
        "fallback": None,
        "values": {
            "Not booked": {"english_test_status": "not_taken"},
            "Booked — awaiting date": {"english_test_status": "booked"},
            "Result awaited": {"english_test_status": "result_awaited"},
            "IELTS Academic — result available": {"english_test_status": "score_available", "english_test_type": "ielts_academic"},
            "IELTS General — result available": {"english_test_status": "score_available", "english_test_type": "ielts_general"},
            "PTE Academic — result available": {"english_test_status": "score_available", "english_test_type": "pte_academic"},
            "TOEFL iBT — result available": {"english_test_status": "score_available", "english_test_type": "toefl_ibt"},
            "CELPIP — result available": {"english_test_status": "score_available", "english_test_type": "celpip"},
            "TEF / TCF (French) — result available": {"english_test_status": "score_available", "english_test_type": "tef_tcf"},
            "Exempt / not required": {"english_test_status": "not_required"},
        },
    },
}
