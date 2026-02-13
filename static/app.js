const API_BASE = '';
const COOKIE_AUTH_SENTINEL = '__cookie_session__';
let currentUser = null;
let authToken = null;
let currentSubscription = null;
let turnstileSiteKey = null;
let turnstileWidgetIds = {
    login: null,
    register: null
};
let newsRequestInFlight = false;
let visaInterviewRequestInFlight = false;
let visaInterviewFiltersInitialized = false;
let documentUploadInProgress = false;
let documentUploadStatusTimer = null;
let proUpgradeInFlight = false;
let checkoutLaunchResolver = null;
let currentVisaSubTab = 'prep';
let documentTypeDropdownController = null;
const PRO_UPGRADE_ENABLED = true;
const PUBLIC_APP_ORIGIN = 'https://rilono.com';
const LEGAL_LAST_UPDATED = {
    about: 'February 12, 2026',
    privacy: 'February 12, 2026',
    terms: 'February 12, 2026',
    refund: 'February 12, 2026',
    delivery: 'February 12, 2026'
};

// Notification System
let notifications = JSON.parse(localStorage.getItem('notifications') || '[]');
let notificationDropdownOpen = false;

const PRICING_BASE_USD = {
    free: 0,
    pro: 19
};
const PRO_PRICE_INR = 699;

const nativeFetch = window.fetch.bind(window);
window.fetch = function secureFetch(input, init = {}) {
    const nextInit = { ...init };
    const headers = new Headers(nextInit.headers || {});
    const authHeader = headers.get('Authorization');
    if (
        authHeader === `Bearer ${COOKIE_AUTH_SENTINEL}` ||
        authHeader === 'Bearer null' ||
        authHeader === 'Bearer undefined'
    ) {
        headers.delete('Authorization');
    }
    nextInit.headers = headers;
    if (nextInit.credentials === undefined) {
        nextInit.credentials = 'same-origin';
    }
    return nativeFetch(input, nextInit);
};

const PRICING_COUNTRY_CONFIG = {
    US: { country: 'United States', currency: 'USD' },
    IN: { country: 'India', currency: 'INR' },
    GB: { country: 'United Kingdom', currency: 'GBP' },
    CA: { country: 'Canada', currency: 'CAD' },
    AU: { country: 'Australia', currency: 'AUD' },
    DE: { country: 'Germany', currency: 'EUR' },
    AE: { country: 'United Arab Emirates', currency: 'AED' },
    SG: { country: 'Singapore', currency: 'SGD' },
    JP: { country: 'Japan', currency: 'JPY' }
};

const VISA_INTERVIEW_CONSULATE_MAP = {
    India: ['New Delhi', 'Mumbai', 'Chennai', 'Hyderabad', 'Kolkata'],
    'United Kingdom': ['London', 'Belfast'],
    Canada: ['Ottawa', 'Toronto', 'Vancouver', 'Montreal', 'Calgary', 'Halifax', 'Quebec City'],
    Australia: ['Sydney', 'Melbourne', 'Perth'],
    Germany: ['Berlin', 'Frankfurt', 'Munich'],
    'United Arab Emirates': ['Abu Dhabi', 'Dubai'],
    Singapore: ['Singapore'],
    Japan: ['Tokyo', 'Osaka / Kobe', 'Naha', 'Sapporo', 'Fukuoka']
};

const FALLBACK_JOURNEY_STAGES = [
    {
        stage: 1,
        name: 'Getting Started',
        emoji: '📝',
        description: 'Build your profile with core academic and test documents.',
        next_step: 'Upload and validate your starter document set',
        required_docs: []
    },
    {
        stage: 2,
        name: 'Admission Received',
        emoji: '🎓',
        description: 'University admission confirmed!',
        next_step: 'Upload admission proof and one financial proof document',
        required_docs: ['university-admission-letter', 'bank-statement']
    },
    {
        stage: 3,
        name: 'I-20 Received',
        emoji: '📘',
        description: 'Upload and validate your signed Form I-20.',
        next_step: 'Complete your DS-160 application online',
        required_docs: ['form-i20-signed']
    },
    {
        stage: 4,
        name: 'DS-160 Filed',
        emoji: '📋',
        description: 'Upload and validate your full DS-160 application and 2x2 photograph.',
        next_step: 'Pay your SEVIS I-901 fee and visa fee',
        required_docs: ['ds-160-application', 'photograph-2x2']
    },
    {
        stage: 5,
        name: 'Fees Paid',
        emoji: '💳',
        description: 'SEVIS payment is mandatory. Other fee/appointment confirmations are optional.',
        next_step: 'Book interview slot and upload interview documents',
        required_docs: ['i901-sevis-fee-confirmation']
    },
    {
        stage: 6,
        name: 'Visa Stage',
        emoji: '🛂',
        description: 'Prepare your visa interview packet and supporting documents.',
        next_step: 'Review final interview checklist and confidence prep',
        required_docs: ['us-visa-appointment-letter', 'stamped-f1-visa']
    },
    {
        stage: 7,
        name: 'Ready to Fly!',
        emoji: '✈️',
        description: 'Interview scheduled! All documents ready.',
        next_step: 'You\'re all set! Good luck with your visa interview!',
        required_docs: ['immunization-vaccination-records']
    }
];

const FALLBACK_DOCUMENT_TYPES = [
    { value: 'passport', label: 'Passport', sort_order: 10, is_active: true, is_required: true, journey_stage: 1, stage_gate_required: true, stage_gate_requires_validation: true, stage_gate_group: null },
    { value: 'high-school-transcripts', label: 'High School Transcripts', sort_order: 20, is_active: true, is_required: false, journey_stage: 1, stage_gate_required: false, stage_gate_requires_validation: false, stage_gate_group: null },
    { value: 'bachelors-transcript', label: 'Bachelors Transcript (Optional)', sort_order: 30, is_active: true, is_required: false, journey_stage: 1, stage_gate_required: false, stage_gate_requires_validation: false, stage_gate_group: null },
    { value: 'masters-transcript', label: 'Master\'s Transcript (Optional)', sort_order: 40, is_active: true, is_required: false, journey_stage: 1, stage_gate_required: false, stage_gate_requires_validation: false, stage_gate_group: null },
    { value: 'other-school-college-degree-certificates', label: 'Other School/College/Degree Certificates', sort_order: 50, is_active: true, is_required: false, journey_stage: 1, stage_gate_required: false, stage_gate_requires_validation: false, stage_gate_group: null },
    { value: 'standardized-test-scores', label: 'Standardized Test Scores (TOEFL/IELTS/Duolingo)', sort_order: 60, is_active: true, is_required: true, journey_stage: 1, stage_gate_required: true, stage_gate_requires_validation: true, stage_gate_group: null },
    { value: 'standardized-test-scores-gre-gmat', label: 'Standardized Test Scores (GRE/GMAT)', sort_order: 70, is_active: true, is_required: false, journey_stage: 1, stage_gate_required: false, stage_gate_requires_validation: false, stage_gate_group: null },
    { value: 'statement-of-purpose-lors', label: 'Statement of Purpose (SOP) & LORs', sort_order: 80, is_active: true, is_required: false, journey_stage: 1, stage_gate_required: false, stage_gate_requires_validation: false, stage_gate_group: null },
    { value: 'resume', label: 'Resume/CV', sort_order: 90, is_active: true, is_required: true, journey_stage: 1, stage_gate_required: true, stage_gate_requires_validation: true, stage_gate_group: null },
    { value: 'university-admission-letter', label: 'University Admission Letter', sort_order: 100, is_active: true, is_required: true, journey_stage: 2, stage_gate_required: true, stage_gate_requires_validation: true, stage_gate_group: 'admission_proof' },
    { value: 'university-offer-letter', label: 'University Offer Letter', sort_order: 101, is_active: true, is_required: false, journey_stage: 2, stage_gate_required: true, stage_gate_requires_validation: true, stage_gate_group: 'admission_proof' },
    { value: 'bank-statement', label: 'Bank Statement', sort_order: 102, is_active: true, is_required: true, journey_stage: 2, stage_gate_required: true, stage_gate_requires_validation: true, stage_gate_group: 'financial_proof' },
    { value: 'bank-balance-certificate', label: 'Bank balance certificate', sort_order: 103, is_active: true, is_required: false, journey_stage: 2, stage_gate_required: true, stage_gate_requires_validation: true, stage_gate_group: 'financial_proof' },
    { value: 'loan-approval-letter', label: 'Loan approval letter (if applicable)', sort_order: 104, is_active: true, is_required: false, journey_stage: 2, stage_gate_required: true, stage_gate_requires_validation: true, stage_gate_group: 'financial_proof' },
    { value: 'loan-sanction-letter', label: 'Loan Sanction Letter', sort_order: 105, is_active: true, is_required: false, journey_stage: 2, stage_gate_required: true, stage_gate_requires_validation: true, stage_gate_group: 'financial_proof' },
    { value: 'provisional-certificates', label: 'Provisional certificates', sort_order: 130, is_active: true, is_required: false, journey_stage: 3, stage_gate_required: false, stage_gate_requires_validation: false, stage_gate_group: null },
    { value: 'form-i20-signed', label: 'Form I-20 (Signed)', sort_order: 140, is_active: true, is_required: true, journey_stage: 3, stage_gate_required: true, stage_gate_requires_validation: true, stage_gate_group: null },
    { value: 'previous-i20s', label: 'Previous I-20\'s', sort_order: 150, is_active: true, is_required: false, journey_stage: 3, stage_gate_required: false, stage_gate_requires_validation: false, stage_gate_group: null },
    { value: 'ds-160-confirmation', label: 'DS-160 Confirmation Page', sort_order: 160, is_active: true, is_required: false, journey_stage: 4, stage_gate_required: false, stage_gate_requires_validation: false, stage_gate_group: null },
    { value: 'ds-160-application', label: 'DS-160 Application (Full Application)', sort_order: 170, is_active: true, is_required: true, journey_stage: 4, stage_gate_required: true, stage_gate_requires_validation: true, stage_gate_group: null },
    { value: 'travel-history-documents', label: 'Travel History Documents', sort_order: 175, is_active: true, is_required: false, journey_stage: 4, stage_gate_required: false, stage_gate_requires_validation: false, stage_gate_group: null },
    { value: 'i901-sevis-fee-confirmation', label: 'SEVIS I-901 Fee Receipt', sort_order: 180, is_active: true, is_required: true, journey_stage: 5, stage_gate_required: true, stage_gate_requires_validation: true, stage_gate_group: null },
    { value: 'visa-fee-receipt', label: 'Visa Application (MRV) Fee Receipts', sort_order: 190, is_active: true, is_required: false, journey_stage: 5, stage_gate_required: false, stage_gate_requires_validation: false, stage_gate_group: null },
    { value: 'biometric-appointment-confirmation', label: 'Biometric Appointment Confirmation', sort_order: 191, is_active: true, is_required: false, journey_stage: 5, stage_gate_required: false, stage_gate_requires_validation: false, stage_gate_group: null },
    { value: 'consular-interview-confirmation', label: 'Consular Interview Confirmation', sort_order: 192, is_active: true, is_required: false, journey_stage: 5, stage_gate_required: false, stage_gate_requires_validation: false, stage_gate_group: null },
    { value: 'affidavit-of-support', label: 'Affidavit of Support (from parents/sponsors)', sort_order: 210, is_active: true, is_required: false, journey_stage: 6, stage_gate_required: false, stage_gate_requires_validation: false, stage_gate_group: null },
    { value: 'sponsor-income-proof', label: 'Sponsor\'s income proof (salary slips, IT returns)', sort_order: 220, is_active: true, is_required: false, journey_stage: 6, stage_gate_required: false, stage_gate_requires_validation: false, stage_gate_group: null },
    { value: 'ca-statement', label: 'CA Statement (summary of assets)', sort_order: 225, is_active: true, is_required: false, journey_stage: 6, stage_gate_required: false, stage_gate_requires_validation: false, stage_gate_group: null },
    { value: 'salary-slips', label: 'Salary slips (last 3-6 months)', sort_order: 230, is_active: true, is_required: false, journey_stage: 6, stage_gate_required: false, stage_gate_requires_validation: false, stage_gate_group: null },
    { value: 'us-visa-appointment-letter', label: 'US Visa Appointment Letter', sort_order: 240, is_active: true, is_required: true, journey_stage: 6, stage_gate_required: true, stage_gate_requires_validation: true, stage_gate_group: null },
    { value: 'stamped-f1-visa', label: 'Stamped F-1 Visa', sort_order: 245, is_active: true, is_required: true, journey_stage: 6, stage_gate_required: true, stage_gate_requires_validation: true, stage_gate_group: null },
    { value: 'photograph-2x2', label: 'Photograph (2x2 Inches)', sort_order: 250, is_active: true, is_required: true, journey_stage: 4, stage_gate_required: true, stage_gate_requires_validation: true, stage_gate_group: null },
    { value: 'experience-letters', label: 'Work Experience Letters', sort_order: 280, is_active: true, is_required: false, journey_stage: 6, stage_gate_required: false, stage_gate_requires_validation: false, stage_gate_group: null },
    { value: 'immunization-vaccination-records', label: 'Immunization/Vaccination Records', sort_order: 290, is_active: true, is_required: true, journey_stage: 7, stage_gate_required: true, stage_gate_requires_validation: true, stage_gate_group: null }
];

let documentTypeCatalog = [];
let requiredDocumentTypeValues = [];
let journeyStageCatalog = [];
let documentTypeLabelByValue = {};

const VISA_PREP_INTERVIEW_INSTRUCTION = `You are an F-1 visa interview coach for a student.
Rules:
- Ask one question at a time.
- After every student answer, provide short coaching with this exact structure:
  1) Feedback: what was strong/weak
  2) Improve: a better sample answer (2-4 lines)
  3) Next Question: ask the next VO-style question
- Focus on clarity, confidence, university/program fit, finances, ties to home country, and post-study intent.
- Keep each turn concise and practical.`;

const VISA_MOCK_INTERVIEW_INSTRUCTION = `You are a U.S. Visa Officer conducting a realistic F-1 interview simulation.
Rules:
- Stay strictly in Visa Officer role.
- Ask one question at a time.
- Do NOT provide coaching, feedback, scores, or suggestions during the interview.
- Keep responses concise and interview-like.
- If answer is vague, ask a direct follow-up question.
- When you decide the interview is complete, include the exact token INTERVIEW_COMPLETE in your response once (preferably at the end).`;

const VISA_MOCK_REPORT_INSTRUCTION = `You are evaluating a completed F-1 visa mock interview transcript.
Generate a concise final report in plain text with these sections:
1) Approval Probability: X%
2) Rejection Probability: Y%
3) Decision Drivers (3-5 bullets)
4) Strengths (3 bullets)
5) Risk Areas (3 bullets)
6) Top Improvements Before Real Interview (3 actionable bullets)
Make probabilities realistic, balanced, and sum to 100%.
Do not use markdown formatting characters such as **, *, #, -, or backticks.`;

let visaMockInterviewState = {
    active: false,
    listening: false,
    pending: false,
    history: [],
    recognition: null,
    channel: null,
    showModePicker: false
};

let visaPrepInterviewState = {
    active: false,
    listening: false,
    pending: false,
    history: [],
    recognition: null,
    channel: null,
    showModePicker: false
};

const PRICING_FALLBACK_RATES = {
    USD: 1.0,
    INR: 83.2,
    GBP: 0.79,
    CAD: 1.35,
    AUD: 1.53,
    EUR: 0.92,
    AED: 3.67,
    SGD: 1.35,
    JPY: 149.0
};

const PRICING_RATES_CACHE_WINDOW_MS = 60 * 60 * 1000;
let pricingRatesByCurrency = { ...PRICING_FALLBACK_RATES };
let pricingRatesMeta = { source: 'fallback', providerDate: null, stale: true, missingCurrencies: [] };
let pricingRatesFetchedAt = 0;
let pricingRatesRequestPromise = null;

// URL Routing System
let isNavigating = false; // Flag to prevent recursive navigation

function updateURL(path, replace = false) {
    if (isNavigating) return; // Prevent recursive calls
    const newURL = window.location.origin + path;
    if (replace) {
        window.history.replaceState({ path }, '', newURL);
    } else {
        window.history.pushState({ path }, '', newURL);
    }
}

function getPathFromURL() {
    return window.location.pathname;
}

function getQueryParams() {
    const params = new URLSearchParams(window.location.search);
    return {
        search: params.get('q') || params.get('search') || '',
        category: params.get('category') || '',
        minPrice: params.get('minPrice') || params.get('min_price') || '',
        maxPrice: params.get('maxPrice') || params.get('max_price') || '',
        itemId: params.get('item') || null
    };
}

function getReferralCodeFromURL() {
    const params = new URLSearchParams(window.location.search);
    const refCode = params.get('ref') || params.get('referral');
    if (!refCode) return null;
    const normalized = refCode.trim().toUpperCase();
    return normalized || null;
}

function getPublicAppOrigin() {
    return PUBLIC_APP_ORIGIN;
}

function persistAuthToken(token) {
    authToken = token || null;
}

function restoreAuthToken() {
    // Intentionally no-op: auth is persisted via secure HttpOnly cookie.
}

function applyDocumentCatalogPayload(payload = null) {
    const sourceDocumentTypes = Array.isArray(payload?.document_types) ? payload.document_types : FALLBACK_DOCUMENT_TYPES;
    const sourceJourneyStages = Array.isArray(payload?.journey_stages) ? payload.journey_stages : FALLBACK_JOURNEY_STAGES;
    const sourceRequiredTypes = Array.isArray(payload?.required_document_types) ? payload.required_document_types : [];

    documentTypeCatalog = sourceDocumentTypes
        .filter((row) => row && row.value)
        .map((row, index) => ({
            value: String(row.value),
            label: String(row.label || row.value),
            description: row.description || null,
            sort_order: Number.isFinite(row.sort_order) ? row.sort_order : index,
            is_active: row.is_active !== false,
            is_required: Boolean(row.is_required),
            journey_stage: Number.isFinite(row.journey_stage) ? row.journey_stage : null,
            stage_gate_required: Boolean(row.stage_gate_required),
            stage_gate_requires_validation: Boolean(row.stage_gate_requires_validation),
            stage_gate_group: row.stage_gate_group || null
        }))
        .sort((a, b) => a.sort_order - b.sort_order);

    documentTypeLabelByValue = {};
    documentTypeCatalog.forEach((row) => {
        documentTypeLabelByValue[row.value] = row.label;
    });

    const requiredFromCatalog = documentTypeCatalog
        .filter((row) => row.is_required)
        .map((row) => row.value);
    requiredDocumentTypeValues = sourceRequiredTypes.length
        ? sourceRequiredTypes.filter((value) => documentTypeLabelByValue[value])
        : requiredFromCatalog;

    journeyStageCatalog = sourceJourneyStages.length ? sourceJourneyStages : FALLBACK_JOURNEY_STAGES;
}

function renderDocumentTypeDropdownItems() {
    const dropdownList = document.getElementById('documentTypeList');
    if (!dropdownList) return;

    const activeTypes = documentTypeCatalog.filter((row) => row.is_active !== false);
    if (!activeTypes.length) {
        dropdownList.innerHTML = '<div class="dropdown-item" data-value="">No document types available</div>';
        return;
    }

    dropdownList.innerHTML = activeTypes
        .map((row) => `<div class="dropdown-item" data-value="${escapeHtml(row.value)}">${escapeHtml(row.label)}</div>`)
        .join('');
}

function getDocumentTypeLabel(documentType) {
    if (!documentType) return 'Document';
    return documentTypeLabelByValue[documentType] || formatDocumentType(documentType);
}

async function initializeDocumentCatalog() {
    try {
        const response = await fetch(`${API_BASE}/api/documents/catalog`);
        if (!response.ok) {
            throw new Error(`Catalog request failed: ${response.status}`);
        }
        const payload = await response.json();
        applyDocumentCatalogPayload(payload);
    } catch (error) {
        console.warn('Unable to load document catalog from backend; using fallback catalog.', error);
        applyDocumentCatalogPayload(null);
    }
    renderDocumentTypeDropdownItems();
}

function buildReferralInviteLink(referralCode) {
    if (!referralCode) return '';
    return `${getPublicAppOrigin()}/register?ref=${encodeURIComponent(referralCode)}`;
}

function getCurrentReferralCode() {
    const codeFromUser = (currentUser?.referral_code || '').trim().toUpperCase();
    if (codeFromUser) return codeFromUser;

    const codeFromProfile = (document.getElementById('profileReferralCode')?.value || '').trim().toUpperCase();
    if (codeFromProfile) return codeFromProfile;

    const codeFromBanner = (document.getElementById('dashboardReferralBannerCode')?.textContent || '').trim().toUpperCase();
    return codeFromBanner && codeFromBanner !== '--------' ? codeFromBanner : '';
}

function buildSearchURL(search, category, minPrice, maxPrice) {
    const params = new URLSearchParams();
    if (search) params.append('q', search);
    if (category) params.append('category', category);
    if (minPrice) params.append('minPrice', minPrice);
    if (maxPrice) params.append('maxPrice', maxPrice);
    const queryString = params.toString();
    return queryString ? `?${queryString}` : '';
}

function handleRoute(skipURLUpdate = false) {
    isNavigating = true; // Set flag to prevent URL updates during route handling
    const path = getPathFromURL();
    const queryParams = getQueryParams();
    
    // Handle routes
    if (path === '/' || path === '') {
        // Homepage - landing page
        showHomepage(skipURLUpdate);
    } else if (path === '/login') {
        showLogin(skipURLUpdate);
    } else if (path === '/register') {
        showRegister(skipURLUpdate);
    } else if (path === '/verify-email') {
        handleEmailVerification(skipURLUpdate);
    } else if (path === '/verify-university-change') {
        handleUniversityChangeVerification(skipURLUpdate);
    } else if (path === '/forgot-password') {
        showForgotPassword(skipURLUpdate);
    } else if (path === '/reset-password') {
        handleResetPasswordPage(skipURLUpdate);
    } else if (path === '/dashboard') {
        showDashboard(skipURLUpdate);
    } else if (path === '/pricing') {
        showPricing(skipURLUpdate);
    } else if (path === '/about-us') {
        showAboutUs(skipURLUpdate);
    } else if (path === '/privacy') {
        showPrivacy(skipURLUpdate);
    } else if (path === '/terms') {
        showTerms(skipURLUpdate);
    } else if (path === '/refund-policy') {
        showRefundPolicy(skipURLUpdate);
    } else if (path === '/delivery-policy') {
        showDeliveryPolicy(skipURLUpdate);
    } else if (path === '/contact') {
        showContact(skipURLUpdate);
    } else {
        // Unknown route, redirect to homepage
        if (!skipURLUpdate) {
            updateURL('/', true);
        }
        showHomepage(skipURLUpdate);
    }
    isNavigating = false; // Reset flag
}

// Handle browser back/forward buttons
window.addEventListener('popstate', (e) => {
    handleRoute(true); // Skip URL update when handling back/forward
});

// Initialize Turnstile site key
async function initializeTurnstile() {
    try {
        const response = await fetch(`${API_BASE}/api/auth/turnstile-site-key`);
        if (response.ok) {
            const data = await response.json();
            turnstileSiteKey = data.site_key;
            
            if (!turnstileSiteKey) {
                // Hide widgets if no site key is configured
                const loginWidget = document.getElementById('turnstile-login');
                const registerWidget = document.getElementById('turnstile-register');
                if (loginWidget) loginWidget.style.display = 'none';
                if (registerWidget) registerWidget.style.display = 'none';
                return;
            }
            
            // Set site key attribute - Turnstile will auto-render when script loads
            const loginWidget = document.getElementById('turnstile-login');
            const registerWidget = document.getElementById('turnstile-register');
            if (loginWidget) {
                loginWidget.setAttribute('data-sitekey', turnstileSiteKey);
            }
            if (registerWidget) {
                registerWidget.setAttribute('data-sitekey', turnstileSiteKey);
            }
        }
    } catch (error) {
        console.error('Error loading Turnstile site key:', error);
    }
}

// Initialize app
document.addEventListener('DOMContentLoaded', async () => {
    setupEventListeners();
    await initializeDocumentCatalog();
    initializeSearchableDropdowns();
    initializePricingSelector();
    initializeRegisterCountrySelector();
    
    // Initialize Turnstile
    await initializeTurnstile();
    
    // Set explicit legal revision dates (stable, not per-page-load dynamic values).
    const aboutLastUpdated = document.getElementById('aboutLastUpdated');
    const privacyLastUpdated = document.getElementById('privacyLastUpdated');
    const termsLastUpdated = document.getElementById('termsLastUpdated');
    const refundLastUpdated = document.getElementById('refundLastUpdated');
    const deliveryLastUpdated = document.getElementById('deliveryLastUpdated');
    if (aboutLastUpdated) aboutLastUpdated.textContent = LEGAL_LAST_UPDATED.about;
    if (privacyLastUpdated) privacyLastUpdated.textContent = LEGAL_LAST_UPDATED.privacy;
    if (termsLastUpdated) termsLastUpdated.textContent = LEGAL_LAST_UPDATED.terms;
    if (refundLastUpdated) refundLastUpdated.textContent = LEGAL_LAST_UPDATED.refund;
    if (deliveryLastUpdated) deliveryLastUpdated.textContent = LEGAL_LAST_UPDATED.delivery;
    
    // Restore token for same-tab refresh persistence and check authentication.
    restoreAuthToken();
    await checkAuth();
    loadNotifications();
    updateFloatingChatVisibility();
    
    // Handle initial route (use replaceState for initial load)
    handleRoute(true);
    // Update URL once after initial route is handled
    const path = getPathFromURL();
    updateURL(path || '/', true);
});

function initializeRegisterCountrySelector() {
    const countrySelect = document.getElementById('registerCountry');
    if (!countrySelect) return;

    const countryFlagsByCode = {
        US: '🇺🇸',
        IN: '🇮🇳',
        GB: '🇬🇧',
        CA: '🇨🇦',
        AU: '🇦🇺',
        DE: '🇩🇪',
        AE: '🇦🇪',
        SG: '🇸🇬',
        JP: '🇯🇵'
    };
    const countries = Object.entries(PRICING_COUNTRY_CONFIG).map(([code, entry]) => ({
        name: entry.country,
        flag: countryFlagsByCode[code] || '🌍'
    }));
    countrySelect.innerHTML = [
        '<option value="">Select country</option>',
        ...countries.map((country) => `<option value="${escapeHtml(country.name)}">${country.flag} ${escapeHtml(country.name)}</option>`)
    ].join('');

    countrySelect.value = 'United States';
}

function setupEventListeners() {
    const loginForm = document.getElementById('loginForm');
    if (loginForm) loginForm.addEventListener('submit', handleLogin);
    const registerForm = document.getElementById('registerForm');
    if (registerForm) registerForm.addEventListener('submit', handleRegister);
    const forgotPasswordForm = document.getElementById('forgotPasswordForm');
    if (forgotPasswordForm) forgotPasswordForm.addEventListener('submit', handleForgotPassword);
    const resetPasswordForm = document.getElementById('resetPasswordForm');
    if (resetPasswordForm) resetPasswordForm.addEventListener('submit', handleResetPassword);
    const createItemForm = document.getElementById('createItemForm');
    if (createItemForm) createItemForm.addEventListener('submit', handleCreateItem);
    const profileForm = document.getElementById('profileForm');
    if (profileForm) profileForm.addEventListener('submit', handleUpdateProfile);
    const profileChangePasswordForm = document.getElementById('profileChangePasswordForm');
    if (profileChangePasswordForm) profileChangePasswordForm.addEventListener('submit', handleProfileChangePassword);
    const contactForm = document.getElementById('contactForm');
    if (contactForm) contactForm.addEventListener('submit', handleContactSubmit);
    const featureRequestForm = document.getElementById('featureRequestForm');
    if (featureRequestForm) featureRequestForm.addEventListener('submit', handleFeatureRequestSubmit);
    const registerPasswordInput = document.getElementById('registerPassword');
    if (registerPasswordInput) registerPasswordInput.addEventListener('input', updateRegisterPasswordHint);
    const resetPasswordNewInput = document.getElementById('resetPasswordNew');
    if (resetPasswordNewInput) resetPasswordNewInput.addEventListener('input', updateResetPasswordHint);
    const profileNewPasswordInput = document.getElementById('profileNewPassword');
    if (profileNewPasswordInput) profileNewPasswordInput.addEventListener('input', updateProfilePasswordHint);
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') loadItems();
        });
    }
    
    // Image preview for multiple file upload
    const imageFileInput = document.getElementById('itemImageFiles');
    if (imageFileInput) {
        imageFileInput.addEventListener('change', handleMultipleImagePreview);
    }
    
    // Profile picture upload
    const profilePictureInput = document.getElementById('profilePictureInput');
    if (profilePictureInput) {
        profilePictureInput.addEventListener('change', handleProfilePicturePreview);
    }
    
    // Update price label when category changes
    const itemCategorySelect = document.getElementById('itemCategory');
    if (itemCategorySelect) {
        itemCategorySelect.addEventListener('change', updatePriceLabel);
    }
    
    // Update price filter placeholders when category filter changes
    const categoryFilter = document.getElementById('categoryFilter');
    if (categoryFilter) {
        categoryFilter.addEventListener('change', updatePriceFilterPlaceholders);
    }
    
    // Documentation form
    const documentationForm = document.getElementById('documentationForm');
    if (documentationForm) {
        documentationForm.addEventListener('submit', handleDocumentationForm);
        initializeYearDropdown();
        loadDocumentationPreferences();
    }
    
    // Document upload form
    const documentUploadForm = document.getElementById('documentUploadForm');
    if (documentUploadForm) {
        documentUploadForm.addEventListener('submit', handleDocumentUpload);
    }
    
    // University email validation and autofill
    const registerEmailInput = document.getElementById('registerEmail');
    if (registerEmailInput) {
        let emailCheckTimeout;
        registerEmailInput.addEventListener('input', (e) => {
            clearTimeout(emailCheckTimeout);
            const email = e.target.value.trim();
            updateRegisterPasswordHint();
            
            // Only check if email looks valid (contains @)
            if (email && email.includes('@')) {
                emailCheckTimeout = setTimeout(() => {
                    checkUniversityByEmail(email);
                }, 500); // Debounce for 500ms
            } else {
                // Clear university if email is invalid
                document.getElementById('registerUniversity').value = '';
                const messageEl = document.getElementById('emailValidationMessage');
                messageEl.style.display = 'none';
            }
        });
    }

    updateRegisterPasswordHint();
    updateResetPasswordHint();
    updateProfilePasswordHint();
}

function updatePriceLabel() {
    const categorySelect = document.getElementById('itemCategory');
    const priceLabel = document.querySelector('label[for="itemPrice"]');
    const priceInput = document.getElementById('itemPrice');
    
    if (categorySelect && priceLabel && priceInput) {
        if (categorySelect.value === 'sublease') {
            priceLabel.textContent = 'Price ($/month) *';
            priceInput.placeholder = 'e.g., 800';
        } else {
            priceLabel.textContent = 'Price ($) *';
            priceInput.placeholder = '';
        }
    }
}

function updatePriceFilterPlaceholders() {
    const categoryFilter = document.getElementById('categoryFilter');
    const minPriceInput = document.getElementById('minPrice');
    const maxPriceInput = document.getElementById('maxPrice');
    
    if (categoryFilter && minPriceInput && maxPriceInput) {
        if (categoryFilter.value === 'sublease') {
            minPriceInput.placeholder = 'Min $/month';
            maxPriceInput.placeholder = 'Max $/month';
        } else {
            minPriceInput.placeholder = 'Min $';
            maxPriceInput.placeholder = 'Max $';
        }
    }
}

const FRONTEND_PASSWORD_MIN_LENGTH = 10;
const FRONTEND_PASSWORD_MAX_LENGTH = 200;

function getPasswordValidationErrors(password, email = '') {
    const value = String(password || '');
    const errors = [];

    if (value.length < FRONTEND_PASSWORD_MIN_LENGTH) {
        errors.push(`at least ${FRONTEND_PASSWORD_MIN_LENGTH} characters`);
    }
    if (new TextEncoder().encode(value).length > FRONTEND_PASSWORD_MAX_LENGTH) {
        errors.push(`at most ${FRONTEND_PASSWORD_MAX_LENGTH} bytes`);
    }
    if (/\s/.test(value)) {
        errors.push('no spaces');
    }
    if (!/[a-z]/.test(value)) {
        errors.push('one lowercase letter');
    }
    if (!/[A-Z]/.test(value)) {
        errors.push('one uppercase letter');
    }
    if (!/\d/.test(value)) {
        errors.push('one number');
    }
    if (!/[^A-Za-z0-9]/.test(value)) {
        errors.push('one special character');
    }

    const weakSet = new Set([
        'password',
        'password123',
        '123456',
        '12345678',
        'qwerty',
        'qwerty123',
        'admin',
        'admin123',
        'letmein',
        'welcome',
        'iloveyou',
        'abc123'
    ]);
    if (weakSet.has(value.toLowerCase())) {
        errors.push('not a common password');
    }

    const emailLocal = String(email || '').split('@')[0].toLowerCase().trim();
    if (emailLocal.length >= 3 && value.toLowerCase().includes(emailLocal)) {
        errors.push('must not contain your email username');
    }

    return errors;
}

function updateRegisterPasswordHint() {
    const hintEl = document.getElementById('registerPasswordPolicyHint');
    const passwordInput = document.getElementById('registerPassword');
    const emailInput = document.getElementById('registerEmail');
    if (!hintEl || !passwordInput) return;

    const password = passwordInput.value || '';
    if (!password) {
        hintEl.style.color = 'var(--text-secondary)';
        hintEl.textContent = 'Use 10+ characters with uppercase, lowercase, number, and special character.';
        return;
    }

    const errors = getPasswordValidationErrors(password, emailInput?.value || '');
    if (!errors.length) {
        hintEl.style.color = '#34d399';
        hintEl.textContent = 'Strong password';
    } else {
        hintEl.style.color = '#f59e0b';
        hintEl.textContent = `Needs: ${errors.join(', ')}`;
    }
}

function updateResetPasswordHint() {
    const hintEl = document.getElementById('resetPasswordPolicyHint');
    const passwordInput = document.getElementById('resetPasswordNew');
    if (!hintEl || !passwordInput) return;

    const password = passwordInput.value || '';
    if (!password) {
        hintEl.style.color = 'var(--text-secondary)';
        hintEl.textContent = 'Use 10+ characters with uppercase, lowercase, number, and special character.';
        return;
    }

    const errors = getPasswordValidationErrors(password);
    if (!errors.length) {
        hintEl.style.color = '#34d399';
        hintEl.textContent = 'Strong password';
    } else {
        hintEl.style.color = '#f59e0b';
        hintEl.textContent = `Needs: ${errors.join(', ')}`;
    }
}

function updateProfilePasswordHint() {
    const hintEl = document.getElementById('profilePasswordPolicyHint');
    const passwordInput = document.getElementById('profileNewPassword');
    if (!hintEl || !passwordInput) return;

    const password = passwordInput.value || '';
    if (!password) {
        hintEl.style.color = 'var(--text-secondary)';
        hintEl.textContent = 'Use 10+ characters with uppercase, lowercase, number, and special character.';
        return;
    }

    const userEmail = currentUser?.email || document.getElementById('profileEmail')?.value || '';
    const errors = getPasswordValidationErrors(password, userEmail);
    if (!errors.length) {
        hintEl.style.color = '#34d399';
        hintEl.textContent = 'Strong password';
    } else {
        hintEl.style.color = '#f59e0b';
        hintEl.textContent = `Needs: ${errors.join(', ')}`;
    }
}

async function checkUniversityByEmail(email) {
    const universityInput = document.getElementById('registerUniversity');
    const messageEl = document.getElementById('emailValidationMessage');
    
    if (!email || !email.includes('@')) {
        universityInput.value = '';
        messageEl.style.display = 'none';
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/university-by-email?email=${encodeURIComponent(email)}`);
        const data = await response.json();
        
        if (data.is_valid && data.university_name) {
            // Valid university email - autofill university
            universityInput.value = data.university_name;
            messageEl.textContent = `✓ Valid university email domain: ${data.email_domain}`;
            messageEl.style.color = 'var(--success-color)';
            messageEl.style.display = 'block';
        } else {
            // Invalid university email domain
            universityInput.value = '';
            messageEl.textContent = `✗ This email domain (${data.email_domain}) is not recognized. Please use your university email address.`;
            messageEl.style.color = 'var(--danger-color)';
            messageEl.style.display = 'block';
        }
    } catch (error) {
        console.error('Error checking university:', error);
        universityInput.value = '';
        messageEl.textContent = 'Unable to verify email domain. Please try again.';
        messageEl.style.color = 'var(--text-secondary)';
        messageEl.style.display = 'block';
    }
}

async function checkAuth() {
    try {
        const headers = {};
        if (authToken && authToken !== COOKIE_AUTH_SENTINEL) {
            headers.Authorization = `Bearer ${authToken}`;
        }
        const response = await fetch(`${API_BASE}/api/auth/me`, {
            headers
        });
        if (response.ok) {
            currentUser = await response.json();
            if (!authToken) {
                authToken = COOKIE_AUTH_SENTINEL;
            }
            updateUIForAuth();
            await loadSubscriptionStatus(true);
            return true;
        } else {
            authToken = null;
            persistAuthToken(null);
            currentSubscription = null;
            updateSubscriptionUI();
            return false;
        }
    } catch (error) {
        console.error('Auth check failed:', error);
        authToken = null;
        persistAuthToken(null);
        currentSubscription = null;
        updateSubscriptionUI();
        return false;
    }
}

function renderUserInfo(user) {
    const userInfoEl = document.getElementById('userInfo');
    if (!userInfoEl) return;

    const safeUsername = user?.username || 'User';
    const safeDisplayName = user?.full_name || safeUsername;
    const safeInitial = (safeDisplayName || 'U').charAt(0).toUpperCase();

    userInfoEl.replaceChildren();

    if (user?.profile_picture) {
        const avatarImg = document.createElement('img');
        avatarImg.src = getImageUrl(user.profile_picture);
        avatarImg.alt = safeUsername;

        const usernameSpan = document.createElement('span');
        usernameSpan.textContent = safeUsername;

        userInfoEl.append(avatarImg, usernameSpan);
        return;
    }

    const avatar = document.createElement('div');
    avatar.style.width = '2rem';
    avatar.style.height = '2rem';
    avatar.style.borderRadius = '50%';
    avatar.style.background = 'rgba(255,255,255,0.3)';
    avatar.style.display = 'flex';
    avatar.style.alignItems = 'center';
    avatar.style.justifyContent = 'center';
    avatar.style.fontWeight = '600';
    avatar.textContent = safeInitial;

    const usernameSpan = document.createElement('span');
    usernameSpan.textContent = safeUsername;

    userInfoEl.append(avatar, usernameSpan);
}

function updateUIForAuth() {
    if (currentUser) {
        document.getElementById('loginLink').style.display = 'none';
        document.getElementById('registerLink').style.display = 'none';
        document.getElementById('userMenu').style.display = 'block';
        document.getElementById('notificationContainer').style.display = 'block';
        updateNotificationBadge();
        updateFloatingChatVisibility();
        
        // Update homepage buttons
        const heroSellBtn = document.getElementById('heroSellBtn');
        const heroRegisterBtn = document.getElementById('heroRegisterBtn');
        const ctaRegisterBtn = document.getElementById('ctaRegisterBtn');
        if (heroSellBtn) heroSellBtn.style.display = 'inline-block';
        if (heroRegisterBtn) heroRegisterBtn.style.display = 'none';
        if (ctaRegisterBtn) ctaRegisterBtn.style.display = 'none';
        
        renderUserInfo(currentUser);
        // Only load profile data if we're on the dashboard section
        const currentSection = sessionStorage.getItem('currentSection');
        if (currentSection === 'dashboard' || currentSection === 'profile') {
            loadProfile();
            loadDashboardStats();
        }
    } else {
        document.getElementById('loginLink').style.display = 'block';
        document.getElementById('registerLink').style.display = 'block';
        document.getElementById('userMenu').style.display = 'none';
        document.getElementById('notificationContainer').style.display = 'none';
        updateFloatingChatVisibility();
        
        // Update homepage buttons
        const heroSellBtn = document.getElementById('heroSellBtn');
        const heroRegisterBtn = document.getElementById('heroRegisterBtn');
        const ctaRegisterBtn = document.getElementById('ctaRegisterBtn');
        if (heroSellBtn) heroSellBtn.style.display = 'none';
        if (heroRegisterBtn) heroRegisterBtn.style.display = 'inline-block';
        if (ctaRegisterBtn) ctaRegisterBtn.style.display = 'inline-block';
        currentSubscription = null;
        updateSubscriptionUI();
    }
}

function toggleUserMenu() {
    const dropdown = document.getElementById('userMenuDropdown');
    dropdown.style.display = dropdown.style.display === 'none' ? 'block' : 'none';
}

// Notification Functions
function addNotification(title, message, type = 'info', data = null) {
    const notification = {
        id: Date.now(),
        title: title,
        message: message,
        type: type, // 'success', 'error', 'warning', 'info'
        data: data,
        timestamp: new Date().toISOString(),
        read: false
    };
    notifications.unshift(notification);
    // Keep only last 50 notifications
    if (notifications.length > 50) {
        notifications = notifications.slice(0, 50);
    }
    saveNotifications();
    updateNotificationBadge();
    renderNotifications();
    return notification;
}

function saveNotifications() {
    localStorage.setItem('notifications', JSON.stringify(notifications));
}

function loadNotifications() {
    notifications = JSON.parse(localStorage.getItem('notifications') || '[]');
    updateNotificationBadge();
    renderNotifications();
}

function updateNotificationBadge() {
    const badge = document.getElementById('notificationBadge');
    const unreadCount = notifications.filter(n => !n.read).length;
    if (badge) {
        if (unreadCount > 0) {
            badge.textContent = unreadCount > 99 ? '99+' : unreadCount;
            badge.style.display = 'block';
        } else {
            badge.style.display = 'none';
        }
    }
}

function renderNotifications() {
    const list = document.getElementById('notificationList');
    if (!list) return;
    
    if (notifications.length === 0) {
        list.innerHTML = '<p style="text-align: center; padding: 1rem; color: var(--text-secondary);">No notifications</p>';
        return;
    }
    
    list.innerHTML = notifications.map(notif => {
        const date = new Date(notif.timestamp);
        const timeAgo = getTimeAgo(date);
        const icon = getNotificationIcon(notif.type);
        const readClass = notif.read ? 'read' : '';
        
        // Format message with line breaks
        const formattedMessage = escapeHtml(notif.message).replace(/\n/g, '<br>');
        
        return `
            <div class="notification-item ${readClass}" onclick="markNotificationRead(${notif.id})">
                <div class="notification-icon ${notif.type}">${icon}</div>
                <div class="notification-content">
                    <div class="notification-title">${escapeHtml(notif.title)}</div>
                    <div class="notification-message">${formattedMessage}</div>
                    <div class="notification-time">${timeAgo}</div>
                </div>
                ${!notif.read ? '<div class="notification-dot"></div>' : ''}
            </div>
        `;
    }).join('');
}

function getNotificationIcon(type) {
    const icons = {
        'success': '✅',
        'error': '❌',
        'warning': '⚠️',
        'info': 'ℹ️'
    };
    return icons[type] || 'ℹ️';
}

function getTimeAgo(date) {
    const seconds = Math.floor((new Date() - date) / 1000);
    if (seconds < 60) return 'just now';
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Convert markdown to HTML for AI responses
function markdownToHtml(text) {
    if (!text) return '';
    
    // Escape HTML first to prevent XSS
    let html = escapeHtml(text);
    
    // Convert **bold** to <strong>
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    
    // Convert *italic* to <em> (but not if it's part of **)
    html = html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');
    
    // Convert `code` to <code>
    html = html.replace(/`([^`]+)`/g, '<code style="background: rgba(139, 92, 246, 0.2); padding: 2px 6px; border-radius: 4px; font-family: monospace;">$1</code>');
    
    // Convert bullet points (lines starting with - or •)
    html = html.replace(/^[\-•]\s+(.+)$/gm, '<li>$1</li>');
    
    // Convert numbered lists (lines starting with 1. 2. etc)
    html = html.replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>');
    
    // Wrap consecutive <li> elements in <ul>
    html = html.replace(/(<li>.*<\/li>\n?)+/g, (match) => {
        return '<ul style="margin: 8px 0; padding-left: 20px; list-style-type: disc;">' + match + '</ul>';
    });
    
    // Convert line breaks to <br> but not inside lists
    html = html.replace(/\n(?!<)/g, '<br>');
    
    // Clean up extra <br> before/after lists
    html = html.replace(/<br><ul/g, '<ul');
    html = html.replace(/<\/ul><br>/g, '</ul>');
    html = html.replace(/<br><li>/g, '<li>');
    html = html.replace(/<\/li><br>/g, '</li>');
    
    return html;
}

function toggleNotifications() {
    const dropdown = document.getElementById('notificationDropdown');
    notificationDropdownOpen = !notificationDropdownOpen;
    dropdown.style.display = notificationDropdownOpen ? 'block' : 'none';
    if (notificationDropdownOpen) {
        renderNotifications();
    }
}

function markNotificationRead(id) {
    const notif = notifications.find(n => n.id === id);
    if (notif && !notif.read) {
        notif.read = true;
        saveNotifications();
        updateNotificationBadge();
        renderNotifications();
    }
}

function clearAllNotifications() {
    if (confirm('Clear all notifications?')) {
        notifications = [];
        saveNotifications();
        updateNotificationBadge();
        renderNotifications();
    }
}

// Close dropdown when clicking outside
document.addEventListener('click', (e) => {
    const userMenu = document.getElementById('userMenu');
    const dropdown = document.getElementById('userMenuDropdown');
    if (userMenu && dropdown && !userMenu.contains(e.target)) {
        dropdown.style.display = 'none';
    }
    
    const notificationContainer = document.getElementById('notificationContainer');
    const notificationDropdown = document.getElementById('notificationDropdown');
    if (notificationContainer && notificationDropdown && !notificationContainer.contains(e.target)) {
        notificationDropdown.style.display = 'none';
        notificationDropdownOpen = false;
    }
});

function showMessage(text, type = 'success') {
    const messageEl = document.getElementById('message');
    messageEl.textContent = text;
    messageEl.className = `message ${type} show`;
    setTimeout(() => {
        messageEl.classList.remove('show');
    }, 3000);
}

// Navigation
function showHomepage(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('homepageSection').style.display = 'block';
    // Update button visibility based on auth status
    const heroRegisterBtn = document.getElementById('heroRegisterBtn');
    const heroLoginBtn = document.getElementById('heroLoginBtn');
    const heroDashboardBtn = document.getElementById('heroDashboardBtn');
    const ctaRegisterBtn = document.getElementById('ctaRegisterBtn');
    const ctaDashboardBtn = document.getElementById('ctaDashboardBtn');
    
    if (currentUser) {
        // Logged in: show dashboard buttons, hide login/register
        if (heroRegisterBtn) heroRegisterBtn.style.display = 'none';
        if (heroLoginBtn) heroLoginBtn.style.display = 'none';
        if (heroDashboardBtn) heroDashboardBtn.style.display = 'inline-flex';
        if (ctaRegisterBtn) ctaRegisterBtn.style.display = 'none';
        if (ctaDashboardBtn) ctaDashboardBtn.style.display = 'inline-flex';
    } else {
        // Logged out: show login/register, hide dashboard
        if (heroRegisterBtn) heroRegisterBtn.style.display = 'inline-flex';
        if (heroLoginBtn) heroLoginBtn.style.display = 'inline-flex';
        if (heroDashboardBtn) heroDashboardBtn.style.display = 'none';
        if (ctaRegisterBtn) ctaRegisterBtn.style.display = 'inline-flex';
        if (ctaDashboardBtn) ctaDashboardBtn.style.display = 'none';
    }
    
    if (!skipURLUpdate) {
        updateURL('/', false); // Use pushState for navigation
    }
}

function showLogin(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('loginSection').style.display = 'block';
    
    // Ensure Turnstile widget is properly initialized
    const loginWidget = document.getElementById('turnstile-login');
    if (loginWidget) {
        if (turnstileSiteKey) {
            // Make sure widget is visible
            loginWidget.style.display = 'block';
            // Set site key if not already set
            if (!loginWidget.getAttribute('data-sitekey')) {
                loginWidget.setAttribute('data-sitekey', turnstileSiteKey);
            }
            
            // Wait a bit for Turnstile script to load, then render
            const renderWidget = () => {
                if (window.turnstile) {
                    try {
                        // Check if widget is already rendered by trying to get response
                        const existingToken = window.turnstile.getResponse(loginWidget);
                        if (existingToken) {
                            // Widget exists, just reset it
                            window.turnstile.reset(loginWidget);
                            turnstileWidgetIds.login = loginWidget;
                        } else {
                            // Widget doesn't exist, render it
                            const widgetId = window.turnstile.render(loginWidget, {
                                sitekey: turnstileSiteKey,
                                theme: 'light'
                            });
                            turnstileWidgetIds.login = widgetId || loginWidget;
                        }
                    } catch (e) {
                        // Widget might not be rendered yet, so render it
                        try {
                            const widgetId = window.turnstile.render(loginWidget, {
                                sitekey: turnstileSiteKey,
                                theme: 'light'
                            });
                            turnstileWidgetIds.login = widgetId || loginWidget;
                        } catch (renderError) {
                            console.error('Error rendering Turnstile:', renderError);
                        }
                    }
                } else {
                    // Wait for Turnstile to load
                    setTimeout(renderWidget, 100);
                }
            };
            renderWidget();
        } else {
            // Hide widget if no site key
            loginWidget.style.display = 'none';
        }
    }
    
    if (!skipURLUpdate) {
        updateURL('/login', false); // Use pushState for navigation
    }
}

function showForgotPassword(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('forgotPasswordSection').style.display = 'block';
    if (!skipURLUpdate) {
        updateURL('/forgot-password', false);
    }
}

function showResetPassword(token, skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('resetPasswordSection').style.display = 'block';
    document.getElementById('resetToken').value = token;
    updateResetPasswordHint();
    if (!skipURLUpdate) {
        updateURL(`/reset-password?token=${encodeURIComponent(token)}`, false);
    }
}

async function handleResetPasswordPage(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('resetPasswordSection').style.display = 'block';
    
    // Get token from URL
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token');
    
    if (token) {
        document.getElementById('resetToken').value = token;
        updateResetPasswordHint();
    } else {
        // No token in URL, show error
        document.getElementById('resetPasswordSection').innerHTML = `
            <div class="auth-card">
                <h2>Reset Password</h2>
                <div style="text-align: center; padding: 2rem;">
                    <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--danger-color);">✗</div>
                    <h3 style="margin-bottom: 1rem; color: var(--danger-color);">Invalid Reset Link</h3>
                    <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                        The password reset link is invalid or missing. Please request a new password reset.
                    </p>
                    <a href="#" onclick="showForgotPassword(); return false;" class="btn btn-primary">Request New Reset Link</a>
                </div>
            </div>
        `;
    }
    
    if (!skipURLUpdate) {
        updateURL('/reset-password' + (token ? `?token=${encodeURIComponent(token)}` : ''), false);
    }
}

function showRegister(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('registerSection').style.display = 'block';
    
    // Clear university field and validation message when showing register form
    const universityInput = document.getElementById('registerUniversity');
    const messageEl = document.getElementById('emailValidationMessage');
    const referralInput = document.getElementById('registerReferralCode');
    const countryInput = document.getElementById('registerCountry');
    const consentInput = document.getElementById('registerConsent');
    if (universityInput) universityInput.value = '';
    if (messageEl) messageEl.style.display = 'none';
    if (countryInput) countryInput.value = 'United States';
    if (referralInput) {
        referralInput.value = getReferralCodeFromURL() || '';
    }
    if (consentInput) consentInput.checked = false;
    const registerPasswordInput = document.getElementById('registerPassword');
    if (registerPasswordInput) registerPasswordInput.value = '';
    updateRegisterPasswordHint();
    
    // Ensure Turnstile widget is properly initialized
    const registerWidget = document.getElementById('turnstile-register');
    if (registerWidget) {
        if (turnstileSiteKey) {
            // Make sure widget is visible
            registerWidget.style.display = 'block';
            // Set site key if not already set
            if (!registerWidget.getAttribute('data-sitekey')) {
                registerWidget.setAttribute('data-sitekey', turnstileSiteKey);
            }
            
            // Wait a bit for Turnstile script to load, then render
            const renderWidget = () => {
                if (window.turnstile) {
                    try {
                        // Check if widget is already rendered by trying to get response
                        const existingToken = window.turnstile.getResponse(registerWidget);
                        if (existingToken) {
                            // Widget exists, just reset it
                            window.turnstile.reset(registerWidget);
                            turnstileWidgetIds.register = registerWidget;
                        } else {
                            // Widget doesn't exist, render it
                            const widgetId = window.turnstile.render(registerWidget, {
                                sitekey: turnstileSiteKey,
                                theme: 'light'
                            });
                            turnstileWidgetIds.register = widgetId || registerWidget;
                        }
                    } catch (e) {
                        // Widget might not be rendered yet, so render it
                        try {
                            const widgetId = window.turnstile.render(registerWidget, {
                                sitekey: turnstileSiteKey,
                                theme: 'light'
                            });
                            turnstileWidgetIds.register = widgetId || registerWidget;
                        } catch (renderError) {
                            console.error('Error rendering Turnstile:', renderError);
                        }
                    }
                } else {
                    // Wait for Turnstile to load
                    setTimeout(renderWidget, 100);
                }
            };
            renderWidget();
        } else {
            // Hide widget if no site key
            registerWidget.style.display = 'none';
        }
    }
    
    if (!skipURLUpdate) {
        updateURL('/register', false); // Use pushState for navigation
    }
}

function showVerification(email = null, expiryHours = 24) {
    hideAllSections();
    document.getElementById('verificationSection').style.display = 'block';
    const content = document.getElementById('verificationContent');
    const safeExpiryHours = Number.isFinite(Number(expiryHours)) ? Math.max(1, Number(expiryHours)) : 24;
    if (email) {
        content.innerHTML = `
            <div style="text-align: center; margin-bottom: 2rem;">
                <div style="font-size: 3rem; margin-bottom: 1rem;">📧</div>
                <h3 style="margin-bottom: 1rem;">Check Your Email</h3>
                <p style="color: var(--text-secondary); margin-bottom: 1rem;">
                    We've sent a verification email to <strong>${escapeHtml(email)}</strong>
                </p>
                <p style="color: var(--text-secondary); font-size: 0.875rem;">
                    Click the link in the email to verify your account and start using Rilono.
                </p>
                <p style="color: var(--text-secondary); font-size: 0.85rem; margin-top: 0.5rem;">
                    For security, this verification link expires in <strong>${safeExpiryHours} hours</strong>.
                </p>
            </div>
            <div style="text-align: center;">
                <button onclick="resendVerificationEmail('${escapeHtml(email)}')" class="btn btn-primary">Resend Verification Email</button>
                <p style="margin-top: 1rem;">
                    <a href="#" onclick="showLogin(); return false;">Back to Login</a>
                </p>
            </div>
        `;
    }
    updateURL('/verify-email', false);
}

async function handleEmailVerification(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('verificationSection').style.display = 'block';
    
    // Get token from URL
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token');
    
    if (token) {
        // Verify the token
        try {
            const response = await fetch(`${API_BASE}/api/auth/verify-email?token=${encodeURIComponent(token)}`);
            const data = await response.json();
            
            if (response.ok) {
                document.getElementById('verificationContent').innerHTML = `
                    <div style="text-align: center;">
                        <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--success-color);">✓</div>
                        <h3 style="margin-bottom: 1rem; color: var(--success-color);">Email Verified!</h3>
                        <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                            Your email has been successfully verified. You can now log in to your account.
                        </p>
                        <a href="#" onclick="showLogin(); return false;" class="btn btn-primary">Go to Login</a>
                    </div>
                `;
            } else {
                document.getElementById('verificationContent').innerHTML = `
                    <div style="text-align: center;">
                        <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--danger-color);">✗</div>
                        <h3 style="margin-bottom: 1rem; color: var(--danger-color);">Verification Failed</h3>
                        <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                            ${escapeHtml(data.detail || 'Invalid or expired verification token.')}
                        </p>
                        <button onclick="showLogin(); return false;" class="btn btn-primary">Go to Login</button>
                    </div>
                `;
            }
        } catch (error) {
            console.error('Verification error:', error);
            document.getElementById('verificationContent').innerHTML = `
                <div style="text-align: center;">
                    <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--danger-color);">✗</div>
                    <h3 style="margin-bottom: 1rem; color: var(--danger-color);">Error</h3>
                    <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                        An error occurred during verification. Please try again.
                    </p>
                    <button onclick="showLogin(); return false;" class="btn btn-primary">Go to Login</button>
                </div>
            `;
        }
    } else {
        // No token, show resend option
        showVerification();
    }
    
    if (!skipURLUpdate) {
        updateURL('/verify-email' + (token ? `?token=${token}` : ''), false);
    }
}

async function handleUniversityChangeVerification(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('verificationSection').style.display = 'block';
    
    // Get token from URL
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token');
    
    if (token) {
        // Show loading
        document.getElementById('verificationContent').innerHTML = `
            <div style="text-align: center;">
                <div style="font-size: 4rem; margin-bottom: 1rem;">⏳</div>
                <h3 style="margin-bottom: 1rem;">Verifying University Change...</h3>
                <p style="color: var(--text-secondary);">Please wait while we verify your request.</p>
            </div>
        `;
        
        // Verify the token
        try {
            const response = await fetch(`${API_BASE}/api/auth/verify-university-change?token=${encodeURIComponent(token)}`);
            const data = await response.json();
            
            if (response.ok) {
                document.getElementById('verificationContent').innerHTML = `
                    <div style="text-align: center;">
                        <div style="font-size: 4rem; margin-bottom: 1rem;">🎓</div>
                        <h3 style="margin-bottom: 1rem; color: var(--success-color);">University Changed!</h3>
                        <p style="color: var(--text-secondary); margin-bottom: 1.5rem;">
                            Your university has been successfully updated.
                        </p>
                        <div style="background: var(--bg-tertiary); padding: 1.5rem; border-radius: 12px; margin-bottom: 2rem; text-align: left;">
                            <p style="margin: 0.5rem 0;"><strong>New University:</strong> ${escapeHtml(data.new_university)}</p>
                            <p style="margin: 0.5rem 0;"><strong>New Email:</strong> ${escapeHtml(data.new_email)}</p>
                        </div>
                        <p style="color: var(--text-secondary); margin-bottom: 2rem; font-size: 0.9rem;">
                            Please log in again with your new email address.
                        </p>
                        <a href="#" onclick="logout(); showLogin(); return false;" class="btn btn-primary">Login with New Email</a>
                    </div>
                `;
            } else {
                document.getElementById('verificationContent').innerHTML = `
                    <div style="text-align: center;">
                        <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--danger-color);">✗</div>
                        <h3 style="margin-bottom: 1rem; color: var(--danger-color);">Verification Failed</h3>
                        <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                            ${escapeHtml(data.detail || 'Invalid or expired verification token.')}
                        </p>
                        <button onclick="showDashboard(); return false;" class="btn btn-primary">Go to Dashboard</button>
                    </div>
                `;
            }
        } catch (error) {
            console.error('University change verification error:', error);
            document.getElementById('verificationContent').innerHTML = `
                <div style="text-align: center;">
                    <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--danger-color);">✗</div>
                    <h3 style="margin-bottom: 1rem; color: var(--danger-color);">Error</h3>
                    <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                        An error occurred during verification. Please try again.
                    </p>
                    <button onclick="showDashboard(); return false;" class="btn btn-primary">Go to Dashboard</button>
                </div>
            `;
        }
    } else {
        // No token
        document.getElementById('verificationContent').innerHTML = `
            <div style="text-align: center;">
                <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--danger-color);">✗</div>
                <h3 style="margin-bottom: 1rem; color: var(--danger-color);">Invalid Link</h3>
                <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                    This verification link is invalid. Please request a new university change from your profile.
                </p>
                <button onclick="showDashboard(); return false;" class="btn btn-primary">Go to Dashboard</button>
            </div>
        `;
    }
    
    if (!skipURLUpdate) {
        updateURL('/verify-university-change' + (token ? `?token=${token}` : ''), false);
    }
}

async function resendVerificationEmail(email = null) {
    if (!email) {
        email = prompt('Please enter your email address:');
        if (!email) return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/resend-verification`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ email: email })
        });
        
        const data = await response.json();
        const expiryHours = Number(response.headers.get('X-Verification-Link-Expires-Hours') || 24);
        
        if (response.ok) {
            showMessage(data.message || `Verification email sent. The link expires in ${expiryHours} hours.`, 'success');
            showVerification(email, expiryHours);
        } else {
            showMessage(data.detail || 'Failed to send verification email', 'error');
        }
    } catch (error) {
        console.error('Resend verification error:', error);
        showMessage('An error occurred. Please try again.', 'error');
    }
}

function showMarketplace(skipURLUpdate = false) {
    showHomepage(skipURLUpdate);
}

function showMarketplaceWithFilters(params, skipURLUpdate = false) {
    showHomepage(skipURLUpdate);
}

function showCreateItem(skipURLUpdate = false) {
    showDashboard(skipURLUpdate);
}

function showMyListings(skipURLUpdate = false) {
    showDashboard(skipURLUpdate);
}

function showMessages(skipURLUpdate = false) {
    showDashboard(skipURLUpdate);
}

function showDashboard(skipURLUpdate = false) {
    if (!currentUser) {
        showMessage('Please login to view dashboard', 'error');
        showLogin();
        return;
    }
    hideAllSections();
    document.getElementById('dashboardSection').style.display = 'block';
    const pageContainer = document.querySelector('.container');
    if (pageContainer) {
        pageContainer.classList.add('dashboard-fluid');
    }
    loadProfile();
    loadDashboardStats();
    initializeRilonoAiChat();
    initializeYearDropdown();
    loadDocumentationPreferences();
    loadMyDocuments();
    loadSubscriptionStatus(true);
    renderReferralPromotions();
    
    // Set default tab to overview if no tab is active
    const activeTab = document.querySelector('.dashboard-tab.active');
    if (!activeTab) {
        switchDashboardTab('overview');
    }
    
    if (!skipURLUpdate) {
        updateURL('/dashboard', false); // Use pushState for navigation
    }
}

async function loadSubscriptionStatus(silent = true) {
    if (!authToken) {
        currentSubscription = null;
        updateSubscriptionUI();
        return null;
    }

    try {
        const response = await fetch(`${API_BASE}/api/subscription/me`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            if (!silent) {
                showMessage(errorData.detail || 'Failed to load subscription status', 'error');
            }
            return null;
        }

        currentSubscription = await response.json();
        updateSubscriptionUI();
        return currentSubscription;
    } catch (error) {
        console.error('Error loading subscription status:', error);
        if (!silent) {
            showMessage('Failed to load subscription status', 'error');
        }
        return null;
    }
}

function formatUsageText(used, limit, metricLabel) {
    if (limit < 0) {
        return `${metricLabel}: Unlimited`;
    }
    return `${metricLabel}: ${used}/${limit} used`;
}

function updateSubscriptionUI() {
    const planNameEl = document.getElementById('dashboardPlanName');
    const aiUsageEl = document.getElementById('dashboardPlanUsage');
    const uploadUsageEl = document.getElementById('dashboardUploadUsage');
    const prepUsageEl = document.getElementById('dashboardPrepUsage');
    const mockUsageEl = document.getElementById('dashboardMockUsage');
    const sidebarUpgradeButton = document.getElementById('dashboardUpgradeButton');
    const sidebarCancelButton = document.getElementById('dashboardCancelButton');
    const pricingUpgradeButton = document.getElementById('pricingProUpgradeButton');

    if (!currentSubscription) {
        if (planNameEl) planNameEl.textContent = 'Free';
        if (aiUsageEl) aiUsageEl.textContent = 'AI: 0/25 used';
        if (uploadUsageEl) uploadUsageEl.textContent = 'Uploads: 0/5 used';
        if (prepUsageEl) prepUsageEl.textContent = 'Prep: 0/3 used';
        if (mockUsageEl) mockUsageEl.textContent = 'Mock: 0/2 used';
        if (sidebarUpgradeButton) {
            sidebarUpgradeButton.disabled = !PRO_UPGRADE_ENABLED;
            sidebarUpgradeButton.textContent = PRO_UPGRADE_ENABLED ? 'Upgrade to Pro' : 'Pro Coming Soon';
            sidebarUpgradeButton.style.opacity = PRO_UPGRADE_ENABLED ? '1' : '0.75';
            sidebarUpgradeButton.style.cursor = PRO_UPGRADE_ENABLED ? 'pointer' : 'not-allowed';
        }
        if (sidebarCancelButton) {
            sidebarCancelButton.style.display = 'none';
        }
        if (pricingUpgradeButton) {
            pricingUpgradeButton.disabled = !PRO_UPGRADE_ENABLED;
            pricingUpgradeButton.textContent = PRO_UPGRADE_ENABLED ? 'Upgrade to Pro' : 'Pro Coming Soon';
        }
        return;
    }

    const isPro = Boolean(currentSubscription.is_pro);
    const subscriptionStatus = (currentSubscription.status || '').toLowerCase();
    const planLabel = isPro ? 'Pro' : 'Free';

    if (planNameEl) {
        planNameEl.textContent = `${planLabel} Plan`;
    }
    if (aiUsageEl) {
        aiUsageEl.textContent = formatUsageText(
            currentSubscription.ai_messages_used,
            currentSubscription.ai_messages_limit,
            'AI'
        );
    }
    if (uploadUsageEl) {
        uploadUsageEl.textContent = formatUsageText(
            currentSubscription.document_uploads_used,
            currentSubscription.document_uploads_limit,
            'Uploads'
        );
    }
    if (prepUsageEl) {
        prepUsageEl.textContent = formatUsageText(
            currentSubscription.prep_sessions_used,
            currentSubscription.prep_sessions_limit,
            'Prep'
        );
    }
    if (mockUsageEl) {
        mockUsageEl.textContent = formatUsageText(
            currentSubscription.mock_interviews_used,
            currentSubscription.mock_interviews_limit,
            'Mock'
        );
    }

    if (sidebarUpgradeButton) {
        const canUpgrade = !isPro && PRO_UPGRADE_ENABLED;
        sidebarUpgradeButton.disabled = !canUpgrade;
        sidebarUpgradeButton.textContent = isPro ? 'You are on Pro' : (canUpgrade ? 'Upgrade to Pro' : 'Pro Coming Soon');
        sidebarUpgradeButton.style.opacity = canUpgrade || isPro ? '0.8' : '0.75';
        sidebarUpgradeButton.style.cursor = canUpgrade ? 'pointer' : 'not-allowed';
    }

    if (sidebarCancelButton) {
        const showCancel = isPro && subscriptionStatus === 'active';
        sidebarCancelButton.style.display = showCancel ? 'block' : 'none';
    }

    if (pricingUpgradeButton) {
        const canUpgrade = !isPro && PRO_UPGRADE_ENABLED;
        pricingUpgradeButton.disabled = !canUpgrade;
        pricingUpgradeButton.textContent = isPro ? 'You are on Pro' : (canUpgrade ? 'Upgrade to Pro' : 'Pro Coming Soon');
    }
}

async function handleUpgradeToPro() {
    if (!authToken) {
        showRegister();
        return;
    }

    if (proUpgradeInFlight) {
        return;
    }

    if (currentSubscription?.is_pro) {
        showMessage('Your account is already on Pro.', 'success');
        return;
    }

    if (!PRO_UPGRADE_ENABLED) {
        showMessage('Pro upgrades are coming soon. Payment integration is pending.', 'error');
        return;
    }

    proUpgradeInFlight = true;
    const dashboardUpgradeButton = document.getElementById('dashboardUpgradeButton');
    const pricingUpgradeButton = document.getElementById('pricingProUpgradeButton');
    const upgradeButtons = [dashboardUpgradeButton, pricingUpgradeButton].filter(Boolean);
    upgradeButtons.forEach((button) => {
        button.dataset.prevText = button.textContent;
        button.disabled = true;
        button.textContent = 'Opening checkout...';
    });

    try {
        const response = await fetch(`${API_BASE}/api/subscription/upgrade`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        const data = await response.json();
        if (!response.ok) {
            showMessage(data.detail || 'Failed to upgrade subscription', 'error');
            return;
        }

        if (data.action === 'already_pro') {
            currentSubscription = data.subscription || currentSubscription;
            updateSubscriptionUI();
            showMessage(data.message || 'Your account is already on Pro.', 'success');
            return;
        }

        if (data.action === 'contact_support') {
            showMessage(data.message || 'Pro billing is not available right now. Please contact support.', 'error');
            showContact();
            return;
        }

        if (data.action !== 'razorpay_checkout') {
            showMessage('Unable to start Pro checkout right now. Please try again.', 'error');
            return;
        }

        if (typeof window.Razorpay !== 'function') {
            showMessage('Razorpay Checkout failed to load. Please refresh and try again.', 'error');
            return;
        }

        const options = {
            key: data.key_id,
            name: data.name || 'Rilono',
            description: data.description || 'Rilono Pro Subscription',
            image: `${PUBLIC_APP_ORIGIN}/static/logo.png?v=1`,
            handler: async function (paymentResponse) {
                await verifyRazorpayPayment(paymentResponse, data.checkout_mode || 'order');
            },
            prefill: {
                name: currentUser?.full_name || '',
                email: currentUser?.email || ''
            },
            notes: {
                user_id: String(currentUser?.id || '')
            },
            theme: {
                color: '#7c5cff'
            },
            retry: {
                enabled: true,
                max_count: 2
            },
            remember_customer: true,
            modal: {
                confirm_close: true,
                backdropclose: false,
                escape: true,
                handleback: true,
                animation: true,
                ondismiss: function () {
                    showMessage('Payment cancelled.', 'error');
                }
            }
        };

        if ((data.checkout_mode || 'order') === 'subscription') {
            if (!data.subscription_id) {
                showMessage('Recurring checkout is temporarily unavailable. Please try again.', 'error');
                return;
            }
            options.subscription_id = data.subscription_id;
        } else {
            options.order_id = data.order_id;
            options.amount = data.amount;
            options.currency = data.currency;
        }

        const razorpay = new window.Razorpay(options);
        razorpay.on('payment.failed', function (event) {
            const reason = event?.error?.description || 'Payment failed. Please try again.';
            showMessage(reason, 'error');
        });

        const proceedToCheckout = await openCheckoutLaunchModal({
            amountPaise: data.amount,
            currency: data.currency,
            checkoutMode: data.checkout_mode || 'order'
        });
        if (!proceedToCheckout) {
            showMessage('Upgrade cancelled.', 'error');
            return;
        }

        razorpay.open();
    } catch (error) {
        console.error('Upgrade to pro failed:', error);
        showMessage('Failed to upgrade subscription. Please try again.', 'error');
    } finally {
        proUpgradeInFlight = false;
        updateSubscriptionUI();
        upgradeButtons.forEach((button) => {
            if (button.dataset.prevText) {
                delete button.dataset.prevText;
            }
        });
    }
}

function closeCheckoutLaunchModal(shouldProceed = false) {
    const modal = document.getElementById('checkoutLaunchModal');
    if (modal) {
        modal.style.display = 'none';
    }

    const resolver = checkoutLaunchResolver;
    checkoutLaunchResolver = null;
    if (resolver) {
        resolver(Boolean(shouldProceed));
    }
}

async function openCheckoutLaunchModal({ amountPaise, currency, checkoutMode }) {
    const modal = document.getElementById('checkoutLaunchModal');
    if (!modal) {
        return true;
    }

    const amountEl = document.getElementById('checkoutLaunchAmount');
    const modeEl = document.getElementById('checkoutLaunchMode');
    const continueBtn = document.getElementById('checkoutLaunchContinueBtn');

    if (!continueBtn) {
        return true;
    }

    const normalizedCurrency = (currency || 'INR').toUpperCase();
    const parsedAmount = Number(amountPaise);
    const amountValue = Number.isFinite(parsedAmount) && parsedAmount > 0 ? parsedAmount / 100 : PRO_PRICE_INR;
    if (amountEl) {
        amountEl.textContent = `${formatCurrencyAmount(amountValue, normalizedCurrency)} / month`;
    }

    if (modeEl) {
        modeEl.textContent = String(checkoutMode || '').toLowerCase() === 'subscription'
            ? 'Auto-renew enabled. Cancel anytime from Profile > Subscription.'
            : 'One-time checkout for your current billing cycle.';
    }

    modal.style.display = 'flex';

    return new Promise((resolve) => {
        checkoutLaunchResolver = resolve;
        continueBtn.onclick = () => closeCheckoutLaunchModal(true);
    });
}

async function upgradeToProFromPricing() {
    if (!authToken) {
        showRegister();
        return;
    }
    await handleUpgradeToPro();
}

async function verifyRazorpayPayment(paymentResponse, checkoutMode = 'order') {
    const mode = (checkoutMode || '').toLowerCase();
    const isRecurringMode = mode === 'subscription' || Boolean(paymentResponse?.razorpay_subscription_id);

    if (isRecurringMode) {
        if (!paymentResponse?.razorpay_subscription_id || !paymentResponse?.razorpay_payment_id || !paymentResponse?.razorpay_signature) {
            showMessage('Recurring payment response is incomplete. Please contact support.', 'error');
            return;
        }
    } else if (!paymentResponse?.razorpay_order_id || !paymentResponse?.razorpay_payment_id || !paymentResponse?.razorpay_signature) {
        showMessage('Payment response is incomplete. Please contact support.', 'error');
        return;
    }

    try {
        const endpoint = isRecurringMode
            ? `${API_BASE}/api/subscription/verify-recurring-payment`
            : `${API_BASE}/api/subscription/verify-payment`;
        const body = isRecurringMode
            ? {
                razorpay_subscription_id: paymentResponse.razorpay_subscription_id,
                razorpay_payment_id: paymentResponse.razorpay_payment_id,
                razorpay_signature: paymentResponse.razorpay_signature
            }
            : {
                razorpay_order_id: paymentResponse.razorpay_order_id,
                razorpay_payment_id: paymentResponse.razorpay_payment_id,
                razorpay_signature: paymentResponse.razorpay_signature
            };

        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify(body)
        });

        const data = await response.json();
        if (!response.ok) {
            showMessage(data.detail || 'Payment verification failed. Please contact support.', 'error');
            return;
        }

        currentSubscription = data;
        updateSubscriptionUI();
        showMessage(isRecurringMode
            ? 'Payment successful. Pro subscription activated with auto-renew.'
            : 'Payment successful. Pro subscription activated.', 'success');
        if (document.getElementById('pricingSection')?.style.display === 'block') {
            showPricing(true);
        }
    } catch (error) {
        console.error('Razorpay payment verification failed:', error);
        showMessage('Payment was received but verification failed. Please contact support.', 'error');
    }
}

async function handleCancelSubscription() {
    if (!authToken) {
        showLogin();
        return;
    }

    if (!currentSubscription?.is_pro) {
        showMessage('Your account is not on Pro.', 'error');
        return;
    }

    if (!confirm('Do you want to cancel your Pro subscription?')) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/subscription/cancel`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        const data = await response.json();
        if (!response.ok) {
            showMessage(data.detail || 'Failed to cancel subscription.', 'error');
            return;
        }
        currentSubscription = data;
        updateSubscriptionUI();
        showMessage('Auto-renew cancel request submitted. Your Pro access remains active until current cycle end.', 'success');
    } catch (error) {
        console.error('Subscription cancellation failed:', error);
        showMessage('Failed to cancel subscription. Please try again.', 'error');
    }
}

async function consumeInterviewSession(sessionType) {
    if (!authToken) {
        showLogin();
        return false;
    }
    try {
        const response = await fetch(`${API_BASE}/api/subscription/consume-session`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ session_type: sessionType })
        });
        const data = await response.json();
        if (!response.ok) {
            showMessage(data.detail || 'Session limit reached for your current plan.', 'error');
            if (response.status === 403) {
                showPricing();
            }
            return false;
        }
        currentSubscription = data;
        updateSubscriptionUI();
        return true;
    } catch (error) {
        console.error('Session quota check failed:', error);
        showMessage('Unable to validate session quota. Please try again.', 'error');
        return false;
    }
}

async function loadF1VisaNews(forceRefresh = false) {
    if (!authToken) return;

    const newsContainer = document.getElementById('newsContainer');
    const metaInfo = document.getElementById('newsMetaInfo');
    if (!newsContainer || !metaInfo) return;

    if (newsRequestInFlight) return;
    newsRequestInFlight = true;

    if (!forceRefresh) {
        newsContainer.innerHTML = '<div class="news-loading">Fetching latest F1 visa news...</div>';
    } else {
        metaInfo.textContent = 'Refreshing...';
    }

    try {
        const endpoint = forceRefresh
            ? `${API_BASE}/api/news/f1-latest?refresh=1`
            : `${API_BASE}/api/news/f1-latest`;
        const response = await fetch(endpoint, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to load news');
        }

        const items = Array.isArray(data.items) ? data.items : [];
        if (items.length === 0) {
            newsContainer.innerHTML = '<div class="news-loading">No recent F1 visa updates were found.</div>';
        } else {
            newsContainer.innerHTML = items.map((item) => {
                const title = escapeHtml(item.title || 'Update');
                const summary = escapeHtml(item.summary || '');
                const impact = escapeHtml(item.why_it_matters || '');
                const sourceName = escapeHtml(item.source_name || 'Source');
                const sourceUrl = item.source_url && (item.source_url.startsWith('http://') || item.source_url.startsWith('https://'))
                    ? item.source_url
                    : '';
                const safeSourceUrl = sourceUrl ? encodeURI(sourceUrl) : '';
                const publishedDate = escapeHtml(item.published_date || 'unknown');
                const sourceLink = safeSourceUrl
                    ? `<a href="${safeSourceUrl}" target="_blank" rel="noopener noreferrer" class="news-item-link">Read Source</a>`
                    : '<span class="news-item-link" style="opacity:0.6; cursor:not-allowed;">No Link</span>';

                return `
                    <article class="news-item">
                        <h4 class="news-item-title">${title}</h4>
                        <p class="news-item-summary">${summary}</p>
                        ${impact ? `<p class="news-item-impact"><strong>Why this matters:</strong> ${impact}</p>` : ''}
                        <div class="news-item-footer">
                            <div class="news-item-source">${sourceName} • ${publishedDate}</div>
                            ${sourceLink}
                        </div>
                    </article>
                `;
            }).join('');
        }

        const fetchedAt = data.fetched_at ? new Date(data.fetched_at) : null;
        const fetchedText = fetchedAt && !Number.isNaN(fetchedAt.getTime())
            ? fetchedAt.toLocaleString()
            : 'just now';
        const cacheText = data.cached ? 'cached' : 'fresh';
        metaInfo.textContent = `Last updated: ${fetchedText} (${cacheText})`;
    } catch (error) {
        console.error('Error loading F1 visa news:', error);
        newsContainer.innerHTML = '<div class="news-loading">Unable to load F1 visa news right now. Try refresh in a moment.</div>';
        metaInfo.textContent = 'Failed to load updates';
    } finally {
        newsRequestInFlight = false;
    }
}

function initializeVisaInterviewFilters() {
    const countrySelect = document.getElementById('visaExperienceCountry');
    const consulateContainer = document.getElementById('visaExperienceConsulates');
    if (!countrySelect || !consulateContainer) return;

    if (!visaInterviewFiltersInitialized) {
        countrySelect.innerHTML = Object.keys(VISA_INTERVIEW_CONSULATE_MAP)
            .map((country) => `<option value="${escapeHtml(country)}">${escapeHtml(country)}</option>`)
            .join('');
        visaInterviewFiltersInitialized = true;
    }

    const savedCountry = localStorage.getItem('visaExperienceCountry');
    const country = savedCountry && VISA_INTERVIEW_CONSULATE_MAP[savedCountry] ? savedCountry : 'India';
    countrySelect.value = country;

    const savedConsulates = JSON.parse(localStorage.getItem(`visaExperienceConsulates:${country}`) || '[]');
    renderVisaConsulateOptions(country, Array.isArray(savedConsulates) ? savedConsulates : []);

    const container = document.getElementById('visaExperienceContainer');
    const loaded = container?.dataset.loaded === '1';
    if (!loaded) {
        void loadF1InterviewExperiences(false);
    }
}

function renderVisaConsulateOptions(country, selectedConsulates = []) {
    const consulateContainer = document.getElementById('visaExperienceConsulates');
    if (!consulateContainer) return;

    const consulates = VISA_INTERVIEW_CONSULATE_MAP[country] || [];
    const defaultToAll = !Array.isArray(selectedConsulates) || selectedConsulates.length === 0;
    const selectedSet = new Set(defaultToAll ? consulates : selectedConsulates.filter((name) => consulates.includes(name)));

    consulateContainer.innerHTML = consulates.map((consulate, index) => {
        const isSelected = selectedSet.has(consulate);
        const safeConsulate = escapeHtml(consulate);
        const chipClass = isSelected ? 'visa-consulate-chip active' : 'visa-consulate-chip';
        return `
            <label class="${chipClass}">
                <input type="checkbox" class="visa-consulate-checkbox" value="${safeConsulate}" ${isSelected ? 'checked' : ''} onchange="handleVisaConsulateSelectionChange()">
                <span>${safeConsulate}</span>
            </label>
        `;
    }).join('');

    persistVisaConsulateSelection();
}

function getSelectedVisaConsulates() {
    return Array.from(document.querySelectorAll('#visaExperienceConsulates .visa-consulate-checkbox:checked'))
        .map((checkbox) => checkbox.value.trim())
        .filter(Boolean);
}

function persistVisaConsulateSelection() {
    const country = document.getElementById('visaExperienceCountry')?.value || 'India';
    const selected = getSelectedVisaConsulates();
    localStorage.setItem('visaExperienceCountry', country);
    localStorage.setItem(`visaExperienceConsulates:${country}`, JSON.stringify(selected));
}

function handleVisaConsulateSelectionChange() {
    document.querySelectorAll('#visaExperienceConsulates .visa-consulate-chip').forEach((chip) => {
        const checkbox = chip.querySelector('input[type="checkbox"]');
        if (!checkbox) return;
        chip.classList.toggle('active', checkbox.checked);
    });
    persistVisaConsulateSelection();
}

function toggleVisaConsulates(selectAll) {
    const checkboxes = document.querySelectorAll('#visaExperienceConsulates .visa-consulate-checkbox');
    checkboxes.forEach((checkbox) => {
        checkbox.checked = Boolean(selectAll);
    });
    handleVisaConsulateSelectionChange();
}

function handleVisaExperienceCountryChange(country) {
    if (!country || !VISA_INTERVIEW_CONSULATE_MAP[country]) return;
    localStorage.setItem('visaExperienceCountry', country);
    const savedConsulates = JSON.parse(localStorage.getItem(`visaExperienceConsulates:${country}`) || '[]');
    renderVisaConsulateOptions(country, Array.isArray(savedConsulates) ? savedConsulates : []);
}

async function loadF1InterviewExperiences(forceRefresh = false) {
    if (!authToken) return;

    const container = document.getElementById('visaExperienceContainer');
    const metaInfo = document.getElementById('visaExperienceMeta');
    const countrySelect = document.getElementById('visaExperienceCountry');
    if (!container || !metaInfo || !countrySelect) return;

    if (visaInterviewRequestInFlight) return;
    visaInterviewRequestInFlight = true;

    const country = countrySelect.value || 'India';
    const consulates = getSelectedVisaConsulates();
    if (consulates.length === 0) {
        showMessage('Select at least one consulate to fetch experiences.', 'error');
        visaInterviewRequestInFlight = false;
        return;
    }
    persistVisaConsulateSelection();

    if (!forceRefresh) {
        container.innerHTML = '<div class="news-loading">Fetching latest interview experiences...</div>';
    } else {
        metaInfo.textContent = 'Refreshing interview experiences...';
    }

    try {
        const params = new URLSearchParams();
        params.set('country', country);
        consulates.forEach((consulate) => params.append('consulates', consulate));
        if (forceRefresh) params.set('refresh', '1');

        const response = await fetch(`${API_BASE}/api/news/f1-interview-experiences?${params.toString()}`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to load interview experiences');
        }

        const items = Array.isArray(data.items) ? data.items : [];
        if (items.length === 0) {
            container.innerHTML = '<div class="news-loading">No interview experiences found for the selected filters right now.</div>';
            delete container.dataset.loaded;
        } else {
            container.innerHTML = items.map((item) => {
                const consulate = escapeHtml(item.consulate || 'Consulate');
                const result = escapeHtml(item.interview_result || 'Reported');
                const summary = escapeHtml(item.summary || '');
                const keyTakeaway = escapeHtml(item.key_takeaway || '');
                const platform = escapeHtml(item.platform || 'Community');
                const sourceName = escapeHtml(item.source_name || 'Source');
                const reportedDate = escapeHtml(item.reported_date || 'unknown');
                const sourceUrl = item.source_url && (item.source_url.startsWith('http://') || item.source_url.startsWith('https://'))
                    ? encodeURI(item.source_url)
                    : '';
                const sourceLink = sourceUrl
                    ? `<a href="${sourceUrl}" target="_blank" rel="noopener noreferrer">Open Source</a>`
                    : '<span style="opacity:0.6;">No Source Link</span>';

                return `
                    <article class="visa-experience-item">
                        <div class="visa-experience-title">${consulate} • ${result}</div>
                        <div class="visa-experience-note">${summary || 'No summary available.'}</div>
                        ${keyTakeaway ? `<div class="visa-experience-note"><strong>Key takeaway:</strong> ${keyTakeaway}</div>` : ''}
                        <div class="visa-experience-badges">
                            <span class="visa-experience-badge">${platform}</span>
                        </div>
                        <div class="visa-experience-source">
                            <span>${sourceName} • ${reportedDate}</span>
                            ${sourceLink}
                        </div>
                    </article>
                `;
            }).join('');
            container.dataset.loaded = '1';
        }

        const fetchedAt = data.fetched_at ? new Date(data.fetched_at) : null;
        const fetchedText = fetchedAt && !Number.isNaN(fetchedAt.getTime())
            ? fetchedAt.toLocaleString()
            : 'just now';
        const cacheText = data.cached ? 'cached' : 'fresh';
        metaInfo.textContent = `${country} • ${consulates.length} consulate(s) • Updated ${fetchedText} (${cacheText})`;
    } catch (error) {
        console.error('Error loading F1 interview experiences:', error);
        container.innerHTML = '<div class="news-loading">Unable to load interview experiences right now. Try again shortly.</div>';
        metaInfo.textContent = 'Failed to load interview experiences';
    } finally {
        visaInterviewRequestInFlight = false;
    }
}

function getSpeechRecognitionConstructor() {
    return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function stripMarkdownForSpeech(text) {
    return String(text || '')
        .replace(/\[(.*?)\]\((.*?)\)/g, '$1')
        .replace(/[`*_>#-]/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
}

function getVisaInterviewSessionConfig(mode) {
    if (mode === 'prep') {
        return {
            statusId: 'visaPrepInterviewStatus',
            logId: 'visaPrepInterviewLog',
            startSelector: '#visaPrepStartBtn',
            speakId: 'visaPrepSpeakBtn',
            stopId: 'visaPrepStopBtn',
            finishId: null,
            assistantLabel: 'Prep Coach'
        };
    }
    return {
        statusId: 'visaMockInterviewStatus',
        logId: 'visaMockInterviewLog',
        startSelector: '#visaMockStartBtn',
        speakId: 'visaMockSpeakBtn',
        stopId: null,
        finishId: 'visaMockFinishBtn',
        assistantLabel: 'Visa Officer'
    };
}

function getVisaInterviewState(mode) {
    return mode === 'prep' ? visaPrepInterviewState : visaMockInterviewState;
}

function setVisaInterviewStatus(mode, statusText) {
    const cfg = getVisaInterviewSessionConfig(mode);
    const statusEl = document.getElementById(cfg.statusId);
    if (statusEl) {
        statusEl.textContent = statusText;
    }
}

function formatPrepInterviewLogHtml(text) {
    const raw = String(text || '').replace(/\r/g, '').trim();
    if (!raw) return '';

    // Add visible breaks before major coaching blocks for better readability.
    const normalized = raw
        .replace(/\s*(\*\*?Feedback:\*\*?)/gi, '\n$1')
        .replace(/\s*(\*\*?Improve:\*\*?)/gi, '\n$1')
        .replace(/\s*(\*\*?Next Question:\*\*?)/gi, '\n$1');

    return markdownToHtml(normalized);
}

function appendVisaInterviewLog(mode, role, text) {
    const cfg = getVisaInterviewSessionConfig(mode);
    const logEl = document.getElementById(cfg.logId);
    if (!logEl) return;

    const item = document.createElement('div');
    item.className = `visa-mock-log-item ${role}`;
    if (mode === 'prep' && role === 'assistant') {
        item.innerHTML = formatPrepInterviewLogHtml(text);
    } else {
        item.textContent = text;
    }
    logEl.appendChild(item);
    logEl.scrollTop = logEl.scrollHeight;
}

function upsertVisaInterviewPendingBubble(mode, text) {
    const cfg = getVisaInterviewSessionConfig(mode);
    const logEl = document.getElementById(cfg.logId);
    if (!logEl) return;

    let pendingItem = logEl.querySelector('.visa-mock-log-item.pending');
    if (!pendingItem) {
        pendingItem = document.createElement('div');
        pendingItem.className = 'visa-mock-log-item assistant pending';
        logEl.appendChild(pendingItem);
    }
    pendingItem.textContent = text;
    logEl.scrollTop = logEl.scrollHeight;
}

function clearVisaInterviewPendingBubble(mode) {
    const cfg = getVisaInterviewSessionConfig(mode);
    const logEl = document.getElementById(cfg.logId);
    if (!logEl) return;
    logEl.querySelectorAll('.visa-mock-log-item.pending').forEach((node) => node.remove());
}

function updateVisaInterviewControls(mode) {
    const cfg = getVisaInterviewSessionConfig(mode);
    const state = getVisaInterviewState(mode);
    const startBtn = document.querySelector(cfg.startSelector);
    const speakBtn = document.getElementById(cfg.speakId);
    const stopBtn = document.getElementById(cfg.stopId);
    const finishBtn = cfg.finishId ? document.getElementById(cfg.finishId) : null;
    const speechSupported = Boolean(getSpeechRecognitionConstructor());

    if (startBtn) {
        if (mode === 'mock' || mode === 'prep') {
            startBtn.disabled = state.active || state.pending;
        } else {
            startBtn.disabled = !speechSupported || state.active || state.pending;
        }
    }
    if (speakBtn) {
        if (mode === 'mock' || mode === 'prep') {
            const voiceMode = state.channel === 'voice';
            speakBtn.disabled = !speechSupported || !voiceMode || !state.active || state.pending || state.listening;
        } else {
            speakBtn.disabled = !speechSupported || !state.active || state.pending || state.listening;
        }
    }
    if (stopBtn) {
        stopBtn.disabled = !state.active && !state.pending;
    }
    if (finishBtn) {
        finishBtn.disabled = state.pending || (!state.active && state.history.length === 0);
    }
    if (mode === 'mock') {
        renderMockInterviewModeUI();
    } else if (mode === 'prep') {
        renderPrepInterviewModeUI();
    }
}

function renderMockInterviewModeUI() {
    const modePicker = document.getElementById('visaMockModePicker');
    const chatComposer = document.getElementById('visaMockChatComposer');
    const chatInput = document.getElementById('visaMockChatInput');
    const chatSendBtn = document.getElementById('visaMockChatSendBtn');
    const startBtn = document.getElementById('visaMockStartBtn');
    const secondaryControls = document.getElementById('visaMockSecondaryControls');
    const speakBtn = document.getElementById('visaMockSpeakBtn');
    const modeBadge = document.getElementById('visaMockModeBadge');
    const guide = document.getElementById('visaMockInterviewGuide');
    const state = visaMockInterviewState;
    if (!modePicker || !chatComposer || !chatInput || !chatSendBtn || !startBtn || !secondaryControls || !speakBtn || !modeBadge || !guide) {
        return;
    }

    if (!chatInput.dataset.boundMockInput) {
        chatInput.addEventListener('input', () => renderMockInterviewModeUI());
        chatInput.dataset.boundMockInput = '1';
    }

    const showPicker = !state.active && !state.pending && state.showModePicker;
    modePicker.style.display = showPicker ? 'grid' : 'none';
    const showSecondaryControls = state.active || state.pending || state.history.length > 0;
    secondaryControls.style.display = showSecondaryControls ? 'flex' : 'none';
    startBtn.textContent = state.active
        ? 'Interview Running'
        : (showPicker ? 'Cancel Mode Selection' : (state.history.length > 0 ? 'Start New Interview' : 'Start Interview'));

    const chatModeActive = state.active && state.channel === 'chat';
    chatComposer.style.display = chatModeActive ? 'flex' : 'none';
    chatInput.disabled = !chatModeActive || state.pending;
    chatSendBtn.disabled = !chatModeActive || state.pending || !chatInput.value.trim();
    speakBtn.style.display = state.channel === 'chat' && state.active ? 'none' : 'inline-flex';

    if (state.channel === 'voice') {
        modeBadge.textContent = 'Mode: Voice';
        modeBadge.classList.remove('visa-hub-tag-mode-chat');
        modeBadge.classList.add('visa-hub-tag-mode-voice');
        guide.textContent = state.active
            ? 'Use Speak Answer for each response. The AI officer ends the interview automatically.'
            : 'Click Start Interview and choose Voice to run a microphone-based simulation.';
    } else if (state.channel === 'chat') {
        modeBadge.textContent = 'Mode: Chat';
        modeBadge.classList.remove('visa-hub-tag-mode-voice');
        modeBadge.classList.add('visa-hub-tag-mode-chat');
        guide.textContent = state.active
            ? 'Type each answer in the input below. The AI officer ends the interview automatically.'
            : 'Click Start Interview and choose Chat to run a typed interview simulation.';
    } else {
        modeBadge.textContent = 'Mode: not selected';
        modeBadge.classList.remove('visa-hub-tag-mode-voice', 'visa-hub-tag-mode-chat');
        guide.textContent = 'Click Start Interview, choose Voice or Chat, then proceed question by question. The AI officer closes the interview when complete.';
    }

    if (chatModeActive && !state.pending) {
        requestAnimationFrame(() => chatInput.focus());
    }
}

function renderPrepInterviewModeUI() {
    const modePicker = document.getElementById('visaPrepModePicker');
    const chatComposer = document.getElementById('visaPrepChatComposer');
    const chatInput = document.getElementById('visaPrepChatInput');
    const chatSendBtn = document.getElementById('visaPrepChatSendBtn');
    const startBtn = document.getElementById('visaPrepStartBtn');
    const secondaryControls = document.getElementById('visaPrepSecondaryControls');
    const speakBtn = document.getElementById('visaPrepSpeakBtn');
    const modeBadge = document.getElementById('visaPrepModeBadge');
    const guide = document.getElementById('visaPrepInterviewGuide');
    const state = visaPrepInterviewState;
    if (!modePicker || !chatComposer || !chatInput || !chatSendBtn || !startBtn || !secondaryControls || !speakBtn || !modeBadge || !guide) {
        return;
    }

    if (!chatInput.dataset.boundPrepInput) {
        chatInput.addEventListener('input', () => renderPrepInterviewModeUI());
        chatInput.dataset.boundPrepInput = '1';
    }

    const showPicker = !state.active && !state.pending && state.showModePicker;
    modePicker.style.display = showPicker ? 'grid' : 'none';
    const showSecondaryControls = state.active || state.pending || state.history.length > 0;
    secondaryControls.style.display = showSecondaryControls ? 'flex' : 'none';
    startBtn.textContent = state.active
        ? 'Prep Running'
        : (showPicker ? 'Cancel Mode Selection' : (state.history.length > 0 ? 'Start New Prep Session' : 'Start Prep Session'));

    const chatModeActive = state.active && state.channel === 'chat';
    chatComposer.style.display = chatModeActive ? 'flex' : 'none';
    chatInput.disabled = !chatModeActive || state.pending;
    chatSendBtn.disabled = !chatModeActive || state.pending || !chatInput.value.trim();
    speakBtn.style.display = state.channel === 'chat' && state.active ? 'none' : 'inline-flex';

    if (state.channel === 'voice') {
        modeBadge.textContent = 'Mode: Voice';
        modeBadge.classList.remove('visa-hub-tag-mode-chat');
        modeBadge.classList.add('visa-hub-tag-mode-voice');
        guide.textContent = state.active
            ? 'Use Speak Answer for each response. Rilono AI will coach and ask the next question.'
            : 'Click Start Prep Session and choose Voice to practice with microphone input.';
    } else if (state.channel === 'chat') {
        modeBadge.textContent = 'Mode: Chat';
        modeBadge.classList.remove('visa-hub-tag-mode-voice');
        modeBadge.classList.add('visa-hub-tag-mode-chat');
        guide.textContent = state.active
            ? 'Type each answer below. Rilono AI gives feedback and improvement on every turn.'
            : 'Click Start Prep Session and choose Chat to practice in typed mode.';
    } else {
        modeBadge.textContent = 'Mode: not selected';
        modeBadge.classList.remove('visa-hub-tag-mode-voice', 'visa-hub-tag-mode-chat');
        guide.textContent = 'Choose Voice or Chat mode to start your prep session. You will get feedback after each answer.';
    }

    if (chatModeActive && !state.pending) {
        requestAnimationFrame(() => chatInput.focus());
    }
}

function initializeVisaInterviewUI(mode) {
    const cfg = getVisaInterviewSessionConfig(mode);
    const state = getVisaInterviewState(mode);
    const logEl = document.getElementById(cfg.logId);
    if (!logEl) return;

    const speechSupported = Boolean(getSpeechRecognitionConstructor());
    if (!speechSupported && state.channel === 'voice') {
        setVisaInterviewStatus(mode, 'Mic Unsupported');
        appendVisaInterviewLog(mode, 'system', 'Voice input is not supported in this browser. Use Chrome/Edge for mic-based interview mode.');
    } else if (!state.active && !state.pending) {
        setVisaInterviewStatus(mode, 'Idle');
    }
    updateVisaInterviewControls(mode);
}

function initializeVisaPrepInterviewUI() {
    initializeVisaInterviewUI('prep');
}

function initializeVisaMockInterviewUI() {
    initializeVisaInterviewUI('mock');
}

function stopVisaInterviewRecognition(mode) {
    const state = getVisaInterviewState(mode);
    if (state.recognition) {
        try {
            state.recognition.onresult = null;
            state.recognition.onerror = null;
            state.recognition.onend = null;
            state.recognition.stop();
        } catch (error) {
            // no-op
        }
        state.recognition = null;
    }
    state.listening = false;
}

async function speakVisaInterviewResponse(text) {
    const utteranceText = stripMarkdownForSpeech(text);
    if (!utteranceText || !window.speechSynthesis) {
        return;
    }

    await new Promise((resolve) => {
        try {
            window.speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance(utteranceText);
            utterance.lang = 'en-US';
            utterance.rate = 1;
            utterance.pitch = 1;

            const voices = window.speechSynthesis.getVoices();
            const preferredVoice = voices.find((voice) => voice.lang && voice.lang.toLowerCase().startsWith('en-us'));
            if (preferredVoice) {
                utterance.voice = preferredVoice;
            }

            utterance.onend = () => resolve();
            utterance.onerror = () => resolve();
            window.speechSynthesis.speak(utterance);
        } catch (error) {
            resolve();
        }
    });
}

function listenVisaInterviewAnswer(mode) {
    const cfg = getVisaInterviewSessionConfig(mode);
    const state = getVisaInterviewState(mode);
    if (!state.active || state.pending) {
        return;
    }

    const SpeechRecognitionCtor = getSpeechRecognitionConstructor();
    if (!SpeechRecognitionCtor) {
        showMessage('Voice recognition is not supported in this browser.', 'error');
        return;
    }

    stopVisaInterviewRecognition(mode);
    const recognition = new SpeechRecognitionCtor();
    state.recognition = recognition;
    recognition.lang = 'en-US';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.continuous = false;

    recognition.onstart = () => {
        state.listening = true;
        setVisaInterviewStatus(mode, 'Listening...');
        updateVisaInterviewControls(mode);
    };

    recognition.onerror = (event) => {
        state.listening = false;
        updateVisaInterviewControls(mode);
        if (!state.active) return;
        if (event.error === 'no-speech') {
            setVisaInterviewStatus(mode, 'No speech detected');
            appendVisaInterviewLog(mode, 'system', 'No speech detected. Click "Speak Answer" and try again.');
            return;
        }
        setVisaInterviewStatus(mode, 'Mic error');
        appendVisaInterviewLog(mode, 'system', `Mic error: ${event.error}. Try again.`);
    };

    recognition.onend = () => {
        state.listening = false;
        updateVisaInterviewControls(mode);
        if (state.active && !state.pending) {
            setVisaInterviewStatus(mode, 'Ready for answer');
        }
    };

    recognition.onresult = async (event) => {
        const transcript = event?.results?.[0]?.[0]?.transcript?.trim() || '';
        if (!transcript) {
            setVisaInterviewStatus(mode, 'No speech detected');
            return;
        }
        appendVisaInterviewLog(mode, 'user', `Student: ${transcript}`);
        await sendVisaInterviewTurn(mode, transcript, false);
    };

    try {
        recognition.start();
    } catch (error) {
        state.listening = false;
        updateVisaInterviewControls(mode);
        setVisaInterviewStatus(mode, 'Mic start failed');
        appendVisaInterviewLog(mode, 'system', 'Could not start microphone. Click "Speak Answer" again and allow mic permission.');
    }
}

function listenPrepInterviewAnswer() {
    listenVisaInterviewAnswer('prep');
}

function listenMockInterviewAnswer() {
    listenVisaInterviewAnswer('mock');
}

async function sendVisaInterviewTurn(mode, studentMessage, isInitialTurn) {
    const cfg = getVisaInterviewSessionConfig(mode);
    const state = getVisaInterviewState(mode);
    if (!state.active || state.pending) {
        return;
    }

    if (mode === 'mock' && !isInitialTurn && /end interview/i.test(studentMessage)) {
        state.history.push({ role: 'user', content: studentMessage });
        await finishVoiceMockInterview();
        return;
    }

    state.pending = true;
    const waitingStatus = state.channel === 'chat' ? 'VO is typing...' : 'VO is thinking...';
    setVisaInterviewStatus(mode, waitingStatus);
    upsertVisaInterviewPendingBubble(mode, waitingStatus);
    updateVisaInterviewControls(mode);

    const initialTurnPrompt = mode === 'prep'
        ? 'Start the prep session now. Ask the first F-1 interview question.'
        : 'Start the mock interview now. Ask your first visa-officer question only.';
    const instruction = mode === 'prep' ? VISA_PREP_INTERVIEW_INSTRUCTION : VISA_MOCK_INTERVIEW_INSTRUCTION;
    const userTurnContent = isInitialTurn ? initialTurnPrompt : `Student answer: ${studentMessage}`;
    const geminiMessage = `${instruction}\n\n${userTurnContent}`;

    const conversationHistory = state.history.slice(-14);
    conversationHistory.push({
        role: 'user',
        content: studentMessage
    });

    let shouldAutoFinish = false;

    try {
        const response = await fetch(`${API_BASE}/api/ai-chat/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                message: geminiMessage,
                conversation_history: conversationHistory
            })
        });

        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            if (response.status === 403) {
                void loadSubscriptionStatus(true);
            }
            throw new Error(data.detail || 'Failed to get mock interview response');
        }

        const data = await response.json();
        const rawAiResponse = data.response || 'I could not generate a response right now.';
        const completionDetected = mode === 'mock' && /INTERVIEW_COMPLETE/i.test(rawAiResponse);
        const cleanedAiResponse = mode === 'mock'
            ? rawAiResponse.replace(/INTERVIEW_COMPLETE/gi, '').trim()
            : rawAiResponse;
        const aiResponse = cleanedAiResponse || (completionDetected ? 'Thank you. This interview is complete.' : 'I could not generate a response right now.');

        state.history.push({ role: 'user', content: studentMessage });
        state.history.push({ role: 'assistant', content: aiResponse });
        if (state.history.length > 40) {
            state.history = state.history.slice(-40);
        }

        clearVisaInterviewPendingBubble(mode);
        appendVisaInterviewLog(mode, 'assistant', `${cfg.assistantLabel}: ${aiResponse}`);
        const isChatMode = state.channel === 'chat' && (mode === 'mock' || mode === 'prep');
        if (!isChatMode) {
            await speakVisaInterviewResponse(aiResponse);
        }
        void loadSubscriptionStatus(true);

        if (mode === 'mock' && completionDetected) {
            state.active = false;
            setVisaInterviewStatus('mock', 'Interview complete');
            appendVisaInterviewLog('mock', 'system', 'Interview completed by Visa Officer. Generating final report...');
            shouldAutoFinish = true;
        } else if (state.active) {
            if (state.channel === 'chat' && (mode === 'mock' || mode === 'prep')) {
                setVisaInterviewStatus(mode, 'Type your answer');
                if (mode === 'mock') {
                    renderMockInterviewModeUI();
                } else {
                    renderPrepInterviewModeUI();
                }
            } else {
                setVisaInterviewStatus(mode, 'Speak your answer');
                listenVisaInterviewAnswer(mode);
            }
        }
    } catch (error) {
        console.error('Voice interview error:', error);
        clearVisaInterviewPendingBubble(mode);
        appendVisaInterviewLog(mode, 'system', `Error: ${error.message || 'Unable to continue this session.'}`);
        setVisaInterviewStatus(mode, 'Error');
    } finally {
        clearVisaInterviewPendingBubble(mode);
        state.pending = false;
        updateVisaInterviewControls(mode);
        if (mode === 'mock' && shouldAutoFinish) {
            await finishVoiceMockInterview();
        }
    }
}

function buildVisaInterviewTranscript(history) {
    return history
        .map((turn) => {
            const role = turn.role === 'assistant' ? 'Officer' : 'Student';
            return `${role}: ${turn.content}`;
        })
        .join('\n');
}

function normalizeMockInterviewReportText(reportText) {
    return String(reportText || '')
        .replace(/\r/g, '')
        .replace(/^\s*---+\s*$/gm, '')
        .replace(/\*\*/g, '')
        .replace(/^(\s*)\*\s+/gm, '$1- ')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
}

function buildMockInterviewReportHtml(reportText) {
    const text = normalizeMockInterviewReportText(reportText);
    if (!text) {
        return '<p class="visa-mock-report-paragraph">No report content available.</p>';
    }

    const lines = text.split('\n');
    const htmlParts = [];
    const metricCards = [];
    let listItems = [];

    const flushList = () => {
        if (!listItems.length) return;
        htmlParts.push(`<ul class="visa-mock-report-list">${listItems.join('')}</ul>`);
        listItems = [];
    };

    for (const rawLine of lines) {
        const line = rawLine.trim();
        if (!line) {
            flushList();
            continue;
        }

        let normalized = line
            .replace(/^\d+\)\s*/, '')
            .replace(/^\d+\.\s*/, '')
            .trim();

        const metricMatch = normalized.match(/^(Approval Probability|Rejection Probability)\s*:?\s*(\d{1,3})%/i);
        if (metricMatch) {
            flushList();
            metricCards.push(
                `<div class="visa-mock-report-metric-card">` +
                `<div class="visa-mock-report-metric-label">${escapeHtml(metricMatch[1])}</div>` +
                `<div class="visa-mock-report-metric-value">${escapeHtml(metricMatch[2])}%</div>` +
                `</div>`
            );
            continue;
        }

        if (/^[-•]\s+/.test(normalized)) {
            normalized = normalized.replace(/^[-•]\s+/, '').trim();
            if (normalized) {
                listItems.push(`<li>${escapeHtml(normalized)}</li>`);
            }
            continue;
        }

        if (/^(Decision Drivers|Strengths|Risk Areas|Top Improvements Before Real Interview|Rilono AI Note)/i.test(normalized)) {
            flushList();
            htmlParts.push(`<h4 class="visa-mock-report-section-title">${escapeHtml(normalized)}</h4>`);
            continue;
        }

        flushList();
        htmlParts.push(`<p class="visa-mock-report-paragraph">${escapeHtml(normalized)}</p>`);
    }

    flushList();

    const metricHtml = metricCards.length
        ? `<div class="visa-mock-report-metrics">${metricCards.join('')}</div>`
        : '';

    return `${metricHtml}${htmlParts.join('')}`;
}

function renderVisaMockInterviewReport(reportText) {
    const reportEl = document.getElementById('visaMockInterviewReport');
    if (!reportEl) return;
    reportEl.style.display = 'block';
    reportEl.innerHTML = `
        <div class="visa-mock-report-title">Final Interview Report</div>
        <div class="visa-mock-report-body">${buildMockInterviewReportHtml(reportText)}</div>
    `;
}

async function finishVoiceMockInterview() {
    const state = visaMockInterviewState;
    if (state.pending) {
        return;
    }
    if (state.history.length === 0) {
        showMessage('No mock interview history found. Start the interview first.', 'error');
        return;
    }

    stopVisaInterviewRecognition('mock');
    state.active = false;
    state.pending = true;
    setVisaInterviewStatus('mock', 'Generating final report...');
    updateVisaInterviewControls('mock');
    appendVisaInterviewLog('mock', 'system', 'Interview completed. Generating final approval/rejection report...');

    try {
        const transcript = buildVisaInterviewTranscript(state.history);
        const reportPrompt = `${VISA_MOCK_REPORT_INSTRUCTION}\n\nInterview transcript:\n${transcript}`;
        const response = await fetch(`${API_BASE}/api/ai-chat/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                message: reportPrompt,
                conversation_history: []
            })
        });

        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            if (response.status === 403) {
                void loadSubscriptionStatus(true);
            }
            throw new Error(data.detail || 'Failed to generate interview report');
        }

        const data = await response.json();
        const report = data.response || 'Could not generate a report right now.';
        renderVisaMockInterviewReport(report);
        appendVisaInterviewLog('mock', 'assistant', 'Visa Officer: Final report is ready below.');
        void loadSubscriptionStatus(true);
    } catch (error) {
        console.error('Mock report generation error:', error);
        appendVisaInterviewLog('mock', 'system', `Error: ${error.message || 'Unable to generate final report.'}`);
        setVisaInterviewStatus('mock', 'Report error');
    } finally {
        state.pending = false;
        if (window.speechSynthesis) {
            window.speechSynthesis.cancel();
        }
        if (state.history.length > 0) {
            setVisaInterviewStatus('mock', 'Completed');
        }
        updateVisaInterviewControls('mock');
    }
}

function openMockInterviewModePicker() {
    const state = visaMockInterviewState;
    if (state.active || state.pending) {
        return;
    }
    state.showModePicker = !state.showModePicker;
    renderMockInterviewModeUI();
}

function handleMockChatInputKeydown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        void sendMockInterviewChatAnswer();
    }
}

async function sendMockInterviewChatAnswer() {
    const state = visaMockInterviewState;
    if (!state.active || state.pending || state.channel !== 'chat') {
        return;
    }

    const input = document.getElementById('visaMockChatInput');
    if (!input) {
        return;
    }

    const answer = input.value.trim();
    if (!answer) {
        return;
    }

    input.value = '';
    appendVisaInterviewLog('mock', 'user', `Student: ${answer}`);
    renderMockInterviewModeUI();
    await sendVisaInterviewTurn('mock', answer, false);
}

async function beginMockInterview(channel) {
    if (channel !== 'voice' && channel !== 'chat') {
        return;
    }
    visaMockInterviewState.channel = channel;
    visaMockInterviewState.showModePicker = false;
    renderMockInterviewModeUI();
    await startVoiceInterviewSession('mock', { channel });
}

function openPrepInterviewModePicker() {
    const state = visaPrepInterviewState;
    if (state.active || state.pending) {
        return;
    }
    state.showModePicker = !state.showModePicker;
    renderPrepInterviewModeUI();
}

function handlePrepChatInputKeydown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        void sendPrepInterviewChatAnswer();
    }
}

async function sendPrepInterviewChatAnswer() {
    const state = visaPrepInterviewState;
    if (!state.active || state.pending || state.channel !== 'chat') {
        return;
    }

    const input = document.getElementById('visaPrepChatInput');
    if (!input) {
        return;
    }

    const answer = input.value.trim();
    if (!answer) {
        return;
    }

    input.value = '';
    appendVisaInterviewLog('prep', 'user', `Student: ${answer}`);
    renderPrepInterviewModeUI();
    await sendVisaInterviewTurn('prep', answer, false);
}

async function beginPrepInterview(channel) {
    if (channel !== 'voice' && channel !== 'chat') {
        return;
    }
    visaPrepInterviewState.channel = channel;
    visaPrepInterviewState.showModePicker = false;
    renderPrepInterviewModeUI();
    await startVoiceInterviewSession('prep', { channel });
}

async function startVoiceInterviewSession(mode, options = {}) {
    const state = getVisaInterviewState(mode);
    const cfg = getVisaInterviewSessionConfig(mode);
    if (!authToken) {
        showMessage('Please login to start this interview session.', 'error');
        return;
    }

    const useVoiceInput = options.channel === 'voice';
    const SpeechRecognitionCtor = getSpeechRecognitionConstructor();
    if (useVoiceInput && !SpeechRecognitionCtor) {
        showMessage('Voice recognition is not supported in this browser. Use Chrome/Edge.', 'error');
        initializeVisaInterviewUI(mode);
        return;
    }

    const sessionType = mode === 'prep' ? 'prep' : 'mock';
    const quotaAllowed = await consumeInterviewSession(sessionType);
    if (!quotaAllowed) {
        initializeVisaInterviewUI(mode);
        return;
    }

    if (mode === 'prep') {
        stopVoicePrepInterview(true);
        state.channel = options.channel || 'voice';
        state.showModePicker = false;
    } else {
        stopVoiceMockInterview(true);
        state.channel = options.channel || 'voice';
        state.showModePicker = false;
    }

    state.active = true;
    state.pending = false;
    state.history = [];

    const logEl = document.getElementById(cfg.logId);
    if (logEl) {
        logEl.innerHTML = '';
    }
    if (mode === 'prep') {
        appendVisaInterviewLog('prep', 'system', 'Prep session started. Rilono AI will coach your answer after every question.');
    } else {
        const reportEl = document.getElementById('visaMockInterviewReport');
        if (reportEl) {
            reportEl.style.display = 'none';
            reportEl.innerHTML = '';
        }
        appendVisaInterviewLog('mock', 'system', 'Session started. Rilono AI is now acting as your Visa Officer.');
    }

    setVisaInterviewStatus(mode, 'Starting interview...');
    updateVisaInterviewControls(mode);
    const readyMessage = mode === 'prep'
        ? 'I am ready for my F-1 interview prep session.'
        : 'I am ready for my F-1 visa mock interview.';
    await sendVisaInterviewTurn(mode, readyMessage, true);
}

async function startVoicePrepInterview() {
    await beginPrepInterview('voice');
}

async function startVoiceMockInterview() {
    await beginMockInterview('voice');
}

function stopVoiceMockInterview(silent = false) {
    clearVisaInterviewPendingBubble('mock');
    stopVisaInterviewRecognition('mock');
    visaMockInterviewState.active = false;
    visaMockInterviewState.pending = false;
    visaMockInterviewState.channel = null;
    visaMockInterviewState.showModePicker = false;
    if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
    }
    setVisaInterviewStatus('mock', 'Stopped');
    updateVisaInterviewControls('mock');
    if (!silent) {
        appendVisaInterviewLog('mock', 'system', 'Session stopped. Click "Finish & Report" to generate the final result.');
    }
}

function stopVoicePrepInterview(silent = false) {
    clearVisaInterviewPendingBubble('prep');
    stopVisaInterviewRecognition('prep');
    visaPrepInterviewState.active = false;
    visaPrepInterviewState.pending = false;
    visaPrepInterviewState.channel = null;
    visaPrepInterviewState.showModePicker = false;
    if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
    }
    setVisaInterviewStatus('prep', 'Stopped');
    updateVisaInterviewControls('prep');
    if (!silent) {
        appendVisaInterviewLog('prep', 'system', 'Prep session stopped.');
    }
}

function setVisaSubNavVisibility(isVisible) {
    const subNav = document.getElementById('visaSubNav');
    if (subNav) {
        subNav.style.display = isVisible ? 'grid' : 'none';
    }

    const visaNavItem = document.querySelector('.nav-item[data-tab="visa"]');
    if (visaNavItem) {
        visaNavItem.classList.toggle('expanded', isVisible);
    }

    const caret = document.getElementById('visaNavCaret');
    if (caret) {
        caret.textContent = isVisible ? '▴' : '▾';
    }
}

function switchVisaSubTab(subTab) {
    const validSubTabs = ['prep', 'mock', 'experiences'];
    const targetSubTab = validSubTabs.includes(subTab) ? subTab : 'prep';

    if (currentVisaSubTab === 'mock' && targetSubTab !== 'mock' && (visaMockInterviewState.active || visaMockInterviewState.listening || visaMockInterviewState.pending)) {
        stopVoiceMockInterview(true);
    }
    if (currentVisaSubTab === 'prep' && targetSubTab !== 'prep' && (visaPrepInterviewState.active || visaPrepInterviewState.listening || visaPrepInterviewState.pending)) {
        stopVoicePrepInterview(true);
    }

    currentVisaSubTab = targetSubTab;

    document.querySelectorAll('.visa-subnav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.visaSubtab === targetSubTab);
    });

    document.querySelectorAll('.visa-subtab-panel').forEach(panel => {
        panel.classList.remove('active');
    });

    const selectedPanel = document.getElementById(`visaSubTab-${targetSubTab}`);
    if (selectedPanel) {
        selectedPanel.classList.add('active');
    }

    if (targetSubTab === 'experiences') {
        initializeVisaInterviewFilters();
    }

    if (targetSubTab === 'prep') {
        initializeVisaPrepInterviewUI();
    }

    if (targetSubTab === 'mock') {
        initializeVisaMockInterviewUI();
    }
}

function openVisaSubTab(subTab) {
    currentVisaSubTab = subTab;
    if (document.getElementById('dashboardTab-visa')?.classList.contains('active')) {
        switchVisaSubTab(subTab);
        return;
    }
    switchDashboardTab('visa');
}

function switchDashboardTab(tabName) {
    if (tabName !== 'visa' && (visaMockInterviewState.active || visaMockInterviewState.listening || visaMockInterviewState.pending)) {
        stopVoiceMockInterview(true);
    }
    if (tabName !== 'visa' && (visaPrepInterviewState.active || visaPrepInterviewState.listening || visaPrepInterviewState.pending)) {
        stopVoicePrepInterview(true);
    }

    // Hide all tabs
    document.querySelectorAll('.dashboard-tab').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Remove active class from all nav items
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
    });
    
    // Show selected tab
    const selectedTab = document.getElementById(`dashboardTab-${tabName}`);
    if (selectedTab) {
        selectedTab.classList.add('active');
    }
    
    // Activate corresponding nav item
    const navItem = document.querySelector(`.nav-item[data-tab="${tabName}"]`);
    if (navItem) {
        navItem.classList.add('active');
    }

    setVisaSubNavVisibility(tabName === 'visa');
    
    // Load data for specific tabs
    if (tabName === 'documents') {
        loadMyDocuments();
    } else if (tabName === 'overview') {
        loadDashboardStats();
    } else if (tabName === 'visa') {
        loadDashboardStats();
        switchVisaSubTab(currentVisaSubTab);
    } else if (tabName === 'records') {
        initializeRilonoAiChat();
    } else if (tabName === 'news') {
        loadF1VisaNews();
    }
    
    // Scroll to top of dashboard content
    const dashboardContent = document.querySelector('.dashboard-content');
    if (dashboardContent) {
        dashboardContent.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function openVisaAiPrompt(prompt) {
    switchDashboardTab('records');
    setTimeout(() => {
        sendQuickMessage(prompt);
    }, 120);
}

function openVisaNewsSection() {
    switchDashboardTab('news');
}

function showPrivacy(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('privacySection').style.display = 'block';
    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (!skipURLUpdate) {
        updateURL('/privacy', false);
    }
}

function showPricing(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('pricingSection').style.display = 'block';
    initializePricingSelector();
    if (authToken) {
        void loadSubscriptionStatus(true);
    } else {
        updateSubscriptionUI();
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (!skipURLUpdate) {
        updateURL('/pricing', false);
    }
}

function showAboutUs(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('aboutUsSection').style.display = 'block';
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (!skipURLUpdate) {
        updateURL('/about-us', false);
    }
}

function initializePricingSelector() {
    const countrySelect = document.getElementById('pricingCountrySelect');
    if (!countrySelect) return;

    const savedCountry = localStorage.getItem('pricingCountry');
    const countryCode = PRICING_COUNTRY_CONFIG[savedCountry] ? savedCountry : 'US';
    const searchParams = new URLSearchParams(window.location.search);
    const shouldForceRefresh = searchParams.get('fx_refresh') === '1';
    countrySelect.value = countryCode;
    updatePricingByCountry(countryCode);

    void ensurePricingExchangeRates(shouldForceRefresh).then(() => {
        updatePricingByCountry(countrySelect.value || countryCode);
    });
}

function handlePricingCountryChange(countryCode) {
    if (!PRICING_COUNTRY_CONFIG[countryCode]) {
        countryCode = 'US';
    }
    localStorage.setItem('pricingCountry', countryCode);
    updatePricingByCountry(countryCode);
}

function ensurePricingExchangeRates(forceRefresh = false) {
    const now = Date.now();
    if (
        !forceRefresh &&
        pricingRatesFetchedAt &&
        (now - pricingRatesFetchedAt) < PRICING_RATES_CACHE_WINDOW_MS
    ) {
        return Promise.resolve();
    }

    if (pricingRatesRequestPromise) {
        return pricingRatesRequestPromise;
    }

    pricingRatesRequestPromise = (async () => {
        try {
            const ratesUrl = forceRefresh
                ? `${API_BASE}/api/pricing/exchange-rates?refresh=1`
                : `${API_BASE}/api/pricing/exchange-rates`;
            const response = await fetch(ratesUrl);
            if (!response.ok) {
                throw new Error(`Pricing rates request failed: ${response.status}`);
            }

            const data = await response.json();
            if (!data || !data.rates || typeof data.rates !== 'object') {
                throw new Error('Pricing rates response missing rates payload');
            }

            const normalizedRates = { ...PRICING_FALLBACK_RATES };
            Object.keys(normalizedRates).forEach((currencyCode) => {
                const rawRate = Number(data.rates[currencyCode]);
                if (Number.isFinite(rawRate) && rawRate > 0) {
                    normalizedRates[currencyCode] = rawRate;
                }
            });

            pricingRatesByCurrency = normalizedRates;
            pricingRatesMeta = {
                source: data.source || 'frankfurter',
                providerDate: data.provider_date || null,
                stale: Boolean(data.stale),
                missingCurrencies: Array.isArray(data.missing_currencies) ? data.missing_currencies : []
            };
            pricingRatesFetchedAt = Date.now();
        } catch (error) {
            console.warn('Unable to refresh pricing exchange rates, using fallback rates:', error);
            pricingRatesByCurrency = { ...PRICING_FALLBACK_RATES };
            pricingRatesMeta = { source: 'fallback', providerDate: null, stale: true, missingCurrencies: [] };
            pricingRatesFetchedAt = Date.now();
        } finally {
            pricingRatesRequestPromise = null;
        }
    })();

    return pricingRatesRequestPromise;
}

function updatePricingByCountry(countryCode) {
    const config = PRICING_COUNTRY_CONFIG[countryCode] || PRICING_COUNTRY_CONFIG.US;
    const freePriceEl = document.getElementById('pricingFreePrice');
    const proPriceEl = document.getElementById('pricingProPrice');
    const hintEl = document.getElementById('pricingCurrencyHint');
    const rate = pricingRatesByCurrency[config.currency] || PRICING_FALLBACK_RATES[config.currency] || 1;
    const inrRate = pricingRatesByCurrency.INR || PRICING_FALLBACK_RATES.INR || 1;

    const convertedFree = PRICING_BASE_USD.free * rate;
    const convertedPro = (PRO_PRICE_INR / inrRate) * rate;

    if (freePriceEl) {
        freePriceEl.innerHTML = `${formatCurrencyAmount(convertedFree, config.currency)}<span>/month</span>`;
    }
    if (proPriceEl) {
        proPriceEl.innerHTML = `${formatCurrencyAmount(convertedPro, config.currency)}<span>/month</span>`;
    }
    if (hintEl) {
        let hintText = `Currency: ${config.currency} (${config.country})`;
        if (pricingRatesMeta.source === 'fallback') {
            hintText += ' • Using fallback rates';
        } else if (pricingRatesMeta.missingCurrencies.includes(config.currency)) {
            hintText += ` • Using fallback for ${config.currency}`;
        } else if (pricingRatesMeta.stale) {
            hintText += ' • Using cached rates';
        }
        hintText += ' • Converted from base ₹699/month';
        hintEl.textContent = hintText;
    }
}

function formatCurrencyAmount(amount, currencyCode) {
    try {
        return new Intl.NumberFormat(undefined, {
            style: 'currency',
            currency: currencyCode,
            maximumFractionDigits: currencyCode === 'JPY' ? 0 : 2
        }).format(amount);
    } catch (error) {
        return `$${amount.toFixed(2)}`;
    }
}

function showTerms(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('termsSection').style.display = 'block';
    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (!skipURLUpdate) {
        updateURL('/terms', false);
    }
}

function showRefundPolicy(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('refundPolicySection').style.display = 'block';
    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (!skipURLUpdate) {
        updateURL('/refund-policy', false);
    }
}

function showDeliveryPolicy(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('deliveryPolicySection').style.display = 'block';
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (!skipURLUpdate) {
        updateURL('/delivery-policy', false);
    }
}

function showContact(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('contactSection').style.display = 'block';
    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
    
    // Pre-fill email if user is logged in
    if (currentUser) {
        const emailField = document.getElementById('contactEmail');
        const nameField = document.getElementById('contactName');
        const userTypeField = document.getElementById('contactUserType');
        
        if (emailField && currentUser.email) {
            emailField.value = currentUser.email;
        }
        if (nameField && currentUser.full_name) {
            nameField.value = currentUser.full_name;
        }
        if (userTypeField) {
            userTypeField.value = 'student';
        }
    }
    
    if (!skipURLUpdate) {
        updateURL('/contact', false);
    }
}

function openFeatureRequestModal() {
    if (!currentUser) {
        showMessage('Please login to submit a feature request.', 'error');
        showLogin();
        return;
    }

    const modal = document.getElementById('featureRequestModal');
    const form = document.getElementById('featureRequestForm');
    const nameEl = document.getElementById('featureRequestUserName');
    const emailEl = document.getElementById('featureRequestUserEmail');
    const titleInput = document.getElementById('featureRequestTitle');
    const areaInput = document.getElementById('featureRequestArea');
    const priorityInput = document.getElementById('featureRequestPriority');
    const detailsInput = document.getElementById('featureRequestDetails');

    if (!modal || !form || !nameEl || !emailEl) return;

    form.reset();
    nameEl.textContent = currentUser.full_name || currentUser.username || 'Student';
    emailEl.textContent = currentUser.email || '';
    if (titleInput) titleInput.value = '';
    if (areaInput) areaInput.value = '';
    if (priorityInput) priorityInput.value = 'Medium';
    if (detailsInput) detailsInput.value = '';

    modal.style.display = 'flex';
}

function closeFeatureRequestModal() {
    const modal = document.getElementById('featureRequestModal');
    if (!modal) return;
    modal.style.display = 'none';
}

async function handleFeatureRequestSubmit(e) {
    e.preventDefault();

    if (!currentUser) {
        showMessage('Please login to submit a feature request.', 'error');
        closeFeatureRequestModal();
        showLogin();
        return;
    }

    const title = document.getElementById('featureRequestTitle')?.value.trim() || '';
    const area = document.getElementById('featureRequestArea')?.value || 'Not specified';
    const priority = document.getElementById('featureRequestPriority')?.value || 'Medium';
    const details = document.getElementById('featureRequestDetails')?.value.trim() || '';
    const submitBtn = document.getElementById('featureRequestSubmitBtn');

    if (title.length < 3) {
        showMessage('Please provide a feature title (at least 3 characters).', 'error');
        return;
    }

    if (details.length < 10) {
        showMessage('Please provide more details (at least 10 characters).', 'error');
        return;
    }

    const requesterName = (currentUser.full_name || currentUser.username || 'Student').trim();
    const requesterEmail = (currentUser.email || '').trim();
    if (!requesterEmail || !requesterEmail.includes('@')) {
        showMessage('Your account email is missing. Please update your profile and try again.', 'error');
        return;
    }

    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Submitting...';
    }

    try {
        const formData = new FormData();
        formData.append('name', requesterName);
        formData.append('email', requesterEmail);
        formData.append('user_type', 'student');
        formData.append('subject', `Feature Request: ${title}`);
        formData.append(
            'message',
            [
                `Requested Area: ${area}`,
                `Priority: ${priority}`,
                `Requested By: ${requesterName} (${requesterEmail})`,
                '',
                'Details:',
                details
            ].join('\n')
        );

        const response = await fetch(`${API_BASE}/api/auth/contact`, {
            method: 'POST',
            body: formData
        });
        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(data.detail || 'Failed to submit feature request.');
        }

        showMessage(data.message || 'Feature request submitted. Thank you!', 'success');
        closeFeatureRequestModal();
    } catch (error) {
        console.error('Feature request submit error:', error);
        showMessage(error.message || 'Failed to submit feature request. Please try again.', 'error');
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Submit Request';
        }
    }
}

async function handleContactSubmit(e) {
    e.preventDefault();
    
    const name = document.getElementById('contactName').value.trim();
    const email = document.getElementById('contactEmail').value.trim();
    const userType = document.getElementById('contactUserType').value;
    const subject = document.getElementById('contactSubject').value.trim();
    const message = document.getElementById('contactMessage').value.trim();
    const submitBtn = document.getElementById('contactSubmitBtn');
    
    // Validation
    if (!name || name.length < 2) {
        showMessage('Please enter your name', 'error');
        return;
    }
    
    if (!email || !email.includes('@')) {
        showMessage('Please enter a valid email address', 'error');
        return;
    }
    
    if (!subject || subject.length < 3) {
        showMessage('Please enter a subject', 'error');
        return;
    }
    
    if (!message || message.length < 10) {
        showMessage('Please enter a message (at least 10 characters)', 'error');
        return;
    }
    
    // Disable button and show loading state
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span>Sending...</span>';
    
    try {
        const formData = new FormData();
        formData.append('name', name);
        formData.append('email', email);
        formData.append('user_type', userType);
        formData.append('subject', subject);
        formData.append('message', message);
        
        const response = await fetch(`${API_BASE}/api/auth/contact`, {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showMessage(data.message || 'Message sent successfully! We\'ll get back to you soon.', 'success');
            // Clear the form
            document.getElementById('contactForm').reset();
            // Re-fill email/name if logged in
            if (currentUser) {
                if (currentUser.email) document.getElementById('contactEmail').value = currentUser.email;
                if (currentUser.full_name) document.getElementById('contactName').value = currentUser.full_name;
                document.getElementById('contactUserType').value = 'student';
            }
        } else {
            showMessage(data.detail || 'Failed to send message. Please try again.', 'error');
        }
    } catch (error) {
        console.error('Contact form error:', error);
        showMessage('Failed to send message. Please try again or email us directly at contact@rilono.com', 'error');
    } finally {
        // Re-enable button
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<span>Send Message</span>';
    }
}

async function showItemDetail(itemId, skipURLUpdate = false) {
    showMessage('That page is no longer available.', 'error');
    showHomepage(skipURLUpdate);
}

function hideAllSections() {
    stopVoiceMockInterview(true);
    stopVoicePrepInterview(true);
    document.querySelectorAll('.section').forEach(section => {
        section.style.display = 'none';
    });
    const pageContainer = document.querySelector('.container');
    if (pageContainer) {
        pageContainer.classList.remove('dashboard-fluid');
    }
}

// Auth functions
async function handleLogin(e) {
    e.preventDefault();
    const email = document.getElementById('loginEmail').value.trim();
    const password = document.getElementById('loginPassword').value;

    if (!email || !password) {
        showMessage('Please enter both email and password', 'error');
        return;
    }

    // Get Turnstile token (only if Turnstile is configured)
    let turnstileToken = null;
    if (turnstileSiteKey && window.turnstile) {
        try {
            // Try to get token using stored widget ID or element
            const loginWidget = document.getElementById('turnstile-login');
            if (loginWidget) {
                // Use the element directly (more reliable than ID string)
                turnstileToken = window.turnstile.getResponse(loginWidget);
            }
            
            // Fallback: try using stored widget ID
            if (!turnstileToken && turnstileWidgetIds.login) {
                turnstileToken = window.turnstile.getResponse(turnstileWidgetIds.login);
            }
            
            // Last fallback: try using ID string
            if (!turnstileToken) {
                turnstileToken = window.turnstile.getResponse('turnstile-login');
            }
            
            if (!turnstileToken) {
                showMessage('Please complete the security verification', 'error');
                return;
            }
        } catch (error) {
            console.error('Turnstile error:', error);
            showMessage('Please complete the security verification', 'error');
            return;
        }
    }

    try {
        const formData = new URLSearchParams();
        formData.append('username', email);  // OAuth2PasswordRequestForm expects 'username' field, but we use it for email
        formData.append('password', password);
        if (turnstileToken) {
            formData.append('cf_turnstile_token', turnstileToken);
        }

        const response = await fetch(`${API_BASE}/api/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: formData
        });

        const data = await response.json();

        if (response.ok) {
            // Session is persisted in a secure HttpOnly cookie set by backend.
            authToken = COOKIE_AUTH_SENTINEL;
            persistAuthToken(authToken);
            let authVerified = await checkAuth();
            if (!authVerified && data.access_token) {
                // Safe fallback for environments where secure cookies are misconfigured.
                authToken = data.access_token;
                persistAuthToken(authToken);
                authVerified = await checkAuth();
            }
            if (!authVerified) {
                showMessage('Login succeeded but session setup failed. Please refresh and try again.', 'error');
                return;
            }
            showMessage('Login successful!', 'success');
            document.getElementById('loginForm').reset();
            // Reset Turnstile widget
            if (window.turnstile) {
                const loginWidget = document.getElementById('turnstile-login');
                if (loginWidget) {
                    try {
                        window.turnstile.reset(loginWidget);
                    } catch (e) {
                        // Ignore reset errors
                    }
                }
            }
            showDashboard();
            renderReferralPromotions();
            setTimeout(() => {
                openReferralPromoModal(true);
            }, 260);
            if (data.referral_bonus_awarded && data.referral_bonus_message) {
                setTimeout(() => {
                    showMessage(data.referral_bonus_message, 'success');
                }, 800);
            }
        } else {
            let errorMessage = 'Login failed';
            if (data.detail) {
                if (Array.isArray(data.detail)) {
                    errorMessage = data.detail.map(err => `${err.loc.join('.')}: ${err.msg}`).join(', ');
                } else {
                    errorMessage = data.detail;
                }
            }
            
            // Check if it's an email verification error
            if (data.detail && data.detail.includes('verify your email')) {
                const email = document.getElementById('loginEmail').value.trim();
                showMessage(errorMessage, 'error');
                // Show option to resend verification
                setTimeout(() => {
                    if (confirm('Would you like to resend the verification email?')) {
                        resendVerificationEmail(email);
                    }
                }, 2000);
            } else {
                showMessage(errorMessage, 'error');
            }
        }
    } catch (error) {
        console.error('Login error:', error);
        showMessage('An error occurred. Please check your connection and try again.', 'error');
    }
}

async function handleRegister(e) {
    e.preventDefault();

    const consentInput = document.getElementById('registerConsent');
    const acceptedTermsPrivacy = Boolean(consentInput && consentInput.checked);
    if (!acceptedTermsPrivacy) {
        showMessage('Please accept the Terms & Conditions and Privacy Policy to continue.', 'error');
        return;
    }
    
    // Get form values and convert empty strings to null
    const getValue = (id) => {
        const value = document.getElementById(id).value.trim();
        return value === '' ? null : value;
    };
    
    const userData = {
        email: getValue('registerEmail'),
        password: getValue('registerPassword'),
        full_name: getValue('registerFullName'),
        university: getValue('registerUniversity'),
        current_residence_country: getValue('registerCountry'),
        referral_code: getValue('registerReferralCode'),
        accepted_terms_privacy: acceptedTermsPrivacy
        // Username is optional - will be auto-generated from email on backend
    };
    const confirmPassword = getValue('registerPasswordConfirm');

    // Validate required fields
    if (!userData.email || !userData.password) {
        showMessage('Please fill in all required fields (Email, Password)', 'error');
        return;
    }

    if (!confirmPassword) {
        showMessage('Please retype your password to confirm.', 'error');
        return;
    }

    if (userData.password !== confirmPassword) {
        showMessage('Password and confirm password do not match.', 'error');
        return;
    }
    
    // Validate that university email domain is valid
    const universityInput = document.getElementById('registerUniversity');
    if (!universityInput.value.trim()) {
        showMessage('Please use a valid university email address. The email domain must be from a recognized university.', 'error');
        // Re-check the email to show validation message
        await checkUniversityByEmail(userData.email);
        return;
    }
    
    const registerPasswordErrors = getPasswordValidationErrors(userData.password, userData.email || '');
    if (registerPasswordErrors.length > 0) {
        showMessage(`Please use a stronger password: ${registerPasswordErrors[0]}.`, 'error');
        updateRegisterPasswordHint();
        return;
    }

    // Get Turnstile token (only if Turnstile is configured)
    let turnstileToken = null;
    if (turnstileSiteKey && window.turnstile) {
        try {
            // Try to get token using stored widget ID or element
            const registerWidget = document.getElementById('turnstile-register');
            if (registerWidget) {
                // Use the element directly (more reliable than ID string)
                turnstileToken = window.turnstile.getResponse(registerWidget);
            }
            
            // Fallback: try using stored widget ID
            if (!turnstileToken && turnstileWidgetIds.register) {
                turnstileToken = window.turnstile.getResponse(turnstileWidgetIds.register);
            }
            
            // Last fallback: try using ID string
            if (!turnstileToken) {
                turnstileToken = window.turnstile.getResponse('turnstile-register');
            }
            
            if (!turnstileToken) {
                showMessage('Please complete the security verification', 'error');
                return;
            }
        } catch (error) {
            console.error('Turnstile error:', error);
            showMessage('Please complete the security verification', 'error');
            return;
        }
    }
    
    if (turnstileToken) {
        userData.cf_turnstile_token = turnstileToken;
    }

    try {
        const response = await fetch(`${API_BASE}/api/auth/register`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(userData)
        });

        const data = await response.json();
        const expiryHours = Number(response.headers.get('X-Verification-Link-Expires-Hours') || 24);

        if (response.ok) {
            const email = userData.email;
            showMessage(`Registration successful! Please verify your email. The link expires in ${expiryHours} hours.`, 'success');
            document.getElementById('registerForm').reset();
            // Reset Turnstile widget
            if (window.turnstile) {
                const registerWidget = document.getElementById('turnstile-register');
                if (registerWidget) {
                    try {
                        window.turnstile.reset(registerWidget);
                    } catch (e) {
                        // Ignore reset errors
                    }
                }
            }
            showVerification(email, expiryHours);
        } else {
            // Handle different error formats
            let errorMessage = 'Registration failed';
            if (data.detail) {
                if (Array.isArray(data.detail)) {
                    // Pydantic validation errors
                    errorMessage = data.detail.map(err => `${err.loc.join('.')}: ${err.msg}`).join(', ');
                } else {
                    errorMessage = data.detail;
                }
            }
            showMessage(errorMessage, 'error');
        }
    } catch (error) {
        console.error('Registration error:', error);
        showMessage('An error occurred. Please check your connection and try again.', 'error');
    }
}

async function logout() {
    fetch(`${API_BASE}/api/auth/logout`, {
        method: 'POST'
    }).catch(() => null);
    authToken = null;
    persistAuthToken(null);
    currentUser = null;
    currentSubscription = null;
    closeReferralPromoModal();
    floatingChatOpen = false;
    rilonoAiConversationHistory = [];  // Clear shared chat history
    stopVoiceMockInterview(true);
    stopVoicePrepInterview(true);
    document.getElementById('floatingChatWindow').style.display = 'none';
    // Clear floating chat messages
    const floatingMessages = document.getElementById('floatingChatMessages');
    if (floatingMessages) floatingMessages.innerHTML = '';
    // Clear main chat messages in all dashboard chat panels
    getMainChatContainers().forEach((mainMessages) => {
        const existingMsgs = mainMessages.querySelectorAll('.rilono-ai-message');
        existingMsgs.forEach(msg => msg.remove());
    });
    updateDocumentTypeAvailability([]);
    updateUIForAuth();
    showMessage('Logged out successfully', 'success');
    showHomepage();
}

async function handleForgotPassword(e) {
    e.preventDefault();
    const email = document.getElementById('forgotPasswordEmail').value.trim();
    
    if (!email) {
        showMessage('Please enter your email address', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/forgot-password`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ email: email })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showMessage(data.message || 'Password reset link has been sent to your email.', 'success');
            // Show success message in the form
            document.getElementById('forgotPasswordSection').innerHTML = `
                <div class="auth-card">
                    <div style="text-align: center;">
                        <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--success-color);">✓</div>
                        <h2 style="margin-bottom: 1rem;">Check Your Email</h2>
                        <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                            We've sent a password reset link to <strong>${escapeHtml(email)}</strong>. 
                            Please check your inbox.
                        </p>
                        <p style="color: var(--text-secondary); font-size: 0.875rem; margin-bottom: 2rem;">
                            The link will expire in 1 hour.
                        </p>
                        <a href="#" onclick="showLogin(); return false;" class="btn btn-primary">Back to Login</a>
                    </div>
                </div>
            `;
        } else {
            let errorMessage = data.detail || 'Failed to send password reset email';
            
            // If account doesn't exist, show helpful message with link to register
            if (response.status === 404) {
                showMessage(errorMessage, 'error');
                // Show option to create account
                setTimeout(() => {
                    const forgotSection = document.getElementById('forgotPasswordSection');
                    if (forgotSection) {
                        const errorDiv = document.createElement('div');
                        errorDiv.style.marginTop = '1rem';
                        errorDiv.style.textAlign = 'center';
                        errorDiv.innerHTML = `
                            <p style="color: var(--text-secondary); margin-bottom: 1rem;">
                                Don't have an account?
                            </p>
                            <a href="#" onclick="showRegister(); return false;" class="btn btn-primary">Create Account</a>
                        `;
                        forgotSection.querySelector('.auth-card').appendChild(errorDiv);
                    }
                }, 100);
            } else {
                showMessage(errorMessage, 'error');
            }
        }
    } catch (error) {
        console.error('Forgot password error:', error);
        showMessage('An error occurred. Please try again.', 'error');
    }
}

async function handleResetPassword(e) {
    e.preventDefault();
    const token = document.getElementById('resetToken').value;
    const newPassword = document.getElementById('resetPasswordNew').value;
    const confirmPassword = document.getElementById('resetPasswordConfirm').value;
    
    if (!token) {
        showMessage('Invalid reset token', 'error');
        return;
    }
    
    const resetPasswordErrors = getPasswordValidationErrors(newPassword);
    if (resetPasswordErrors.length > 0) {
        showMessage(`Please use a stronger password: ${resetPasswordErrors[0]}.`, 'error');
        updateResetPasswordHint();
        return;
    }
    
    if (newPassword !== confirmPassword) {
        showMessage('Passwords do not match', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/reset-password`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                token: token,
                new_password: newPassword
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showMessage(data.message || 'Password reset successfully! You can now log in.', 'success');
            // Show success and redirect to login
            document.getElementById('resetPasswordSection').innerHTML = `
                <div class="auth-card">
                    <div style="text-align: center;">
                        <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--success-color);">✓</div>
                        <h2 style="margin-bottom: 1rem; color: var(--success-color);">Password Reset Successful!</h2>
                        <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                            Your password has been reset successfully. You can now log in with your new password.
                        </p>
                        <a href="#" onclick="showLogin(); return false;" class="btn btn-primary">Go to Login</a>
                    </div>
                </div>
            `;
            // Auto-redirect to login after 3 seconds
            setTimeout(() => {
                showLogin();
            }, 3000);
        } else {
            let errorMessage = 'Failed to reset password';
            if (data.detail) {
                errorMessage = data.detail;
            }
            showMessage(errorMessage, 'error');
        }
    } catch (error) {
        console.error('Reset password error:', error);
        showMessage('An error occurred. Please try again.', 'error');
    }
}

// Item functions
async function loadItems(skipURLUpdate = false) {
    if (!document.getElementById('marketplaceSection')) {
        return;
    }
    const search = document.getElementById('searchInput')?.value || '';
    const category = document.getElementById('categoryFilter')?.value || '';
    const minPrice = document.getElementById('minPrice')?.value || '';
    const maxPrice = document.getElementById('maxPrice')?.value || '';

    // Update URL with current search filters (only if not handling back/forward)
    if (!skipURLUpdate) {
        const searchURL = buildSearchURL(search.trim(), category, minPrice, maxPrice);
        updateURL('/' + (searchURL ? '?' + searchURL : ''), false);
    }

    let url = `${API_BASE}/api/items/?`;
    const params = new URLSearchParams();
    if (search.trim()) params.append('search', search.trim());
    if (category) params.append('category', category);
    if (minPrice) params.append('min_price', minPrice);
    if (maxPrice) params.append('max_price', maxPrice);
    
    url += params.toString();

    try {
        const response = await fetch(url);
        if (response.ok) {
            const items = await response.json();
            displayItems(items, 'itemsGrid');
        } else {
            const error = await response.json().catch(() => ({}));
            showMessage(error.detail || 'Failed to load items', 'error');
        }
    } catch (error) {
        console.error('Load items error:', error);
        showMessage('An error occurred while loading items. Please check your connection.', 'error');
    }
}

async function loadMyItems() {
    if (!authToken) return;

    try {
        const response = await fetch(`${API_BASE}/api/items/my/listings`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        if (response.ok) {
            const items = await response.json();
            displayItems(items, 'myItemsGrid', true);
        } else {
            const error = await response.json().catch(() => ({}));
            if (response.status === 401) {
                showMessage('Session expired. Please login again.', 'error');
                logout();
            } else {
                showMessage(error.detail || 'Failed to load your items', 'error');
            }
        }
    } catch (error) {
        console.error('Load my items error:', error);
        showMessage('An error occurred while loading your items. Please check your connection.', 'error');
    }
}

function getImageUrl(imageUrl) {
    if (!imageUrl) return null;

    const raw = String(imageUrl).trim();
    if (!raw) return null;

    let candidate = raw;
    if (!(raw.startsWith('http://') || raw.startsWith('https://') || raw.startsWith('/'))) {
        candidate = API_BASE + (raw.startsWith('/') ? '' : '/') + raw;
    }

    try {
        const parsed = new URL(candidate, window.location.origin);
        const protocol = parsed.protocol.toLowerCase();
        if (protocol !== 'http:' && protocol !== 'https:') {
            return null;
        }
        return parsed.href;
    } catch (error) {
        return null;
    }
}

function displayItems(items, containerId, showActions = false) {
    const container = document.getElementById(containerId);
    if (items.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: var(--text-secondary); grid-column: 1 / -1;">No items found.</p>';
        return;
    }

    container.innerHTML = items.map((item, itemIndex) => {
        // Get images - prefer new images array, fallback to image_url
        const images = item.images && item.images.length > 0 
            ? item.images.map(img => img.image_url)
            : (item.image_url ? [item.image_url] : []);
        
        const firstImage = images.length > 0 ? images[0] : null;
        const imageUrl = firstImage ? getImageUrl(firstImage) : null;
        const imageCount = images.length;
        
        // Store images in a global map for easy access
        const imageKey = `item_${item.id}_${itemIndex}`;
        if (!window.itemImagesMap) {
            window.itemImagesMap = {};
        }
        window.itemImagesMap[imageKey] = images.map((img) => getImageUrl(img)).filter(Boolean);
        
        return `
        <div class="item-card" style="cursor: pointer;" onclick="showItemDetail(${item.id})" data-item-id="${item.id}">
            <div class="item-image" style="position: relative; cursor: ${imageCount > 0 ? 'pointer' : 'default'};" ${imageCount > 0 ? `data-image-key="${imageKey}" data-item-id="${item.id}" data-item-title="${escapeHtml(item.title)}" onclick="event.stopPropagation(); handleItemImageClick(this)"` : ''}>
                ${imageUrl ? `<img src="${imageUrl}" alt="${escapeHtml(item.title)}" style="width: 100%; height: 100%; object-fit: cover; pointer-events: none;" onerror="this.parentElement.innerHTML='📦';">` : '📦'}
                ${imageCount > 1 ? `<div style="position: absolute; bottom: 0.5rem; right: 0.5rem; background: rgba(0,0,0,0.7); color: white; padding: 0.25rem 0.5rem; border-radius: 0.25rem; font-size: 0.875rem; pointer-events: none;">${imageCount} photos</div>` : ''}
            </div>
            <div class="item-content">
                ${item.is_sold ? '<span class="sold-badge">SOLD</span>' : ''}
                <div class="item-title">${escapeHtml(item.title)}</div>
                <div class="item-price">$${item.price.toFixed(2)}${item.category === 'sublease' ? ' /month' : ''}</div>
                ${item.category ? `<span class="item-category">${escapeHtml(item.category)}</span>` : ''}
                ${item.description ? `<div class="item-description">${escapeHtml(item.description)}</div>` : ''}
                ${item.address ? `<div class="item-location" style="font-size: 0.875rem; color: var(--text-secondary); margin-top: 0.5rem;">📍 ${escapeHtml(item.address)}</div>` : ''}
                <div class="item-seller">Seller: ${escapeHtml(item.seller.username)}</div>
                ${showActions && !item.is_sold ? `
                    <div class="item-actions" onclick="event.stopPropagation();">
                        <button class="btn btn-primary" onclick="editItem(${item.id})">Edit</button>
                        <button class="btn btn-primary" onclick="markAsSold(${item.id})">Mark as Sold</button>
                        <button class="btn btn-danger" onclick="deleteItem(${item.id})">Delete</button>
                    </div>
                ` : !item.is_sold && (!currentUser || currentUser.id !== item.seller_id) ? `
                    <div class="item-actions" onclick="event.stopPropagation();">
                        <button class="btn btn-primary" onclick="startConversation(${item.id}, ${item.seller_id})">Message Seller</button>
                    </div>
                ` : ''}
            </div>
        </div>
    `;
    }).join('');
}

// Store selected images (files and URLs)
let selectedImages = [];

function handleMultipleImagePreview(e) {
    const files = Array.from(e.target.files);
    const previewsContainer = document.getElementById('imagePreviews');
    
    if (files.length === 0) {
        return;
    }
    
    // Limit to 10 images
    if (files.length > 10) {
        showMessage('Maximum 10 images allowed', 'error');
        e.target.value = '';
        return;
    }
    
    // Validate and add files
    files.forEach((file, index) => {
        // Validate file type
        if (!file.type.startsWith('image/')) {
            showMessage(`File ${index + 1} is not an image`, 'error');
            return;
        }
        
        // Validate file size (5MB)
        if (file.size > 5 * 1024 * 1024) {
            showMessage(`Image ${index + 1} is too large (max 5MB)`, 'error');
            return;
        }
        
        // Add to selected images
        const imageId = `img_${Date.now()}_${index}`;
        selectedImages.push({
            id: imageId,
            file: file,
            type: 'file',
            url: null
        });
        
        // Show preview
        const reader = new FileReader();
        reader.onload = (e) => {
            addImagePreview(imageId, e.target.result, 'file');
        };
        reader.readAsDataURL(file);
    });
    
    previewsContainer.style.display = 'grid';
}


function addImagePreview(imageId, src, type) {
    const previewsContainer = document.getElementById('imagePreviews');
    const previewDiv = document.createElement('div');
    previewDiv.id = `preview_${imageId}`;
    previewDiv.style.position = 'relative';
    previewDiv.style.aspectRatio = '1';
    previewDiv.style.overflow = 'hidden';
    previewDiv.style.borderRadius = '0.5rem';
    previewDiv.style.border = '2px solid var(--border-color)';
    
    const img = document.createElement('img');
    img.src = src;
    img.style.width = '100%';
    img.style.height = '100%';
    img.style.objectFit = 'cover';
    img.onerror = () => {
        previewDiv.remove();
        selectedImages = selectedImages.filter(img => img.id !== imageId);
        showMessage('Failed to load image', 'error');
    };
    
    const removeBtn = document.createElement('button');
    removeBtn.textContent = '×';
    removeBtn.type = 'button';
    removeBtn.style.position = 'absolute';
    removeBtn.style.top = '0.25rem';
    removeBtn.style.right = '0.25rem';
    removeBtn.style.width = '2rem';
    removeBtn.style.height = '2rem';
    removeBtn.style.borderRadius = '50%';
    removeBtn.style.border = 'none';
    removeBtn.style.background = 'var(--danger-color)';
    removeBtn.style.color = 'white';
    removeBtn.style.cursor = 'pointer';
    removeBtn.style.fontSize = '1.25rem';
    removeBtn.style.fontWeight = 'bold';
    removeBtn.onclick = () => removeImage(imageId);
    
    previewDiv.appendChild(img);
    previewDiv.appendChild(removeBtn);
    previewsContainer.appendChild(previewDiv);
}

function removeImage(imageId) {
    selectedImages = selectedImages.filter(img => img.id !== imageId);
    const preview = document.getElementById(`preview_${imageId}`);
    if (preview) {
        preview.remove();
    }
    
    const previewsContainer = document.getElementById('imagePreviews');
    if (selectedImages.length === 0) {
        previewsContainer.style.display = 'none';
    }
}

let addressAutocomplete = null;

function initializeAddressAutocomplete() {
    const addressInput = document.getElementById('itemAddress');
    if (!addressInput) return;
    
    // Check if Google Maps API is loaded
    const checkGoogleMaps = () => {
        if (typeof google !== 'undefined' && google.maps && google.maps.places) {
            // Initialize Google Places Autocomplete
            addressAutocomplete = new google.maps.places.Autocomplete(addressInput, {
                types: ['address'],
                fields: ['formatted_address', 'address_components', 'geometry']
            });
            
            // Handle place selection
            addressAutocomplete.addListener('place_changed', () => {
                const place = addressAutocomplete.getPlace();
                
                if (!place.geometry) {
                    showMessage('No details available for the selected address', 'error');
                    return;
                }
                
                // Extract address components
                let city = '';
                let state = '';
                let zipCode = '';
                
                place.address_components.forEach(component => {
                    const types = component.types;
                    
                    if (types.includes('locality')) {
                        city = component.long_name;
                    } else if (types.includes('administrative_area_level_1')) {
                        state = component.short_name;
                    } else if (types.includes('postal_code')) {
                        zipCode = component.long_name;
                    }
                });
                
                // Update form fields
                document.getElementById('itemAddress').value = place.formatted_address;
                document.getElementById('itemCity').value = city;
                document.getElementById('itemState').value = state;
                document.getElementById('itemZipCode').value = zipCode;
                document.getElementById('itemLatitude').value = place.geometry.location.lat();
                document.getElementById('itemLongitude').value = place.geometry.location.lng();
                
                // Show address details
                document.getElementById('addressDetails').style.display = 'grid';
            });
        } else {
            // Fallback: Check again after a delay if API is still loading
            setTimeout(checkGoogleMaps, 500);
        }
    };
    
    // Start checking for Google Maps API
    checkGoogleMaps();
}

function initializeSearchableDropdowns() {
    // Initialize document type searchable dropdown
    const documentTypeDropdown = document.getElementById('documentTypeDropdown');
    if (!documentTypeDropdown) return;
    
    const searchInput = documentTypeDropdown.querySelector('.dropdown-search');
    const hiddenInput = documentTypeDropdown.querySelector('input[type="hidden"]');
    const dropdownList = documentTypeDropdown.querySelector('.dropdown-list');
    const items = Array.from(dropdownList.querySelectorAll('.dropdown-item'));
    
    // Open dropdown on focus
    searchInput.addEventListener('focus', () => {
        documentTypeDropdown.classList.add('open');
        filterItems('');
    });
    
    // Filter items on input
    searchInput.addEventListener('input', (e) => {
        const searchTerm = e.target.value.toLowerCase();
        filterItems(searchTerm);
        
        // Clear selection if user is typing
        if (searchTerm) {
            hiddenInput.value = '';
            items.forEach(item => item.classList.remove('selected'));
        }
    });
    
    // Handle item selection
    items.forEach(item => {
        item.addEventListener('click', () => {
            if (item.classList.contains('rule-hidden')) return;
            const value = item.dataset.value;
            const text = item.textContent;
            
            searchInput.value = text;
            hiddenInput.value = value;
            
            // Update selected state
            items.forEach(i => i.classList.remove('selected'));
            item.classList.add('selected');
            
            documentTypeDropdown.classList.remove('open');
        });
    });
    
    // Close dropdown on click outside
    document.addEventListener('click', (e) => {
        if (!documentTypeDropdown.contains(e.target)) {
            documentTypeDropdown.classList.remove('open');
            
            // If no valid selection, clear the input
            if (!hiddenInput.value && searchInput.value) {
                // Try to find an exact match
                const matchingItem = Array.from(items).find(
                    item => (
                        item.textContent.toLowerCase() === searchInput.value.toLowerCase() &&
                        !item.classList.contains('rule-hidden')
                    )
                );
                if (matchingItem) {
                    hiddenInput.value = matchingItem.dataset.value;
                    searchInput.value = matchingItem.textContent;
                    matchingItem.classList.add('selected');
                } else {
                    searchInput.value = '';
                }
            }
        }
    });
    
    // Handle keyboard navigation
    searchInput.addEventListener('keydown', (e) => {
        const visibleItems = Array.from(items).filter(item => !item.classList.contains('hidden'));
        const currentIndex = visibleItems.findIndex(item => item.classList.contains('highlighted'));
        
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (!documentTypeDropdown.classList.contains('open')) {
                documentTypeDropdown.classList.add('open');
            }
            const nextIndex = currentIndex < visibleItems.length - 1 ? currentIndex + 1 : 0;
            highlightItem(visibleItems, nextIndex);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            const prevIndex = currentIndex > 0 ? currentIndex - 1 : visibleItems.length - 1;
            highlightItem(visibleItems, prevIndex);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            const highlightedItem = visibleItems.find(item => item.classList.contains('highlighted'));
            if (highlightedItem) {
                highlightedItem.click();
            } else if (visibleItems.length === 1) {
                visibleItems[0].click();
            }
        } else if (e.key === 'Escape') {
            documentTypeDropdown.classList.remove('open');
        }
    });
    
    function filterItems(searchTerm) {
        let hasResults = false;
        items.forEach(item => {
            const text = item.textContent.toLowerCase();
            const matches = text.includes(searchTerm);
            const blockedByRule = item.classList.contains('rule-hidden');
            const shouldHide = !matches || blockedByRule;
            item.classList.toggle('hidden', shouldHide);
            if (!shouldHide) hasResults = true;
        });
        
        // Show "no results" message
        let noResultsEl = dropdownList.querySelector('.no-results');
        if (!hasResults) {
            if (!noResultsEl) {
                noResultsEl = document.createElement('div');
                noResultsEl.className = 'no-results';
                noResultsEl.textContent = 'No document types found';
                dropdownList.appendChild(noResultsEl);
            }
            noResultsEl.style.display = 'block';
        } else if (noResultsEl) {
            noResultsEl.style.display = 'none';
        }
    }
    
    function highlightItem(visibleItems, index) {
        items.forEach(item => item.classList.remove('highlighted'));
        if (visibleItems[index]) {
            visibleItems[index].classList.add('highlighted');
            visibleItems[index].scrollIntoView({ block: 'nearest' });
        }
    }

    documentTypeDropdownController = {
        dropdown: documentTypeDropdown,
        searchInput,
        hiddenInput,
        dropdownList,
        items,
        filterItems
    };
}

function updateDocumentTypeAvailability(documents = []) {
    const dropdownItems = Array.from(document.querySelectorAll('#documentTypeList .dropdown-item[data-value]'));
    if (!dropdownItems.length) return;

    const uploadedDocumentTypes = new Set(
        (Array.isArray(documents) ? documents : [])
            .map((doc) => doc?.document_type)
            .filter(Boolean)
    );
    const mandatoryDocumentTypes = new Set(
        (documentTypeCatalog || [])
            .filter((row) => row && row.is_active !== false && row.is_required === true)
            .map((row) => row.value)
    );
    if (!mandatoryDocumentTypes.size && Array.isArray(requiredDocumentTypeValues)) {
        requiredDocumentTypeValues.forEach((value) => mandatoryDocumentTypes.add(value));
    }

    const hiddenInput = document.getElementById('documentType');
    const searchInput = document.getElementById('documentTypeSearch');
    let selectionWasCleared = false;

    dropdownItems.forEach((item) => {
        const value = item.dataset.value;
        const shouldHide = mandatoryDocumentTypes.has(value) && uploadedDocumentTypes.has(value);
        item.classList.toggle('rule-hidden', shouldHide);

        if (shouldHide && hiddenInput?.value === value) {
            hiddenInput.value = '';
            item.classList.remove('selected');
            selectionWasCleared = true;
        }
    });

    if (selectionWasCleared && searchInput) {
        searchInput.value = '';
    }

    if (documentTypeDropdownController?.filterItems) {
        const currentTerm = (documentTypeDropdownController.searchInput?.value || '').toLowerCase();
        documentTypeDropdownController.filterItems(currentTerm);
    }
}

async function uploadImages(files) {
    const formData = new FormData();
    files.forEach(file => {
        formData.append('files', file);
    });
    
    const response = await fetch(`${API_BASE}/api/upload/images`, {
        method: 'POST',
        headers: {
            'Authorization': `Bearer ${authToken}`
        },
        body: formData
    });
    
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || 'Failed to upload images');
    }
    
    const data = await response.json();
    return data.images.map(img => img.url);
}

async function editItem(itemId) {
    if (!authToken) {
        showMessage('Please login to edit items', 'error');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/items/${itemId}`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (!response.ok) {
            throw new Error('Failed to load item');
        }

        const item = await response.json();

        // Set editing mode
        document.getElementById('editingItemId').value = itemId;
        document.getElementById('itemFormTitle').textContent = 'Edit Item';
        document.getElementById('itemSubmitButton').textContent = 'Update Item';

        // Populate form fields
        document.getElementById('itemTitle').value = item.title || '';
        document.getElementById('itemDescription').value = item.description || '';
        document.getElementById('itemPrice').value = item.price || '';
        document.getElementById('itemCategory').value = item.category || '';
        document.getElementById('itemCondition').value = item.condition || '';
        document.getElementById('itemAddress').value = item.address || '';
        document.getElementById('itemCity').value = item.city || '';
        document.getElementById('itemState').value = item.state || '';
        document.getElementById('itemZipCode').value = item.zip_code || '';
        document.getElementById('itemLatitude').value = item.latitude || '';
        document.getElementById('itemLongitude').value = item.longitude || '';

        // Show address details if address exists
        if (item.address) {
            document.getElementById('addressDetails').style.display = 'grid';
        }

        // Update price label based on category
        updatePriceLabel();

        // Load existing images
        selectedImages = [];
        const images = item.images && item.images.length > 0 
            ? item.images.map(img => img.image_url)
            : (item.image_url ? [item.image_url] : []);

        const previewsContainer = document.getElementById('imagePreviews');
        previewsContainer.innerHTML = '';
        
        if (images.length > 0) {
            previewsContainer.style.display = 'grid';
            images.forEach((imageUrl, index) => {
                const imageId = `existing_${itemId}_${index}`;
                selectedImages.push({ id: imageId, src: imageUrl, type: 'url' });
                addImagePreview(imageId, imageUrl, 'url');
            });
        } else {
            previewsContainer.style.display = 'none';
        }

        // Show the create/edit form
        showCreateItem();
    } catch (error) {
        console.error('Edit item error:', error);
        showMessage('Failed to load item for editing', 'error');
    }
}

function resetItemForm() {
    document.getElementById('editingItemId').value = '';
    document.getElementById('itemFormTitle').textContent = 'List an Item for Sale';
    document.getElementById('itemSubmitButton').textContent = 'List Item';
    document.getElementById('createItemForm').reset();
    document.getElementById('imagePreviews').innerHTML = '';
    document.getElementById('imagePreviews').style.display = 'none';
    document.getElementById('addressDetails').style.display = 'none';
    selectedImages = [];
    updatePriceLabel();
}

async function handleCreateItem(e) {
    e.preventDefault();
    if (!authToken) {
        showMessage('Please login to list an item', 'error');
        return;
    }

    const getValue = (id) => {
        const value = document.getElementById(id).value.trim();
        return value === '' ? null : value;
    };

    const title = getValue('itemTitle');
    const price = parseFloat(document.getElementById('itemPrice').value);
    const editingItemId = document.getElementById('editingItemId').value;

    if (!title || isNaN(price) || price < 0) {
        showMessage('Please fill in title and a valid price', 'error');
        return;
    }

    // Collect all image URLs
    let imageUrls = [];
    
    // Keep existing images (from URLs)
    const existingImages = selectedImages.filter(img => img.type === 'url').map(img => img.src);
    imageUrls.push(...existingImages);
    
    // Get files to upload
    const filesToUpload = selectedImages.filter(img => img.type === 'file').map(img => img.file);
    
    // Upload new files if any
    if (filesToUpload.length > 0) {
        try {
            showMessage(`Uploading ${filesToUpload.length} image(s)...`, 'success');
            const uploadedUrls = await uploadImages(filesToUpload);
            imageUrls.push(...uploadedUrls);
        } catch (error) {
            showMessage(error.message || 'Failed to upload images', 'error');
            return;
        }
    }

    // Get address data
    const address = getValue('itemAddress');
    const city = getValue('itemCity');
    const state = getValue('itemState');
    const zipCode = getValue('itemZipCode');
    const latitude = document.getElementById('itemLatitude').value ? parseFloat(document.getElementById('itemLatitude').value) : null;
    const longitude = document.getElementById('itemLongitude').value ? parseFloat(document.getElementById('itemLongitude').value) : null;

    const itemData = {
        title: title,
        description: getValue('itemDescription'),
        price: price,
        category: getValue('itemCategory'),
        condition: getValue('itemCondition'),
        image_urls: imageUrls.length > 0 ? imageUrls : null,
        image_url: imageUrls.length > 0 ? imageUrls[0] : null,  // Backward compatibility
        address: address,
        city: city,
        state: state,
        zip_code: zipCode,
        latitude: latitude,
        longitude: longitude
    };

    try {
        const url = editingItemId 
            ? `${API_BASE}/api/items/${editingItemId}`
            : `${API_BASE}/api/items/`;
        const method = editingItemId ? 'PUT' : 'POST';

        const response = await fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify(itemData)
        });

        const data = await response.json();

        if (response.ok) {
            showMessage(editingItemId ? 'Item updated successfully!' : 'Item listed successfully!', 'success');
            resetItemForm();
            showMyListings();
            loadMyItems();
        } else {
            let errorMessage = editingItemId ? 'Failed to update item' : 'Failed to create item';
            if (data.detail) {
                if (Array.isArray(data.detail)) {
                    errorMessage = data.detail.map(err => `${err.loc.join('.')}: ${err.msg}`).join(', ');
                } else {
                    errorMessage = data.detail;
                }
            }
            showMessage(errorMessage, 'error');
        }
    } catch (error) {
        console.error('Create/Update item error:', error);
        showMessage('An error occurred. Please check your connection and try again.', 'error');
    }
}

async function markAsSold(itemId) {
    if (!authToken) return;

    try {
        const response = await fetch(`${API_BASE}/api/items/${itemId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ is_sold: true })
        });

        const data = await response.json().catch(() => ({}));

        if (response.ok) {
            showMessage('Item marked as sold!', 'success');
            loadMyItems();
        } else {
            let errorMessage = 'Failed to update item';
            if (data.detail) {
                if (Array.isArray(data.detail)) {
                    errorMessage = data.detail.map(err => `${err.loc.join('.')}: ${err.msg}`).join(', ');
                } else {
                    errorMessage = data.detail;
                }
            }
            showMessage(errorMessage, 'error');
        }
    } catch (error) {
        console.error('Mark as sold error:', error);
        showMessage('An error occurred. Please try again.', 'error');
    }
}

async function deleteItem(itemId) {
    if (!authToken) return;
    if (!confirm('Are you sure you want to delete this item?')) return;

    try {
        const response = await fetch(`${API_BASE}/api/items/${itemId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok || response.status === 204) {
            showMessage('Item deleted successfully!', 'success');
            loadMyItems();
        } else {
            const error = await response.json().catch(() => ({}));
            showMessage(error.detail || 'Failed to delete item', 'error');
        }
    } catch (error) {
        console.error('Delete item error:', error);
        showMessage('An error occurred. Please try again.', 'error');
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Messaging functions
let currentConversation = null;

async function checkUnreadMessages() {
    if (!authToken) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/messages/unread-count`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        if (response.ok) {
            const data = await response.json();
            const badge = document.getElementById('unreadBadge');
            if (data.unread_count > 0) {
                badge.textContent = data.unread_count;
                badge.style.display = 'inline-block';
            } else {
                badge.style.display = 'none';
            }
        }
    } catch (error) {
        console.error('Failed to check unread messages:', error);
    }
}

async function loadConversations() {
    if (!authToken) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/messages/conversations`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        if (response.ok) {
            const conversations = await response.json();
            displayConversations(conversations);
        } else {
            showMessage('Failed to load conversations', 'error');
        }
    } catch (error) {
        console.error('Load conversations error:', error);
        showMessage('An error occurred while loading conversations', 'error');
    }
}

function displayConversations(conversations) {
    const container = document.getElementById('conversationsList');
    
    if (conversations.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: var(--text-secondary); padding: 2rem;">No conversations yet. Start messaging sellers about items!</p>';
        return;
    }
    
    container.innerHTML = conversations.map(conv => {
        const lastMessage = conv.last_message;
        const preview = lastMessage ? (lastMessage.content.length > 50 ? lastMessage.content.substring(0, 50) + '...' : lastMessage.content) : 'No messages yet';
        const time = lastMessage ? formatTime(lastMessage.created_at) : '';
        const unreadClass = conv.unread_count > 0 ? 'unread' : '';
        
        // Get display name (full name if available, otherwise username)
        const displayName = conv.other_user.full_name || conv.other_user.username;
        const university = conv.other_user.university || '';
        
        const avatarUrl = getImageUrl(conv.other_user.profile_picture);
        const avatarContent = avatarUrl
            ? `<img src="${avatarUrl}" alt="${escapeHtml(displayName)}" style="width: 100%; height: 100%; border-radius: 50%; object-fit: cover;">`
            : displayName.charAt(0).toUpperCase();
        
        return `
            <div class="conversation-item ${unreadClass}" onclick="openConversation(${conv.item.id}, ${conv.other_user.id}, '${escapeHtml(conv.other_user.username)}', '${escapeHtml(conv.item.title)}')">
                <div class="conversation-avatar">${avatarContent}</div>
                <div class="conversation-info">
                    <div class="conversation-header">
                        <div>
                            <span class="conversation-name">${escapeHtml(displayName)}</span>
                            ${university ? `<span style="font-size: 0.75rem; color: var(--text-secondary); margin-left: 0.5rem;">• ${escapeHtml(university)}</span>` : ''}
                        </div>
                        <span class="conversation-time">${time}</span>
                    </div>
                    <div class="conversation-preview">
                        <span class="conversation-item-title">${escapeHtml(conv.item.title)}</span>
                        <span class="conversation-message">${escapeHtml(preview)}</span>
                    </div>
                </div>
                ${conv.unread_count > 0 ? `<span class="unread-badge">${conv.unread_count}</span>` : ''}
            </div>
        `;
    }).join('');
}

async function openConversation(itemId, otherUserId, otherUsername, itemTitle) {
    currentConversation = { itemId, otherUserId, otherUsername, itemTitle };
    
    // Fetch other user details to show name and university
    let userDetails = '';
    try {
        const userResponse = await fetch(`${API_BASE}/api/auth/me`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        if (userResponse.ok) {
            const currentUserData = await userResponse.json();
            // Fetch the other user's details (we'll need to get this from the conversation or messages)
            // For now, we'll get it from the first message or conversation data
        }
    } catch (error) {
        console.error('Failed to fetch user details:', error);
    }
    
    // Update chat header - will be updated with full details after loading messages
    document.getElementById('chatHeaderInfo').innerHTML = `
        <div>
            <strong>${escapeHtml(otherUsername)}</strong>
            <div style="font-size: 0.875rem; color: var(--text-secondary);">${escapeHtml(itemTitle)}</div>
        </div>
    `;
    
    // Show delete button
    document.getElementById('deleteChatBtn').style.display = 'block';
    
    // Show chat, hide no chat selected
    document.getElementById('noChatSelected').style.display = 'none';
    document.getElementById('chatContainer').style.display = 'flex';
    
    // Load messages (which will include user details)
    await loadMessages(itemId, otherUserId);
    
    // Scroll to bottom
    scrollChatToBottom();
}

function closeChat() {
    document.getElementById('chatContainer').style.display = 'none';
    document.getElementById('noChatSelected').style.display = 'block';
    document.getElementById('deleteChatBtn').style.display = 'none';
    currentConversation = null;
}

async function handleDeleteConversation() {
    if (!currentConversation || !authToken) {
        return;
    }
    
    // First confirmation
    if (!confirm('Are you sure you want to delete this conversation? This action cannot be undone.')) {
        return;
    }
    
    // Second confirmation
    if (!confirm('This will permanently delete all messages in this conversation. Are you absolutely sure?')) {
        return;
    }
    
    try {
        const { itemId, otherUserId } = currentConversation;
        const response = await fetch(`${API_BASE}/api/messages/conversation/${itemId}/${otherUserId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok || response.status === 204) {
            showMessage('Conversation deleted successfully', 'success');
            // Close the chat
            closeChat();
            // Reload conversations list
            await loadConversations();
            // Update unread count
            await checkUnreadMessages();
        } else {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Failed to delete conversation');
        }
    } catch (error) {
        console.error('Delete conversation error:', error);
        showMessage(error.message || 'An error occurred while deleting the conversation. Please try again.', 'error');
    }
}

async function loadMessages(itemId, otherUserId) {
    if (!authToken) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/messages/conversation/${itemId}/${otherUserId}`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        if (response.ok) {
            const messages = await response.json();
            displayMessages(messages);
            
            // Update chat header with user details from first message
            if (messages.length > 0) {
                const otherUser = messages[0].sender_id === otherUserId ? messages[0].sender : messages[0].receiver;
                updateChatHeader(otherUser, currentConversation.itemTitle);
                // Show delete button
                document.getElementById('deleteChatBtn').style.display = 'block';
            }
            
            checkUnreadMessages(); // Update badge
        } else {
            showMessage('Failed to load messages', 'error');
        }
    } catch (error) {
        console.error('Load messages error:', error);
        showMessage('An error occurred while loading messages', 'error');
    }
}

function updateChatHeader(otherUser, itemTitle) {
    if (!otherUser) return;
    
    const name = otherUser.full_name || otherUser.username;
    const university = otherUser.university || '';
    
    // Create avatar for header
    const avatarUrl = getImageUrl(otherUser.profile_picture);
    const avatarHtml = avatarUrl
        ? `<img src="${avatarUrl}" alt="${escapeHtml(name)}" style="width: 2.5rem; height: 2.5rem; border-radius: 50%; object-fit: cover; margin-right: 0.75rem; border: 2px solid var(--primary-color);">`
        : `<div style="width: 2.5rem; height: 2.5rem; border-radius: 50%; background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%); display: flex; align-items: center; justify-content: center; color: white; font-weight: 600; margin-right: 0.75rem; border: 2px solid var(--primary-color);">${name.charAt(0).toUpperCase()}</div>`;
    
    document.getElementById('chatHeaderInfo').innerHTML = `
        <div style="display: flex; align-items: center;">
            ${avatarHtml}
            <div>
                <strong>${escapeHtml(name)}</strong>
                ${university ? `<div style="font-size: 0.875rem; color: var(--text-secondary);">${escapeHtml(university)}</div>` : ''}
                <div style="font-size: 0.875rem; color: var(--text-secondary); margin-top: 0.25rem;">${escapeHtml(itemTitle)}</div>
            </div>
        </div>
    `;
}


function displayMessages(messages) {
    const container = document.getElementById('chatMessages');
    
    if (messages.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: var(--text-secondary); padding: 2rem;">No messages yet. Start the conversation!</p>';
        return;
    }
    
    container.innerHTML = messages.map(msg => {
        const isSent = msg.sender_id === currentUser.id;
        const time = formatTime(msg.created_at);
        
        return `
            <div class="message ${isSent ? 'sent' : 'received'}">
                <div class="message-content">
                    <div class="message-text">${escapeHtml(msg.content)}</div>
                    <div class="message-time">${time}</div>
                </div>
            </div>
        `;
    }).join('');
    
    scrollChatToBottom();
}

function toggleEmojiPicker() {
    const picker = document.getElementById('emojiPicker');
    picker.style.display = picker.style.display === 'none' ? 'block' : 'none';
}

function insertEmoji(emoji) {
    const input = document.getElementById('messageInput');
    const cursorPos = input.selectionStart || input.value.length;
    const textBefore = input.value.substring(0, cursorPos);
    const textAfter = input.value.substring(input.selectionEnd || cursorPos);
    input.value = textBefore + emoji + textAfter;
    input.focus();
    input.setSelectionRange(cursorPos + emoji.length, cursorPos + emoji.length);
    // Close emoji picker after selection
    document.getElementById('emojiPicker').style.display = 'none';
}

// Close emoji picker when clicking outside
document.addEventListener('click', (e) => {
    const picker = document.getElementById('emojiPicker');
    const emojiBtn = document.querySelector('.btn-emoji');
    if (picker && emojiBtn && !picker.contains(e.target) && !emojiBtn.contains(e.target)) {
        picker.style.display = 'none';
    }
});

async function sendMessage(e) {
    e.preventDefault();
    if (!authToken || !currentConversation) return;
    
    const input = document.getElementById('messageInput');
    const content = input.value.trim();
    
    if (!content) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/messages/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                item_id: currentConversation.itemId,
                receiver_id: currentConversation.otherUserId,
                content: content
            })
        });
        
        if (response.ok) {
            input.value = '';
            // Reload messages to show the new one
            await loadMessages(currentConversation.itemId, currentConversation.otherUserId);
            // Reload conversations to update last message
            await loadConversations();
        } else {
            const error = await response.json().catch(() => ({}));
            showMessage(error.detail || 'Failed to send message', 'error');
        }
    } catch (error) {
        console.error('Send message error:', error);
        showMessage('An error occurred while sending message', 'error');
    }
}

function startConversation(itemId, sellerId) {
    if (!currentUser) {
        showMessage('Please login to message sellers', 'error');
        showLogin();
        return;
    }
    
    if (currentUser.id === sellerId) {
        showMessage('You cannot message yourself', 'error');
        return;
    }
    
    // Redirect to messages page with query parameters
    window.location.href = `/messages?itemId=${itemId}&sellerId=${sellerId}`;
}

function scrollChatToBottom() {
    const container = document.getElementById('chatMessages');
    container.scrollTop = container.scrollHeight;
}

function formatTime(dateString) {
    if (!dateString) return 'Just now';
    
    // Parse the date string - FastAPI returns ISO 8601 format
    let date;
    try {
        // If date has no timezone info, JavaScript will parse it as local time
        // This is usually correct for server times stored in local timezone
        date = new Date(dateString);
        
        // If parsing failed, try adding UTC timezone
        if (isNaN(date.getTime())) {
            // Try treating as UTC if no timezone specified
            if (!dateString.includes('Z') && !dateString.match(/[+-]\d{2}:?\d{2}$/)) {
                date = new Date(dateString + 'Z');
            } else {
                // Try parsing as-is one more time
                date = new Date(dateString);
            }
        }
    } catch (e) {
        console.error('Error parsing date:', dateString, e);
        return 'Just now';
    }
    
    // Check if date is valid
    if (isNaN(date.getTime())) {
        console.error('Invalid date string:', dateString, 'Type:', typeof dateString);
        return 'Just now';
    }
    
    const now = new Date();
    let diff = now.getTime() - date.getTime();
    
    // If date appears to be in the future (more than 1 hour), likely timezone issue
    // Try parsing as local time without timezone
    if (diff < -3600000) { // More than 1 hour in the future
        try {
            // Remove timezone info and parse as local
            const localStr = dateString.replace(/Z$/, '').replace(/[+-]\d{2}:?\d{2}$/, '');
            const localDate = new Date(localStr);
            if (!isNaN(localDate.getTime())) {
                const localDiff = now.getTime() - localDate.getTime();
                if (localDiff >= 0) {
                    // Use the local time parsing
                    date = localDate;
                    diff = localDiff;
                }
            }
        } catch (e) {
            // Keep original date
        }
    }
    
    // If still in the future after correction, show as "Just now" to avoid confusion
    if (diff < 0) {
        console.warn('Date in future after parsing:', dateString, 'Parsed:', date.toISOString(), 'Now:', now.toISOString());
        return 'Just now';
    }
    
    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);
    const weeks = Math.floor(days / 7);
    const months = Math.floor(days / 30);
    const years = Math.floor(days / 365);
    
    if (seconds < 60) return 'Just now';
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    if (days < 7) return `${days}d ago`;
    if (weeks < 4) return `${weeks}w ago`;
    if (months < 12) return `${months}mo ago`;
    if (years >= 1) return `${years}y ago`;
    
    // For dates older than a year, show the actual date
    return date.toLocaleDateString('en-US', { 
        month: 'short', 
        day: 'numeric',
        year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined
    });
}

// Profile functions
async function loadProfile() {
    if (!authToken) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/profile/`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        if (response.ok) {
            const profile = await response.json();
            displayProfile(profile);
        } else {
            showMessage('Failed to load profile', 'error');
        }
    } catch (error) {
        console.error('Load profile error:', error);
        showMessage('An error occurred while loading profile', 'error');
    }
}

function displayProfile(profile) {
    document.getElementById('profileEmail').value = profile.email || '';
    document.getElementById('profileUsername').value = profile.username || '';
    document.getElementById('profileFullName').value = profile.full_name || '';
    document.getElementById('profileUniversity').value = profile.university || '';
    document.getElementById('profilePhone').value = profile.phone || '';
    const referralCodeInput = document.getElementById('profileReferralCode');
    const referralLinkInput = document.getElementById('profileReferralLink');
    const referralCode = (profile.referral_code || '').trim().toUpperCase();
    if (currentUser) {
        currentUser.referral_code = referralCode || currentUser.referral_code;
    }
    if (referralCodeInput) {
        referralCodeInput.value = referralCode;
    }
    if (referralLinkInput) {
        referralLinkInput.value = buildReferralInviteLink(referralCode);
    }
    renderReferralPromotions();
    
    // Display profile picture
    const preview = document.getElementById('profilePicturePreview');
    const placeholder = document.getElementById('profilePicturePlaceholder');
    
    if (profile.profile_picture) {
        preview.src = getImageUrl(profile.profile_picture);
        preview.style.display = 'block';
        placeholder.style.display = 'none';
    } else {
        preview.style.display = 'none';
        placeholder.style.display = 'flex';
        placeholder.textContent = (profile.full_name || profile.username || 'U').charAt(0).toUpperCase();
    }
    
    // Check for pending university change
    checkPendingUniversityChange();
    loadReferralSummary();
    
    // Load documentation preferences
    loadDocumentationPreferences();

    const profilePasswordForm = document.getElementById('profileChangePasswordForm');
    if (profilePasswordForm) {
        profilePasswordForm.reset();
    }
    updateProfilePasswordHint();
}

async function loadReferralSummary() {
    if (!authToken) return;
    const statsEl = document.getElementById('profileReferralStats');
    if (statsEl) {
        statsEl.textContent = 'Loading referral stats...';
    }

    try {
        const response = await fetch(`${API_BASE}/api/profile/referral-summary`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        if (!response.ok) {
            throw new Error('Failed to load referral summary');
        }

        const summary = await response.json();
        const referralCode = (summary.referral_code || '').trim().toUpperCase();
        if (currentUser) {
            currentUser.referral_code = referralCode || currentUser.referral_code;
        }
        const referralCodeInput = document.getElementById('profileReferralCode');
        const referralLinkInput = document.getElementById('profileReferralLink');
        if (referralCodeInput) referralCodeInput.value = referralCode;
        if (referralLinkInput) {
            referralLinkInput.value = buildReferralInviteLink(referralCode);
        }
        if (statsEl) {
            statsEl.textContent =
                `Invited: ${summary.total_invited} • Rewarded: ${summary.successful_referrals} • Pending: ${summary.pending_referrals}`;
        }
        renderReferralPromotions(summary);
    } catch (error) {
        console.error('Error loading referral summary:', error);
        if (statsEl) {
            statsEl.textContent = 'Unable to load referral stats right now.';
        }
        renderReferralPromotions();
    }
}

function renderReferralPromotions(summary = null) {
    const banner = document.getElementById('dashboardReferralBanner');
    const bannerCodeEl = document.getElementById('dashboardReferralBannerCode');
    const bannerStatsEl = document.getElementById('dashboardReferralBannerStats');
    const promoCodeEl = document.getElementById('referralPromoCode');
    const promoLinkEl = document.getElementById('referralPromoLink');

    const referralCode = getCurrentReferralCode();
    const referralLink = buildReferralInviteLink(referralCode);

    if (banner) {
        banner.style.display = currentUser ? 'flex' : 'none';
    }
    if (bannerCodeEl) {
        bannerCodeEl.textContent = referralCode || '--------';
    }
    if (promoCodeEl) {
        promoCodeEl.textContent = referralCode || '--------';
    }
    if (promoLinkEl) {
        promoLinkEl.textContent = referralLink || 'Referral link will appear shortly.';
    }

    if (bannerStatsEl) {
        if (summary && typeof summary === 'object') {
            bannerStatsEl.textContent =
                `Invited ${summary.total_invited} • Rewarded ${summary.successful_referrals} • Pending ${summary.pending_referrals}`;
        } else {
            bannerStatsEl.textContent = 'Share to unlock rewards.';
        }
    }
}

function openReferralPromoModal(force = false) {
    if (!currentUser && !force) return;
    renderReferralPromotions();
    if (!getCurrentReferralCode() && authToken) {
        void loadReferralSummary();
    }
    const modal = document.getElementById('referralPromoModal');
    if (!modal) return;
    modal.style.display = 'flex';
}

function closeReferralPromoModal() {
    const modal = document.getElementById('referralPromoModal');
    if (!modal) return;
    modal.style.display = 'none';
}

async function copyTextToClipboard(text) {
    if (!text) return false;
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch (error) {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.setAttribute('readonly', '');
        textarea.style.position = 'absolute';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.select();
        let success = false;
        try {
            success = document.execCommand('copy');
        } catch (execError) {
            success = false;
        }
        document.body.removeChild(textarea);
        return success;
    }
}

async function copyReferralCode() {
    const code = getCurrentReferralCode();
    if (!code) {
        showMessage('Referral code not available yet.', 'error');
        return;
    }
    const copied = await copyTextToClipboard(code);
    showMessage(copied ? 'Referral code copied.' : 'Unable to copy referral code.', copied ? 'success' : 'error');
}

async function copyReferralLink() {
    const link = buildReferralInviteLink(getCurrentReferralCode());
    if (!link) {
        showMessage('Referral link not available yet.', 'error');
        return;
    }
    const copied = await copyTextToClipboard(link);
    showMessage(copied ? 'Referral link copied.' : 'Unable to copy referral link.', copied ? 'success' : 'error');
}

async function loadDocumentationPreferences() {
    if (!authToken) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/profile/documentation-preferences`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok) {
            const prefs = await response.json();
            
            // Populate the form fields
            const countryField = document.getElementById('documentationCountry');
            const intakeField = document.getElementById('documentationIntake');
            const yearField = document.getElementById('documentationYear');
            
            if (countryField && prefs.country) {
                countryField.value = prefs.country;
            }
            if (intakeField && prefs.intake) {
                intakeField.value = prefs.intake;
            }
            if (yearField && prefs.year) {
                yearField.value = prefs.year;
            }
        }
    } catch (error) {
        console.error('Error loading documentation preferences:', error);
        // Fall back to localStorage
        const localPrefs = localStorage.getItem('documentationPreferences');
        if (localPrefs) {
            const prefs = JSON.parse(localPrefs);
            const intakeField = document.getElementById('documentationIntake');
            const yearField = document.getElementById('documentationYear');
            if (intakeField && prefs.intake) intakeField.value = prefs.intake;
            if (yearField && prefs.year) yearField.value = prefs.year;
        }
    }
}

async function loadDashboardStats() {
    if (!authToken) return;
    
    try {
        // Load profile completion and pending documents (main dashboard content)
        await loadProfileCompletion();
    } catch (error) {
        console.error('Load dashboard stats error:', error);
    }
}

async function loadProfileCompletion() {
    if (!authToken) return;
    
    try {
        // Load profile data
        const profileResponse = await fetch(`${API_BASE}/api/profile/`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        // Load documents
        const documentsResponse = await fetch(`${API_BASE}/api/documents/my-documents`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        let profile = null;
        let documents = [];
        
        if (profileResponse.ok) {
            profile = await profileResponse.json();
        }
        
        if (documentsResponse.ok) {
            documents = await documentsResponse.json();
        }
        
        // Calculate profile completion
        const completionData = calculateProfileCompletion(profile, documents);
        
        // Update UI
        updateProfileCompletionUI(completionData);
        
        // Update visa journey tracker
        updateVisaJourneyUI(documents);
        updateOverviewDocumentHealthUI(documents);
        updateDocumentsTabHealthUI(documents);
        
        // NOTE: We no longer save to R2 on every dashboard load
        // R2 is only updated when data actually changes (document upload/delete, profile update, preferences update)
    } catch (error) {
        console.error('Load profile completion error:', error);
    }
}

function updateOverviewDocumentHealthUI(documents) {
    updateDocumentHealthUI(documents, {
        totalUploadedId: 'overviewTotalUploaded',
        uniqueTypesId: 'overviewUniqueTypes',
        validatedCountId: 'overviewValidatedCount',
        needsReviewCountId: 'overviewNeedsReviewCount',
        pendingValidationCountId: 'overviewPendingValidationCount',
        processedCountId: 'overviewProcessedCount',
        validationRateId: 'overviewValidationRate',
        validationRateBarId: 'overviewValidationRateBar',
        healthStatusId: 'overviewDocumentHealthStatus',
        validationListId: 'overviewValidationList',
        listItemTitle: 'Open in Documents tab'
    });
}

function updateDocumentsTabHealthUI(documents) {
    updateDocumentHealthUI(documents, {
        totalUploadedId: 'documentsTotalUploaded',
        uniqueTypesId: 'documentsUniqueTypes',
        validatedCountId: 'documentsValidatedCount',
        needsReviewCountId: 'documentsNeedsReviewCount',
        pendingValidationCountId: 'documentsPendingValidationCount',
        processedCountId: 'documentsProcessedCount',
        validationRateId: 'documentsValidationRate',
        validationRateBarId: 'documentsValidationRateBar',
        healthStatusId: 'documentsHealthStatus',
        validationListId: 'documentsValidationList',
        listItemTitle: 'Jump to document'
    });
}

function updateDocumentHealthUI(documents, config) {
    const totalUploaded = documents.length;
    const uniqueTypes = new Set(documents.map(doc => doc.document_type).filter(Boolean)).size;
    const validatedCount = documents.filter(doc => doc.is_valid === true).length;
    const needsReviewCount = documents.filter(doc => doc.is_valid === false).length;
    const pendingValidationCount = documents.filter(doc => doc.is_valid === null || doc.is_valid === undefined).length;
    const processedCount = documents.filter(doc => doc.is_processed === true).length;

    const reviewedCount = validatedCount + needsReviewCount;
    const validationRate = reviewedCount > 0 ? Math.round((validatedCount / reviewedCount) * 100) : 0;
    const processingRate = totalUploaded > 0 ? Math.round((processedCount / totalUploaded) * 100) : 0;
    const healthScore = totalUploaded > 0 ? Math.round((validationRate * 0.7) + (processingRate * 0.3)) : 0;

    setTextContent(config.totalUploadedId, totalUploaded);
    setTextContent(config.uniqueTypesId, uniqueTypes);
    setTextContent(config.validatedCountId, validatedCount);
    setTextContent(config.needsReviewCountId, needsReviewCount);
    setTextContent(config.pendingValidationCountId, pendingValidationCount);
    setTextContent(config.processedCountId, processedCount);
    setTextContent(config.validationRateId, `${validationRate}%`);

    const rateBar = document.getElementById(config.validationRateBarId);
    if (rateBar) {
        rateBar.style.width = `${validationRate}%`;
    }

    const healthBadge = document.getElementById(config.healthStatusId);
    if (healthBadge) {
        if (totalUploaded === 0) {
            healthBadge.textContent = 'No Data';
            healthBadge.style.background = 'var(--bg-tertiary)';
            healthBadge.style.borderColor = 'var(--border-color)';
            healthBadge.style.color = 'var(--text-primary)';
        } else if (needsReviewCount === 0 && healthScore >= 85) {
            healthBadge.textContent = 'Excellent';
            healthBadge.style.background = 'rgba(16, 185, 129, 0.15)';
            healthBadge.style.borderColor = 'rgba(16, 185, 129, 0.35)';
            healthBadge.style.color = '#34d399';
        } else if (healthScore >= 70) {
            healthBadge.textContent = 'Good';
            healthBadge.style.background = 'rgba(99, 102, 241, 0.15)';
            healthBadge.style.borderColor = 'rgba(99, 102, 241, 0.35)';
            healthBadge.style.color = '#818cf8';
        } else if (healthScore >= 50) {
            healthBadge.textContent = 'Fair';
            healthBadge.style.background = 'rgba(245, 158, 11, 0.15)';
            healthBadge.style.borderColor = 'rgba(245, 158, 11, 0.35)';
            healthBadge.style.color = '#fbbf24';
        } else {
            healthBadge.textContent = 'Needs Attention';
            healthBadge.style.background = 'rgba(239, 68, 68, 0.15)';
            healthBadge.style.borderColor = 'rgba(239, 68, 68, 0.35)';
            healthBadge.style.color = '#f87171';
        }
    }

    const listContainer = document.getElementById(config.validationListId);
    if (listContainer) {
        if (totalUploaded === 0) {
            listContainer.innerHTML = '<div class="overview-health-empty">No documents uploaded yet.</div>';
            return;
        }

        const recentDocuments = [...documents]
            .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
            .slice(0, 5);

        listContainer.innerHTML = recentDocuments.map((doc) => {
            let statusLabel = 'Pending';
            let statusStyle = 'background: rgba(148, 163, 184, 0.18); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.3);';

            if (doc.is_valid === true) {
                statusLabel = 'Valid';
                statusStyle = 'background: rgba(16, 185, 129, 0.18); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.35);';
            } else if (doc.is_valid === false) {
                statusLabel = 'Needs Review';
                statusStyle = 'background: rgba(239, 68, 68, 0.18); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.35);';
            }

            const name = doc.document_type ? formatDocumentType(doc.document_type) : (doc.original_filename || 'Document');
            const encodedDocumentType = encodeURIComponent(doc.document_type || '');
            const documentId = Number.isFinite(doc.id) ? doc.id : 0;

            return `
                <div class="overview-health-item overview-health-item-clickable" onclick="jumpToDocumentInDocumentsTab(${documentId}, '${encodedDocumentType}')" title="${escapeHtml(config.listItemTitle || 'Open document')}">
                    <div class="overview-health-item-name">${escapeHtml(name)}</div>
                    <div class="overview-health-item-status" style="${statusStyle}">${statusLabel}</div>
                </div>
            `;
        }).join('');
    }
}

function setTextContent(id, value) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = String(value);
    }
}

function formatDocumentType(type) {
    if (documentTypeLabelByValue[type]) {
        return documentTypeLabelByValue[type];
    }
    return type
        .replace(/[-_]/g, ' ')
        .replace(/\b\w/g, (c) => c.toUpperCase());
}

async function jumpToDocumentInDocumentsTab(documentId, encodedDocumentType = '') {
    const documentType = encodedDocumentType ? decodeURIComponent(encodedDocumentType) : '';

    switchDashboardTab('documents');

    // Ensure document list is freshly rendered before searching for anchors.
    await loadMyDocuments();

    const targetById = documentId ? document.querySelector(`[data-document-id="${documentId}"]`) : null;
    const targetByType = !targetById && documentType
        ? document.querySelector(`[data-document-type="${documentType}"]`)
        : null;
    const target = targetById || targetByType;

    if (!target) {
        showMessage('Could not find that document in the documents list.', 'error');
        return;
    }

    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    target.classList.add('document-focus-highlight');
    setTimeout(() => target.classList.remove('document-focus-highlight'), 2200);
}

async function saveVisaStatusToR2() {
    if (!authToken) return;
    
    try {
        // Use POST /refresh endpoint to actually write to R2
        // GET /visa-status only reads (doesn't write)
        const response = await fetch(`${API_BASE}/api/documents/visa-status/refresh`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok) {
            const data = await response.json();
            console.log('Visa status saved to R2:', data.r2_key);
        }
    } catch (error) {
        console.error('Failed to save visa status to R2:', error);
    }
}

function calculateProfileCompletion(profile, documents) {
    // Profile fields to check
    const profileFields = {
        'full_name': profile?.full_name,
        'university': profile?.university,
        'phone': profile?.phone,
        'profile_picture': profile?.profile_picture
    };
    
    // Required document types come from database-backed catalog.
    const requiredDocuments = requiredDocumentTypeValues.length
        ? [...requiredDocumentTypeValues]
        : FALLBACK_DOCUMENT_TYPES.filter((row) => row.is_required).map((row) => row.value);
    
    // Count completed profile fields
    let completedFields = 0;
    const totalFields = Object.keys(profileFields).length;
    
    for (const field of Object.values(profileFields)) {
        if (field && field.trim() !== '') {
            completedFields++;
        }
    }
    
    // Get uploaded document types
    const uploadedDocTypes = new Set(
        documents.map(doc => doc.document_type).filter(type => type)
    );
    
    // Find pending documents
    const pendingDocuments = requiredDocuments.filter(docType => !uploadedDocTypes.has(docType));
    
    // Calculate completion percentage
    // Profile fields: 40% weight, Documents: 60% weight
    const profileCompletion = (completedFields / totalFields) * 100;
    const documentsCompletion = requiredDocuments.length
        ? ((requiredDocuments.length - pendingDocuments.length) / requiredDocuments.length) * 100
        : 100;
    const overallCompletion = Math.round((profileCompletion * 0.4) + (documentsCompletion * 0.6));
    
    return {
        overallCompletion,
        profileCompletion: Math.round(profileCompletion),
        documentsCompletion: Math.round(documentsCompletion),
        pendingDocuments,
        uploadedCount: documents.length,
        totalRequiredDocuments: requiredDocuments.length
    };
}

function updateProfileCompletionUI(data) {
    // Update completion percentage
    const percentEl = document.getElementById('profileCompletionPercent');
    const barEl = document.getElementById('profileCompletionBar');
    const pendingListEl = document.getElementById('pendingDocumentsList');
    
    if (percentEl) {
        percentEl.textContent = `${data.overallCompletion}%`;
    }
    
    if (barEl) {
        barEl.style.width = `${data.overallCompletion}%`;
    }
    
    // Update pending documents list
    if (pendingListEl) {
        if (data.pendingDocuments.length === 0) {
            pendingListEl.innerHTML = `
                <div style="background: #d4edda; border: 1px solid #c3e6cb; border-radius: 0.5rem; padding: 0.75rem; text-align: center;">
                    <span style="color: #155724; font-weight: 600;">✓ All required documents uploaded!</span>
                </div>
            `;
        } else {
            const pendingList = data.pendingDocuments.slice(0, 5).map(docType => {
                const displayName = getDocumentTypeLabel(docType);
                return `
                    <div style="display: flex; align-items: center; padding: 0.5rem 0; border-bottom: 1px solid var(--border-color);">
                        <span style="color: var(--danger-color); margin-right: 0.5rem;">○</span>
                        <span style="color: var(--text-primary); font-size: 0.875rem;">${escapeHtml(displayName)}</span>
                    </div>
                `;
            }).join('');
            
            const moreCount = data.pendingDocuments.length > 5 ? data.pendingDocuments.length - 5 : 0;
            
            pendingListEl.innerHTML = `
                ${pendingList}
                ${moreCount > 0 ? `
                    <div style="padding: 0.5rem 0; text-align: center; color: var(--text-secondary); font-size: 0.875rem;">
                        +${moreCount} more document${moreCount > 1 ? 's' : ''} pending
                    </div>
                ` : ''}
                <div style="margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px solid var(--border-color); font-size: 0.875rem; color: var(--text-secondary);">
                    ${data.uploadedCount} of ${data.totalRequiredDocuments} required documents uploaded
                </div>
            `;
        }
    }
}

// Visa Journey Tracker Functions
function calculateVisaJourneyStage(documents) {
    const uploadedDocTypes = new Set(
        documents.map(doc => doc.document_type).filter(type => type)
    );
    const validatedDocTypes = new Set(
        documents
            .filter((doc) => doc && doc.document_type && doc.is_valid === true)
            .map((doc) => doc.document_type)
    );
    const stages = (journeyStageCatalog && journeyStageCatalog.length)
        ? journeyStageCatalog.map((stage) => ({
            stage: stage.stage,
            name: stage.name,
            emoji: stage.emoji,
            description: stage.description,
            nextStep: stage.next_step || stage.nextStep || '',
            requiredDocs: Array.isArray(stage.required_docs) ? stage.required_docs : []
        }))
        : FALLBACK_JOURNEY_STAGES.map((stage) => ({
            stage: stage.stage,
            name: stage.name,
            emoji: stage.emoji,
            description: stage.description,
            nextStep: stage.next_step || stage.nextStep || '',
            requiredDocs: Array.isArray(stage.required_docs) ? stage.required_docs : []
        }));

    let currentStage = 1;
    const stageGateRules = documentTypeCatalog.filter((row) => row.stage_gate_required && row.journey_stage);
    const orderedStages = [...stages].sort((a, b) => a.stage - b.stage);

    const isRuleSatisfied = (rule) => {
        if (rule.stage_gate_requires_validation) {
            return validatedDocTypes.has(rule.value);
        }
        return uploadedDocTypes.has(rule.value);
    };

    const isStageComplete = (stageNumber) => {
        const gateDocs = stageGateRules.filter((row) => Number(row.journey_stage) === stageNumber);
        if (!gateDocs.length) return true;

        const directRules = gateDocs.filter((row) => !row.stage_gate_group);
        if (directRules.some((rule) => !isRuleSatisfied(rule))) {
            return false;
        }

        const grouped = {};
        gateDocs.forEach((row) => {
            if (!row.stage_gate_group) return;
            if (!grouped[row.stage_gate_group]) grouped[row.stage_gate_group] = [];
            grouped[row.stage_gate_group].push(row);
        });

        return Object.values(grouped).every((groupRules) => groupRules.some((rule) => isRuleSatisfied(rule)));
    };

    const stageCompletionMap = {};
    orderedStages.forEach((stage) => {
        stageCompletionMap[stage.stage] = isStageComplete(stage.stage);
    });

    let foundInProgressStage = false;
    for (const stage of orderedStages) {
        const stageNumber = Number(stage.stage || 0);
        if (!stageNumber) continue;

        const previousStageComplete = stageNumber === 1 ? true : stageCompletionMap[stageNumber - 1] === true;
        const thisStageComplete = stageCompletionMap[stageNumber] === true;
        if (previousStageComplete && !thisStageComplete) {
            currentStage = stageNumber;
            foundInProgressStage = true;
            break;
        }
    }

    let completedStageCount = 0;
    for (const stage of orderedStages) {
        if (stageCompletionMap[stage.stage]) {
            completedStageCount += 1;
            continue;
        }
        break;
    }

    const allStagesComplete = completedStageCount === orderedStages.length && orderedStages.length > 0;
    if (!foundInProgressStage && allStagesComplete) {
        currentStage = orderedStages[orderedStages.length - 1]?.stage || 1;
    }

    const stageInfo = stages.find((stage) => stage.stage === currentStage) || stages[0];
    const progressPercent = Math.round((completedStageCount / Math.max(stages.length, 1)) * 100);

    return {
        currentStage,
        stageInfo,
        stages,
        stageCompletionMap,
        allStagesComplete,
        completedStageCount,
        progressPercent
    };
}

function updateVisaJourneyUI(documents) {
    const journeyData = calculateVisaJourneyStage(documents);
    const { currentStage, stageInfo, stages } = journeyData;

    updateVisaJourneyWidget({
        progressLineId: 'journeyProgressLine',
        stageIconPrefix: 'stageIcon',
        currentStageEmojiId: 'currentStageEmoji',
        currentStageNameId: 'currentStageName',
        currentStageDescId: 'currentStageDesc',
        nextStepHintId: 'nextStepHint',
        nextStepTextId: 'nextStepText'
    }, journeyData);

    updateVisaJourneyWidget({
        progressLineId: 'visaTabJourneyProgressLine',
        stageIconPrefix: 'visaTabStageIcon',
        currentStageEmojiId: 'visaTabCurrentStageEmoji',
        currentStageNameId: 'visaTabCurrentStageName',
        currentStageDescId: 'visaTabCurrentStageDesc',
        nextStepHintId: 'visaTabNextStepHint',
        nextStepTextId: 'visaTabNextStepText'
    }, journeyData);
}

function updateVisaJourneyWidget(config, journeyData) {
    const { currentStage, stageInfo, stages, stageCompletionMap = {}, allStagesComplete = false, progressPercent } = journeyData;

    const progressLine = document.getElementById(config.progressLineId);
    if (progressLine) {
        const normalizedPercent = Math.max(0, Math.min(100, Number(progressPercent) || 0));
        progressLine.style.width = `${(normalizedPercent / 100) * 90}%`;
    }

    // A stage should look completed only when it and all previous stages are completed.
    const sequentialCompletionMap = {};
    let previousSequentialComplete = true;
    for (let i = 1; i <= stages.length; i++) {
        const thisStageComplete = stageCompletionMap[i] === true;
        const isSequentiallyComplete = previousSequentialComplete && thisStageComplete;
        sequentialCompletionMap[i] = isSequentiallyComplete;
        previousSequentialComplete = isSequentiallyComplete;
    }

    for (let i = 1; i <= stages.length; i++) {
        const stageIcon = document.getElementById(`${config.stageIconPrefix}${i}`);
        if (!stageIcon) continue;

        const defaultEmoji = stages[i - 1]?.emoji || '•';
        stageIcon.style.animation = 'none';
        const isCompleted = sequentialCompletionMap[i] === true;
        const isInProgress = !allStagesComplete && i === currentStage && !isCompleted;

        if (isCompleted) {
            stageIcon.style.background = 'linear-gradient(135deg, var(--primary-color), var(--secondary-color))';
            stageIcon.style.color = 'white';
            stageIcon.style.boxShadow = '0 0 0 2px rgba(99, 102, 241, 0.45), 0 8px 22px rgba(139, 92, 246, 0.45)';
            stageIcon.innerHTML = '✓';
        } else if (isInProgress) {
            stageIcon.style.background = 'linear-gradient(135deg, var(--primary-color), var(--secondary-color))';
            stageIcon.style.color = 'white';
            stageIcon.style.boxShadow = '0 0 0 2px rgba(99, 102, 241, 0.5), 0 10px 24px rgba(99, 102, 241, 0.5)';
            stageIcon.style.animation = 'pulse 2s ease-in-out infinite';
            stageIcon.innerHTML = defaultEmoji;
        } else {
            stageIcon.style.background = 'var(--border-color)';
            stageIcon.style.color = 'var(--text-secondary)';
            stageIcon.style.boxShadow = 'none';
            stageIcon.innerHTML = defaultEmoji;
        }
    }

    const currentStageEmoji = document.getElementById(config.currentStageEmojiId);
    const currentStageName = document.getElementById(config.currentStageNameId);
    const currentStageDesc = document.getElementById(config.currentStageDescId);
    const nextStepText = document.getElementById(config.nextStepTextId);
    const nextStepHint = document.getElementById(config.nextStepHintId);

    if (currentStageEmoji) currentStageEmoji.textContent = stageInfo.emoji;
    if (currentStageName) currentStageName.textContent = `Stage ${currentStage}: ${stageInfo.name}`;
    if (currentStageDesc) currentStageDesc.textContent = stageInfo.description;
    if (nextStepText) nextStepText.textContent = stageInfo.nextStep;

    if (nextStepHint) {
        if (allStagesComplete) {
            nextStepHint.innerHTML = '<span style="color: #34d399; font-weight: 600;">🎉 Congratulations! You\'re all set for your journey!</span>';
        } else {
            nextStepHint.innerHTML = `<strong>Next step:</strong> <span id="${config.nextStepTextId}">${escapeHtml(stageInfo.nextStep)}</span>`;
        }
    }
}

function handleProfilePicturePreview(e) {
    const file = e.target.files[0];
    const preview = document.getElementById('profilePicturePreview');
    const placeholder = document.getElementById('profilePicturePlaceholder');
    
    if (file) {
        // Validate file type
        if (!file.type.startsWith('image/')) {
            showMessage('Please select an image file', 'error');
            e.target.value = '';
            return;
        }
        
        // Validate file size (2MB)
        if (file.size > 2 * 1024 * 1024) {
            showMessage('Image size must be less than 2MB', 'error');
            e.target.value = '';
            return;
        }
        
        // Show preview
        const reader = new FileReader();
        reader.onload = (e) => {
            preview.src = e.target.result;
            preview.style.display = 'block';
            placeholder.style.display = 'none';
        };
        reader.readAsDataURL(file);
    }
}

async function uploadProfilePicture(file) {
    const formData = new FormData();
    formData.append('file', file);
    
    const response = await fetch(`${API_BASE}/api/upload/profile-picture`, {
        method: 'POST',
        headers: {
            'Authorization': `Bearer ${authToken}`
        },
        body: formData
    });
    
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || 'Failed to upload profile picture');
    }
    
    const data = await response.json();
    return data.url;
}

async function handleUpdateProfile(e) {
    e.preventDefault();
    if (!authToken) {
        showMessage('Please login to update profile', 'error');
        return;
    }
    
    const getValue = (id) => {
        const value = document.getElementById(id).value.trim();
        return value === '' ? null : value;
    };
    
    // Handle profile picture upload if a file is selected
    let profilePictureUrl = null;
    const profilePictureInput = document.getElementById('profilePictureInput');
    if (profilePictureInput && profilePictureInput.files && profilePictureInput.files.length > 0) {
        try {
            showMessage('Uploading profile picture...', 'success');
            profilePictureUrl = await uploadProfilePicture(profilePictureInput.files[0]);
            showMessage('Profile picture uploaded!', 'success');
        } catch (error) {
            showMessage(error.message || 'Failed to upload profile picture', 'error');
            return;
        }
    }
    
    const profileData = {
        full_name: getValue('profileFullName'),
        // university is not editable - derived from .edu email at registration
        phone: getValue('profilePhone'),
        profile_picture: profilePictureUrl || currentUser.profile_picture || null
    };
    
    try {
        const response = await fetch(`${API_BASE}/api/profile/`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify(profileData)
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showMessage('Profile updated successfully!', 'success');
            currentUser = data;
            // Update UI to reflect changes
            renderUserInfo(currentUser);
            // Reload profile display if on dashboard
            displayProfile(data);
            
            // Update R2 with new profile data
            await saveVisaStatusToR2();
        } else {
            let errorMessage = 'Failed to update profile';
            if (data.detail) {
                if (Array.isArray(data.detail)) {
                    errorMessage = data.detail.map(err => `${err.loc.join('.')}: ${err.msg}`).join(', ');
                } else {
                    errorMessage = data.detail;
                }
            }
            showMessage(errorMessage, 'error');
        }
    } catch (error) {
        console.error('Update profile error:', error);
        showMessage('An error occurred. Please check your connection and try again.', 'error');
    }
}

async function handleProfileChangePassword(e) {
    e.preventDefault();

    if (!authToken) {
        showMessage('Please login to change your password', 'error');
        showLogin();
        return;
    }

    const currentPasswordInput = document.getElementById('profileCurrentPassword');
    const newPasswordInput = document.getElementById('profileNewPassword');
    const confirmPasswordInput = document.getElementById('profileConfirmPassword');
    const submitBtn = document.getElementById('profileChangePasswordBtn');

    const currentPassword = currentPasswordInput?.value || '';
    const newPassword = newPasswordInput?.value || '';
    const confirmPassword = confirmPasswordInput?.value || '';

    if (!currentPassword || !newPassword || !confirmPassword) {
        showMessage('Please fill all password fields', 'error');
        return;
    }

    if (currentPassword === newPassword) {
        showMessage('New password must be different from your current password.', 'error');
        return;
    }

    const userEmail = currentUser?.email || document.getElementById('profileEmail')?.value || '';
    const passwordErrors = getPasswordValidationErrors(newPassword, userEmail);
    if (passwordErrors.length > 0) {
        showMessage(`Please use a stronger password: ${passwordErrors[0]}.`, 'error');
        updateProfilePasswordHint();
        return;
    }

    if (newPassword !== confirmPassword) {
        showMessage('New password and confirmation do not match', 'error');
        return;
    }

    const originalButtonText = submitBtn?.textContent || 'Change Password';
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Changing...';
    }

    try {
        const response = await fetch(`${API_BASE}/api/profile/change-password`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                current_password: currentPassword,
                new_password: newPassword
            })
        });

        const data = await response.json().catch(() => ({}));

        if (response.ok) {
            const form = document.getElementById('profileChangePasswordForm');
            if (form) form.reset();
            updateProfilePasswordHint();
            showMessage(data.message || 'Password changed successfully.', 'success');
            return;
        }

        if (response.status === 401) {
            showMessage('Session expired. Please login again.', 'error');
            logout();
            return;
        }

        showMessage(data.detail || 'Failed to change password. Please try again.', 'error');
    } catch (error) {
        console.error('Change password error:', error);
        showMessage('An error occurred while changing password. Please try again.', 'error');
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = originalButtonText;
        }
    }
}

// ========== Change University Functions ==========

function showChangeUniversityModal() {
    const modal = document.getElementById('changeUniversityModal');
    modal.style.display = 'flex';
    document.getElementById('newUniversityEmail').value = '';
    document.getElementById('newUniversityName').value = '';
    document.getElementById('universityChangeError').style.display = 'none';
    
    // Add email input listener for auto-fill
    const emailInput = document.getElementById('newUniversityEmail');
    emailInput.addEventListener('input', debounce(checkNewUniversityEmail, 500));
}

function closeChangeUniversityModal() {
    document.getElementById('changeUniversityModal').style.display = 'none';
}

// Simple debounce function
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

async function checkNewUniversityEmail() {
    const email = document.getElementById('newUniversityEmail').value.trim();
    const universityInput = document.getElementById('newUniversityName');
    const errorDiv = document.getElementById('universityChangeError');
    
    if (!email || !email.includes('@')) {
        universityInput.value = '';
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/university-by-email?email=${encodeURIComponent(email)}`);
        const data = await response.json();
        
        if (data.is_valid && data.university_name) {
            universityInput.value = data.university_name;
            errorDiv.style.display = 'none';
        } else {
            universityInput.value = '';
            errorDiv.textContent = 'Please use a valid university .edu email address.';
            errorDiv.style.display = 'block';
        }
    } catch (error) {
        console.error('Error checking university email:', error);
        universityInput.value = '';
    }
}

async function handleChangeUniversity(e) {
    e.preventDefault();
    
    const email = document.getElementById('newUniversityEmail').value.trim();
    const university = document.getElementById('newUniversityName').value.trim();
    const errorDiv = document.getElementById('universityChangeError');
    const submitBtn = document.getElementById('changeUniversitySubmitBtn');
    const btnText = document.getElementById('changeUniversityBtnText');
    
    if (!email || !university) {
        errorDiv.textContent = 'Please enter a valid university email.';
        errorDiv.style.display = 'block';
        return;
    }
    
    // Disable button and show loading
    submitBtn.disabled = true;
    btnText.textContent = 'Sending...';
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/request-university-change`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                new_email: email,
                new_university: university
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            closeChangeUniversityModal();
            showMessage(data.message || 'Verification email sent! Check your inbox.', 'success');
            // Show pending change UI
            checkPendingUniversityChange();
        } else {
            errorDiv.textContent = data.detail || 'Failed to request university change.';
            errorDiv.style.display = 'block';
        }
    } catch (error) {
        console.error('Change university error:', error);
        errorDiv.textContent = 'An error occurred. Please try again.';
        errorDiv.style.display = 'block';
    } finally {
        submitBtn.disabled = false;
        btnText.textContent = 'Send Verification';
    }
}

async function checkPendingUniversityChange() {
    if (!authToken) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/pending-university-change`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        const data = await response.json();
        const pendingDiv = document.getElementById('pendingUniversityChange');
        const pendingName = document.getElementById('pendingUniversityName');
        
        if (data.has_pending_change) {
            pendingName.textContent = data.pending_university;
            pendingDiv.style.display = 'block';
        } else {
            pendingDiv.style.display = 'none';
        }
    } catch (error) {
        console.error('Error checking pending university change:', error);
    }
}

async function cancelUniversityChange() {
    if (!authToken) return;
    
    if (!confirm('Are you sure you want to cancel the university change request?')) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/cancel-university-change`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok) {
            showMessage('University change request cancelled.', 'success');
            document.getElementById('pendingUniversityChange').style.display = 'none';
        } else {
            const data = await response.json();
            showMessage(data.detail || 'Failed to cancel request.', 'error');
        }
    } catch (error) {
        console.error('Cancel university change error:', error);
        showMessage('An error occurred.', 'error');
    }
}

// ========== End Change University Functions ==========

async function handleDeleteAccount() {
    if (!authToken) {
        showMessage('Please login to delete your account', 'error');
        return;
    }
    
    // Double confirmation
    const confirmText = 'DELETE';
    const userInput = prompt(`This action cannot be undone. All your data including documents and profile will be permanently deleted.\n\nType "${confirmText}" to confirm account deletion:`);
    
    if (userInput !== confirmText) {
        if (userInput !== null) {
            showMessage('Account deletion cancelled. The confirmation text did not match.', 'error');
        }
        return;
    }
    
    // Final confirmation
    if (!confirm('Are you absolutely sure you want to delete your account? This action is permanent and cannot be undone.')) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/profile/`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok || response.status === 204) {
            showMessage('Your account has been deleted successfully.', 'success');
            // Clear auth state and logout
            authToken = null;
            persistAuthToken(null);
            currentUser = null;
            updateUIForAuth();
            showHomepage();
            // Redirect to home after a short delay
            setTimeout(() => {
                window.location.reload();
            }, 2000);
        } else {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Failed to delete account');
        }
    } catch (error) {
        console.error('Delete account error:', error);
        showMessage(error.message || 'An error occurred while deleting your account. Please try again.', 'error');
    }
}

// Image Gallery Functions
let currentGalleryImages = [];
let currentGalleryIndex = 0;
let currentGalleryItemId = null;
let currentGalleryItemTitle = '';

function handleItemImageClick(element) {
    const imageKey = element.getAttribute('data-image-key');
    const itemId = element.getAttribute('data-item-id');
    const itemTitle = element.getAttribute('data-item-title');
    
    if (!imageKey || !window.itemImagesMap || !window.itemImagesMap[imageKey]) {
        return;
    }
    
    openImageGallery(itemId, itemTitle, window.itemImagesMap[imageKey]);
}

function openImageGallery(itemId, itemTitle, images) {
    try {
        currentGalleryImages = Array.isArray(images) ? images : [];
        currentGalleryItemId = itemId;
        currentGalleryItemTitle = itemTitle;
        currentGalleryIndex = 0;
        
        if (currentGalleryImages.length === 0) {
            return;
        }
        
        const modal = document.getElementById('imageGalleryModal');
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden'; // Prevent background scrolling
        
        updateGalleryDisplay();
        setupGalleryKeyboardNavigation();
    } catch (error) {
        console.error('Error opening image gallery:', error);
    }
}

function closeImageGallery() {
    const modal = document.getElementById('imageGalleryModal');
    modal.style.display = 'none';
    document.body.style.overflow = ''; // Restore scrolling
    removeGalleryKeyboardNavigation();
}

function navigateGallery(direction) {
    if (currentGalleryImages.length === 0) return;
    
    currentGalleryIndex += direction;
    
    // Wrap around
    if (currentGalleryIndex < 0) {
        currentGalleryIndex = currentGalleryImages.length - 1;
    } else if (currentGalleryIndex >= currentGalleryImages.length) {
        currentGalleryIndex = 0;
    }
    
    updateGalleryDisplay();
}

function updateGalleryDisplay() {
    if (currentGalleryImages.length === 0) return;
    
    const mainImage = document.getElementById('galleryMainImage');
    const counter = document.getElementById('galleryImageCounter');
    const thumbnails = document.getElementById('galleryThumbnails');
    
    // Update main image
    mainImage.src = currentGalleryImages[currentGalleryIndex];
    mainImage.alt = `${currentGalleryItemTitle} - Image ${currentGalleryIndex + 1}`;
    
    // Update counter
    counter.textContent = `${currentGalleryIndex + 1} / ${currentGalleryImages.length}`;
    
    // Update thumbnails
    thumbnails.innerHTML = currentGalleryImages.map((img, index) => {
        const isActive = index === currentGalleryIndex ? 'active' : '';
        return `
            <div class="gallery-thumbnail ${isActive}" onclick="jumpToGalleryImage(${index})">
                <img src="${img}" alt="Thumbnail ${index + 1}">
            </div>
        `;
    }).join('');
    
    // Show/hide navigation arrows
    const prevBtn = document.querySelector('.image-gallery-prev');
    const nextBtn = document.querySelector('.image-gallery-next');
    
    if (currentGalleryImages.length <= 1) {
        prevBtn.style.display = 'none';
        nextBtn.style.display = 'none';
    } else {
        prevBtn.style.display = 'flex';
        nextBtn.style.display = 'flex';
    }
}

function jumpToGalleryImage(index) {
    if (index >= 0 && index < currentGalleryImages.length) {
        currentGalleryIndex = index;
        updateGalleryDisplay();
    }
}

function setupGalleryKeyboardNavigation() {
    document.addEventListener('keydown', handleGalleryKeyPress);
}

function removeGalleryKeyboardNavigation() {
    document.removeEventListener('keydown', handleGalleryKeyPress);
}

// Documentation Agent functions
function initializeYearDropdown() {
    const yearSelect = document.getElementById('documentationYear');
    if (!yearSelect) return;
    
    // Clear existing options except the first one
    yearSelect.innerHTML = '<option value="">Select Year</option>';
    
    // Get current year
    const currentYear = new Date().getFullYear();
    
    // Add years from current year to 5 years in the future
    for (let i = 0; i <= 5; i++) {
        const year = currentYear + i;
        const option = document.createElement('option');
        option.value = year;
        option.textContent = year;
        yearSelect.appendChild(option);
    }
}

function loadDocumentationPreferences() {
    // Load saved preferences from localStorage
    const savedPreferences = localStorage.getItem('documentationPreferences');
    if (savedPreferences) {
        try {
            const prefs = JSON.parse(savedPreferences);
            const intakeSelect = document.getElementById('documentationIntake');
            const yearSelect = document.getElementById('documentationYear');
            
            if (intakeSelect && prefs.intake) {
                intakeSelect.value = prefs.intake;
            }
            if (yearSelect && prefs.year) {
                yearSelect.value = prefs.year;
            }
        } catch (error) {
            console.error('Error loading documentation preferences:', error);
        }
    }
}

async function handleDocumentationForm(e) {
    e.preventDefault();
    
    const intake = document.getElementById('documentationIntake').value;
    const year = document.getElementById('documentationYear').value;
    const country = document.getElementById('documentationCountry').value;
    
    if (!intake || !year) {
        showMessage('Please select both intake and year', 'error');
        return;
    }
    
    if (!authToken) {
        showMessage('Please login to save preferences', 'error');
        return;
    }
    
    try {
        // Save to backend API
        const response = await fetch(`${API_BASE}/api/profile/documentation-preferences`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                country: country,
                intake: intake,
                year: parseInt(year)
            })
        });
        
        if (response.ok) {
            // Also save to localStorage as backup
            const preferences = {
                country: country,
                intake: intake,
                year: year,
                savedAt: new Date().toISOString()
            };
            localStorage.setItem('documentationPreferences', JSON.stringify(preferences));
            
            showMessage(`Preferences saved: ${intake} ${year}`, 'success');
            
            // Refresh the R2 student profile file
            await saveVisaStatusToR2();
        } else {
            const data = await response.json();
            showMessage(data.detail || 'Failed to save preferences', 'error');
        }
    } catch (error) {
        console.error('Save preferences error:', error);
        showMessage('Failed to save preferences. Please try again.', 'error');
    }
}

async function handleDocumentUpload(e) {
    e.preventDefault();
    if (documentUploadInProgress) {
        return;
    }

    if (!authToken) {
        showMessage('Please login to upload documents', 'error');
        return;
    }
    
    const fileInput = document.getElementById('documentFile');
    const password = document.getElementById('documentPassword').value;
    const documentType = document.getElementById('documentType').value;
    const description = document.getElementById('documentDescription').value.trim();
    const country = document.getElementById('documentationCountry').value;
    const intake = document.getElementById('documentationIntake').value;
    const year = document.getElementById('documentationYear').value ? parseInt(document.getElementById('documentationYear').value) : null;
    
    if (!fileInput.files || fileInput.files.length === 0) {
        showMessage('Please select a file to upload', 'error');
        return;
    }
    
    if (!password) {
        showMessage('Please enter your password to encrypt the document', 'error');
        return;
    }
    
    if (!documentType) {
        showMessage('Please select a document type', 'error');
        return;
    }
    
    const file = fileInput.files[0];
    
    // Validate file size (50MB)
    const maxSize = 50 * 1024 * 1024;
    if (file.size > maxSize) {
        showMessage('File is too large. Maximum size is 50MB', 'error');
        return;
    }
    
    try {
        setDocumentUploadLoading(true, 'Encrypting document...');
        showMessage('Encrypting and uploading document...', 'success');
        
        const formData = new FormData();
        formData.append('file', file);
        formData.append('password', password);  // Required for Zero-Knowledge encryption
        formData.append('document_type', documentType);  // Required field
        if (country) formData.append('country', country);
        if (intake) formData.append('intake', intake);
        if (year) formData.append('year', year);
        if (description) formData.append('description', description);
        
        const response = await fetch(`${API_BASE}/api/documents/upload`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`
            },
            body: formData
        });
        
        const data = await response.json();
        
        if (response.ok) {
            const documentName = file.name;
            const docType = documentType;
            
            // Check for validation results
            if (data.validation) {
                const validation = data.validation;
                if (!validation.is_valid) {
                    // Document validation failed
                    const docTypeText = docType ? ` (${docType})` : '';
                    const notificationMessage = `File: ${documentName}${docTypeText}\n\n${validation.message || 'The uploaded document does not match the specified type. Please verify and upload the correct document.'}`;
                    
                    addNotification(
                        'Rilono AI: Document Validation Failed',
                        notificationMessage,
                        'error',
                        validation.details
                    );
                    showMessage(validation.message || 'Document uploaded but validation failed. Please check notifications.', 'error');
                } else {
                    // Document validation passed
                    const name = validation.details?.Name || '';
                    const docTypeText = docType ? ` (${docType})` : '';
                    const successMsg = `File: ${documentName}${docTypeText}\n\n${name ? `Extracted name: ${name}\n\n` : ''}Document validated successfully! All information has been extracted.`;
                    
                    addNotification(
                        'Rilono AI: Document Validated',
                        successMsg,
                        'success',
                        validation.details
                    );
                    showMessage('Document encrypted and uploaded successfully!', 'success');
                }
            } else {
                // No validation data (legacy or processing failed)
                const docTypeText = docType ? ` (${docType})` : '';
                addNotification(
                    'Rilono AI: Document Uploaded',
                    `File: ${documentName}${docTypeText}\n\nDocument uploaded successfully. Processing may be in progress.`,
                    'info',
                    null
                );
                showMessage('Document encrypted and uploaded successfully!', 'success');
            }
            
            setDocumentUploadLoading(true, 'Upload complete. Syncing your documents...');
            document.getElementById('documentUploadForm').reset();
            // Also reset the searchable dropdown
            document.getElementById('documentType').value = '';
            document.getElementById('documentTypeSearch').value = '';
            const dropdownItems = document.querySelectorAll('#documentTypeList .dropdown-item');
            dropdownItems.forEach(item => item.classList.remove('selected'));
            await loadMyDocuments(true, 'Refreshing your uploaded documents...');
            setDocumentUploadLoading(false, 'Document is now visible in your list.');
            
            // Refresh visa status after document upload
            await saveVisaStatusToR2();
            await loadDashboardStats(); // Refresh the journey tracker
            void loadSubscriptionStatus(true);
        } else {
            let errorMessage = 'Failed to upload document';
            if (data.detail) {
                if (Array.isArray(data.detail)) {
                    errorMessage = data.detail.map(err => `${err.loc.join('.')}: ${err.msg}`).join(', ');
                } else {
                    errorMessage = data.detail;
                }
            }
            showMessage(errorMessage, 'error');
            if (response.status === 403) {
                void loadSubscriptionStatus(true);
            }
        }
    } catch (error) {
        console.error('Document upload error:', error);
        showMessage('An error occurred while uploading the document. Please try again.', 'error');
    } finally {
        if (documentUploadInProgress) {
            setDocumentUploadLoading(false);
        }
    }
}

function setDocumentUploadLoading(isLoading, message = '') {
    const form = document.getElementById('documentUploadForm');
    const modal = document.getElementById('documentUploadProgressModal');
    const modalTextEl = document.getElementById('documentUploadProgressText');
    if (!form) return;

    const submitButton = form.querySelector('button[type="submit"]');
    if (!submitButton) return;
    if (!submitButton.dataset.defaultText) {
        submitButton.dataset.defaultText = submitButton.textContent || 'Upload Document';
    }

    if (documentUploadStatusTimer) {
        clearTimeout(documentUploadStatusTimer);
        documentUploadStatusTimer = null;
    }

    if (isLoading) {
        documentUploadInProgress = true;
        const fields = form.querySelectorAll('input, textarea, button, select');
        fields.forEach((field) => {
            field.disabled = true;
        });
        submitButton.textContent = 'Uploading...';
        if (modalTextEl) {
            modalTextEl.textContent = message || 'Uploading document...';
        }
        if (modal) {
            modal.style.display = 'flex';
        }
        return;
    }

    documentUploadInProgress = false;
    const fields = form.querySelectorAll('input, textarea, button, select');
    fields.forEach((field) => {
        field.disabled = false;
    });
    submitButton.textContent = submitButton.dataset.defaultText;

    if (message) {
        if (modalTextEl) {
            modalTextEl.textContent = message;
        }
        documentUploadStatusTimer = setTimeout(() => {
            if (modal) {
                modal.style.display = 'none';
            }
        }, 900);
    } else {
        if (modal) {
            modal.style.display = 'none';
        }
    }
}

function showDocumentListLoading(message = 'Loading your documents...') {
    const container = document.getElementById('documentsContainer');
    if (!container) return;
    container.innerHTML = `
        <div class="documents-loading-state">
            <div class="documents-loading-dot"></div>
            <div>${escapeHtml(message)}</div>
        </div>
    `;
}

async function loadMyDocuments(showLoadingState = false, loadingMessage = 'Loading your documents...') {
    if (!authToken) return;

    if (showLoadingState) {
        showDocumentListLoading(loadingMessage);
    }

    try {
        const response = await fetch(`${API_BASE}/api/documents/my-documents`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok) {
            const documents = await response.json();
            displayDocuments(documents);
            updateDocumentsTabHealthUI(documents);
            updateDocumentTypeAvailability(documents);
        } else {
            const error = await response.json().catch(() => ({}));
            if (response.status === 401) {
                showMessage('Session expired. Please login again.', 'error');
                logout();
            } else {
                console.error('Failed to load documents:', error);
            }
        }
    } catch (error) {
        console.error('Load documents error:', error);
    }
}

function getDocumentValidationMeta(doc) {
    if (doc.is_valid === true) {
        return {
            statusLabel: 'Valid',
            statusStyle: 'background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.35);',
            cardStyle: 'border: 1px solid rgba(16, 185, 129, 0.35); background: rgba(16, 185, 129, 0.08);',
            indicatorIcon: '✓',
            indicatorColor: '#34d399',
            reason: '',
            reasonStyle: ''
        };
    }

    if (doc.is_valid === false) {
        return {
            statusLabel: 'Needs Review',
            statusStyle: 'background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.35);',
            cardStyle: 'border: 1px solid rgba(245, 158, 11, 0.35); background: rgba(245, 158, 11, 0.09);',
            indicatorIcon: '!',
            indicatorColor: '#f59e0b',
            reason: doc.validation_message || 'Validation failed. Please upload the correct document.',
            reasonStyle: 'color: #fcd34d; background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.35); border-radius: 0.6rem; padding: 0.55rem 0.65rem;'
        };
    }

    const isProcessing = doc.is_processed === false;
    return {
        statusLabel: isProcessing ? 'Processing' : 'Pending Validation',
        statusStyle: 'background: rgba(99, 102, 241, 0.15); color: #a5b4fc; border: 1px solid rgba(99, 102, 241, 0.35);',
        cardStyle: 'border: 1px solid rgba(99, 102, 241, 0.35); background: rgba(99, 102, 241, 0.08);',
        indicatorIcon: '•',
        indicatorColor: '#818cf8',
        reason: '',
        reasonStyle: ''
    };
}

function displayDocuments(documents) {
    const container = document.getElementById('documentsContainer');
    if (!container) return;

    const activeCatalog = ((documentTypeCatalog && documentTypeCatalog.length) ? documentTypeCatalog : FALLBACK_DOCUMENT_TYPES)
        .filter((row) => row && row.value && row.is_active !== false)
        .map((row, index) => ({
            value: String(row.value),
            label: String(row.label || row.value),
            sort_order: Number.isFinite(row.sort_order) ? row.sort_order : index,
            is_required: Boolean(row.is_required),
            journey_stage: Number.isFinite(row.journey_stage) ? row.journey_stage : null
        }))
        .sort((a, b) => {
            const stageA = Number.isFinite(a.journey_stage) ? a.journey_stage : 999;
            const stageB = Number.isFinite(b.journey_stage) ? b.journey_stage : 999;
            if (stageA !== stageB) return stageA - stageB;
            return a.sort_order - b.sort_order;
        });

    const catalogByType = {};
    activeCatalog.forEach((row) => {
        catalogByType[row.value] = row;
    });

    const stageSource = (journeyStageCatalog && journeyStageCatalog.length) ? journeyStageCatalog : FALLBACK_JOURNEY_STAGES;
    const stageLabelByNumber = {};
    stageSource.forEach((stage) => {
        const stageNo = Number(stage.stage);
        if (Number.isFinite(stageNo)) {
            stageLabelByNumber[stageNo] = stage.name || `Stage ${stageNo}`;
        }
    });

    const uploadedDocs = (Array.isArray(documents) ? documents : [])
        .filter((doc) => doc && doc.document_type)
        .slice()
        .sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime());
    const uploadedTypeSet = new Set(uploadedDocs.map((doc) => doc.document_type).filter(Boolean));

    const pendingCatalogTypes = activeCatalog.filter((row) => !uploadedTypeSet.has(row.value));

    const summaryLine = `
        <div style="margin-bottom: 0.9rem; color: var(--text-secondary); font-size: 0.86rem;">
            Showing all document types from your database catalog. Uploaded documents are listed first.
        </div>
    `;

    const renderMetaBadges = (docType) => {
        const meta = catalogByType[docType] || null;
        const isMandatory = meta ? meta.is_required : false;
        const stageNo = meta ? meta.journey_stage : null;
        const stageLabel = stageNo && stageLabelByNumber[stageNo] ? stageLabelByNumber[stageNo] : (stageNo ? `Stage ${stageNo}` : 'Unassigned');

        const requirementText = meta ? (isMandatory ? 'Mandatory' : 'Optional') : 'Not In Catalog';
        const requirementStyle = meta
            ? (isMandatory
                ? 'background: rgba(239, 68, 68, 0.14); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.35);'
                : 'background: rgba(59, 130, 246, 0.14); color: #93c5fd; border: 1px solid rgba(59, 130, 246, 0.35);')
            : 'background: rgba(148, 163, 184, 0.14); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.35);';

        return `
            <div style="margin-top: 0.5rem; display: flex; flex-wrap: wrap; gap: 0.45rem;">
                <span style="font-size: 0.75rem; font-weight: 700; border-radius: 999px; padding: 0.15rem 0.5rem; ${requirementStyle}">
                    ${escapeHtml(requirementText)}
                </span>
                <span style="font-size: 0.75rem; font-weight: 700; border-radius: 999px; padding: 0.15rem 0.5rem; background: rgba(99, 102, 241, 0.14); color: #a5b4fc; border: 1px solid rgba(99, 102, 241, 0.35);">
                    ${escapeHtml(stageNo ? `Stage ${stageNo}: ${stageLabel}` : stageLabel)}
                </span>
            </div>
        `;
    };

    let cardsHtml = '';

    uploadedDocs.forEach((doc) => {
        const fileSizeMB = ((doc.file_size || 0) / (1024 * 1024)).toFixed(2);
        const uploadDate = doc.created_at
            ? new Date(doc.created_at).toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric'
            })
            : 'Unknown date';
        const isEncrypted = doc.encrypted_file_key || !doc.file_url;
        const docTypeLabel = getDocumentTypeLabel(doc.document_type);
        const validationMeta = getDocumentValidationMeta(doc);

        cardsHtml += `
            <div data-document-id="${doc.id}" data-document-type="${escapeHtml(doc.document_type || '')}" style="${validationMeta.cardStyle} border-radius: 0.75rem; padding: 1rem; margin-bottom: 0.8rem;">
                <div style="display: flex; align-items: start; gap: 0.75rem;">
                    <div style="color: ${validationMeta.indicatorColor}; font-size: 1.25rem; font-weight: bold; flex-shrink: 0;">${validationMeta.indicatorIcon}</div>
                    <div style="flex: 1;">
                        <div style="font-weight: 650; margin-bottom: 0.25rem; color: var(--text-primary);">
                            ${escapeHtml(docTypeLabel)}
                        </div>
                        <div style="font-size: 0.875rem; color: var(--text-secondary);">
                            ${escapeHtml(doc.original_filename || 'Uploaded file')} • ${fileSizeMB} MB • ${uploadDate}
                            ${isEncrypted ? ' • <span style="color: #34d399;">🔒 Encrypted</span>' : ''}
                        </div>
                        ${renderMetaBadges(doc.document_type)}
                        <div style="margin-top: 0.5rem; display: flex; align-items: center; gap: 0.5rem;">
                            <span style="font-size: 0.8rem; color: var(--text-secondary);">Validation:</span>
                            <span style="font-size: 0.78rem; font-weight: 700; border-radius: 999px; padding: 0.15rem 0.5rem; ${validationMeta.statusStyle}">
                                ${validationMeta.statusLabel}
                            </span>
                        </div>
                        ${validationMeta.reason ? `
                            <div style="font-size: 0.85rem; margin-top: 0.55rem; ${validationMeta.reasonStyle}">
                                <strong>Reason:</strong> ${escapeHtml(validationMeta.reason)}
                            </div>
                        ` : ''}
                        ${doc.description ? `<div style="font-size: 0.875rem; color: var(--text-secondary); margin-top: 0.5rem; font-style: italic;">${escapeHtml(doc.description)}</div>` : ''}
                        <div style="display: flex; gap: 0.5rem; margin-top: 0.75rem;">
                            ${isEncrypted ? `
                                <button onclick="downloadEncryptedDocument(${doc.id})" class="btn btn-primary" style="font-size: 0.875rem; padding: 0.5rem 1rem;">Download</button>
                            ` : `
                                <a href="${doc.file_url}" target="_blank" class="btn btn-primary" style="font-size: 0.875rem; padding: 0.5rem 1rem; text-decoration: none; display: inline-block;">View</a>
                                <a href="${API_BASE}/api/documents/${doc.id}/download" class="btn" style="font-size: 0.875rem; padding: 0.5rem 1rem; background: var(--bg-color); border: 1px solid var(--border-color); text-decoration: none; display: inline-block;">Download</a>
                            `}
                            <button onclick="deleteDocument(${doc.id}, '${escapeHtml(doc.original_filename || 'document')}')" class="btn" style="font-size: 0.875rem; padding: 0.5rem 1rem; background: rgba(239, 68, 68, 0.14); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.35);">Delete</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    });

    pendingCatalogTypes.forEach((pendingType) => {
        const isMandatory = pendingType.is_required === true;
        const stageNo = pendingType.journey_stage;
        const stageLabel = stageNo && stageLabelByNumber[stageNo] ? stageLabelByNumber[stageNo] : (stageNo ? `Stage ${stageNo}` : 'Unassigned');
        const requirementStyle = isMandatory
            ? 'background: rgba(239, 68, 68, 0.14); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.35);'
            : 'background: rgba(59, 130, 246, 0.14); color: #93c5fd; border: 1px solid rgba(59, 130, 246, 0.35);';

        cardsHtml += `
            <div data-document-type="${escapeHtml(pendingType.value)}" style="border: 1px solid var(--border-color); border-radius: 0.75rem; padding: 0.95rem 1rem; margin-bottom: 0.75rem; background: var(--bg-secondary);">
                <div style="display: flex; align-items: center; gap: 0.75rem;">
                    <div style="color: #94a3b8; font-size: 1.15rem; font-weight: bold; flex-shrink: 0;">○</div>
                    <div style="flex: 1;">
                        <div style="font-weight: 600; color: var(--text-primary); margin-bottom: 0.25rem;">
                            ${escapeHtml(pendingType.label)}
                        </div>
                        <div style="font-size: 0.84rem; color: var(--text-secondary); display: inline-flex; align-items: center; gap: 0.35rem;">
                            <span style="display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #fbbf24;"></span>
                            Not uploaded yet
                        </div>
                        <div style="margin-top: 0.5rem; display: flex; flex-wrap: wrap; gap: 0.45rem;">
                            <span style="font-size: 0.75rem; font-weight: 700; border-radius: 999px; padding: 0.15rem 0.5rem; ${requirementStyle}">
                                ${isMandatory ? 'Mandatory' : 'Optional'}
                            </span>
                            <span style="font-size: 0.75rem; font-weight: 700; border-radius: 999px; padding: 0.15rem 0.5rem; background: rgba(99, 102, 241, 0.14); color: #a5b4fc; border: 1px solid rgba(99, 102, 241, 0.35);">
                                ${escapeHtml(stageNo ? `Stage ${stageNo}: ${stageLabel}` : stageLabel)}
                            </span>
                        </div>
                    </div>
                </div>
            </div>
        `;
    });

    if (!cardsHtml) {
        container.innerHTML = '<p style="color: var(--text-secondary); text-align: center; padding: 1rem;">No document types found in catalog.</p>';
        return;
    }

    container.innerHTML = `${summaryLine}${cardsHtml}`;
}

async function downloadEncryptedDocument(documentId) {
    if (!authToken) {
        showMessage('Please login to download documents', 'error');
        return;
    }
    
    const password = prompt('Enter your password to decrypt and download this document:');
    if (!password) {
        return; // User cancelled
    }
    
    try {
        showMessage('Decrypting document...', 'success');
        
        const formData = new FormData();
        formData.append('password', password);
        
        const response = await fetch(`${API_BASE}/api/documents/${documentId}/download`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`
            },
            body: formData
        });
        
        if (response.ok) {
            // Get the file blob
            const blob = await response.blob();
            
            // Get filename from response headers or use default
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename = 'document';
            if (contentDisposition) {
                const filenameMatch = contentDisposition.match(/filename="?(.+)"?/);
                if (filenameMatch) {
                    filename = filenameMatch[1];
                }
            }
            
            // Create download link
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            
            showMessage('Document decrypted and downloaded successfully!', 'success');
        } else {
            const error = await response.json().catch(() => ({}));
            let errorMessage = 'Failed to download document';
            if (error.detail) {
                errorMessage = error.detail;
            }
            showMessage(errorMessage, 'error');
        }
    } catch (error) {
        console.error('Download error:', error);
        showMessage('An error occurred while downloading the document. Please try again.', 'error');
    }
}

async function deleteDocument(documentId, filename) {
    if (!authToken) {
        showMessage('Please login to delete documents', 'error');
        return;
    }
    
    // Confirm deletion
    const confirmed = confirm(`Are you sure you want to delete "${filename}"?\n\nThis action cannot be undone. The file will be permanently deleted from R2 storage.`);
    if (!confirmed) {
        return; // User cancelled
    }
    
    try {
        showMessage('Deleting document...', 'success');
        
        const response = await fetch(`${API_BASE}/api/documents/${documentId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok || response.status === 204) {
            showMessage('Document deleted successfully', 'success');
            // Reload documents list
            await loadMyDocuments();
            
            // Refresh visa status after document deletion
            await saveVisaStatusToR2();
            await loadDashboardStats();
        } else {
            const error = await response.json().catch(() => ({}));
            if (response.status === 403) {
                showMessage('You do not have permission to delete this document', 'error');
            } else if (response.status === 404) {
                showMessage('Document not found', 'error');
                // Reload documents list anyway
                await loadMyDocuments();
            } else {
                showMessage(error.detail || 'Failed to delete document. Please try again.', 'error');
            }
        }
    } catch (error) {
        console.error('Delete error:', error);
        showMessage('Failed to delete document. Please try again.', 'error');
    }
}

// Rilono AI Chat Functions
function getMainChatContainers() {
    const containers = document.querySelectorAll('.rilono-ai-messages[data-main-chat="true"]');
    if (containers.length > 0) {
        return Array.from(containers);
    }
    const fallback = document.getElementById('rilonoAiChatMessages');
    return fallback ? [fallback] : [];
}

function getMainChatForms() {
    const forms = document.querySelectorAll('.rilono-ai-form[data-main-chat-form="true"]');
    if (forms.length > 0) {
        return Array.from(forms);
    }
    const fallback = document.getElementById('rilonoAiChatForm');
    return fallback ? [fallback] : [];
}

function getMainChatWelcomeMarkup() {
    return `
        <div class="rilono-ai-message assistant">
            <div class="message-avatar">🤖</div>
            <div class="message-bubble">
                <p>Hello! I can help with your visa docs, profile status, and next steps.</p>
            </div>
        </div>
    `;
}

function handleRilonoAiChatKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        const form = event.target.closest('form');
        if (form) {
            form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
        }
    }
}

function autoResizeRilonoAiInput(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
}

function sendQuickMessage(message, triggerElement = null) {
    let input = null;
    let form = null;

    if (triggerElement) {
        const chatWidget = triggerElement.closest('.rilono-ai-widget');
        if (chatWidget) {
            input = chatWidget.querySelector('.rilono-ai-input');
            form = chatWidget.querySelector('.rilono-ai-form');
        }
    }

    if (!input || !form) {
        const forms = getMainChatForms();
        if (forms.length > 0) {
            form = forms[0];
            input = form.querySelector('.rilono-ai-input');
        }
    }

    if (!input || !form) {
        return;
    }

    input.value = message;
    autoResizeRilonoAiInput(input);
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
}

function addMessageToRilonoAiChat(message, isUser = false) {
    const messagesContainers = getMainChatContainers();
    if (messagesContainers.length === 0) return;

    messagesContainers.forEach((messagesContainer) => {
        const messageDiv = document.createElement('div');
        messageDiv.className = `rilono-ai-message ${isUser ? 'user' : 'assistant'}`;

        if (isUser) {
            messageDiv.innerHTML = `
                <div class="message-avatar">${currentUser?.full_name?.charAt(0) || currentUser?.username?.charAt(0) || 'U'}</div>
                <div class="message-bubble">
                    <p>${escapeHtml(message)}</p>
                </div>
            `;
        } else {
            // Use markdown parser for AI responses
            messageDiv.innerHTML = `
                <div class="message-avatar">🤖</div>
                <div class="message-bubble">
                    <div class="ai-response-content">${markdownToHtml(message)}</div>
                </div>
            `;
        }

        messagesContainer.appendChild(messageDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    });
}

function showRilonoAiTypingIndicator() {
    const messagesContainers = getMainChatContainers();
    if (messagesContainers.length === 0) return;

    messagesContainers.forEach((messagesContainer) => {
        const existing = messagesContainer.querySelector('.rilono-ai-typing-indicator');
        if (existing) existing.remove();

        const typingDiv = document.createElement('div');
        typingDiv.className = 'rilono-ai-typing rilono-ai-typing-indicator';
        typingDiv.innerHTML = `
            <div class="message-avatar">🤖</div>
            <div class="typing-bubble">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        `;
        messagesContainer.appendChild(typingDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    });
}

function removeRilonoAiTypingIndicator() {
    document.querySelectorAll('.rilono-ai-typing-indicator').forEach((typingIndicator) => {
        typingIndicator.remove();
    });
}

// Store conversation history for Rilono AI
let rilonoAiConversationHistory = [];

async function handleRilonoAiChatSubmit(e) {
    e.preventDefault();
    const form = e.currentTarget;
    const input = form ? form.querySelector('.rilono-ai-input') : null;
    if (!input) return;
    const message = input.value.trim();
    
    if (!message) return;
    
    if (!authToken) {
        showMessage('Please login to chat with Rilono AI', 'error');
        return;
    }
    
    // Add user message to both chats
    addMessageToRilonoAiChat(message, true);
    addMessageToFloatingChat(message, true);
    
    // Add to shared conversation history
    rilonoAiConversationHistory.push({
        role: 'user',
        content: message
    });
    
    input.value = '';
    autoResizeRilonoAiInput(input);
    
    // Show typing indicator
    showRilonoAiTypingIndicator();
    
    try {
        // Call the AI chat API
        const response = await fetch(`${API_BASE}/api/ai-chat/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                message: message,
                conversation_history: rilonoAiConversationHistory.slice(-10)  // Last 10 messages for context
            })
        });
        
        removeRilonoAiTypingIndicator();
        
        if (response.ok) {
            const data = await response.json();
            const aiResponse = data.response;
            
            // Add AI response to shared conversation history
            rilonoAiConversationHistory.push({
                role: 'assistant',
                content: aiResponse
            });
            
            // Keep only last 20 messages in history
            if (rilonoAiConversationHistory.length > 20) {
                rilonoAiConversationHistory = rilonoAiConversationHistory.slice(-20);
            }
            
            // Add to both chats
            addMessageToRilonoAiChat(aiResponse, false);
            addMessageToFloatingChat(aiResponse, false);
            void loadSubscriptionStatus(true);
        } else {
            const errorData = await response.json();
            const errorMsg = errorData.detail || 'Failed to get response from Rilono AI';
            addMessageToRilonoAiChat(`Sorry, I encountered an error: ${errorMsg}. Please try again.`, false);
            if (response.status === 403) {
                void loadSubscriptionStatus(true);
            }
        }
    } catch (error) {
        removeRilonoAiTypingIndicator();
        console.error('Rilono AI chat error:', error);
        addMessageToRilonoAiChat('Sorry, I encountered an error. Please try again later.', false);
    }
}

function generateRilonoAiResponse(userMessage) {
    const message = userMessage.toLowerCase();
    
    if (message.includes('document') || message.includes('checklist') || message.includes('upload')) {
        return `Here are the key documents you need to upload for your US visa application:

📋 **Required Documents:**
• Passport (valid for at least 6 months)
• DS-160 Confirmation Page
• DS-160 Application
• US Visa Appointment Letter
• Visa Fee Receipt
• Photograph (2x2 Inches)
• Form I-20 (Signed)
• University Admission Letter
• Bank balance certificate
• Transcripts / mark sheets
• Degree certificates
• I-901 SEVIS fee payment confirmation

You can check your profile completion status in the Overview tab to see which documents you've already uploaded and which are still pending.`;
    } else if (message.includes('profile') || message.includes('status') || message.includes('complete')) {
        return `I can help you check your profile completion! Here's what you can do:

1. **Check Overview Tab**: Go to the Overview section to see your profile completion percentage and pending documents.

2. **Profile Information**: Make sure you've filled out:
   • Full Name
   • University
   • Phone Number
   • Profile Picture

3. **Documents**: Upload all required documents in the Documents tab.

Would you like me to help you with any specific document or profile field?`;
    } else if (message.includes('visa') || message.includes('application') || message.includes('process')) {
        return `I'm here to help with your visa application process! Here's a general overview:

🛂 **US Student Visa Process:**

1. **Get I-20**: Receive your I-20 form from your university
2. **Pay SEVIS Fee**: Pay the I-901 SEVIS fee and get confirmation
3. **Complete DS-160**: Fill out the DS-160 application form online
4. **Pay Visa Fee**: Pay the visa application fee
5. **Schedule Interview**: Book your visa appointment
6. **Prepare Documents**: Gather all required documents
7. **Attend Interview**: Go to your visa interview

For specific guidance on any step, feel free to ask! I can also help you track which documents you've uploaded and what's still pending.`;
    } else if (message.includes('help') || message.includes('assist')) {
        return `I'm Rilono AI, and I'm here to help you with:

✅ Document requirements and checklists
✅ Visa application guidance
✅ Profile completion tracking
✅ Answering questions about your uploaded documents
✅ General visa process information

You can ask me about:
• What documents you need
• Your profile completion status
• Visa application steps
• Document requirements
• Any other questions about your visa journey

What would you like to know?`;
    } else {
        return `I understand you're asking about "${userMessage}". 

I'm here to help with your visa documentation and application process. I can assist with:
• Document requirements and checklists
• Profile completion status
• Visa application guidance
• Questions about your uploaded documents

Could you be more specific about what you need help with? Or try one of the quick action buttons below!`;
    }
}

// Initialize Rilono AI Chat when tab is shown
function initializeRilonoAiChat() {
    const chatForms = getMainChatForms();
    chatForms.forEach((chatForm) => {
        // Remove existing listener to prevent duplicates
        chatForm.removeEventListener('submit', handleRilonoAiChatSubmit);
        chatForm.addEventListener('submit', handleRilonoAiChatSubmit);
    });
    // Sync messages from shared history
    syncMainChatFromHistory();
}

// Floating Chat Widget Functions
let floatingChatOpen = false;
// Note: floatingChatConversationHistory removed - using shared rilonoAiConversationHistory instead

function toggleFloatingChat() {
    const widget = document.getElementById('floatingAiChatWidget');
    const chatWindow = document.getElementById('floatingChatWindow');
    const chatToggle = document.getElementById('floatingChatToggle');
    const messagesContainer = document.getElementById('floatingChatMessages');
    
    // Toggle the state
    floatingChatOpen = !floatingChatOpen;
    
    // If closing, hide window and show toggle button
    if (!floatingChatOpen) {
        chatWindow.style.display = 'none';
        if (chatToggle) chatToggle.style.display = 'flex';
        return;
    }
    
    // Hide toggle button when chat is open
    if (chatToggle) chatToggle.style.display = 'none';
    
    if (!currentUser) {
        // Show login prompt
        document.getElementById('floatingChatLoginPrompt').style.display = 'flex';
        document.getElementById('floatingChatInputContainer').style.display = 'none';
        messagesContainer.innerHTML = '';
        chatWindow.style.display = 'flex';
        return;
    }
    
    if (floatingChatOpen) {
        chatWindow.style.display = 'flex';
        document.getElementById('floatingChatLoginPrompt').style.display = 'none';
        document.getElementById('floatingChatInputContainer').style.display = 'block';
        messagesContainer.style.display = 'flex';
        
        // Sync conversation from shared history
        syncFloatingChatFromHistory();
        
        // Ensure proper layout and scrolling
        setTimeout(() => {
            const messagesContainer = document.getElementById('floatingChatMessages');
            if (messagesContainer) {
                messagesContainer.style.display = 'flex';
                // Force a reflow to ensure scrolling works
                messagesContainer.offsetHeight;
                scrollFloatingChatToBottom();
            }
            document.getElementById('floatingChatInput')?.focus();
        }, 150);
    } else {
        chatWindow.style.display = 'none';
    }
}

// Sync floating chat UI from shared conversation history
function syncFloatingChatFromHistory() {
    const messagesContainer = document.getElementById('floatingChatMessages');
    if (!messagesContainer) return;
    
    // Clear existing messages
    messagesContainer.innerHTML = '';
    
    // Show welcome message if no conversation history
    if (rilonoAiConversationHistory.length === 0) {
        const welcomeDiv = document.createElement('div');
        welcomeDiv.className = 'chat-welcome-message';
        welcomeDiv.innerHTML = `
            <div class="chat-avatar">🤖</div>
            <div class="welcome-bubble">
                <p><strong>Hello! I'm Rilono AI</strong></p>
                <p>I'm here to help you with your F1 student visa process and documentation. How can I assist you today?</p>
            </div>
        `;
        messagesContainer.appendChild(welcomeDiv);
    } else {
        // Rebuild messages from shared history
        for (const msg of rilonoAiConversationHistory) {
            addMessageToFloatingChat(msg.content, msg.role === 'user');
        }
    }
    
    scrollFloatingChatToBottom();
}

// Sync main Rilono AI chat UI from shared conversation history
function syncMainChatFromHistory() {
    const messagesContainers = getMainChatContainers();
    if (messagesContainers.length === 0) return;

    messagesContainers.forEach((messagesContainer) => {
        messagesContainer.innerHTML = '';
    });

    if (rilonoAiConversationHistory.length === 0) {
        messagesContainers.forEach((messagesContainer) => {
            messagesContainer.innerHTML = getMainChatWelcomeMarkup();
        });
        return;
    }

    // Rebuild messages from shared history in all main chat panels
    for (const msg of rilonoAiConversationHistory) {
        addMessageToRilonoAiChat(msg.content, msg.role === 'user');
    }
}

function handleFloatingChatKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        document.getElementById('floatingChatForm').dispatchEvent(new Event('submit'));
    }
}

function autoResizeFloatingChatInput(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
}

function scrollFloatingChatToBottom() {
    const messagesContainer = document.getElementById('floatingChatMessages');
    if (!messagesContainer) return;
    
    // Force immediate scroll first
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    
    // Then smooth scroll with requestAnimationFrame for better performance
    requestAnimationFrame(() => {
        messagesContainer.scrollTo({
            top: messagesContainer.scrollHeight,
            behavior: 'smooth'
        });
    });
}

function addMessageToFloatingChat(message, isUser = false) {
    const messagesContainer = document.getElementById('floatingChatMessages');
    if (!messagesContainer) return;  // Guard: container might not exist
    
    // Remove welcome message if it exists (only when adding first user message)
    if (isUser) {
        const welcomeMsg = messagesContainer.querySelector('.chat-welcome-message');
        if (welcomeMsg) {
            welcomeMsg.remove();
        }
    }
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message ${isUser ? 'user' : 'assistant'}`;
    
    if (!isUser) {
        const avatar = document.createElement('div');
        avatar.className = 'chat-avatar';
        avatar.textContent = '🤖';
        messageDiv.appendChild(avatar);
    }
    
    const bubble = document.createElement('div');
    bubble.className = 'chat-message-bubble';
    
    if (isUser) {
        // User messages: plain text
        bubble.textContent = message;
    } else {
        // AI responses: parse markdown
        bubble.innerHTML = markdownToHtml(message);
    }
    messageDiv.appendChild(bubble);
    
    if (isUser) {
        const avatar = document.createElement('div');
        avatar.className = 'chat-avatar';
        avatar.textContent = currentUser?.full_name?.charAt(0).toUpperCase() || currentUser?.username?.charAt(0).toUpperCase() || 'U';
        messageDiv.appendChild(avatar);
    }
    
    messagesContainer.appendChild(messageDiv);
    // Scroll to bottom with smooth behavior after DOM update
    scrollFloatingChatToBottom();
}

function showFloatingChatTyping() {
    const typingIndicator = document.getElementById('floatingChatTyping');
    typingIndicator.style.display = 'block';
    // Scroll to bottom to show typing indicator
    scrollFloatingChatToBottom();
}

function removeFloatingChatTyping() {
    const typingIndicator = document.getElementById('floatingChatTyping');
    typingIndicator.style.display = 'none';
}

async function handleFloatingChatSubmit(e) {
    e.preventDefault();
    const input = document.getElementById('floatingChatInput');
    const message = input.value.trim();
    
    if (!message) return;
    
    if (!authToken) {
        showMessage('Please login to chat with Rilono AI', 'error');
        toggleFloatingChat();
        return;
    }
    
    // Add user message to both chats
    addMessageToFloatingChat(message, true);
    addMessageToRilonoAiChat(message, true);
    
    // Add to shared conversation history
    rilonoAiConversationHistory.push({
        role: 'user',
        content: message
    });
    
    input.value = '';
    autoResizeFloatingChatInput(input);
    
    // Show typing indicator
    showFloatingChatTyping();
    
    try {
        // Call the AI chat API
        const response = await fetch(`${API_BASE}/api/ai-chat/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                message: message,
                conversation_history: rilonoAiConversationHistory.slice(-10)
            })
        });
        
        removeFloatingChatTyping();
        
        if (response.ok) {
            const data = await response.json();
            const aiResponse = data.response;
            
            // Add AI response to shared conversation history
            rilonoAiConversationHistory.push({
                role: 'assistant',
                content: aiResponse
            });
            
            // Keep only last 20 messages in history
            if (rilonoAiConversationHistory.length > 20) {
                rilonoAiConversationHistory = rilonoAiConversationHistory.slice(-20);
            }
            
            // Add to both chats
            addMessageToFloatingChat(aiResponse, false);
            addMessageToRilonoAiChat(aiResponse, false);
            void loadSubscriptionStatus(true);
        } else {
            const errorData = await response.json();
            const errorMsg = errorData.detail || 'Failed to get response from Rilono AI';
            addMessageToFloatingChat(`Sorry, I encountered an error: ${errorMsg}. Please try again.`, false);
            if (response.status === 403) {
                void loadSubscriptionStatus(true);
            }
        }
    } catch (error) {
        removeFloatingChatTyping();
        console.error('Floating chat error:', error);
        addMessageToFloatingChat('Sorry, I encountered an error. Please try again later.', false);
    }
}

function updateFloatingChatVisibility() {
    const widget = document.getElementById('floatingAiChatWidget');
    const messagesContainer = document.getElementById('floatingChatMessages');
    if (currentUser) {
        widget.style.display = 'block';
        document.getElementById('floatingChatLoginPrompt').style.display = 'none';
        document.getElementById('floatingChatInputContainer').style.display = 'block';
        if (messagesContainer) {
            messagesContainer.style.display = 'flex';
        }
    } else {
        widget.style.display = 'block'; // Still show widget but with login prompt
        if (floatingChatOpen) {
            document.getElementById('floatingChatLoginPrompt').style.display = 'flex';
            document.getElementById('floatingChatInputContainer').style.display = 'none';
            if (messagesContainer) {
                messagesContainer.style.display = 'none';
            }
        }
    }
}

function handleGalleryKeyPress(e) {
    const modal = document.getElementById('imageGalleryModal');
    if (modal.style.display === 'none') return;
    
    switch(e.key) {
        case 'ArrowLeft':
            e.preventDefault();
            navigateGallery(-1);
            break;
        case 'ArrowRight':
            e.preventDefault();
            navigateGallery(1);
            break;
        case 'Escape':
            e.preventDefault();
            closeImageGallery();
            break;
    }
}
