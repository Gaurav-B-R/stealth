const API_BASE = '';
const COOKIE_AUTH_SENTINEL = '__cookie_session__';
let currentUser = null;
let authToken = null;
let currentSubscription = null;
let turnstileSiteKey = null;
let turnstileWidgetIds = {
    login: null,
    register: null,
    forgotPassword: null,
    resetPassword: null
};
let newsRequestInFlight = false;
let visaInterviewRequestInFlight = false;
let visaInterviewFiltersInitialized = false;
let documentUploadInProgress = false;
let documentUploadStatusTimer = null;
let documentUploadScanStartedAt = 0;
let proUpgradeInFlight = false;
let checkoutLaunchResolver = null;
let currentVisaSubTab = 'prep';
let documentTypeDropdownController = null;
const PRO_UPGRADE_ENABLED = true;
const PUBLIC_APP_ORIGIN = 'https://rilono.com';
const RILONO_AI_PUBLIC_ERROR_MESSAGE = 'Sorry, I encountered an issue while responding. Please try again in a little while. This issue has been raised for review.';
const LEGAL_LAST_UPDATED = {
    about: 'February 12, 2026',
    privacy: 'July 25, 2026',
    terms: 'July 30, 2026',
    refund: 'July 30, 2026',
    delivery: 'July 10, 2026',
    dpa: 'July 25, 2026'
};
const COOKIE_CONSENT_STORAGE_KEY = 'rilono_cookie_preferences_v1';
const COOKIE_CONSENT_VERSION = 1;
const COOKIE_CONSENT_DEFAULTS = Object.freeze({
    necessary: true,
    analytics: true
});
const COOKIE_CONSENT_GTAG_DENIED = Object.freeze({
    analytics_storage: 'denied',
    ad_storage: 'denied',
    ad_user_data: 'denied',
    ad_personalization: 'denied'
});
const COOKIE_CONSENT_GTAG_GRANTED = Object.freeze({
    analytics_storage: 'granted',
    ad_storage: 'denied',
    ad_user_data: 'denied',
    ad_personalization: 'denied'
});
const cookieConsentState = {
    gaScriptLoaded: false,
    gaScriptLoadPromise: null,
    preferences: null
};

// Notification System
const NOTIFICATION_STORAGE_PREFIX = 'notifications_user_';
// Old builds stored every account's notifications under one shared browser key.
// Never read that unscoped data: on a shared browser it can belong to another user.
const LEGACY_NOTIFICATION_STORAGE_KEY = 'notifications';
let notifications = [];
let notificationDropdownOpen = false;
let messageHideTimer = null;
let expandedChatWidgetId = null;
let floatingChatExpanded = false;
let mobileNavOpen = false;
let expandedChatOriginalParent = null;
let expandedChatPlaceholder = null;
let runtimeSubscriptionNotifyState = null;
let subscriptionNotifyStateUserId = null;
const MOBILE_NAV_BREAKPOINT = 900;
const RILONO_REEL_SCENE_DURATION_MS = 5200;
const RILONO_REEL_PROGRESS_INTERVAL_MS = 90;
const RILONO_REEL_PREFERS_REDUCED_MOTION = window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
let rilonoReelTimer = null;
let rilonoReelProgressTimer = null;
let rilonoReelCurrentScene = 0;
let rilonoReelSceneStartedAt = 0;
let rilonoReelPausedElapsed = 0;
let rilonoReelIsPlaying = false;
let rilonoReelUserPaused = false;
let rilonoReelInitialized = false;
const DOCUMENT_UPLOAD_ENCRYPTING_MS = 1200;
const DOCUMENT_UPLOAD_UPLOADING_MS = 700;
const DOCUMENT_UPLOAD_MIN_SCAN_MS = 8000;
const ADMIN_USERS_PAGE_SIZE = 20;
const ADMIN_USERS_DEFAULT_FILTERS = Object.freeze({
    search: '',
    status: 'all',
    role: 'all'
});

const adminUsersState = {
    loading: false,
    page: 1,
    pageSize: ADMIN_USERS_PAGE_SIZE,
    total: 0,
    search: ADMIN_USERS_DEFAULT_FILTERS.search,
    status: ADMIN_USERS_DEFAULT_FILTERS.status,
    role: ADMIN_USERS_DEFAULT_FILTERS.role,
    rows: []
};

function normalizeCookieConsentPreferences(raw) {
    return {
        necessary: true,
        analytics: Boolean(raw && raw.analytics === true)
    };
}

function readCookieConsentPreferences() {
    try {
        const raw = localStorage.getItem(COOKIE_CONSENT_STORAGE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object') return null;
        if (Number(parsed.version) !== COOKIE_CONSENT_VERSION) return null;
        return normalizeCookieConsentPreferences(parsed);
    } catch (error) {
        console.warn('Cookie preferences unavailable:', error);
        return null;
    }
}

function persistCookieConsentPreferences(preferences) {
    const normalized = normalizeCookieConsentPreferences(preferences);
    try {
        localStorage.setItem(COOKIE_CONSENT_STORAGE_KEY, JSON.stringify({
            version: COOKIE_CONSENT_VERSION,
            necessary: true,
            analytics: normalized.analytics,
            updated_at: new Date().toISOString()
        }));
    } catch (error) {
        console.warn('Failed to save cookie preferences:', error);
    }
    cookieConsentState.preferences = normalized;
    return normalized;
}

function ensureGtagStub() {
    window.dataLayer = window.dataLayer || [];
    if (typeof window.gtag !== 'function') {
        window.gtag = function gtag() {
            window.dataLayer.push(arguments);
        };
    }
}

function getAnalyticsMeasurementId() {
    const fromWindow = String(window.RILONO_ANALYTICS_ID || '').trim();
    return fromWindow || 'G-85F78RGWJQ';
}

function ensureGoogleAnalyticsScriptLoaded() {
    if (cookieConsentState.gaScriptLoaded) {
        return Promise.resolve();
    }
    if (cookieConsentState.gaScriptLoadPromise) {
        return cookieConsentState.gaScriptLoadPromise;
    }

    const markLoaded = () => {
        cookieConsentState.gaScriptLoaded = true;
    };
    const measurementId = getAnalyticsMeasurementId();
    if (!measurementId) {
        return Promise.resolve();
    }

    const existingScript = document.querySelector('script[data-rilono-ga="true"]');
    if (existingScript) {
        if (existingScript.getAttribute('data-loaded') === 'true') {
            markLoaded();
            return Promise.resolve();
        }
        cookieConsentState.gaScriptLoadPromise = new Promise((resolve) => {
            let done = false;
            const finish = () => {
                if (done) return;
                done = true;
                existingScript.setAttribute('data-loaded', 'true');
                markLoaded();
                resolve();
            };
            existingScript.addEventListener('load', finish, { once: true });
            existingScript.addEventListener('error', finish, { once: true });
            window.setTimeout(finish, 800);
        }).finally(() => {
            cookieConsentState.gaScriptLoadPromise = null;
        });
        return cookieConsentState.gaScriptLoadPromise;
    }

    cookieConsentState.gaScriptLoadPromise = new Promise((resolve) => {
        const script = document.createElement('script');
        script.async = true;
        script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(measurementId)}`;
        script.setAttribute('data-rilono-ga', 'true');
        const finish = () => {
            script.setAttribute('data-loaded', 'true');
            markLoaded();
            resolve();
        };
        script.addEventListener('load', finish, { once: true });
        script.addEventListener('error', finish, { once: true });
        document.head.appendChild(script);
    }).finally(() => {
        cookieConsentState.gaScriptLoadPromise = null;
    });

    return cookieConsentState.gaScriptLoadPromise;
}

async function applyCookieConsentPreferences(preferences) {
    const normalized = normalizeCookieConsentPreferences(preferences);
    cookieConsentState.preferences = normalized;
    ensureGtagStub();

    if (normalized.analytics) {
        await ensureGoogleAnalyticsScriptLoaded();
    }

    if (typeof window.gtag !== 'function') return;

    window.gtag('consent', 'update', normalized.analytics ? COOKIE_CONSENT_GTAG_GRANTED : COOKIE_CONSENT_GTAG_DENIED);

    if (normalized.analytics) {
        const measurementId = getAnalyticsMeasurementId();
        window.gtag('js', new Date());
        window.gtag('config', measurementId, {
            anonymize_ip: true,
            allow_google_signals: false,
            allow_ad_personalization_signals: false
        });
    }
}

function showCookieConsentBanner() {
    const banner = document.getElementById('cookieConsentBanner');
    if (!banner) return;
    banner.hidden = false;
}

function hideCookieConsentBanner() {
    const banner = document.getElementById('cookieConsentBanner');
    if (!banner) return;
    banner.hidden = true;
}

function openCookieSettingsModal() {
    const modal = document.getElementById('cookieSettingsModal');
    if (!modal) return;
    const analyticsToggle = document.getElementById('cookieAnalyticsToggle');
    if (analyticsToggle) {
        const currentPreferences = cookieConsentState.preferences || readCookieConsentPreferences() || COOKIE_CONSENT_DEFAULTS;
        analyticsToggle.checked = Boolean(currentPreferences.analytics);
    }
    modal.style.display = 'flex';
}

function closeCookieSettingsModal() {
    const modal = document.getElementById('cookieSettingsModal');
    if (!modal) return;
    modal.style.display = 'none';
}

async function acceptAllCookieConsent() {
    const preferences = persistCookieConsentPreferences({ ...COOKIE_CONSENT_DEFAULTS, analytics: true });
    await applyCookieConsentPreferences(preferences);
    hideCookieConsentBanner();
    closeCookieSettingsModal();
}

async function rejectNonEssentialCookieConsent() {
    const preferences = persistCookieConsentPreferences({ ...COOKIE_CONSENT_DEFAULTS, analytics: false });
    await applyCookieConsentPreferences(preferences);
    hideCookieConsentBanner();
    closeCookieSettingsModal();
}

async function saveCookieSettingsFromModal() {
    const analyticsToggle = document.getElementById('cookieAnalyticsToggle');
    const analyticsEnabled = Boolean(analyticsToggle && analyticsToggle.checked);
    const preferences = persistCookieConsentPreferences({ ...COOKIE_CONSENT_DEFAULTS, analytics: analyticsEnabled });
    await applyCookieConsentPreferences(preferences);
    hideCookieConsentBanner();
    closeCookieSettingsModal();
}

function initializeCookieConsentManager() {
    const footerLink = document.getElementById('cookieSettingsFooterLink');
    const acceptBtn = document.getElementById('cookieAcceptAllBtn');
    const rejectBtn = document.getElementById('cookieRejectAllBtn');
    const manageBtn = document.getElementById('cookieManageBtn');
    const saveBtn = document.getElementById('cookieSavePreferencesBtn');
    const rejectModalBtn = document.getElementById('cookieRejectAllModalBtn');
    const closeModalBtn = document.getElementById('cookieSettingsCloseBtn');
    const modal = document.getElementById('cookieSettingsModal');

    if (footerLink) {
        footerLink.addEventListener('click', (event) => {
            event.preventDefault();
            openCookieSettingsModal();
        });
    }
    if (acceptBtn) {
        acceptBtn.addEventListener('click', () => { void acceptAllCookieConsent(); });
    }
    if (rejectBtn) {
        rejectBtn.addEventListener('click', () => { void rejectNonEssentialCookieConsent(); });
    }
    if (manageBtn) {
        manageBtn.addEventListener('click', () => {
            openCookieSettingsModal();
        });
    }
    if (saveBtn) {
        saveBtn.addEventListener('click', () => { void saveCookieSettingsFromModal(); });
    }
    if (rejectModalBtn) {
        rejectModalBtn.addEventListener('click', () => { void rejectNonEssentialCookieConsent(); });
    }
    if (closeModalBtn) {
        closeModalBtn.addEventListener('click', () => {
            closeCookieSettingsModal();
        });
    }
    if (modal) {
        modal.addEventListener('click', (event) => {
            if (event.target === modal) {
                closeCookieSettingsModal();
            }
        });
    }
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeCookieSettingsModal();
        }
    });

    const existingPreferences = readCookieConsentPreferences();
    const activePreferences = existingPreferences || COOKIE_CONSENT_DEFAULTS;
    void applyCookieConsentPreferences(activePreferences);

    if (existingPreferences) {
        hideCookieConsentBanner();
    } else {
        showCookieConsentBanner();
    }
}

window.openCookieSettings = openCookieSettingsModal;

// The Visa Success Pass price ladder — one owner-chosen price per currency, mirroring
// app/money.py PRICE_BOOK["visa_pass"]. These are NOT conversions of ₹999: a live rate
// quotes a different number every hour and lands on amounts nobody actually charges
// ("≈ $12.01"), which is why the old FX estimate is gone.
//
// This copy exists only so the PUBLIC pricing page — no session, so no /api/pass/status —
// can show a real price. It is display-only: the server's own ladder replaces it as soon
// as entitlements load, and the amount charged is resolved server-side by
// /api/pass/checkout. Drift here shows a stale price; it cannot mis-charge anyone.
const PASS_PRICE_LADDER_FALLBACK = Object.freeze([
    { currency: 'INR', amount_minor: 99900 },
    { currency: 'USD', amount_minor: 1299 },
    { currency: 'GBP', amount_minor: 999 },
    { currency: 'EUR', amount_minor: 1199 },
    { currency: 'CAD', amount_minor: 1799 },
    { currency: 'AUD', amount_minor: 1999 },
    { currency: 'AED', amount_minor: 4900 },
    { currency: 'SGD', amount_minor: 1699 }
]);
// The Enterprise plan ladders — one owner-chosen price per currency per plan, mirroring
// app/money.py PRICE_BOOK["plan_starter"/"plan_growth"/"plan_scale"]; the two must be
// updated together. Same deal as PASS_PRICE_LADDER_FALLBACK above: this copy exists only
// so the PUBLIC pricing page can show real prices, it is display-only, and the amount
// charged is always resolved server-side. Amounts are ex-tax minor units; GST (+18%)
// applies ONLY to INR — every other currency is a zero-rated export, so the listed price
// IS the charged price and "+ GST" must never be shown next to a non-INR amount.
const ENTERPRISE_PLAN_LADDER_FALLBACK = Object.freeze({
    INR: { plan_starter: 299900, plan_growth: 699900, plan_scale: 1499900 },
    USD: { plan_starter: 3900, plan_growth: 8900, plan_scale: 19500 },
    GBP: { plan_starter: 2900, plan_growth: 6900, plan_scale: 14500 },
    EUR: { plan_starter: 3500, plan_growth: 7900, plan_scale: 17500 },
    CAD: { plan_starter: 5200, plan_growth: 11900, plan_scale: 25900 },
    AUD: { plan_starter: 5900, plan_growth: 13900, plan_scale: 29500 },
    AED: { plan_starter: 14500, plan_growth: 33900, plan_scale: 72500 },
    SGD: { plan_starter: 4900, plan_growth: 11500, plan_scale: 24500 }
});
// The currency the buyer is being quoted, shared by the pricing page and the paywall so
// the two can never show different prices for the same product.
const PASS_CURRENCY_STORAGE_KEY = 'rilono_pass_currency';
// Region we do not price (or cannot detect): quote USD. Both USD and INR are chargeable,
// but USD is the one an unknown visitor is most likely to recognise.
const PASS_CURRENCY_FALLBACK = 'USD';
let passPriceOptions = PASS_PRICE_LADDER_FALLBACK.map((option) => ({ ...option }));
let passPriceOptionsPromise = null;
let selectedPassCurrency = null;

const PRICING_MODEL_MONTHLY = 'pro_monthly';
const PRICING_MODEL_SIX_MONTH = 'pro_six_month';
const PRO_PRICING_MODELS = {
    [PRICING_MODEL_MONTHLY]: {
        id: PRICING_MODEL_MONTHLY,
        label: 'Visa Success Pass',
        amountInr: 699,
        cycleLabel: '/month',
        checkoutMode: 'subscription',
        autoRenewText: 'Auto-renew enabled. Cancel anytime from Profile > Subscription.'
    },
    [PRICING_MODEL_SIX_MONTH]: {
        id: PRICING_MODEL_SIX_MONTH,
        label: 'Visa Success Pass',
        amountInr: 2499,
        cycleLabel: '/6 months',
        checkoutMode: 'order',
        autoRenewText: 'One-time payment. Access remains active for 6 months from activation.'
    }
};

function normalizePricingModel(rawModel) {
    const value = String(rawModel || '').trim().toLowerCase();
    if (
        value === PRICING_MODEL_SIX_MONTH
        || value === 'pro_6_month'
        || value === 'pro_6month'
        || value === '6_month'
        || value === '6month'
        || value === 'one_time_6_month'
        || value === 'six_month'
    ) {
        return PRICING_MODEL_SIX_MONTH;
    }
    return PRICING_MODEL_MONTHLY;
}

function getPricingModelConfig(rawModel) {
    const model = normalizePricingModel(rawModel);
    return PRO_PRICING_MODELS[model] || PRO_PRICING_MODELS[PRICING_MODEL_MONTHLY];
}

const nativeFetch = window.fetch.bind(window);
window.fetch = async function secureFetch(input, init = {}) {
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
    const response = await nativeFetch(input, nextInit);
    const refreshedAccessToken = response.headers.get('X-Access-Token');
    if (refreshedAccessToken) {
        persistAuthToken(refreshedAccessToken);
    }
    return response;
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

// Geo → currency helpers: auto-pick the visitor's currency on first visit. This only
// chooses which price to show first — a currency we do not price falls back to the ladder
// default, and the charge is priced server-side from the currency the buyer confirms.
const PRICING_COUNTRY_TO_CURRENCY = {
    IN: 'INR', GB: 'GBP', CA: 'CAD', AU: 'AUD', AE: 'AED', SG: 'SGD', JP: 'JPY', US: 'USD',
    DE: 'EUR', FR: 'EUR', IT: 'EUR', ES: 'EUR', NL: 'EUR', IE: 'EUR', AT: 'EUR', BE: 'EUR',
    PT: 'EUR', GR: 'EUR', FI: 'EUR', LU: 'EUR', SK: 'EUR', SI: 'EUR', EE: 'EUR', LV: 'EUR',
    LT: 'EUR', CY: 'EUR', MT: 'EUR', HR: 'EUR'
};
const PRICING_TZ_COUNTRY = {
    'Asia/Kolkata': 'IN', 'Asia/Calcutta': 'IN', 'Europe/London': 'GB',
    'America/Toronto': 'CA', 'America/Vancouver': 'CA', 'America/Edmonton': 'CA', 'America/Winnipeg': 'CA', 'America/Halifax': 'CA', 'America/St_Johns': 'CA',
    'Australia/Sydney': 'AU', 'Australia/Melbourne': 'AU', 'Australia/Brisbane': 'AU', 'Australia/Perth': 'AU', 'Australia/Adelaide': 'AU', 'Australia/Hobart': 'AU',
    'Asia/Dubai': 'AE', 'Asia/Singapore': 'SG', 'Asia/Tokyo': 'JP',
    'Europe/Berlin': 'DE', 'Europe/Paris': 'FR', 'Europe/Madrid': 'ES', 'Europe/Rome': 'IT', 'Europe/Amsterdam': 'NL', 'Europe/Dublin': 'IE', 'Europe/Vienna': 'AT', 'Europe/Brussels': 'BE', 'Europe/Lisbon': 'PT', 'Europe/Athens': 'GR', 'Europe/Helsinki': 'FI'
};

// Resolve any country code to one of the supported pricing-config keys (matched by currency,
// so e.g. any Eurozone country maps to the EUR entry).
function pricingConfigCodeForCountry(cc) {
    if (!cc) return null;
    cc = String(cc).toUpperCase();
    if (PRICING_COUNTRY_CONFIG[cc]) return cc;
    const currency = PRICING_COUNTRY_TO_CURRENCY[cc];
    if (!currency) return null;
    return Object.keys(PRICING_COUNTRY_CONFIG).find((k) => PRICING_COUNTRY_CONFIG[k].currency === currency) || null;
}

// Best-effort visitor country: CDN geo header → browser locale region → timezone → US.
async function detectPricingCountry() {
    try {
        const r = await fetch(`${API_BASE}/api/pricing/geo`, { credentials: 'same-origin' });
        if (r.ok) {
            const d = await r.json().catch(() => ({}));
            const code = pricingConfigCodeForCountry(d && d.country_code);
            if (code) return code;
        }
    } catch (e) { /* fall through to client-side signals */ }
    try {
        const langs = (navigator.languages && navigator.languages.length) ? navigator.languages : [navigator.language];
        for (const l of langs) {
            const m = String(l || '').match(/[-_]([A-Za-z]{2})\b/);
            const code = m && pricingConfigCodeForCountry(m[1]);
            if (code) return code;
        }
    } catch (e) { /* no locale region */ }
    try {
        const tz = (Intl.DateTimeFormat().resolvedOptions().timeZone) || '';
        const code = pricingConfigCodeForCountry(PRICING_TZ_COUNTRY[tz]);
        if (code) return code;
    } catch (e) { /* no timezone */ }
    return 'US';
}

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
        name: 'Visa',
        emoji: '🛂',
        description: 'Prepare your visa interview packet and supporting documents.',
        next_step: 'Review final interview checklist and confidence prep',
        required_docs: ['us-visa-appointment-letter', 'stamped-f1-visa']
    },
    {
        stage: 7,
        name: 'Ready to Fly!',
        emoji: '✈️',
        description: 'Visa approved. Complete final pre-departure documents and travel readiness.',
        next_step: 'Upload remaining arrival documents (for example vaccination records) and finalize travel plans.',
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
// Which (country|visa) scope the catalog above was loaded for — lets checkAuth() detect
// a stale anonymous/US catalog after login and re-personalize BEFORE the journey renders.
let loadedCatalogScopeKey = null;
let documentTypeLabelByValue = {};
let journeyStageSelectionByWidget = {};

// Per-destination interview framing so the AI coach/officer matches the student's
// actual visa (US keeps the F-1 wording; other destinations get their own authority + focus).
const VISA_INTERVIEW_CONTEXT = {
    US: {
        coach: 'an F-1 visa interview coach',
        officer: 'a U.S. Visa Officer conducting a realistic F-1 interview simulation',
        report: 'F-1 visa',
        focus: 'university/program fit, finances, ties to home country, and post-study intent',
    },
    UK: {
        coach: 'a UK Student visa credibility-interview coach',
        officer: 'a UK visa caseworker conducting a realistic UK Student visa credibility interview simulation',
        report: 'UK Student visa',
        focus: 'course and university choice, finances and maintenance funds, English ability, and genuine-student intentions',
    },
    CA: {
        coach: 'a Canada study permit interview coach',
        officer: 'a Canadian visa officer conducting a realistic study permit interview simulation',
        report: 'Canada study permit',
        focus: 'study plan and program fit, proof of funds, ties to home country, and intent to leave after studies',
    },
    AU: {
        coach: 'an Australian Student visa (subclass 500) interview coach',
        officer: 'an Australian Department of Home Affairs officer conducting a realistic subclass 500 Genuine Student interview simulation',
        report: 'Australian Student visa (subclass 500)',
        focus: 'course and provider choice, Genuine Student (GS) intentions, finances and OSHC, and ties to home country',
    },
    DE: {
        coach: 'a German student visa interview coach',
        officer: 'a German embassy or consulate visa officer conducting a realistic National Visa (Type D) study interview simulation',
        report: 'German student visa / National Visa (Type D)',
        focus: 'course and university fit, admission status, proof of financing such as blocked account or scholarship, health insurance, and credible study intent',
    },
};

function currentInterviewContext() {
    const code = (currentUser && currentUser.destination_country_code) || 'US';
    return VISA_INTERVIEW_CONTEXT[code] || VISA_INTERVIEW_CONTEXT.US;
}

function visaPrepInterviewInstruction() {
    const ctx = currentInterviewContext();
    return `You are ${ctx.coach} for a student. Be supportive but rigorous — prepare them for a tough real interview.
Rules:
- Ask challenging, realistic visa-officer-style questions one at a time, grounded in the student's attached profile and uploaded documents.
- After every student answer, provide short coaching with this exact structure:
  1) Feedback: what was strong/weak (be honest and direct)
  2) Improve: a stronger sample answer (2-4 lines), specific to their real documents and situation
  3) Next Question: ask the next, harder visa-officer-style question
- Focus on clarity, confidence, ${ctx.focus}.
- Push the student out of rehearsed, generic answers; demand specificity backed by their real documents.
- Keep each turn concise and practical.
- If asked about your AI model/provider/training, do not mention Gemini, Google, or internal model names.
- In those cases, say you are Rilono AI and continue the prep flow.`;
}

function visaMockInterviewInstruction() {
    const ctx = currentInterviewContext();
    // Consulate Window (US voice mock): per-session temperament + grounded stage cues so
    // no two sessions feel identical and the booth feels physical, not chat-like.
    const consulateExtras = visaMockInterviewState.consulate ? `
- Officer temperament this session: ${visaMockInterviewState.strictness || 'brisk and procedural'}. Officers are efficient, not warm — keep every reply to 1-3 clipped sentences.
- Occasionally (at most once every third turn) you may open with one short bracketed stage cue grounded in a document the candidate actually uploaded, e.g. "[The officer glances at your bank statement]". Never invent documents they don't have, and never use a cue two turns in a row.` : '';
    return `You are ${ctx.officer}. This is a demanding, high-pressure mock interview meant to expose this specific candidate's weak spots before the real one, so they walk in confident.${consulateExtras}
Rules:
- Stay strictly in the visa officer role — skeptical, professional, and tough. Never break character.
- Use the candidate's attached profile and uploaded documents to ask the hardest, most personalized questions possible — never generic textbook questions.
- Concentrate your toughest scrutiny on ${ctx.focus}.
- Ask one question at a time, and cross-examine: if an answer is vague, rehearsed, over-confident, or contradicts their documents/profile, hit back with a sharper follow-up.
- Progressively escalate the difficulty as the interview goes on.
- Do NOT provide coaching, feedback, scores, hints, or reassurance during the interview.
- Keep responses concise and interview-like.
- When you have thoroughly tested the candidate, include the exact token INTERVIEW_COMPLETE in your response once (at the end).
- If asked about your AI model/provider/training, do not mention Gemini, Google, or internal model names.
- In those cases, say you are Rilono AI and continue the interview simulation.`;
}

function visaMockReportInstruction() {
    const ctx = currentInterviewContext();
    return `You are evaluating a completed ${ctx.report} mock interview transcript.
Cross-check the candidate's answers against their attached profile and uploaded documents; reward answers backed by their real evidence and penalize vague, rehearsed, or unsupported ones.
Generate a concise final report in plain text with these sections:
1) Approval Probability: X%
2) Rejection Probability: Y%
3) Decision Drivers (3-5 bullets)
4) Strengths (3 bullets)
5) Risk Areas (3 bullets, specific to this candidate's real profile/documents)
6) Top Improvements Before Real Interview (3 actionable bullets)
Make probabilities realistic, balanced, honest (do not inflate), and sum to 100%.
Do not use markdown formatting characters such as **, *, #, -, or backticks.
If asked about your AI model/provider/training, do not mention Gemini, Google, or internal model names.
In those cases, say you are Rilono AI and continue with the report task.`;
}

let visaMockInterviewState = {
    active: false,
    listening: false,
    pending: false,
    finishRequested: false,
    reportGenerating: false,
    history: [],
    recognition: null,
    channel: null,
    showModePicker: false,
    // Consulate Window (US voice mock) — immersive embassy-booth experience
    consulate: false,
    officerSpeaking: false,
    strictness: null,
    windowNumber: null,
    nudgeTimerId: null,
    orbIntervalId: null,
    timerIntervalId: null,
    timerStartedAt: null,
    elapsedMs: 0,
    reportProgressIntervalId: null,
    reportGenerationStartedAt: null,
    reportGenerationElapsedMs: 0,
    micPermission: 'unknown',
    micPermissionStatus: null,
    micPermissionCheckPromise: null
};

let visaPrepInterviewState = {
    active: false,
    listening: false,
    pending: false,
    history: [],
    recognition: null,
    channel: null,
    showModePicker: false,
    micPermission: 'unknown',
    micPermissionStatus: null,
    micPermissionCheckPromise: null
};

const MOCK_INTERVIEW_TIMER_INTERVAL_MS = 1000;
const MOCK_REPORT_PROGRESS_STAGES = [
    { afterSeconds: 0, label: 'Preparing transcript' },
    { afterSeconds: 5, label: 'Reviewing your responses' },
    { afterSeconds: 10, label: 'Analyzing decision factors' },
    { afterSeconds: 15, label: 'Finalizing your report' }
];

// ISO-4217 minor-unit exponents. This must stay a FULL mirror of app/money.py
// MINOR_UNIT_EXPONENT, not just the eight chargeable codes: the UI also renders
// historical payment rows, whose `currency` comes from whatever Razorpay reported, and a
// code missing from this table silently falls back to exponent 2. That is a 100× display
// error for a zero-decimal currency (ISK 999 rendered as "ISK 9.99") and a 10× one for a
// three-decimal currency (KWD 99990 rendered as "KWD 999.90" instead of "KWD 99.990").
// Non-chargeable codes are listed on purpose for exactly that reason.
const CURRENCY_MINOR_UNIT_EXPONENT = {
    // 2-decimal — the launch charge set
    INR: 2, USD: 2, GBP: 2, EUR: 2, CAD: 2, AUD: 2, AED: 2, SGD: 2,
    // 2-decimal — display only
    NZD: 2, CHF: 2, ZAR: 2, HKD: 2, MYR: 2, PHP: 2, THB: 2, SEK: 2,
    NOK: 2, DKK: 2, PLN: 2, MXN: 2, BRL: 2, TRY: 2, SAR: 2, QAR: 2,
    LKR: 2, NPR: 2, BDT: 2, PKR: 2, CNY: 2, IDR: 2, ILS: 2, RUB: 2,
    // zero-decimal — dividing these by 100 shows the amount 100× too small
    JPY: 0, KRW: 0, VND: 0, ISK: 0, CLP: 0, BIF: 0, DJF: 0, GNF: 0,
    KMF: 0, MGA: 0, PYG: 0, RWF: 0, UGX: 0, VUV: 0, XAF: 0, XOF: 0,
    XPF: 0,
    // three-decimal
    KWD: 3, BHD: 3, OMR: 3, JOD: 3, TND: 3, IQD: 3, LYD: 3
};

// URL Routing System
let isNavigating = false; // Flag to prevent recursive navigation

const APP_ROUTE_TITLES = Object.freeze({
    '/': 'Rilono — AI-Powered Study-Abroad Platform · US, UK, Canada, Australia & Germany',
    '/us-f1-visa': 'F1 Student Visa Guidance | DS-160, I-20, Documents & Interview | Rilono AI',
    '/products/us-f1-visa': 'F1 Student Visa Guidance | DS-160, I-20, Documents & Interview | Rilono AI',
    '/login': 'Log in · Rilono',
    '/register': 'Create your account · Rilono',
    '/forgot-password': 'Reset your password · Rilono',
    '/reset-password': 'Reset your password · Rilono',
    '/verify-email': 'Verify your email · Rilono',
    '/verify-university-change': 'Confirm your university change · Rilono',
    '/unsubscribe-email': 'Email preferences · Rilono',
    '/dashboard': 'Your Dashboard · Rilono',
    '/documents': 'Your Documents · Rilono',
    '/interviews': 'Visa Interview Prep · Rilono',
    '/universities': 'University Shortlist · Rilono',
    '/courses': 'Course Finder · Rilono',
    '/news': 'Visa News · Rilono',
    '/copilot': 'AI Copilot · Rilono',
    '/sop': 'SOP Studio · Rilono',
    '/rilono-ai': 'Rilono AI Assistant · Rilono',
    '/profile': 'Your Profile · Rilono',
    '/settings': 'Settings · Rilono',
    '/referral': 'Referral Program · Rilono',
    '/subscription': 'Your Subscription · Rilono',
    '/pricing': 'Pricing — Plans & Visa Success Pass · Rilono',
    '/about-us': 'About Rilono — AI Study-Abroad Guidance for US, UK, Canada, Australia & Germany',
    '/contact': 'Contact Rilono — Support for Students & Study-Abroad Consultancies',
    '/privacy': 'Privacy Policy · Rilono',
    '/terms': 'Terms & Conditions · Rilono',
    '/refund-policy': 'Refund Policy · Rilono',
    '/delivery-policy': 'Service Delivery Policy · Rilono',
    '/dpa': 'Data Processing Agreement · Rilono'
});

function normalizeAppRoutePath(path) {
    const rawPath = String(path || '/');
    try {
        const pathname = new URL(rawPath, window.location.origin).pathname;
        return pathname.length > 1 && pathname.endsWith('/') ? pathname.slice(0, -1) : pathname;
    } catch (error) {
        const pathname = rawPath.split(/[?#]/, 1)[0] || '/';
        return pathname.length > 1 && pathname.endsWith('/') ? pathname.slice(0, -1) : pathname;
    }
}

function syncDocumentTitle(path = window.location.pathname) {
    const title = APP_ROUTE_TITLES[normalizeAppRoutePath(path)];
    if (title && document.title !== title) {
        document.title = title;
    }
}

function updateURL(path, replace = false) {
    syncDocumentTitle(path);
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

// Destination + visa type the dashboard should personalize for (null when unknown
// or for anonymous visitors, in which case the backend serves the US F-1 catalog).
function currentUserVisaScope() {
    const country = (currentUser && currentUser.destination_country_code) || '';
    const visa = (currentUser && currentUser.visa_type_key) || '';
    return country ? { country, visa } : null;
}

async function initializeDocumentCatalog(scope = null) {
    try {
        let url = `${API_BASE}/api/documents/catalog`;
        if (scope && scope.country) {
            const qs = new URLSearchParams({ country: scope.country });
            if (scope.visa) qs.set('visa_type', scope.visa);
            url += `?${qs.toString()}`;
        }
        const response = await fetch(url, { credentials: 'same-origin' });
        if (!response.ok) {
            throw new Error(`Catalog request failed: ${response.status}`);
        }
        const payload = await response.json();
        applyDocumentCatalogPayload(payload);
        loadedCatalogScopeKey = (scope && scope.country) ? `${scope.country}|${scope.visa || ''}` : 'default';
    } catch (error) {
        console.warn('Unable to load document catalog from backend; using fallback catalog.', error);
        applyDocumentCatalogPayload(null);
        // Leave loadedCatalogScopeKey unchanged so a later checkAuth() can retry personalization.
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

// Dashboard sections are deep-linkable: each tab owns a real path (bookmarkable,
// refresh- and back/forward-safe). The server serves the SPA for every path here
// (read_preserved_public_spa_routes) — without that, these URLs fell through to the
// catch-all and rendered the marketing homepage even for logged-in users.
const DASHBOARD_PATH_TO_TAB = {
    '/documents': 'documents',
    '/interviews': 'visa',
    '/universities': 'universities',
    '/courses': 'courses',
    '/news': 'news',
    '/copilot': 'copilot',
    '/sop': 'sop',
    '/rilono-ai': 'records',
    '/profile': 'profile',
    '/settings': 'settings',
    '/referral': 'referral',
};
const DASHBOARD_TAB_TO_PATH = Object.fromEntries(
    Object.entries(DASHBOARD_PATH_TO_TAB).map(([p, t]) => [t, p]));
DASHBOARD_TAB_TO_PATH.overview = '/dashboard';

function handleRoute(skipURLUpdate = false) {
    isNavigating = true; // Set flag to prevent URL updates during route handling
    const rawPath = getPathFromURL();
    const path = rawPath.length > 1 && rawPath.endsWith('/') ? rawPath.slice(0, -1) : rawPath;
    const queryParams = getQueryParams();
    syncDocumentTitle(path);

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
    } else if (DASHBOARD_PATH_TO_TAB[path]) {
        // Deep link straight to a dashboard section (/documents, /interviews, …):
        // open the dashboard WITHOUT rewriting the URL, then switch to that tab.
        showDashboard(true);
        switchDashboardTab(DASHBOARD_PATH_TO_TAB[path]);
    } else if (path === '/subscription') {
        showSubscription(skipURLUpdate);
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
    } else if (path === '/dpa') {
        showDPA(skipURLUpdate);
    } else if (path === '/contact') {
        showContact(skipURLUpdate);
    } else if (path === '/unsubscribe-email') {
        showEmailUnsubscribe(skipURLUpdate);
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

// The site footer is shared verbatim with the static marketing pages, so its
// links are plain hrefs (crawlable, work without JS). Inside the SPA, the paths
// handleRoute() already owns are navigated client-side instead of reloading the
// whole bundle; everything else (/blog, /careers, country pages) loads normally.
const SPA_FOOTER_ROUTES = new Set([
    '/', '/pricing', '/about-us', '/contact', '/privacy', '/terms',
    '/refund-policy', '/delivery-policy', '/dpa', '/login', '/register',
]);

document.addEventListener('click', (e) => {
    // defaultPrevented === the Cookie Settings link already opened its modal.
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const link = e.target.closest && e.target.closest('.hx-footer a[href^="/"]');
    if (!link || link.target === '_blank') return;
    const href = link.getAttribute('href') || '';
    const path = href.length > 1 && href.endsWith('/') ? href.slice(0, -1) : href;
    if (!SPA_FOOTER_ROUTES.has(path)) return;
    e.preventDefault();
    updateURL(path);
    handleRoute(true);
    window.scrollTo(0, 0);
});

// Initialize Turnstile site key
async function initializeTurnstile() {
    try {
        const response = await fetch(`${API_BASE}/api/auth/turnstile-site-key`);
        if (response.ok) {
            const data = await response.json();
            turnstileSiteKey = data.site_key;

            const loginWidget = document.getElementById('turnstile-login');
            const registerWidget = document.getElementById('turnstile-register');
            const forgotWidget = document.getElementById('turnstile-forgot-password');
            const resetWidget = document.getElementById('turnstile-reset-password');
            const widgets = [loginWidget, registerWidget, forgotWidget, resetWidget];

            if (!turnstileSiteKey) {
                // Hide widgets if no site key is configured
                widgets.forEach((widget) => {
                    if (widget) widget.style.display = 'none';
                });
                return;
            }

            // Set site key attribute - Turnstile will auto-render when script loads
            widgets.forEach((widget) => {
                if (widget) widget.setAttribute('data-sitekey', turnstileSiteKey);
            });
        }
    } catch (error) {
        console.error('Error loading Turnstile site key:', error);
    }
}

function renderAuthTurnstileWidget(widgetElement, widgetKey) {
    if (!widgetElement) return;

    if (!turnstileSiteKey) {
        widgetElement.style.display = 'none';
        return;
    }

    widgetElement.style.display = 'block';
    if (!widgetElement.getAttribute('data-sitekey')) {
        widgetElement.setAttribute('data-sitekey', turnstileSiteKey);
    }

    const renderWidget = () => {
        if (!window.turnstile) {
            setTimeout(renderWidget, 100);
            return;
        }

        try {
            // If widget auto-rendered by Turnstile, reuse and reset it.
            window.turnstile.getResponse(widgetElement);
            window.turnstile.reset(widgetElement);
            turnstileWidgetIds[widgetKey] = widgetElement;
            return;
        } catch (autoRenderCheckError) {
            // Continue with explicit render path.
        }

        try {
            const existingWidget = turnstileWidgetIds[widgetKey];
            if (existingWidget) {
                window.turnstile.reset(existingWidget);
                return;
            }
            const widgetId = window.turnstile.render(widgetElement, {
                sitekey: turnstileSiteKey,
                theme: 'light'
            });
            turnstileWidgetIds[widgetKey] = widgetId || widgetElement;
        } catch (error) {
            try {
                const widgetId = window.turnstile.render(widgetElement, {
                    sitekey: turnstileSiteKey,
                    theme: 'light'
                });
                turnstileWidgetIds[widgetKey] = widgetId || widgetElement;
            } catch (renderError) {
                console.error('Error rendering Turnstile:', renderError);
            }
        }
    };

    renderWidget();
}

function getAuthTurnstileToken(widgetElement, widgetKey) {
    if (!turnstileSiteKey || !window.turnstile) return '';

    try {
        if (widgetElement) {
            const directToken = window.turnstile.getResponse(widgetElement);
            if (directToken) return directToken;
        }
    } catch (error) {
        // noop
    }

    try {
        const knownWidgetId = turnstileWidgetIds[widgetKey];
        if (knownWidgetId) {
            const token = window.turnstile.getResponse(knownWidgetId);
            if (token) return token;
        }
    } catch (error) {
        // noop
    }

    if (widgetElement && widgetElement.id) {
        try {
            return window.turnstile.getResponse(widgetElement.id) || '';
        } catch (error) {
            return '';
        }
    }
    return '';
}

async function initializeFooterVersion() {
    const footerVersion = document.getElementById('footerVersion');
    if (!footerVersion) return;

    try {
        const response = await fetch(`${API_BASE}/api/meta`);
        if (!response.ok) return;

        const data = await response.json();
        const version = String(data?.version || '').trim();
        if (!version) return;

        footerVersion.textContent = `v${version}`;
    } catch (error) {
        console.warn('Error loading app version:', error);
    }
}

// Initialize app
document.addEventListener('DOMContentLoaded', async () => {
    setupEventListeners();
    initializeCookieConsentManager();
    discardLegacyNotificationStorage();
    syncMobileNavState();
    await initializeDocumentCatalog();
    initializeSearchableDropdowns();
    void initializePricingSelector();
    initializeRegisterCountrySelector();
    initializeRilonoProductReel();
    initChromeExtPlayer();
    void initializeFooterVersion();

    // Initialize Turnstile
    await initializeTurnstile();

    // Set explicit legal revision dates (stable, not per-page-load dynamic values).
    const aboutLastUpdated = document.getElementById('aboutLastUpdated');
    const privacyLastUpdated = document.getElementById('privacyLastUpdated');
    const termsLastUpdated = document.getElementById('termsLastUpdated');
    const refundLastUpdated = document.getElementById('refundLastUpdated');
    const deliveryLastUpdated = document.getElementById('deliveryLastUpdated');
    const dpaLastUpdated = document.getElementById('dpaLastUpdated');
    if (aboutLastUpdated) aboutLastUpdated.textContent = LEGAL_LAST_UPDATED.about;
    if (privacyLastUpdated) privacyLastUpdated.textContent = LEGAL_LAST_UPDATED.privacy;
    if (termsLastUpdated) termsLastUpdated.textContent = LEGAL_LAST_UPDATED.terms;
    if (refundLastUpdated) refundLastUpdated.textContent = LEGAL_LAST_UPDATED.refund;
    if (deliveryLastUpdated) deliveryLastUpdated.textContent = LEGAL_LAST_UPDATED.delivery;
    if (dpaLastUpdated) dpaLastUpdated.textContent = LEGAL_LAST_UPDATED.dpa;

    // Restore token for same-tab refresh persistence and check authentication.
    restoreAuthToken();
    await checkAuth();
    // Personalize the document/journey catalog to the signed-in student's destination.
    if (currentUser) {
        const scope = currentUserVisaScope();
        if (scope) { try { await initializeDocumentCatalog(scope); } catch (e) { /* keep default */ } }
    }
    loadSocialAuthButtons();
    showOAuthErrorIfPresent();
    showOAuthSuccessIfPresent();
    loadNotifications();
    updateFloatingChatVisibility();
    initializeRilonoAiAttachmentUi();
    initializeFloatingChatPopup();

    // Handle initial route (use replaceState for initial load)
    handleRoute(true);
    // Preserve full URL (including query params like unsubscribe token) on initial load.
    const initialPathWithQuery = `${window.location.pathname}${window.location.search || ''}`;
    updateURL(initialPathWithQuery || '/', true);
});

// A browser can restore a page from its back/forward cache with the previous DOM and
// JavaScript heap intact. Reset personalized chrome immediately, then re-authenticate,
// so an expired/logged-out session can never leave a name or notification badge visible.
window.addEventListener('pageshow', async (event) => {
    if (!event.persisted) return;
    clearClientAuthState();
    await checkAuth();
});

function isMobileViewport() {
    return window.matchMedia(`(max-width: ${MOBILE_NAV_BREAKPOINT}px)`).matches;
}

function syncMobileNavState() {
    const navLinks = document.getElementById('navLinks');
    const navToggle = document.getElementById('mobileNavToggle');
    if (!navLinks || !navToggle) return;

    if (!isMobileViewport()) {
        mobileNavOpen = false;
    }

    navLinks.classList.toggle('mobile-open', mobileNavOpen);
    navToggle.setAttribute('aria-expanded', mobileNavOpen ? 'true' : 'false');
    navToggle.setAttribute('aria-label', mobileNavOpen ? 'Close navigation menu' : 'Open navigation menu');
    navToggle.textContent = mobileNavOpen ? '✕' : '☰';
}

function toggleMobileNav(forceState = null) {
    if (!isMobileViewport()) return;
    mobileNavOpen = typeof forceState === 'boolean' ? forceState : !mobileNavOpen;
    syncMobileNavState();
}

function closeMobileNav() {
    if (!mobileNavOpen) return;
    mobileNavOpen = false;
    syncMobileNavState();
}

// Canonical residence-country list — MUST stay identical to app/countries.py
// RESIDENCE_COUNTRIES (tests/test_residence_country.py compares the two). Until 2026-08-24
// this dropdown offered only the 9 pricing countries and pre-selected "United States".
const RESIDENCE_COUNTRIES = ['Afghanistan', 'Albania', 'Algeria', 'Andorra', 'Angola', 'Antigua and Barbuda', 'Argentina', 'Armenia', 'Australia', 'Austria', 'Azerbaijan', 'Bahamas', 'Bahrain', 'Bangladesh', 'Barbados', 'Belarus', 'Belgium', 'Belize', 'Benin', 'Bhutan', 'Bolivia', 'Bosnia and Herzegovina', 'Botswana', 'Brazil', 'Brunei', 'Bulgaria', 'Burkina Faso', 'Burundi', 'Cabo Verde', 'Cambodia', 'Cameroon', 'Canada', 'Central African Republic', 'Chad', 'Chile', 'China', 'Colombia', 'Comoros', 'Congo (Democratic Republic)', 'Congo (Republic)', 'Costa Rica', 'Cote d\'Ivoire', 'Croatia', 'Cuba', 'Cyprus', 'Czech Republic', 'Denmark', 'Djibouti', 'Dominica', 'Dominican Republic', 'Ecuador', 'Egypt', 'El Salvador', 'Equatorial Guinea', 'Eritrea', 'Estonia', 'Eswatini', 'Ethiopia', 'Fiji', 'Finland', 'France', 'Gabon', 'Gambia', 'Georgia', 'Germany', 'Ghana', 'Greece', 'Grenada', 'Guatemala', 'Guinea', 'Guinea-Bissau', 'Guyana', 'Haiti', 'Honduras', 'Hong Kong', 'Hungary', 'Iceland', 'India', 'Indonesia', 'Iran', 'Iraq', 'Ireland', 'Israel', 'Italy', 'Jamaica', 'Japan', 'Jordan', 'Kazakhstan', 'Kenya', 'Kiribati', 'Kosovo', 'Kuwait', 'Kyrgyzstan', 'Laos', 'Latvia', 'Lebanon', 'Lesotho', 'Liberia', 'Libya', 'Liechtenstein', 'Lithuania', 'Luxembourg', 'Macau', 'Madagascar', 'Malawi', 'Malaysia', 'Maldives', 'Mali', 'Malta', 'Marshall Islands', 'Mauritania', 'Mauritius', 'Mexico', 'Micronesia', 'Moldova', 'Monaco', 'Mongolia', 'Montenegro', 'Morocco', 'Mozambique', 'Myanmar', 'Namibia', 'Nauru', 'Nepal', 'Netherlands', 'New Zealand', 'Nicaragua', 'Niger', 'Nigeria', 'North Korea', 'North Macedonia', 'Norway', 'Oman', 'Pakistan', 'Palau', 'Palestine', 'Panama', 'Papua New Guinea', 'Paraguay', 'Peru', 'Philippines', 'Poland', 'Portugal', 'Qatar', 'Romania', 'Russia', 'Rwanda', 'Saint Kitts and Nevis', 'Saint Lucia', 'Saint Vincent and the Grenadines', 'Samoa', 'San Marino', 'Sao Tome and Principe', 'Saudi Arabia', 'Senegal', 'Serbia', 'Seychelles', 'Sierra Leone', 'Singapore', 'Slovakia', 'Slovenia', 'Solomon Islands', 'Somalia', 'South Africa', 'South Korea', 'South Sudan', 'Spain', 'Sri Lanka', 'Sudan', 'Suriname', 'Sweden', 'Switzerland', 'Syria', 'Taiwan', 'Tajikistan', 'Tanzania', 'Thailand', 'Timor-Leste', 'Togo', 'Tonga', 'Trinidad and Tobago', 'Tunisia', 'Turkey', 'Turkmenistan', 'Tuvalu', 'Uganda', 'Ukraine', 'United Arab Emirates', 'United Kingdom', 'United States', 'Uruguay', 'Uzbekistan', 'Vanuatu', 'Vatican City', 'Venezuela', 'Vietnam', 'Yemen', 'Zambia', 'Zimbabwe'];
const POPULAR_RESIDENCE_COUNTRIES = ['India', 'Nigeria', 'Pakistan', 'Bangladesh', 'Nepal', 'Sri Lanka', 'China', 'Vietnam', 'Philippines', 'United Arab Emirates', 'United States', 'United Kingdom'];
function residenceCountryOptions(selected) {
    const opt = (name) => `<option value="${escapeHtml(name)}" ${name === selected ? 'selected' : ''}>${escapeHtml(name)}</option>`;
    return '<option value="">Select your country…</option>'
        + `<optgroup label="Popular">${POPULAR_RESIDENCE_COUNTRIES.map(opt).join('')}</optgroup>`
        + `<optgroup label="All countries">${RESIDENCE_COUNTRIES.map(opt).join('')}</optgroup>`;
}

function initializeRegisterCountrySelector() {
    const countrySelect = document.getElementById('registerCountry');
    if (!countrySelect) return;
    countrySelect.innerHTML = residenceCountryOptions('');

    countrySelect.value = 'United States';
}

function setupEventListeners() {
    bindVisaInterviewChatComposer('mock');
    bindVisaInterviewChatComposer('prep');
    // Main chat forms can be shown before their tab-specific initializer runs. A delegated
    // submit listener guarantees the first message is handled even in that empty state.
    document.addEventListener('submit', handleDelegatedRilonoAiChatSubmit);

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
    const emailUnsubscribeForm = document.getElementById('emailUnsubscribeForm');
    if (emailUnsubscribeForm) emailUnsubscribeForm.addEventListener('submit', handleEmailUnsubscribeSubmit);
    const emailUnsubQuickReasons = document.getElementById('emailUnsubQuickReasons');
    if (emailUnsubQuickReasons) {
        emailUnsubQuickReasons.addEventListener('click', handleEmailUnsubQuickReasonClick);
    }
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
    const mobileNavToggle = document.getElementById('mobileNavToggle');
    if (mobileNavToggle) {
        mobileNavToggle.addEventListener('click', () => {
            toggleMobileNav();
        });
    }
    const navLinks = document.getElementById('navLinks');
    if (navLinks) {
        navLinks.addEventListener('click', (e) => {
            if (e.target.closest('a')) {
                closeMobileNav();
            }
        });
    }
    window.addEventListener('resize', syncMobileNavState);
    window.addEventListener('orientationchange', syncMobileNavState);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeMobileNav();
        }
    });
    document.addEventListener('fullscreenchange', () => {
        renderPrepInterviewModeUI();
        renderMockInterviewModeUI();
    });

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
    // Reject unsupported file types the moment they're picked (the `accept` attribute is
    // only a soft hint — "All Files" bypasses it), instead of at the passphrase step.
    const documentFileInput = document.getElementById('documentFile');
    if (documentFileInput) {
        documentFileInput.addEventListener('change', () => {
            const f = documentFileInput.files && documentFileInput.files[0];
            if (f && !isAllowedDocumentFile(f.name)) {
                showMessage('That file type isn\'t supported. Please upload PDF, DOC, DOCX, TXT or an image (JPG, PNG, GIF, WEBP).', 'error');
                documentFileInput.value = '';
            }
        });
    }

    const adminUsersFilterForm = document.getElementById('adminUsersFilterForm');
    if (adminUsersFilterForm) {
        adminUsersFilterForm.addEventListener('submit', handleAdminUsersFilterSubmit);
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
        hintEl.style.color = '#065f46';
        hintEl.textContent = 'Strong password';
    } else {
        hintEl.style.color = '#b45309';
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
        hintEl.style.color = '#065f46';
        hintEl.textContent = 'Strong password';
    } else {
        hintEl.style.color = '#b45309';
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
        hintEl.style.color = '#065f46';
        hintEl.textContent = 'Strong password';
    } else {
        hintEl.style.color = '#b45309';
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
            // Recognized university email — auto-fill the university as a convenience.
            universityInput.value = data.university_name;
            messageEl.textContent = `✓ Recognized university email: ${data.email_domain}`;
            messageEl.style.color = 'var(--success-color)';
            messageEl.style.display = 'block';
        } else {
            // Open signup: any email is welcome. Don't block — university is optional
            // and can be set later during onboarding or in profile settings.
            universityInput.value = '';
            messageEl.style.display = 'none';
        }
    } catch (error) {
        console.error('Error checking university:', error);
        universityInput.value = '';
        messageEl.style.display = 'none';
    }
}

const SOCIAL_PROVIDER_ICONS = {
    google: '<svg viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>',
    microsoft: '<svg viewBox="0 0 21 21"><rect x="1" y="1" width="9" height="9" fill="#f25022"/><rect x="11" y="1" width="9" height="9" fill="#7fba00"/><rect x="1" y="11" width="9" height="9" fill="#00a4ef"/><rect x="11" y="11" width="9" height="9" fill="#ffb900"/></svg>',
    apple: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M16.36 12.78c-.02-2.28 1.86-3.38 1.95-3.43-1.06-1.56-2.72-1.77-3.31-1.79-1.41-.14-2.75.83-3.46.83-.71 0-1.81-.81-2.98-.79-1.53.02-2.95.89-3.74 2.26-1.6 2.77-.41 6.87 1.14 9.12.76 1.1 1.66 2.34 2.84 2.29 1.14-.05 1.57-.74 2.95-.74 1.38 0 1.76.74 2.96.71 1.22-.02 2-1.12 2.75-2.22.86-1.27 1.22-2.5 1.24-2.57-.03-.01-2.38-.91-2.4-3.62zM14.13 5.9c.63-.76 1.05-1.82.94-2.88-.91.04-2 .61-2.65 1.37-.58.67-1.09 1.75-.95 2.78 1.01.08 2.04-.51 2.66-1.27z"/></svg>',
};

function renderSocialButtons(container, providers, dividerEl, options) {
    if (!container) return;
    const opts = options || {};
    const consentNoteEl = opts.consentNoteEl || null;
    const clickwrapConsent = !!opts.clickwrapConsent;
    if (!providers || !providers.length) {
        container.innerHTML = '';
        // Clear any inline override so the CSS rule `.social-auth:empty { display:none }`
        // governs an empty container (no stale inline display left from the load race).
        container.style.display = '';
        if (dividerEl) dividerEl.style.display = 'none';
        if (consentNoteEl) consentNoteEl.style.display = 'none';
        return;
    }
    container.innerHTML = providers.map((p) => {
        const key = p.key;
        const icon = SOCIAL_PROVIDER_ICONS[key] || '';
        const startUrl = `${API_BASE}/api/auth/oauth/${key}/start`;
        return `<a class="social-btn social-btn-${key}" data-oauth-start="${startUrl}" href="${startUrl}">${icon}<span>Continue with ${p.label}</span></a>`;
    }).join('');
    // Buttons are present now — un-stick any inline `display:none` a view-switch
    // (e.g. backToRegisterStep1) may have set while the container was momentarily empty
    // during the async providers fetch. Without this the buttons render but stay hidden
    // (the "Google button disappears on hard refresh" bug).
    container.style.display = '';
    if (dividerEl) dividerEl.style.display = '';
    if (consentNoteEl) consentNoteEl.style.display = '';

    // Clickwrap consent: clicking a provider button IS the affirmative acceptance of the
    // Terms & Privacy (and age), disclosed inline in `consentNoteEl`. We pass consent=1 so
    // the backend may create a new account and record proof-of-consent (version, IP, UA,
    // timestamp). No separate checkbox to hunt for — clean one-tap social sign-up.
    if (clickwrapConsent) {
        container.querySelectorAll('a[data-oauth-start]').forEach((a) => {
            a.addEventListener('click', () => {
                const base = a.getAttribute('data-oauth-start');
                a.setAttribute('href', `${base}${base.includes('?') ? '&' : '?'}consent=1`);
            });
        });
    }
}

async function loadSocialAuthButtons() {
    try {
        const response = await fetch(`${API_BASE}/api/auth/oauth/providers`, { credentials: 'include' });
        if (!response.ok) return;
        const data = await response.json();
        const providers = (data && data.providers) || [];
        renderSocialButtons(
            document.getElementById('socialAuthLogin'),
            providers,
            document.getElementById('socialAuthLoginDivider'),
            { consentNoteEl: document.getElementById('socialConsentNoteLogin'), clickwrapConsent: true }
        );
        renderSocialButtons(
            document.getElementById('socialAuthRegister'),
            providers,
            document.getElementById('socialAuthRegisterDivider'),
            { consentNoteEl: document.getElementById('socialConsentNoteRegister'), clickwrapConsent: true }
        );
    } catch (error) {
        // Social login is optional — fail silently and leave the email forms.
    }
}

function showOAuthErrorIfPresent() {
    try {
        const err = new URLSearchParams(window.location.search).get('auth_error');
        if (!err) return;
        if (typeof showMessage === 'function') showMessage(err, 'error');
        const params = new URLSearchParams(window.location.search);
        params.delete('auth_error');
        const qs = params.toString();
        window.history.replaceState({}, '', window.location.pathname + (qs ? `?${qs}` : ''));
    } catch (e) { /* ignore */ }
}

// Social login (Google/Microsoft/Apple) returns via a redirect, so the in-page success
// message the email/password path shows would be lost. The backend tags that redirect with
// `signed_in=1`; surface the same confirmation here, then strip the flag from the URL so a
// refresh (or the initial updateURL below) never replays it.
function showOAuthSuccessIfPresent() {
    try {
        const params = new URLSearchParams(window.location.search);
        if (!params.get('signed_in')) return;
        params.delete('signed_in');
        const qs = params.toString();
        window.history.replaceState({}, '', window.location.pathname + (qs ? `?${qs}` : ''));
        if (!currentUser || typeof showMessage !== 'function') return;
        // Same treatment as the email/password path: hold the one-time prompts back (the dashboard
        // render below queues them) so this confirmation is readable first.
        holdPostLoginPrompts();
        showMessage('Login successful!', 'success');
    } catch (e) { /* ignore */ }
}

function discardLegacyNotificationStorage() {
    try {
        localStorage.removeItem(LEGACY_NOTIFICATION_STORAGE_KEY);
    } catch (error) {
        // Storage may be unavailable in strict privacy mode; the key is never read below.
    }
}

function clearClientAuthState({ render = true } = {}) {
    authToken = null;
    currentUser = null;
    currentSubscription = null;
    runtimeSubscriptionNotifyState = null;
    subscriptionNotifyStateUserId = null;
    notifications = [];
    persistAuthToken(null);
    // Drop any post-login prompt still waiting its turn — the session it belonged to is over.
    postLoginPromptQueue.length = 0;
    postLoginQuietUntil = 0;
    if (render) {
        updateUIForAuth();
        const authedPaths = ['/dashboard', '/subscription', ...Object.keys(DASHBOARD_PATH_TO_TAB)];
        if (authedPaths.includes(window.location.pathname)) {
            showLogin();
        }
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
            // Personalize the document/journey catalog to the signed-in student's destination
            // BEFORE any dashboard paint. updateUIForAuth() below — and showDashboard() later —
            // kick off loadProfile() → the visa-journey widget, which reads journeyStageCatalog.
            // If that still holds the anonymous US fallback, the widget paints US stages
            // ("I-20", "DS-160", "Fees Paid") under the correct UK heading. Awaiting the scoped
            // load HERE, before the render is triggered, closes the profile-fetch-vs-catalog-fetch
            // race the tester saw intermittently. (A prior attempt loaded it AFTER updateUIForAuth,
            // which is why the wrong US template still showed up on some loads.)
            const catalogScope = currentUserVisaScope();
            const catalogScopeKey = catalogScope ? `${catalogScope.country}|${catalogScope.visa || ''}` : null;
            if (catalogScopeKey && catalogScopeKey !== loadedCatalogScopeKey) {
                try { await initializeDocumentCatalog(catalogScope); } catch (e) { /* keep current catalog */ }
            }
            updateUIForAuth();
            updateVisaSectionLabels();
            updateVisaJourneyHeading();
            await loadSubscriptionStatus(true);
            return true;
        } else {
            clearClientAuthState();
            return false;
        }
    } catch (error) {
        console.error('Auth check failed:', error);
        clearClientAuthState();
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

function hasAdminConsoleAccess() {
    return Boolean(currentUser && (currentUser.is_admin || currentUser.is_developer));
}

function syncAdminConsoleVisibility() {
    const canManageUsers = hasAdminConsoleAccess();
    const navItem = document.getElementById('dashboardAdminNavItem');

    if (navItem) {
        navItem.style.display = canManageUsers ? 'flex' : 'none';
    }

    if (!canManageUsers && document.getElementById('dashboardTab-admin')?.classList.contains('active')) {
        switchDashboardTab('overview');
    }
}

function updateUIForAuth() {
    if (currentUser) {
        document.getElementById('loginLink').style.display = 'none';
        document.getElementById('registerLink').style.display = 'none';
        document.getElementById('userMenu').style.display = 'block';
        document.getElementById('notificationContainer').style.display = 'block';
        loadNotifications();
        updateFloatingChatVisibility();

        // Update homepage buttons
        const heroSellBtn = document.getElementById('heroSellBtn');
        const heroRegisterBtn = document.getElementById('heroRegisterBtn');
        const ctaRegisterBtn = document.getElementById('ctaRegisterBtn');
        if (heroSellBtn) heroSellBtn.style.display = 'inline-block';
        if (heroRegisterBtn) heroRegisterBtn.style.display = 'none';
        if (ctaRegisterBtn) ctaRegisterBtn.style.display = 'none';

        renderUserInfo(currentUser);
        syncAdminConsoleVisibility();
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
        const userInfoEl = document.getElementById('userInfo');
        const userDropdownEl = document.getElementById('userMenuDropdown');
        const notificationDropdownEl = document.getElementById('notificationDropdown');
        const dashUserNameEl = document.getElementById('dashUserName');
        const dashUserAvatarEl = document.getElementById('dashUserAvatar');
        if (userInfoEl) userInfoEl.replaceChildren();
        if (userDropdownEl) userDropdownEl.style.display = 'none';
        if (notificationDropdownEl) notificationDropdownEl.style.display = 'none';
        if (dashUserNameEl) dashUserNameEl.textContent = '';
        if (dashUserAvatarEl) dashUserAvatarEl.textContent = '';
        notificationDropdownOpen = false;
        notifications = [];
        updateNotificationBadge();
        renderNotifications();
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
        clearRilonoAiSessionAttachments(false);
        rilonoAiAttachmentRegistry = new Map();
        resetAdminUsersState(true);
        syncAdminConsoleVisibility();
    }
}

function toggleUserMenu() {
    const dropdown = document.getElementById('userMenuDropdown');
    dropdown.style.display = dropdown.style.display === 'none' ? 'block' : 'none';
}

let dashNotifOpen = false;

function toggleDashNotifications() {
    const dropdown = document.getElementById('dashNotifDropdown');
    dashNotifOpen = !dashNotifOpen;
    dropdown.style.display = dashNotifOpen ? 'block' : 'none';
    closeDashUserMenu();
    if (dashNotifOpen) {
        renderNotifications();
        markAllNotificationsRead();
    }
}

function closeDashNotifications() {
    const dropdown = document.getElementById('dashNotifDropdown');
    if (dropdown) dropdown.style.display = 'none';
    dashNotifOpen = false;
}

function toggleDashUserMenu() {
    const dropdown = document.getElementById('dashUserDropdown');
    if (!dropdown) return;
    const isOpen = dropdown.style.display !== 'none';
    dropdown.style.display = isOpen ? 'none' : 'block';
    closeDashNotifications();
}

function closeDashUserMenu() {
    const dropdown = document.getElementById('dashUserDropdown');
    if (dropdown) dropdown.style.display = 'none';
}

function updateDashHeaderUser() {
    if (!currentUser) return;
    const avatarEl = document.getElementById('dashUserAvatar');
    const nameEl = document.getElementById('dashUserName');
    if (avatarEl) {
        const name = currentUser.full_name || currentUser.email || '';
        const initials = name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
        avatarEl.textContent = initials || '?';
    }
    if (nameEl) {
        nameEl.textContent = currentUser.full_name || currentUser.email || 'User';
    }
}

// Notification Functions
function addNotification(title, message, type = 'info', data = null) {
    const notification = {
        id: `local-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
        title: title,
        message: message,
        type: type, // 'success', 'error', 'warning', 'info'
        data: data,
        timestamp: new Date().toISOString(),
        read: false,
        origin: 'local'
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

function getNotificationStorageKey() {
    if (currentUser?.id) {
        return `${NOTIFICATION_STORAGE_PREFIX}${currentUser.id}`;
    }
    return null;
}

function readLocalNotifications() {
    const userScopedKey = getNotificationStorageKey();
    if (!userScopedKey) return [];
    const rawUserScoped = localStorage.getItem(userScopedKey);
    if (rawUserScoped) {
        try {
            const parsed = JSON.parse(rawUserScoped);
            if (Array.isArray(parsed)) {
                return parsed.map((notif) => ({
                    ...notif,
                    origin: 'local'
                }));
            }
        } catch (error) {
            console.warn('Failed to parse local notifications:', error);
        }
    }

    return [];
}

function saveNotifications() {
    const userScopedKey = getNotificationStorageKey();
    if (!userScopedKey) return;
    const localOnlyNotifications = notifications
        .filter((notif) => notif.origin !== 'server')
        .slice(0, 50)
        .map((notif) => ({
            id: notif.id,
            title: notif.title,
            message: notif.message,
            type: notif.type,
            data: notif.data || null,
            timestamp: notif.timestamp,
            read: Boolean(notif.read),
            origin: 'local'
        }));
    localStorage.setItem(userScopedKey, JSON.stringify(localOnlyNotifications));
}

function normalizeServerNotification(rawNotification) {
    return {
        id: `srv-${rawNotification.id}`,
        serverId: rawNotification.id,
        title: rawNotification.title || 'Notification',
        message: rawNotification.message || '',
        type: rawNotification.notification_type || 'info',
        timestamp: rawNotification.created_at || new Date().toISOString(),
        read: Boolean(rawNotification.is_read),
        origin: 'server',
        data: null
    };
}

function mergeNotificationLists(serverNotifications, localNotifications) {
    const mergedByKey = new Map();
    [...serverNotifications, ...localNotifications].forEach((notif) => {
        if (!notif || !notif.id) return;
        mergedByKey.set(String(notif.id), notif);
    });
    return Array.from(mergedByKey.values())
        .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
        .slice(0, 100);
}

async function loadNotifications() {
    const localNotifications = currentUser ? readLocalNotifications() : [];
    let serverNotifications = [];

    if (currentUser && authToken) {
        try {
            const response = await fetch(`${API_BASE}/api/notifications?limit=100`, {
                headers: {
                    'Authorization': `Bearer ${authToken}`
                }
            });
            if (response.ok) {
                const payload = await response.json();
                if (Array.isArray(payload.notifications)) {
                    serverNotifications = payload.notifications.map(normalizeServerNotification);
                }
            }
        } catch (error) {
            console.warn('Failed to load server notifications:', error);
        }
    }

    notifications = mergeNotificationLists(serverNotifications, localNotifications);
    updateNotificationBadge();
    renderNotifications();
}

function updateNotificationBadge() {
    const badge = document.getElementById('notificationBadge');
    const dashDot = document.getElementById('dashNotifDot');
    const unreadCount = notifications.filter(n => !n.read).length;
    if (badge) {
        if (unreadCount > 0) {
            badge.textContent = unreadCount > 99 ? '99+' : unreadCount;
            badge.style.display = 'block';
        } else {
            badge.style.display = 'none';
        }
    }
    if (dashDot) {
        if (unreadCount > 0) {
            dashDot.textContent = unreadCount > 99 ? '99+' : unreadCount;
            dashDot.style.display = 'flex';
        } else {
            dashDot.textContent = '';
            dashDot.style.display = 'none';
        }
    }
}

function renderNotifications() {
    const list = document.getElementById('notificationList');
    const dashList = document.getElementById('dashNotifList');

    const emptyMsg = '<p style="text-align: center; padding: 1rem; color: var(--text-secondary);">No notifications</p>';

    if (notifications.length === 0) {
        if (list) list.innerHTML = emptyMsg;
        if (dashList) dashList.innerHTML = emptyMsg;
        return;
    }

    const html = notifications.map(notif => {
        const date = new Date(notif.timestamp);
        const timeAgo = getTimeAgo(date);
        const icon = getNotificationIcon(notif.type);
        const readClass = notif.read ? 'read' : '';
        const escapedId = String(notif.id).replace(/\\/g, '\\\\').replace(/'/g, "\\'");

        const formattedMessage = escapeHtml(notif.message).replace(/\n/g, '<br>');

        return `
            <div class="notification-item ${readClass}" onclick="markNotificationRead('${escapedId}')">
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

    if (list) list.innerHTML = html;
    if (dashList) dashList.innerHTML = html;
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

    // Normalize '*' bullet markers so they don't conflict with italic parsing
    html = html.replace(/^\s*\*(?=\s+)/gm, '•');

    // Convert markdown headings
    html = html.replace(/^###\s+(.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^##\s+(.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^#\s+(.+)$/gm, '<h1>$1</h1>');

    // Convert **bold** to <strong>
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Convert *italic* to <em> (but not if it's part of **)
    html = html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');

    // Convert `code` to <code>
    html = html.replace(/`([^`]+)`/g, '<code style="background: rgba(139, 92, 246, 0.2); padding: 2px 6px; border-radius: 4px; font-family: monospace;">$1</code>');

    // Convert bullet points (lines starting with -, •, or *)
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
        markAllNotificationsRead();
    }
}

async function markAllNotificationsRead() {
    const unread = notifications.filter(n => !n.read);
    if (unread.length === 0) return;

    unread.forEach(n => { n.read = true; });
    saveNotifications();
    updateNotificationBadge();
    renderNotifications();

    if (authToken) {
        try {
            await fetch(`${API_BASE}/api/notifications/read-all`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${authToken}` }
            });
        } catch (error) {
            console.warn('Failed to mark server notifications as read:', error);
        }
    }
}

async function markNotificationRead(id) {
    const notif = notifications.find(n => String(n.id) === String(id));
    if (notif && !notif.read) {
        if (notif.origin === 'server' && notif.serverId && authToken) {
            try {
                await fetch(`${API_BASE}/api/notifications/${notif.serverId}/read`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${authToken}`
                    }
                });
            } catch (error) {
                console.warn('Failed to mark server notification as read:', error);
            }
        }
        notif.read = true;
        saveNotifications();
        updateNotificationBadge();
        renderNotifications();
    }
}

async function clearAllNotifications() {
    if (await confirmDialog('This will clear all your notifications.', { title: 'Clear all notifications?', okText: 'Clear all' })) {
        const previousNotifications = [...notifications];
        notifications = [];
        saveNotifications();
        updateNotificationBadge();
        renderNotifications();

        if (currentUser && authToken) {
            try {
                const response = await fetch(`${API_BASE}/api/notifications`, {
                    method: 'DELETE',
                    headers: {
                        'Authorization': `Bearer ${authToken}`
                    }
                });
                if (!response.ok) {
                    throw new Error(`clear-all failed: ${response.status}`);
                }
            } catch (error) {
                console.warn('Failed to clear server notifications:', error);
                notifications = previousNotifications;
                saveNotifications();
                updateNotificationBadge();
                renderNotifications();
            }
        }
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

    const navContainer = document.querySelector('.nav-container');
    if (mobileNavOpen && navContainer && !navContainer.contains(e.target)) {
        closeMobileNav();
    }
});

function getRilonoReelElements() {
    const player = document.getElementById('rilonoRemotionPlayer');
    const progressBar = document.getElementById('rilonoReelProgress');
    const sceneLabel = document.getElementById('rilonoReelSceneLabel');
    const playPauseBtn = document.getElementById('rilonoReelPlayPause');
    if (!player || !progressBar || !sceneLabel || !playPauseBtn) return null;

    const scenes = Array.from(player.querySelectorAll('.rilono-reel-scene'));
    const dots = Array.from(player.querySelectorAll('.rilono-reel-dot'));
    if (!scenes.length || !dots.length) return null;

    return {
        player,
        progressBar,
        sceneLabel,
        playPauseBtn,
        scenes,
        dots
    };
}

function stopRilonoProductReelTimers() {
    if (rilonoReelTimer) {
        clearTimeout(rilonoReelTimer);
        rilonoReelTimer = null;
    }
    if (rilonoReelProgressTimer) {
        clearInterval(rilonoReelProgressTimer);
        rilonoReelProgressTimer = null;
    }
}

function syncRilonoReelControls() {
    const elements = getRilonoReelElements();
    if (!elements) return;
    elements.playPauseBtn.textContent = rilonoReelIsPlaying ? '❚❚' : '▶';
    elements.playPauseBtn.setAttribute('aria-label', rilonoReelIsPlaying ? 'Pause product reel' : 'Play product reel');
}

function updateRilonoReelProgress() {
    const elements = getRilonoReelElements();
    if (!elements) return;
    if (!rilonoReelSceneStartedAt) {
        elements.progressBar.style.transform = 'scaleX(0)';
        return;
    }

    const elapsed = Math.max(Date.now() - rilonoReelSceneStartedAt, 0);
    const ratio = Math.min(elapsed / RILONO_REEL_SCENE_DURATION_MS, 1);
    elements.progressBar.style.transform = `scaleX(${ratio})`;
}

function setRilonoReelScene(sceneIndex, restartPlayback = true) {
    const elements = getRilonoReelElements();
    if (!elements) return;

    const sceneCount = elements.scenes.length;
    const normalizedIndex = ((sceneIndex % sceneCount) + sceneCount) % sceneCount;

    rilonoReelCurrentScene = normalizedIndex;
    rilonoReelSceneStartedAt = Date.now();
    rilonoReelPausedElapsed = 0;

    elements.scenes.forEach((scene, index) => {
        scene.classList.toggle('is-active', index === normalizedIndex);
    });
    elements.dots.forEach((dot, index) => {
        dot.classList.toggle('is-active', index === normalizedIndex);
    });

    const activeSceneLabel = elements.scenes[normalizedIndex].getAttribute('data-scene-label') || 'Rilono Product Reel';
    elements.sceneLabel.textContent = activeSceneLabel;
    elements.progressBar.style.transform = 'scaleX(0)';

    if (restartPlayback && rilonoReelIsPlaying) {
        startRilonoProductReel(true);
    }
}

function startRilonoProductReel(resetSceneClock = true) {
    const elements = getRilonoReelElements();
    if (!elements) return;

    stopRilonoProductReelTimers();
    rilonoReelIsPlaying = true;

    if (resetSceneClock || !rilonoReelSceneStartedAt) {
        rilonoReelSceneStartedAt = Date.now();
        rilonoReelPausedElapsed = 0;
    } else if (rilonoReelPausedElapsed > 0) {
        rilonoReelSceneStartedAt = Date.now() - Math.min(rilonoReelPausedElapsed, RILONO_REEL_SCENE_DURATION_MS - 120);
    }

    const elapsed = Math.max(Date.now() - rilonoReelSceneStartedAt, 0);
    const remaining = Math.max(RILONO_REEL_SCENE_DURATION_MS - elapsed, 250);

    rilonoReelTimer = window.setTimeout(() => {
        const nextScene = (rilonoReelCurrentScene + 1) % elements.scenes.length;
        setRilonoReelScene(nextScene, false);
        startRilonoProductReel(true);
    }, remaining);

    rilonoReelProgressTimer = window.setInterval(updateRilonoReelProgress, RILONO_REEL_PROGRESS_INTERVAL_MS);
    updateRilonoReelProgress();
    syncRilonoReelControls();
}

function pauseRilonoProductReel(userInitiated = false) {
    if (rilonoReelSceneStartedAt) {
        rilonoReelPausedElapsed = Math.max(Date.now() - rilonoReelSceneStartedAt, 0);
    }
    updateRilonoReelProgress();
    stopRilonoProductReelTimers();
    rilonoReelIsPlaying = false;
    if (userInitiated) {
        rilonoReelUserPaused = true;
    }
    syncRilonoReelControls();
}

function resumeRilonoProductReelIfAllowed() {
    if (!rilonoReelInitialized || rilonoReelUserPaused || RILONO_REEL_PREFERS_REDUCED_MOTION) return;
    startRilonoProductReel(false);
}

function initializeRilonoProductReel() {
    const elements = getRilonoReelElements();
    if (!elements || rilonoReelInitialized) return;

    rilonoReelInitialized = true;
    setRilonoReelScene(0, false);
    syncRilonoReelControls();

    elements.dots.forEach((dot) => {
        dot.addEventListener('click', () => {
            const nextScene = Number.parseInt(dot.getAttribute('data-scene-target') || '0', 10);
            if (Number.isNaN(nextScene)) return;
            rilonoReelUserPaused = false;
            rilonoReelIsPlaying = true;
            setRilonoReelScene(nextScene, true);
        });
    });

    elements.playPauseBtn.addEventListener('click', () => {
        if (rilonoReelIsPlaying) {
            pauseRilonoProductReel(true);
            return;
        }
        rilonoReelUserPaused = false;
        startRilonoProductReel(false);
    });

    if (window.IntersectionObserver) {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (!entry.isIntersecting) {
                    pauseRilonoProductReel(false);
                    return;
                }
                const homepageSection = document.getElementById('homepageSection');
                if (homepageSection && homepageSection.style.display !== 'none') {
                    resumeRilonoProductReelIfAllowed();
                }
            });
        }, { threshold: 0.35 });
        observer.observe(elements.player);
    }

    if (RILONO_REEL_PREFERS_REDUCED_MOTION) {
        rilonoReelUserPaused = true;
        syncRilonoReelControls();
    }
}

/* --- Chrome Extension Player --- */
let chromeExtCurrentScene = 0;
let chromeExtTimer = null;
const CHROME_EXT_SCENE_DURATION_MS = 6500;
let chromeExtInitialized = false;

function getChromeExtElements() {
    const player = document.getElementById('chromeExtPlayer');
    if (!player) return null;
    const scenes = Array.from(player.querySelectorAll('.chrome-ext-scene'));
    if (!scenes.length) return null;
    return { player, scenes };
}

function stopChromeExtTimer() {
    if (chromeExtTimer) {
        clearTimeout(chromeExtTimer);
        chromeExtTimer = null;
    }
}

function setChromeExtScene(sceneIndex) {
    const elements = getChromeExtElements();
    if (!elements) return;

    const sceneCount = elements.scenes.length;
    chromeExtCurrentScene = ((sceneIndex % sceneCount) + sceneCount) % sceneCount;

    elements.scenes.forEach((scene, index) => {
        if (index === chromeExtCurrentScene) {
            // Force redraw to restart animations
            scene.style.display = 'none';
            void scene.offsetWidth;
            scene.style.display = '';
            scene.classList.add('is-active');
        } else {
            scene.classList.remove('is-active');
        }
    });
}

function startChromeExtPlayer() {
    const elements = getChromeExtElements();
    if (!elements) return;

    if (RILONO_REEL_PREFERS_REDUCED_MOTION) return;

    stopChromeExtTimer();

    chromeExtTimer = window.setTimeout(() => {
        const nextScene = (chromeExtCurrentScene + 1) % elements.scenes.length;
        setChromeExtScene(nextScene);
        startChromeExtPlayer();
    }, CHROME_EXT_SCENE_DURATION_MS);
}

function initChromeExtPlayer() {
    if (chromeExtInitialized) return;
    const elements = getChromeExtElements();
    if (!elements) return;

    chromeExtInitialized = true;
    setChromeExtScene(0);

    if (window.IntersectionObserver) {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    startChromeExtPlayer();
                } else {
                    stopChromeExtTimer();
                }
            });
        }, { threshold: 0.25 });
        observer.observe(elements.player);
    } else {
        startChromeExtPlayer();
    }
}

function showMessage(text, type = 'success') {
    const messageEl = document.getElementById('message');
    if (!messageEl) return;

    if (messageHideTimer) {
        clearTimeout(messageHideTimer);
        messageHideTimer = null;
    }

    messageEl.textContent = text;
    messageEl.className = `message ${type} show`;
    const hideDelayMs = type === 'error' ? 15000 : 10000;
    messageHideTimer = setTimeout(() => {
        messageEl.classList.remove('show');
        messageHideTimer = null;
    }, hideDelayMs);
}

/* ---------------- Post-login prompt queue ----------------
   Signing in shows a "Login successful" confirmation, and a brand-new account also has two
   one-time prompts: "How did you hear about us?" and the referral nudge. Firing them the instant
   the dashboard painted buried that confirmation AND opened both dialogs at once (the heard-about
   overlay landing on top of the referral modal). Anything that wants to interrupt the user right
   after login goes through this queue instead: it waits a beat so the confirmation can be read,
   then runs prompts strictly one at a time, each waiting for the previous to be dismissed.
   Outside of login it is a pass-through — the quiet period is zero and nothing else is pending. */
const POST_LOGIN_PROMPT_DELAY_MS = 2600;   // long enough to read the confirmation, short enough not to feel broken
const POST_LOGIN_PROMPT_MAX_WAIT_MS = 60000;
let postLoginQuietUntil = 0;
const postLoginPromptQueue = [];
let postLoginPromptDraining = false;

function holdPostLoginPrompts() {
    postLoginQuietUntil = Date.now() + POST_LOGIN_PROMPT_DELAY_MS;
}

function postLoginPromptSleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// Is something already claiming the screen? (The heard-about dialog removes its overlay node on
// close; the referral promo toggles display; the onboarding wizard is a full-screen opaque overlay
// that outranks both — z-index 11000 vs the promo's 10000 — so a prompt opened while it is up
// would be invisible underneath it.)
function postLoginPromptOnScreen() {
    if (document.getElementById('hauOverlay')) return true;
    if (document.getElementById('onboardingOverlay')) return true;
    const promo = document.getElementById('referralPromoModal');
    return !!(promo && promo.style.display && promo.style.display !== 'none');
}

function queuePostLoginPrompt(run) {
    postLoginPromptQueue.push(run);
    void drainPostLoginPrompts();
}

async function drainPostLoginPrompts() {
    if (postLoginPromptDraining) return;
    postLoginPromptDraining = true;
    try {
        const quietFor = postLoginQuietUntil - Date.now();
        if (quietFor > 0) await postLoginPromptSleep(quietFor);
        while (postLoginPromptQueue.length) {
            // Never open on top of something else — checked BEFORE opening, so this also covers a
            // dialog that was already up when we started (the onboarding wizard). If the user
            // simply leaves that open, stop draining and leave the rest QUEUED rather than firing
            // into an overlay they can't see: whatever closes it re-renders the dashboard, which
            // queues again and restarts the drain.
            const deadline = Date.now() + POST_LOGIN_PROMPT_MAX_WAIT_MS;
            while (postLoginPromptOnScreen()) {
                if (Date.now() > deadline) return;
                await postLoginPromptSleep(300);
            }
            const run = postLoginPromptQueue.shift();
            try { await run(); } catch (e) { /* one bad prompt must not stall the rest */ }
        }
    } finally {
        postLoginPromptDraining = false;
    }
}

// Navigation
function showHomepage(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('homepageSection').style.display = 'block';
    const pageContainer = document.querySelector('.container');
    if (pageContainer) {
        pageContainer.classList.add('homepage-layout');
    }
    // Update button visibility based on auth status
    const heroRegisterBtn = document.getElementById('heroRegisterBtn');
    const heroLoginBtn = document.getElementById('heroLoginBtn');
    const heroDashboardBtn = document.getElementById('heroDashboardBtn');
    const reelRegisterBtn = document.getElementById('reelRegisterBtn');
    const reelDashboardBtn = document.getElementById('reelDashboardBtn');
    const ctaRegisterBtn = document.getElementById('ctaRegisterBtn');
    const ctaDashboardBtn = document.getElementById('ctaDashboardBtn');

    if (currentUser) {
        // Logged in: show dashboard buttons, hide login/register
        if (heroRegisterBtn) heroRegisterBtn.style.display = 'none';
        if (heroLoginBtn) heroLoginBtn.style.display = 'none';
        if (heroDashboardBtn) heroDashboardBtn.style.display = 'inline-flex';
        if (reelRegisterBtn) reelRegisterBtn.style.display = 'none';
        if (reelDashboardBtn) reelDashboardBtn.style.display = 'inline-flex';
        if (ctaRegisterBtn) ctaRegisterBtn.style.display = 'none';
        if (ctaDashboardBtn) ctaDashboardBtn.style.display = 'inline-flex';
    } else {
        // Logged out: show login/register, hide dashboard
        if (heroRegisterBtn) heroRegisterBtn.style.display = 'inline-flex';
        if (heroLoginBtn) heroLoginBtn.style.display = 'inline-flex';
        if (heroDashboardBtn) heroDashboardBtn.style.display = 'none';
        if (reelRegisterBtn) reelRegisterBtn.style.display = 'inline-flex';
        if (reelDashboardBtn) reelDashboardBtn.style.display = 'none';
        if (ctaRegisterBtn) ctaRegisterBtn.style.display = 'inline-flex';
        if (ctaDashboardBtn) ctaDashboardBtn.style.display = 'none';
    }

    window.scrollTo({ top: 0, behavior: 'auto' });

    resumeRilonoProductReelIfAllowed();

    if (!skipURLUpdate) {
        updateURL('/', false); // Use pushState for navigation
    }
}

function showLogin(skipURLUpdate = false) {
    if (currentUser) {
        showDashboard(true);
        const dashboardURL = `${window.location.origin}/dashboard`;
        if (skipURLUpdate || isNavigating) {
            window.history.replaceState({ path: '/dashboard' }, '', dashboardURL);
        } else {
            updateURL('/dashboard', false);
        }
        return;
    }

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
    const forgotPasswordEmailInput = document.getElementById('forgotPasswordEmail');
    const emailFromQuery = new URLSearchParams(window.location.search).get('email');
    if (forgotPasswordEmailInput && emailFromQuery && !forgotPasswordEmailInput.value) {
        forgotPasswordEmailInput.value = emailFromQuery.trim();
    }
    const forgotWidget = document.getElementById('turnstile-forgot-password');
    renderAuthTurnstileWidget(forgotWidget, 'forgotPassword');
    if (!skipURLUpdate) {
        updateURL('/forgot-password', false);
    }
}

function showResetPassword(token, skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('resetPasswordSection').style.display = 'block';
    document.getElementById('resetToken').value = token;
    updateResetPasswordHint();
    const resetWidget = document.getElementById('turnstile-reset-password');
    renderAuthTurnstileWidget(resetWidget, 'resetPassword');
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
        const resetWidget = document.getElementById('turnstile-reset-password');
        renderAuthTurnstileWidget(resetWidget, 'resetPassword');
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

    // Always start on Step 1 (a prior OTP step may still be showing).
    backToRegisterStep1();

    // Clear university field and validation message when showing register form
    const universityInput = document.getElementById('registerUniversity');
    const messageEl = document.getElementById('emailValidationMessage');
    const referralInput = document.getElementById('registerReferralCode');
    const countryInput = document.getElementById('registerCountry');
    const consentInput = document.getElementById('registerConsent');
    if (universityInput) universityInput.value = '';
    if (messageEl) messageEl.style.display = 'none';
    if (countryInput) countryInput.value = '';   // no pre-selected country — it must be a real answer
    if (referralInput) {
        referralInput.value = getReferralCodeFromURL() || '';
    }
    if (consentInput) consentInput.checked = false;
    const marketingConsentInput = document.getElementById('registerMarketingConsent');
    if (marketingConsentInput) marketingConsentInput.checked = false;
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
                <button onclick="resendVerificationEmailFromButton(this)" data-email="${escapeHtml(email)}" class="btn btn-primary">Resend Verification Email</button>
                <p style="margin-top: 1rem;">
                    <a href="#" onclick="showLogin(); return false;">Back to Login</a>
                </p>
            </div>
        `;
    }
    updateURL('/verify-email', false);
}

function resendVerificationEmailFromButton(buttonEl) {
    const email = buttonEl?.dataset?.email || '';
    resendVerificationEmail(email);
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
        email = await promptDialog('Please enter your email address:', { title: 'Your email address', type: 'email', placeholder: 'you@example.com', okText: 'Continue' });
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


function showCreateItem(skipURLUpdate = false) {
    showDashboard(skipURLUpdate);
}

function showMyListings(skipURLUpdate = false) {
    showDashboard(skipURLUpdate);
}

function showMessages(skipURLUpdate = false) {
    showDashboard(skipURLUpdate);
}

// ===========================================================================
// Onboarding wizard — runs once after sign-up/login. Destination country + visa
// type are required (they drive the personalized journey); the rest is optional.
// ===========================================================================
let _onboardingCatalog = null;

function needsOnboarding() {
    return Boolean(currentUser && authToken && !currentUser.onboarding_completed_at);
}

function closeOnboardingWizard() {
    const overlay = document.getElementById('onboardingOverlay');
    if (overlay) overlay.remove();
    document.body.style.overflow = '';
}

async function showOnboardingWizard() {
    if (document.getElementById('onboardingOverlay')) return;
    const overlay = document.createElement('div');
    overlay.id = 'onboardingOverlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.style.cssText = 'position:fixed;inset:0;z-index:11000;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(5,6,15,.80);backdrop-filter:blur(6px);overflow-y:auto;';
    overlay.innerHTML = `
      <style>
        #onboardingOverlay summary { list-style:none; display:inline-flex; align-items:center; gap:7px; cursor:pointer; color:#4f46e5; font-size:13px; font-weight:700; padding:7px 9px; margin-left:-9px; border-radius:9px; user-select:none; transition:background .15s ease; }
        #onboardingOverlay summary::-webkit-details-marker { display:none; }
        #onboardingOverlay summary:hover { background:rgba(99,102,241,.09); }
        #onboardingOverlay .onb-chev { width:13px; height:13px; flex:none; transition:transform .2s ease; }
        #onboardingOverlay details[open] .onb-chev { transform:rotate(90deg); }
      </style>
      <div style="width:min(560px,100%);background:#ffffff;border:1px solid #e2e8f0;border-radius:20px;box-shadow:0 30px 90px rgba(0,0,0,.6);overflow:hidden;color:#0f172a">
        <div style="padding:26px 28px 8px">
          <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#64748b;font-weight:700">Welcome to Rilono</div>
          <h2 style="margin:8px 0 4px;font-size:24px;font-weight:800;color:#0f172a">Let's personalize your study-abroad journey</h2>
          <p style="margin:0;font-size:14px;color:#64748b">Tell us where you're headed. You can change this anytime in settings.</p>
        </div>
        <div id="onbBody" style="padding:18px 28px 4px">
          <div style="text-align:center;color:#64748b;padding:30px 0">Loading options…</div>
        </div>
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:16px 28px 24px">
          <span id="onbError" style="font-size:13px;color:#be123c;min-height:18px"></span>
          <button id="onbSubmit" disabled style="border:none;border-radius:12px;padding:12px 24px;font-size:15px;font-weight:700;color:#94a3b8;background:#e2e8f0;cursor:not-allowed;box-shadow:none;transition:background .2s ease,box-shadow .2s ease,color .2s ease,transform .12s ease">Continue to dashboard</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';
    try {
        if (!_onboardingCatalog) {
            const r = await fetch(`${API_BASE}/api/onboarding/catalog`, { credentials: 'same-origin' });
            _onboardingCatalog = await r.json();
        }
        renderOnboardingForm();
    } catch (e) {
        const b = document.getElementById('onbBody');
        if (b) b.innerHTML = '<div style="color:#be123c;padding:20px 0">Could not load options. Please refresh and try again.</div>';
    }
}

function renderOnboardingForm() {
    const countries = (_onboardingCatalog && _onboardingCatalog.countries) || [];
    const body = document.getElementById('onbBody');
    if (!body) return;
    const lbl = (t) => `<div style="font-size:12px;font-weight:700;color:#64748b;margin:0 0 6px">${t}</div>`;
    const inp = 'width:100%;box-sizing:border-box;background:#ffffff;border:1px solid #e2e8f0;border-radius:11px;color:#0f172a;font-size:14px;padding:11px 12px';
    const countryOpts = countries.map((c) => `<option value="${escapeHtml(c.code)}">${(c.flag_emoji || '')} ${escapeHtml(c.name)}</option>`).join('');
    body.innerHTML = `
      <div style="margin-bottom:14px">${lbl('Destination country <span style=\"color:#be123c\">*</span>')}
        <select id="onbCountry" style="${inp}"><option value="">Select a country…</option>${countryOpts}</select></div>
      <div style="margin-bottom:14px">${lbl('Visa type <span style=\"color:#be123c\">*</span>')}
        <select id="onbVisa" style="${inp}" disabled><option value="">Select a country first…</option></select></div>
      <div style="margin-bottom:14px">${lbl('Home country <span style=\"color:#be123c\">*</span>')}
        <select id="onbHome" style="${inp}">${residenceCountryOptions((currentUser && currentUser.current_residence_country) || '')}</select></div>
      <details style="margin:6px 0 4px"><summary><svg class="onb-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 6 15 12 9 18"></polyline></svg>Add more details <span style="color:#94a3b8;font-weight:600">(optional)</span></summary>
        <div style="margin-top:12px;display:grid;gap:12px">
          <div>${lbl('Target university')}<input id="onbUni" placeholder="e.g. University of Toronto" style="${inp}"></div>
          <div>${lbl('University email')}<input id="onbUniEmail" type="email" placeholder="you@university.edu" style="${inp}"></div>
          <div>${lbl('Intake')}<select id="onbIntake" style="${inp}"><option value="">Select intake…</option></select></div>
        </div></details>`;
    const countrySel = document.getElementById('onbCountry');
    const visaSel = document.getElementById('onbVisa');
    const intakeSel = document.getElementById('onbIntake');
    const submit = document.getElementById('onbSubmit');
    const homeSel = document.getElementById('onbHome');
    if (homeSel) homeSel.addEventListener('change', () => updateSubmit());
    const updateSubmit = () => {
        const ok = Boolean(countrySel.value && visaSel.value && homeSel && homeSel.value);
        submit.disabled = !ok;
        // Disabled → a clean solid grey (clearly "pick a country first"), not a faded
        // gradient that reads as broken. Enabled → the vibrant gradient lights up.
        submit.style.cursor = ok ? 'pointer' : 'not-allowed';
        submit.style.color = ok ? '#fff' : '#94a3b8';
        submit.style.background = ok ? 'linear-gradient(135deg,#6366f1,#a855f7)' : '#e2e8f0';
        submit.style.boxShadow = ok ? '0 10px 24px rgba(99,102,241,.35)' : 'none';
        if (!ok) submit.style.transform = 'none';
    };
    countrySel.addEventListener('change', () => {
        const c = countries.find((x) => x.code === countrySel.value);
        if (!c) {
            visaSel.innerHTML = '<option value="">Select a country first…</option>';
            visaSel.disabled = true;
            intakeSel.innerHTML = '<option value="">Select intake…</option>';
        } else {
            visaSel.innerHTML = c.visa_types.map((v) => `<option value="${escapeHtml(v.key)}"${v.default ? ' selected' : ''}>${escapeHtml(v.label)}</option>`).join('');
            visaSel.disabled = false;
            intakeSel.innerHTML = '<option value="">Select intake…</option>' + (c.intakes || []).map((i) => `<option value="${escapeHtml(i)}">${escapeHtml(i)}</option>`).join('');
        }
        updateSubmit();
    });
    visaSel.addEventListener('change', updateSubmit);
    submit.addEventListener('click', submitOnboarding);
    submit.addEventListener('mouseenter', () => { if (!submit.disabled) submit.style.transform = 'translateY(-1px)'; });
    submit.addEventListener('mouseleave', () => { submit.style.transform = 'none'; });
    updateSubmit();
}

async function submitOnboarding() {
    const errEl = document.getElementById('onbError');
    const submit = document.getElementById('onbSubmit');
    const country = (document.getElementById('onbCountry') || {}).value || '';
    const visa = (document.getElementById('onbVisa') || {}).value || '';
    const home = (document.getElementById('onbHome') || {}).value || '';
    if (!country || !visa) { if (errEl) errEl.textContent = 'Please choose a country and visa type.'; return; }
    if (!home) { if (errEl) errEl.textContent = 'Please select your home country.'; return; }
    const val = (id) => ((document.getElementById(id) || {}).value || '').trim() || null;
    const payload = {
        destination_country_code: country,
        visa_type_key: visa,
        home_country: val('onbHome'),
        university: val('onbUni'),
        university_email: val('onbUniEmail'),
        intake: val('onbIntake'),
    };
    if (errEl) errEl.textContent = '';
    if (submit) { submit.disabled = true; submit.textContent = 'Saving…'; }
    try {
        const headers = { 'Content-Type': 'application/json' };
        if (authToken && authToken !== COOKIE_AUTH_SENTINEL) headers['Authorization'] = `Bearer ${authToken}`;
        const res = await fetch(`${API_BASE}/api/onboarding`, { method: 'POST', headers, credentials: 'same-origin', body: JSON.stringify(payload) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            if (errEl) errEl.textContent = (data && (data.detail || data.message)) || 'Could not save. Please try again.';
            if (submit) { submit.disabled = false; submit.textContent = 'Continue to dashboard'; }
            return;
        }
        currentUser = data;
        closeOnboardingWizard();
        const scope = currentUserVisaScope();
        if (scope) { try { await initializeDocumentCatalog(scope); } catch (e) { /* keep default */ } }
        showDashboard();
    } catch (e) {
        if (errEl) errEl.textContent = 'Network error. Please try again.';
        if (submit) { submit.disabled = false; submit.textContent = 'Continue to dashboard'; }
    }
}

// ===========================================================================
// ===================== AI request reliability =====================
// AI calls (chat, prep/mock interview, SOP, university recs) can take 10-40s on the premium
// model. Two safeguards so a slow network or backend hiccup never leaves the user staring at
// a spinner forever, unsure whether it's working or has silently died:
//   aiFetch()         — fetch with an abort timeout; a hang becomes a clear, catchable error
//                       the existing per-handler catch/finally already recovers from.
//   startAiProgress() — escalating "still working (Ns)…" text so long waits feel alive.
const AI_FETCH_TIMEOUT_MS = 75000; // generous: only fires on a genuine hang, not a slow-but-working call

async function aiFetch(url, options = {}, timeoutMs = AI_FETCH_TIMEOUT_MS) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        return await fetch(url, { ...options, signal: controller.signal });
    } catch (err) {
        if (err && err.name === 'AbortError') {
            const e = new Error('Rilono AI is taking longer than usual — please check your connection and try again.');
            e.isTimeout = true;
            throw e;
        }
        const e = new Error("Couldn't reach Rilono AI. Check your connection and try again.");
        e.isNetwork = true;
        throw e;
    } finally {
        clearTimeout(timer);
    }
}

// Drives a text setter with an escalating, elapsed-time message. Returns { stop() }.
function startAiProgress(setText, baseLabel) {
    const started = Date.now();
    const tick = () => {
        const s = Math.round((Date.now() - started) / 1000);
        let text;
        if (s < 6) text = baseLabel;
        else if (s < 18) text = `${baseLabel} · ${s}s`;
        else if (s < 35) text = `Still working — almost there… ${s}s`;
        else text = `Hang tight, Rilono AI is finishing up… ${s}s`;
        try { setText(text); } catch (e) { /* element gone */ }
    };
    tick();
    const id = setInterval(tick, 1000);
    return { stop() { clearInterval(id); } };
}

// ===================== SOP Studio (Application Kit) =====================
// Personalized SOP / Motivation-letter generator: country + university + program
// specific, grounded in the student's profile + documents, iteratively refinable.
let _sopData = { entitlement: null, doc_name: 'Statement of Purpose', drafts: [], activeRoot: null, busy: false };

const SOP_REFINE_CHIPS = [
    'Make it more technical',
    'Tie it more strongly to my work experience',
    'Make the tone more formal',
    'Shorten it toward the lower word limit',
    'Strengthen the closing career goal',
];

// Human-readable error for SOP API failures. The app itself accepts any characters
// (verified: script tags / SQL-looking text generate fine and are stored safely), but the
// CDN's security filter (WAF) can block request BODIES that look like code injection —
// returning an HTML error page with no JSON detail. Without this, that surfaced as a
// bare "Generation failed" with no hint that the INPUT was the problem.
function sopErrorMessage(r, data, fallback) {
    const detail = data && data.detail;
    if (typeof detail === 'string' && detail) return detail;
    if (Array.isArray(detail) && detail.length) {
        const first = detail[0];
        if (first && first.msg) return `${first.msg}${first.loc ? ` (${first.loc[first.loc.length - 1]})` : ''}`;
    }
    if (!detail) {
        // Rate-limited at the edge — distinct, actionable message (not a "bad input" one).
        if (r.status === 429) return 'Too many requests right now — please wait a moment and try again.';
        // WAF/security filter blocked the request body (verified in prod: 403; some filters use
        // 400/406). It returns an HTML page with no JSON detail, so tell the user their INPUT was
        // the problem instead of surfacing a bare "Generation failed".
        if (r.status === 403 || r.status === 400 || r.status === 406) {
            return 'Our security layer blocked this request — that can happen when a field contains code-like text (e.g. "<script>" tags or quotes with semicolons). Please rewrite those characters and try again.';
        }
    }
    return fallback;
}

function sopAuthHeaders(extra) {
    const headers = Object.assign({}, extra || {});
    if (authToken && authToken !== COOKIE_AUTH_SENTINEL) headers['Authorization'] = `Bearer ${authToken}`;
    return headers;
}

function sopMarkdownToHtml(md) {
    // Minimal, safe renderer: escape everything first, then re-introduce structure.
    const esc = escapeHtml(String(md || ''));
    return esc.split(/\n{2,}/).map((block) => {
        const b = block.trim();
        if (!b) return '';
        if (b.startsWith('# ')) return `<h3 style="margin:0 0 4px;font-size:1.05rem">${b.slice(2)}</h3>`;
        if (/^-{3,}$/.test(b)) return '<hr style="border:0;border-top:1px dashed var(--border-color,#e2e8f0);margin:14px 0">';
        return `<p style="margin:0 0 12px;line-height:1.75">${b.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/\n/g, '<br>')}</p>`;
    }).join('');
}

function sopPlainText(md) {
    return String(md || '').replace(/^# /gm, '').replace(/\*\*/g, '');
}

async function loadSopStudio() {
    const el = document.getElementById('sopContent');
    if (!el) return;
    try {
        const r = await fetch(`${API_BASE}/api/sop/status`, { headers: sopAuthHeaders(), credentials: 'include' });
        if (!r.ok) throw new Error('status ' + r.status);
        const data = await r.json();
        _sopData.entitlement = data.entitlement;
        _sopData.doc_name = data.doc_name || 'Statement of Purpose';
        _sopData.drafts = data.drafts || [];
        if (_sopData.activeRoot == null && _sopData.drafts.length) _sopData.activeRoot = _sopData.drafts[0].root_id;
    } catch (e) {
        el.innerHTML = '<div style="padding:2rem;color:var(--text-secondary,#9a9cb0)">Could not load SOP Studio. Please refresh.</div>';
        return;
    }
    const title = document.getElementById('sopTabTitle');
    if (title) title.textContent = `✍️ ${_sopData.doc_name === 'Motivationsschreiben (Letter of Motivation)' ? 'Motivation Letter Studio' : 'SOP Studio'}`;
    const sub = document.getElementById('sopTabSubtitle');
    if (sub) sub.textContent = `Rilono AI drafts your ${_sopData.doc_name} from your real profile and documents — then refines it with you, line by line.`;
    renderSopStudio();
}

function sopQuotaChip() {
    const ent = _sopData.entitlement || {};
    if (ent.unlimited) return '<span style="font-size:12px;font-weight:700;color:#065f46">Visa Success Pass · unlimited</span>';
    const left = Math.max(0, ent.remaining ?? 0);
    return `<span style="font-size:12px;font-weight:700;color:${left > 0 ? '#065f46' : '#b45309'}">${left} free ${left === 1 ? 'action' : 'actions'} left</span>`;
}

function renderSopStudio() {
    const el = document.getElementById('sopContent');
    if (!el) return;
    const docName = _sopData.doc_name;
    const uniPrefill = escapeHtml(currentUser?.university || '');
    const drafts = _sopData.drafts;
    const active = drafts.find((d) => d.root_id === _sopData.activeRoot) || drafts[0] || null;

    // Destination-appropriate intake example (an AU student applies for "February 2027",
    // not "Fall 2026 / Winter Semester").
    const sopIntakeCode = (currentUser && currentUser.destination_country_code) || 'US';
    const sopIntakeNames = DOCUMENTATION_INTAKES[sopIntakeCode] || DOCUMENTATION_INTAKES.US;
    const sopIntakeExample = `e.g. ${sopIntakeNames[0]} ${new Date().getFullYear() + 1}`;
    const formCard = `
      <div class="dashboard-widget" style="margin-bottom:16px">
        <div class="widget-header" style="display:flex;align-items:center;justify-content:space-between;gap:10px">
          <h3>📝 New ${escapeHtml(docName)}</h3>${sopQuotaChip()}
        </div>
        <div class="widget-content">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
            <div><label style="font-size:12px;font-weight:700">University *</label>
              <input id="sopUniversity" type="text" value="${uniPrefill}" placeholder="e.g. TU Darmstadt" style="width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid var(--border-color,#e2e8f0);border-radius:10px"></div>
            <div><label style="font-size:12px;font-weight:700">Program *</label>
              <input id="sopProgram" type="text" placeholder="e.g. M.Sc. Computer Science" style="width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid var(--border-color,#e2e8f0);border-radius:10px"></div>
            <div><label style="font-size:12px;font-weight:700">Study level</label>
              <select id="sopLevel" style="width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid var(--border-color,#e2e8f0);border-radius:10px">
                <option value="">Select…</option><option>Bachelor's</option><option selected>Master's</option><option>PhD</option><option>Diploma / Other</option>
              </select></div>
            <div><label style="font-size:12px;font-weight:700">Intake</label>
              <input id="sopIntake" type="text" placeholder="${escapeHtml(sopIntakeExample)}" style="width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid var(--border-color,#e2e8f0);border-radius:10px"></div>
          </div>
          <div style="margin-top:12px"><label style="font-size:12px;font-weight:700">What should it emphasize? (optional)</label>
            <textarea id="sopHighlights" rows="2" placeholder="e.g. my fintech internship, 8.4 CGPA, the ML project on fraud detection" style="width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid var(--border-color,#e2e8f0);border-radius:10px"></textarea></div>
          <div style="margin-top:12px;display:flex;align-items:center;gap:12px">
            <button id="sopGenerateBtn" class="btn btn-primary" onclick="generateSop()">Draft my ${escapeHtml(docName.split(' (')[0])}</button>
            <span id="sopFormMsg" style="font-size:12.5px;color:var(--text-secondary,#64748b)"></span>
          </div>
        </div>
      </div>`;

    let draftCard = '';
    if (active) {
        const versionNote = active.version > 1 ? ` · v${active.version}` : '';
        const others = drafts.filter((d) => (d.root_id || d.id) !== (active.root_id || active.id));
        const switcher = others.length ? `
          <select onchange="_sopData.activeRoot=parseInt(this.value,10);renderSopStudio()" style="padding:6px 10px;border:1px solid var(--border-color,#e2e8f0);border-radius:8px;font-size:12.5px">
            ${drafts.map((d) => `<option value="${d.root_id}" ${d.root_id === active.root_id ? 'selected' : ''}>${escapeHtml(d.university)} — ${escapeHtml(d.program)}</option>`).join('')}
          </select>` : '';
        draftCard = `
          <div class="dashboard-widget">
            <div class="widget-header" style="display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap">
              <h3>📄 ${escapeHtml(active.university)} — ${escapeHtml(active.program)}${versionNote}</h3>
              <div style="display:flex;align-items:center;gap:8px">${switcher}
                <button class="btn btn-secondary" style="padding:6px 12px;font-size:12.5px" onclick="copySopDraft()">Copy</button>
                <button class="btn btn-secondary" style="padding:6px 12px;font-size:12.5px" onclick="downloadSopDraft()">Download</button>
                <button class="btn btn-secondary" style="padding:6px 12px;font-size:12.5px;color:#ef4444" onclick="deleteSopDraft()">Delete</button>
              </div>
            </div>
            <div class="widget-content">
              <div style="font-size:12px;color:var(--text-secondary,#64748b);margin-bottom:10px">${active.word_count} words · ${escapeHtml(active.doc_name)}${active.instruction ? ` · last edit: “${escapeHtml(active.instruction)}”` : ''}</div>
              <div id="sopDraftBody" style="background:var(--card-bg,#fff);border:1px solid var(--border-color,#e2e8f0);border-radius:12px;padding:18px 20px;max-height:520px;overflow-y:auto">${sopMarkdownToHtml(active.content_md)}</div>
              <div style="margin-top:14px">
                <label style="font-size:12px;font-weight:700">Refine this draft</label>
                <div style="display:flex;gap:8px;flex-wrap:wrap;margin:8px 0">
                  ${SOP_REFINE_CHIPS.map((c) => `<button class="btn btn-secondary" style="padding:5px 11px;font-size:12px;border-radius:999px" onclick="refineSop('${c.replace(/'/g, "\\'")}')">${c}</button>`).join('')}
                </div>
                <div style="display:flex;gap:8px">
                  <input id="sopRefineInput" type="text" placeholder='Or type your own — e.g. "tie the second paragraph to my internship"' style="flex:1;box-sizing:border-box;padding:10px 12px;border:1px solid var(--border-color,#e2e8f0);border-radius:10px"
                    onkeydown="if(event.key==='Enter'){refineSop();}">
                  <button class="btn btn-primary" onclick="refineSop()">Refine</button>
                </div>
                <div id="sopRefineMsg" style="font-size:12.5px;color:var(--text-secondary,#64748b);margin-top:6px"></div>
              </div>
            </div>
          </div>`;
    }

    const ent = _sopData.entitlement || {};
    const paywall = (!ent.unlimited && (ent.remaining ?? 0) <= 0) ? `
      <div class="copilot-upgrade-prompt" style="display:block;margin-bottom:16px">
        <p class="copilot-upgrade-title">You've used your free ${escapeHtml(docName)} actions</p>
        <p class="copilot-upgrade-copy">Get the Visa Success Pass for unlimited drafts and refinements — polish it until it's perfect.</p>
        <div class="visa-hub-actions copilot-upgrade-actions">
          <button type="button" class="btn btn-primary" onclick="handleUpgradeToPro('sop_studio')">Get the Visa Success Pass</button>
        </div>
      </div>` : '';

    el.innerHTML = paywall + formCard + draftCard;
    attachUniversityAutocomplete(document.getElementById('sopUniversity'));
}

// Reusable university typeahead: as the student types, suggest universities from our
// registry for THEIR destination country (GET /api/shortlist/universities). Used by the
// SOP Studio form and the manual shortlist-add field.
function _ensureUniAutocompleteStyles() {
    if (document.getElementById('uniAcStyles')) return;
    const s = document.createElement('style');
    s.id = 'uniAcStyles';
    s.textContent = `
      .uni-ac-menu { position:absolute; left:0; right:0; top:calc(100% + 4px); z-index:60; background:var(--card-bg,#fff);
        border:1px solid var(--border-color,#e2e8f0); border-radius:12px; box-shadow:0 18px 44px rgba(15,23,42,.16);
        overflow:hidden; max-height:280px; overflow-y:auto; }
      .uni-ac-item { display:flex; flex-direction:column; gap:1px; padding:9px 13px; cursor:pointer; border-bottom:1px solid rgba(148,163,184,.14); }
      .uni-ac-item:last-child { border-bottom:0; }
      .uni-ac-item.active, .uni-ac-item:hover { background:rgba(99,102,241,.09); }
      .uni-ac-name { font-size:13.5px; font-weight:600; color:var(--text-primary,#0f172a); }
      .uni-ac-loc { font-size:11.5px; color:var(--text-secondary,#64748b); }
      .uni-ac-empty { padding:10px 13px; font-size:12.5px; color:var(--text-secondary,#94a3b8); }`;
    document.head.appendChild(s);
}

function attachUniversityAutocomplete(input) {
    if (!input || input._uniAcAttached) return;
    input._uniAcAttached = true;
    _ensureUniAutocompleteStyles();
    const wrap = input.parentElement;
    if (wrap && getComputedStyle(wrap).position === 'static') wrap.style.position = 'relative';
    input.setAttribute('autocomplete', 'off');
    let items = [], active = -1, box = null, timer = null, reqSeq = 0;

    // A pre-filled value (the student's saved university) must be REPLACED — not appended to —
    // the moment the user edits, or the field becomes "The University of WarwickThe University of
    // Warwick" and that garbage gets sent to ?q=. select()-on-focus alone is unreliable for mouse
    // users: the click fires focus (select-all) and then mouseup collapses the selection back to a
    // caret at the end, so typing appends. So we ALSO clear the still-untouched pre-fill on the
    // first keystroke/paste — which needs no selection to survive mouseup.
    const initialValue = input.value;
    let prefillConsumed = !initialValue;
    input.addEventListener('focus', () => {
        if (!prefillConsumed && input.value === initialValue) input.select(); // keyboard/Tab focus
    });
    const consumePrefillOnEdit = () => {
        if (prefillConsumed) return;
        prefillConsumed = true;
        if (input.value !== initialValue) return;            // already diverged from the pre-fill
        const fullySelected = input.selectionStart === 0 && input.selectionEnd === input.value.length;
        if (!fullySelected) input.value = '';                // caret mid/end → clear so the edit replaces
    };
    input.addEventListener('keydown', (e) => {
        if (e.key && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) consumePrefillOnEdit();
    });
    input.addEventListener('paste', consumePrefillOnEdit);

    const close = () => { if (box) { box.remove(); box = null; } active = -1; };
    const pick = (i) => {
        if (i < 0 || i >= items.length) return;
        input.value = items[i].name;
        prefillConsumed = true;
        close();
        input.dispatchEvent(new Event('change'));
        // Advance to the program field reliably — a synchronous focus() inside the menu's
        // mousedown handler is flaky, which let subsequent typing land back in this field.
        const program = document.getElementById('sopProgram');
        if (program && !program.value) setTimeout(() => program.focus(), 0);
    };
    const paint = () => {
        if (!box) return;
        box.innerHTML = items.map((it, i) =>
            `<div class="uni-ac-item${i === active ? ' active' : ''}" data-i="${i}">
               <span class="uni-ac-name">${escapeHtml(it.name)}</span>${it.location ? `<span class="uni-ac-loc">${escapeHtml(it.location)}</span>` : ''}
             </div>`).join('');
        box.querySelectorAll('.uni-ac-item').forEach((el) => {
            el.addEventListener('mousedown', (e) => { e.preventDefault(); pick(parseInt(el.dataset.i, 10)); });
        });
    };
    const open = () => {
        if (!items.length) { close(); return; }
        if (!box) { box = document.createElement('div'); box.className = 'uni-ac-menu'; (wrap || input.parentElement).appendChild(box); }
        active = -1;
        paint();
    };
    const search = async (q) => {
        const mySeq = ++reqSeq;
        try {
            const r = await fetch(`${API_BASE}/api/shortlist/universities?q=${encodeURIComponent(q)}`,
                { headers: sopAuthHeaders(), credentials: 'include' });
            if (mySeq !== reqSeq || input.value.trim() !== q) return; // stale response
            if (!r.ok) { close(); return; }
            const data = await r.json();
            items = (data && data.results) || [];
            open();
        } catch (e) { /* network hiccup — just don't show suggestions */ close(); }
    };
    input.addEventListener('input', () => {
        const q = input.value.trim();
        clearTimeout(timer);
        if (q.length < 2) { close(); return; }
        timer = setTimeout(() => search(q), 180);
    });
    input.addEventListener('keydown', (e) => {
        if (!box || !items.length) return;
        if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(items.length - 1, active + 1); paint(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(0, active - 1); paint(); }
        else if (e.key === 'Enter') { if (active >= 0) { e.preventDefault(); pick(active); } }
        else if (e.key === 'Escape') { close(); }
    });
    input.addEventListener('blur', () => setTimeout(close, 150));
}

async function generateSop() {
    if (_sopData.busy) return;
    const university = (document.getElementById('sopUniversity')?.value || '').trim();
    const program = (document.getElementById('sopProgram')?.value || '').trim();
    const msg = document.getElementById('sopFormMsg');
    if (university.length < 2 || program.length < 2) {
        if (msg) msg.textContent = 'Please fill in the university and program.';
        return;
    }
    if (msg) msg.textContent = '';   // validation passed — clear any lingering "please fill in…" hint
    const btn = document.getElementById('sopGenerateBtn');
    _sopData.busy = true;
    if (btn) btn.disabled = true;
    const progress = startAiProgress((t) => { if (btn) btn.textContent = t; }, 'Rilono AI is drafting your statement…');
    try {
        const r = await aiFetch(`${API_BASE}/api/sop/generate`, {
            method: 'POST', credentials: 'include',
            headers: sopAuthHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({
                university, program,
                study_level: document.getElementById('sopLevel')?.value || null,
                intake: (document.getElementById('sopIntake')?.value || '').trim() || null,
                highlights: (document.getElementById('sopHighlights')?.value || '').trim() || null,
            }),
        });
        const data = await r.json().catch(() => ({}));
        if (r.status === 402) { _sopData.entitlement = { ...( _sopData.entitlement || {}), remaining: 0 }; renderSopStudio(); showMessage(data.detail || 'Free limit reached — unlock the Visa Success Pass.', 'error'); return; }
        if (!r.ok) throw new Error(sopErrorMessage(r, data, 'Generation failed'));
        _sopData.entitlement = data.entitlement;
        _sopData.drafts = [data.draft, ..._sopData.drafts.filter((d) => d.root_id !== data.draft.root_id)];
        _sopData.activeRoot = data.draft.root_id;
        renderSopStudio();
        showMessage('Your draft is ready — read it, then refine it below.', 'success');
    } catch (e) {
        showMessage(e.message || 'Could not draft your statement. Please try again.', 'error');
        renderSopStudio();
    } finally {
        progress.stop();
        _sopData.busy = false;
    }
}

async function refineSop(preset) {
    if (_sopData.busy) return;
    const active = _sopData.drafts.find((d) => d.root_id === _sopData.activeRoot);
    if (!active) return;
    const instruction = (preset || document.getElementById('sopRefineInput')?.value || '').trim();
    const msg = document.getElementById('sopRefineMsg');
    if (instruction.length < 3) { if (msg) msg.textContent = 'Tell Rilono AI what to change.'; return; }
    _sopData.busy = true;
    const progress = startAiProgress((t) => { if (msg) msg.textContent = t; }, `Applying “${instruction}”…`);
    try {
        const r = await aiFetch(`${API_BASE}/api/sop/refine`, {
            method: 'POST', credentials: 'include',
            headers: sopAuthHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ root_id: active.root_id, instruction }),
        });
        const data = await r.json().catch(() => ({}));
        if (r.status === 402) { _sopData.entitlement = { ...( _sopData.entitlement || {}), remaining: 0 }; renderSopStudio(); showMessage(data.detail || 'Free limit reached — unlock the Visa Success Pass.', 'error'); return; }
        if (!r.ok) throw new Error(sopErrorMessage(r, data, 'Refinement failed'));
        _sopData.entitlement = data.entitlement;
        _sopData.drafts = [data.draft, ..._sopData.drafts.filter((d) => d.root_id !== data.draft.root_id)];
        renderSopStudio();
        showMessage(`Updated to v${data.draft.version}.`, 'success');
    } catch (e) {
        showMessage(e.message || 'Could not revise the draft. Please try again.', 'error');
        if (msg) msg.textContent = '';
    } finally {
        progress.stop();
        _sopData.busy = false;
    }
}

function copySopDraft() {
    const active = _sopData.drafts.find((d) => d.root_id === _sopData.activeRoot);
    if (!active) return;
    navigator.clipboard.writeText(sopPlainText(active.content_md)).then(
        () => showMessage('Copied to clipboard.', 'success'),
        () => showMessage('Could not copy — select the text manually.', 'error'));
}

function downloadSopDraft() {
    const active = _sopData.drafts.find((d) => d.root_id === _sopData.activeRoot);
    if (!active) return;
    const blob = new Blob([sopPlainText(active.content_md)], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${active.university} - ${active.program} - ${active.doc_name}.txt`.replace(/[/\\:*?"<>|]/g, '-');
    a.click();
    URL.revokeObjectURL(a.href);
}

async function deleteSopDraft() {
    const active = _sopData.drafts.find((d) => d.root_id === _sopData.activeRoot);
    if (!active) return;
    if (!(await confirmDialog(`Delete the ${active.doc_name} for ${active.university} — all versions? This cannot be undone.`, { title: 'Delete SOP draft?', okText: 'Delete' }))) return;
    try {
        const r = await fetch(`${API_BASE}/api/sop/drafts/${active.root_id}`, {
            method: 'DELETE', credentials: 'include', headers: sopAuthHeaders(),
        });
        if (!r.ok) throw new Error('Delete failed');
        _sopData.drafts = _sopData.drafts.filter((d) => d.root_id !== active.root_id);
        _sopData.activeRoot = _sopData.drafts.length ? _sopData.drafts[0].root_id : null;
        renderSopStudio();
    } catch (e) {
        showMessage('Could not delete the draft.', 'error');
    }
}

// University shortlisting + AI recommendations (Phase 3)
// ===========================================================================
let _shortlistData = { entries: [], entitlement: null, destination_country: '' };

async function shortlistFetch(path, opts) {
    opts = opts || {};
    const headers = opts.body ? { 'Content-Type': 'application/json' } : {};
    if (authToken && authToken !== COOKIE_AUTH_SENTINEL) headers['Authorization'] = `Bearer ${authToken}`;
    const res = await aiFetch(`${API_BASE}/api/shortlist${path}`, {
        method: opts.method || 'GET',
        headers,
        credentials: 'include',
        body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    // A 401 here is an expired/invalid login session (not an AI failure). Surface the
    // standard "session expired" UX the rest of the app uses instead of the raw
    // "Could not validate credentials" detail, which looks like an AI/credentials error.
    if (res.status === 401) {
        showMessage('Session expired. Please login again.', 'error');
        logout();
        const err = new Error('Session expired. Please login again.');
        err.status = 401; throw err;
    }
    let data = null; try { data = await res.json(); } catch (e) { /* no body */ }
    if (!res.ok) {
        const detail = data && (data.detail || data.message);
        const err = new Error(typeof detail === 'string' ? detail : 'Request failed');
        err.status = res.status; throw err;
    }
    return data;
}

// The saved shortlist now lives inside Course Finder (the "My shortlist" tab) — the old
// "Shortlist & Recommendations" page duplicated Course Finder's AI shortlist and was removed.
let _shortlistHostId = 'cfShortlistHost';
async function loadUniversityShortlist(hostId) {
    if (hostId) _shortlistHostId = hostId;
    const c = document.getElementById(_shortlistHostId);
    if (!c) return;
    c.innerHTML = '<div style="padding:2rem;color:#64748b">Loading…</div>';
    try {
        _shortlistData = await shortlistFetch('');
    } catch (e) {
        c.innerHTML = `<div style="padding:2rem;color:#be123c">Could not load universities: ${escapeHtml(e.message)}</div>`;
        return;
    }
    renderUniversitiesUI();
}

function renderUniversitiesUI() {
    const c = document.getElementById(_shortlistHostId);
    if (!c) return;
    const d = _shortlistData || {};
    const inp = 'width:100%;box-sizing:border-box;background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;color:#0f172a;font-size:14px;padding:10px 12px';
    const card = (inner, extra) => `<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:16px;padding:18px 20px;${extra || ''}">${inner}</div>`;

    const statusColors = { considering: '#64748b', applied: '#1d4ed8', admitted: '#065f46', rejected: '#be123c' };
    const statusOpts = ['considering', 'applied', 'admitted', 'rejected'];
    // Fit badge label + color both come from CF_FIT — one map for both B2C surfaces.
    const savedRows = (d.entries || []).map((e) => {
        const sel = statusOpts.map((s) => `<option value="${s}"${e.status === s ? ' selected' : ''}>${s.charAt(0).toUpperCase() + s.slice(1)}</option>`).join('');
        const meta = [e.program, e.location].filter(Boolean).join(' · ');
        const extras = [];
        const fit = CF_FIT[e.admission_difficulty];
        if (fit) extras.push(`<span title="${escapeAttr(fit.hint)}" style="font-size:11px;font-weight:700;color:${fit.color}">${fit.label}</span>`);
        if (e.qs_world_rank) extras.push(`<span style="font-size:11px;color:#b45309;font-weight:600">QS ${escapeHtml(e.qs_world_rank)}</span>`);
        if (e.application_fee) extras.push(`<span style="font-size:11px;color:#64748b">Fee: ${escapeHtml(e.application_fee)}</span>`);
        const isHttp = (u) => typeof u === 'string' && /^https?:\/\//i.test(u) && !/["'<>`]/.test(u);
        if (isHttp(e.website_url)) extras.push(`<a href="${escapeAttr(e.website_url)}" target="_blank" rel="noopener" style="font-size:11px;color:#4f46e5;font-weight:600">Website ↗</a>`);
        if (isHttp(e.admissions_url)) extras.push(`<a href="${escapeAttr(e.admissions_url)}" target="_blank" rel="noopener" style="font-size:11px;color:#4f46e5;font-weight:600">Admissions ↗</a>`);
        return `<div style="display:flex;align-items:flex-start;gap:12px;padding:12px 0;border-bottom:1px solid #f1f5f9">
            <div style="flex:1;min-width:0">
              <div style="font-weight:700;color:#0f172a">${escapeHtml(e.university_name)}${e.source === 'ai' ? ' <span style="font-size:10px;background:rgba(124,58,237,.12);color:#6d28d9;padding:2px 6px;border-radius:6px;margin-left:6px">AI</span>' : ''}</div>
              <div style="font-size:12.5px;color:#64748b">${escapeHtml(meta) || '—'}${e.est_tuition ? ' · ' + escapeHtml(e.est_tuition) : ''}</div>
              ${extras.length ? `<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:3px;align-items:center">${extras.join('')}</div>` : ''}
            </div>
            <select onchange="setShortlistStatus(${e.id}, this.value)" style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;color:${statusColors[e.status] || '#0f172a'};font-size:12.5px;padding:6px 8px">${sel}</select>
            <button onclick="deleteShortlistUniversity(${e.id})" title="Remove" style="background:none;border:none;color:#be123c;cursor:pointer;font-size:18px;line-height:1">&times;</button>
          </div>`;
    }).join('');
    const savedCard = card(`
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
          <div style="font-weight:800;font-size:16px;color:#0f172a">My shortlist</div>
          <span style="font-size:12.5px;color:#64748b">${(d.entries || []).length} saved</span>
        </div>
        <div style="font-size:12.5px;color:#64748b;margin-bottom:4px">Universities you saved from AI shortlists or added yourself — track each one as you apply.</div>
        <div style="display:flex;gap:8px;margin:10px 0 4px">
          <input id="slManualName" placeholder="Add a university manually…" style="${inp}">
          <button onclick="addManualUniversity()" style="background:#f1f5f9;color:#0f172a;border:1px solid #e2e8f0;border-radius:10px;padding:0 16px;font-weight:600;cursor:pointer">Add</button>
        </div>
        ${savedRows || '<div style="color:#64748b;font-size:13px;padding:10px 0">No universities saved yet. Generate an AI shortlist and add picks from it, or add one manually.</div>'}
    `);

    c.innerHTML = savedCard;
    attachUniversityAutocomplete(document.getElementById('slManualName'));
}

async function addManualUniversity() {
    const inp = document.getElementById('slManualName');
    const name = ((inp && inp.value) || '').trim();
    if (!name) return;
    try {
        await shortlistFetch('', { method: 'POST', body: { university_name: name, source: 'manual' } });
        await loadUniversityShortlist();
    } catch (e) { showMessage(e.message || 'Could not add university.', 'error'); }
}

async function setShortlistStatus(id, statusVal) {
    try {
        await shortlistFetch(`/${id}`, { method: 'PATCH', body: { status: statusVal } });
        const e = (_shortlistData.entries || []).find((x) => x.id === id);
        if (e) e.status = statusVal;
    } catch (err) { showMessage(err.message || 'Could not update status.', 'error'); }
}

async function deleteShortlistUniversity(id) {
    if (!(await confirmDialog('This university will be removed from your shortlist.', { title: 'Remove university?', okText: 'Remove' }))) return;
    try {
        await shortlistFetch(`/${id}`, { method: 'DELETE' });
        await loadUniversityShortlist();
    } catch (e) { showMessage(e.message || 'Could not remove university.', 'error'); }
}

// ===========================================================================
// Course Finder (B2C) — browse the shared verified course catalog with advanced
// filters, and run Visa-Pass-metered AI course shortlists personalized to the
// student's destination + profile. Same catalog and contracts as the enterprise
// Course Finder; only the auth (individual account) and metering (pass) differ.
// ===========================================================================
let _cfMeta = null;
let _cf = {
    tab: 'browse',
    country: '', level: '', discipline: '', q: '', maxTuition: '',
    adv: {}, advOpen: false,
    offset: 0, total: 0, universities: [], expanded: {}, seq: 0,
    ai: { field: '', level: '', discipline: '', budget: '', gpa: '', scores: '', notes: '' },
    activeRec: null, recs: [], savedIdx: {},
};
// A completed AI run consumes quota even if we stop waiting, so wait longer than
// usual before declaring a timeout (and refetch history after errors — see below).
const CF_AI_TIMEOUT_MS = 150000;

async function coursesFetch(path, opts) {
    opts = opts || {};
    const headers = opts.body ? { 'Content-Type': 'application/json' } : {};
    if (authToken && authToken !== COOKIE_AUTH_SENTINEL) headers['Authorization'] = `Bearer ${authToken}`;
    const res = await aiFetch(`${API_BASE}/api/courses${path}`, {
        method: opts.method || 'GET',
        headers,
        credentials: 'include',
        body: opts.body ? JSON.stringify(opts.body) : undefined,
    }, opts.timeoutMs);
    if (res.status === 401) {
        showMessage('Session expired. Please login again.', 'error');
        logout();
        const err = new Error('Session expired. Please login again.');
        err.status = 401; throw err;
    }
    let data = null; try { data = await res.json(); } catch (e) { /* no body */ }
    if (!res.ok) {
        const detail = data && (data.detail || data.message);
        const err = new Error(typeof detail === 'string' ? detail : 'Request failed');
        err.status = res.status; throw err;
    }
    return data;
}

const CF_INP = 'width:100%;box-sizing:border-box;background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;color:#0f172a;font-size:13.5px;padding:9px 11px';
const CF_LBL = (t) => `<div style="font-size:11.5px;font-weight:700;color:#64748b;margin:0 0 5px">${t}</div>`;
const CF_CARD = (inner, extra) => `<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:16px;padding:18px 20px;${extra || ''}">${inner}</div>`;
// Display labels ONLY. The reach/match/safety KEYS are the AI + DB tokens
// (course_catalog.py fit_level -> university_shortlist_entries.admission_difficulty)
// and must never change: every server validator substitutes "match" or NULL on a
// mismatch, silently. One map feeds both B2C surfaces — the AI result pill
// (cfActiveRecHtml) and the saved "My shortlist" rows (renderUniversitiesUI).
const CF_FIT = {
    reach: { label: 'Low chance', color: '#be123c', hint: 'Low chance of admission — ambitious for the profile you entered' },
    match: { label: 'Medium chance', color: '#1d4ed8', hint: 'Medium chance of admission — a realistic fit for the profile you entered' },
    safety: { label: 'High chance', color: '#065f46', hint: 'High chance of admission — comfortably within the profile you entered' },
};
// Advanced-filter keys mirrored to the query string — one place, so chips, inputs
// and the request can never drift.
const CF_ADV_KEYS = ['min_tuition', 'require_tuition', 'no_app_fee', 'scholarships_only', 'max_ielts', 'max_toefl',
    'tests_include_unknown', 'gre', 'intake', 'max_duration', 'has_deadline', 'max_qs_rank', 'uni_type', 'city', 'verified_only'];
const CF_ADV_LABELS = {
    min_tuition: 'Min tuition', require_tuition: 'Published fee only', no_app_fee: 'No application fee',
    scholarships_only: 'Scholarships listed', max_ielts: 'IELTS ≤', max_toefl: 'TOEFL ≤',
    tests_include_unknown: 'Include unpublished scores', gre: 'GRE/GMAT', intake: 'Intake',
    max_duration: 'Finishes within', has_deadline: 'Deadline published', max_qs_rank: 'QS top',
    uni_type: 'Type', city: 'City', verified_only: 'Verified data only',
};

// escapeHtml (textContent-based) encodes & < > but NOT quotes — fine for text nodes,
// not for attribute values: a stored URL like `https://a.test/"onmouseover="...` would
// break out of href="…". Everything interpolated into an attribute goes through this.
function escapeAttr(value) {
    return escapeHtml(String(value == null ? '' : value)).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function cfSafeUrl(u) {
    return (typeof u === 'string' && /^https?:\/\//i.test(u) && !/["'<>`]/.test(u)) ? u : '';
}

function cfDaysAgo(iso) {
    if (!iso) return null;
    const days = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 86400000));
    return days;
}

function cfEntitlementText(ent) {
    if (!ent) return '';
    if (ent.unlimited) return 'Unlimited';
    if (ent.tier === 'pass') return `${ent.remaining} left on your Visa Pass`;
    return `${ent.remaining} free ${ent.remaining === 1 ? 'run' : 'runs'} left`;
}

function cfCountry(code) {
    return ((_cfMeta && _cfMeta.countries) || []).find((c) => c.code === code) || null;
}

function cfLevelLabel(key) {
    const l = ((_cfMeta && _cfMeta.degree_levels) || []).find((x) => x.key === key);
    return l ? l.label : (key || '');
}

async function loadCourseFinder() {
    const c = document.getElementById('coursesContent');
    if (!c) return;
    c.innerHTML = '<div style="padding:2rem;color:#64748b">Loading…</div>';
    try {
        _cfMeta = await coursesFetch('/meta');
    } catch (e) {
        c.innerHTML = `<div style="padding:2rem;color:#be123c">Could not load Course Finder: ${escapeHtml(e.message)}</div>`;
        return;
    }
    if (!_cf.country) {
        // Country-specific by default: open on the student's own destination.
        _cf.country = _cfMeta.destination_country_code
            || ((_cfMeta.countries || []).find((x) => x.universities > 0) || (_cfMeta.countries || [])[0] || {}).code || 'US';
    }
    cfRenderShell();
}

function cfRenderShell() {
    const c = document.getElementById('coursesContent');
    if (!c) return;
    const countries = (_cfMeta && _cfMeta.countries) || [];
    const dest = cfCountry(_cfMeta.destination_country_code);
    const chips = countries.map((x) => `
        <button onclick="cfPickCountry('${escapeHtml(x.code)}')" style="border:1px solid ${x.code === _cf.country ? '#6366f1' : '#e2e8f0'};background:${x.code === _cf.country ? 'rgba(99,102,241,.08)' : '#fff'};border-radius:999px;padding:5px 12px;font-size:12px;font-weight:600;color:#0f172a;cursor:pointer">
          ${escapeHtml(x.flag_emoji || '')} ${escapeHtml(x.code)} · ${x.universities}</button>`).join(' ');
    const selected = cfCountry(_cf.country) || {};
    const freshness = cfDaysAgo(selected.last_verified_at);
    const tabBtn = (key, label) => `
        <button onclick="cfSetTab('${key}')" style="border:none;cursor:pointer;font-weight:700;font-size:13.5px;padding:9px 16px;border-radius:10px;background:${_cf.tab === key ? 'linear-gradient(135deg,#6366f1,#a855f7)' : '#f1f5f9'};color:${_cf.tab === key ? '#fff' : '#334155'}">${label}</button>`;
    c.innerHTML = `
      ${CF_CARD(`
        <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center">
          <div>
            <div style="font-weight:800;font-size:16px;color:#0f172a">Verified course catalog</div>
            <div style="font-size:12.5px;color:#64748b">
              ${dest ? `Your destination: ${escapeHtml(dest.flag_emoji || '')} ${escapeHtml(dest.name)} · ` : ''}
              ${selected.universities || 0} universities · ${selected.courses || 0} courses in ${escapeHtml(selected.name || _cf.country)}
              ${freshness !== null ? ` · <span style="color:#065f46;font-weight:600">✓ data refreshed ${freshness}d ago</span>` : ''}
            </div>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap">${chips}</div>
        </div>`)}
      <div style="display:flex;gap:8px;margin:14px 0;flex-wrap:wrap">${tabBtn('browse', '🔎 Browse catalog')}${tabBtn('ai', '✨ AI shortlist')}${tabBtn('shortlist', '🎓 My shortlist')}</div>
      <div id="cfPanel"></div>`;
    if (_cf.tab === 'browse') { cfRenderBrowse(); cfLoadBrowse(false); }
    else if (_cf.tab === 'shortlist') { cfRenderShortlistTab(); }
    else { cfRenderAI(); cfLoadHistory(); }
}

// "My shortlist": the universities the student saved (from AI shortlists or by hand), with
// status tracking — the list the old Shortlist & Recommendations page used to show.
function cfRenderShortlistTab() {
    const p = document.getElementById('cfPanel');
    if (!p) return;
    p.innerHTML = '<div id="cfShortlistHost"></div>';
    loadUniversityShortlist('cfShortlistHost');
}

function cfSetTab(tab) {
    _cf.tab = (tab === 'ai' || tab === 'shortlist') ? tab : 'browse';
    cfRenderShell();
}

function cfPickCountry(code) {
    _cf.country = code;
    _cf.offset = 0; _cf.universities = []; _cf.expanded = {};
    cfRenderShell();
}

function cfActiveAdvCount() {
    return CF_ADV_KEYS.filter((k) => _cf.adv[k] !== undefined && _cf.adv[k] !== '' && _cf.adv[k] !== false).length;
}

function cfRenderBrowse() {
    const p = document.getElementById('cfPanel');
    if (!p) return;
    const m = _cfMeta || {};
    const opt = (v, label, cur) => `<option value="${escapeHtml(String(v))}"${String(cur) === String(v) ? ' selected' : ''}>${escapeHtml(label)}</option>`;
    const levelOpts = ['<option value="">Any level</option>'].concat((m.degree_levels || []).map((l) => opt(l.key, l.label, _cf.level))).join('');
    const discOpts = ['<option value="">Any subject area</option>'].concat((m.disciplines || []).map((d) => opt(d, d, _cf.discipline))).join('');
    const adv = _cf.adv;
    const ieltsOpts = ['<option value="">Any</option>'].concat([5, 5.5, 6, 6.5, 7, 7.5, 8].map((b) => opt(b, `Band ${b.toFixed(1)}`, adv.max_ielts))).join('');
    const greOpts = ['<option value="">Any</option>'].concat((m.gre_filters || []).map((g) => opt(g.key, g.label, adv.gre))).join('');
    const intakeOpts = ['<option value="">Any intake</option>'].concat((m.intakes || []).map((i) => opt(i.key, i.label, adv.intake))).join('');
    const durOpts = ['<option value="">Any duration</option>'].concat([12, 18, 24, 36].map((d) => opt(d, `${d} months`, adv.max_duration))).join('');
    const qsOpts = ['<option value="">Any rank</option>'].concat([50, 100, 200, 300, 500, 1000].map((r) => opt(r, `Top ${r}`, adv.max_qs_rank))).join('');
    const typeOpts = ['<option value="">Any type</option>'].concat((m.university_types || []).map((t) => opt(t.key, t.label, adv.uni_type))).join('');
    const sortOpts = (m.sorts || []).map((s) => opt(s.key, s.label, adv.sort || 'rank')).join('');
    const advCount = cfActiveAdvCount();
    const check = (id, key, label) => `
        <label style="display:flex;align-items:center;gap:7px;font-size:12.5px;color:#334155;cursor:pointer">
          <input type="checkbox" id="${id}"${adv[key] ? ' checked' : ''}> ${label}</label>`;

    p.innerHTML = `
      ${CF_CARD(`
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px">
          <div>${CF_LBL('Level')}<select id="cfLevel" style="${CF_INP}" onchange="cfSelectApply()">${levelOpts}</select></div>
          <div>${CF_LBL('Subject area')}<select id="cfDiscipline" style="${CF_INP}" onchange="cfSelectApply()">${discOpts}</select></div>
          <div>${CF_LBL('Search course or university')}<input id="cfQ" maxlength="80" value="${escapeAttr(_cf.q)}" placeholder="e.g. Data Science or Melbourne" style="${CF_INP}" onkeydown="if(event.key==='Enter')cfApply()"></div>
          <div>${CF_LBL('Max tuition / year')}<input id="cfMaxTuition" type="number" min="0" value="${escapeAttr(_cf.maxTuition)}" placeholder="Local currency" style="${CF_INP}" onkeydown="if(event.key==='Enter')cfApply()"></div>
        </div>
        <div style="display:flex;align-items:center;gap:10px;margin-top:12px;flex-wrap:wrap">
          <button onclick="cfApply()" style="background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;border:none;border-radius:10px;padding:9px 18px;font-weight:700;cursor:pointer">Search</button>
          <button onclick="cfToggleAdv()" style="background:#f1f5f9;border:1px solid #e2e8f0;border-radius:10px;padding:9px 14px;font-weight:600;color:#334155;cursor:pointer">
            Advanced filters${advCount ? ` <span style="background:#6366f1;color:#fff;border-radius:999px;padding:1px 7px;font-size:11px;margin-left:4px">${advCount}</span>` : ''} ${_cf.advOpen ? '▴' : '▾'}</button>
          <span id="cfChips" style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">${cfChipsHtml()}</span>
        </div>
        <div id="cfFilterMsg" style="display:none;color:#be123c;font-size:13px;margin-top:8px"></div>
        <div id="cfAdvPanel" style="display:${_cf.advOpen ? 'block' : 'none'};margin-top:14px;border-top:1px solid #f1f5f9;padding-top:14px">
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px">
            <div>
              <div style="font-weight:700;font-size:12.5px;color:#0f172a;margin-bottom:8px">Fees &amp; funding</div>
              ${CF_LBL('Min tuition / year')}<input id="cfMinTuition" type="number" min="0" value="${escapeAttr(adv.min_tuition || '')}" placeholder="Local currency" style="${CF_INP};margin-bottom:8px">
              <div style="display:grid;gap:6px">
                ${check('cfRequireTuition', 'require_tuition', 'Published fee only')}
                ${check('cfNoAppFee', 'no_app_fee', 'No application fee')}
                ${check('cfScholarships', 'scholarships_only', 'University lists scholarships')}
              </div>
            </div>
            <div>
              <div style="font-weight:700;font-size:12.5px;color:#0f172a;margin-bottom:8px">Tests &amp; entry</div>
              ${CF_LBL('My IELTS band (≤)')}<select id="cfIelts" style="${CF_INP};margin-bottom:8px">${ieltsOpts}</select>
              ${CF_LBL('My TOEFL iBT (≤)')}<input id="cfToefl" type="number" min="40" max="120" value="${escapeAttr(adv.max_toefl || '')}" placeholder="e.g. 95" style="${CF_INP};margin-bottom:8px">
              ${CF_LBL('GRE / GMAT')}<select id="cfGre" style="${CF_INP};margin-bottom:8px">${greOpts}</select>
              ${check('cfTestsUnknown', 'tests_include_unknown', 'Also show programs with no published score')}
            </div>
            <div>
              <div style="font-weight:700;font-size:12.5px;color:#0f172a;margin-bottom:8px">Program</div>
              ${CF_LBL('Intake')}<select id="cfIntake" style="${CF_INP};margin-bottom:8px">${intakeOpts}</select>
              ${CF_LBL('Finishes within')}<select id="cfDuration" style="${CF_INP};margin-bottom:8px">${durOpts}</select>
              ${check('cfHasDeadline', 'has_deadline', 'Application deadline published')}
            </div>
            <div>
              <div style="font-weight:700;font-size:12.5px;color:#0f172a;margin-bottom:8px">University</div>
              ${CF_LBL('QS world rank')}<select id="cfQsRank" style="${CF_INP};margin-bottom:8px">${qsOpts}</select>
              ${CF_LBL('Type')}<select id="cfUniType" style="${CF_INP};margin-bottom:8px">${typeOpts}</select>
              ${CF_LBL('City')}<input id="cfCity" maxlength="60" value="${escapeAttr(adv.city || '')}" placeholder="e.g. Toronto" style="${CF_INP};margin-bottom:8px">
              ${check('cfVerifiedOnly', 'verified_only', 'Verified data only')}
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:10px;margin-top:14px;flex-wrap:wrap">
            <button onclick="cfApplyAdv()" style="background:#0f172a;color:#fff;border:none;border-radius:10px;padding:9px 18px;font-weight:700;cursor:pointer">Apply filters</button>
            <button onclick="cfClearAdv()" style="background:none;border:none;color:#64748b;font-weight:600;cursor:pointer">Clear all</button>
            <span style="margin-left:auto;display:flex;align-items:center;gap:8px">${CF_LBL('Sort')}<select id="cfSort" style="${CF_INP};width:auto" onchange="cfApplyAdv()">${sortOpts}</select></span>
          </div>
        </div>`)}
      <div id="cfResults" style="margin-top:14px"></div>`;
}

function cfChipsHtml() {
    const chips = [];
    for (const k of CF_ADV_KEYS) {
        const v = _cf.adv[k];
        if (v === undefined || v === '' || v === false) continue;
        const label = CF_ADV_LABELS[k] || k;
        const text = (v === true) ? label : `${label}: ${v}`;
        chips.push(`<span style="background:rgba(99,102,241,.08);border:1px solid rgba(99,102,241,.3);color:#4338ca;border-radius:999px;padding:3px 10px;font-size:11.5px;font-weight:600">${escapeHtml(text)}
            <button onclick="cfRemoveFilter('${k}')" style="background:none;border:none;color:#4338ca;cursor:pointer;font-size:12px;padding:0 0 0 4px">×</button></span>`);
    }
    if (chips.length) chips.push(`<button onclick="cfClearAdv()" style="background:none;border:none;color:#64748b;font-size:11.5px;font-weight:600;cursor:pointer">Clear all</button>`);
    return chips.join('');
}

function cfToggleAdv() {
    _cf.advOpen = !_cf.advOpen;
    cfReadBasicInputs();
    cfRenderBrowse();
}

function cfReadBasicInputs() {
    const val = (id) => ((document.getElementById(id) || {}).value || '').trim();
    _cf.level = val('cfLevel'); _cf.discipline = val('cfDiscipline');
    _cf.q = val('cfQ'); _cf.maxTuition = val('cfMaxTuition');
}

function cfReadAdvInputs() {
    const val = (id) => ((document.getElementById(id) || {}).value || '').trim();
    const chk = (id) => Boolean((document.getElementById(id) || {}).checked);
    // Only read the panel when it is rendered — collapsing it must not wipe filters.
    if (!document.getElementById('cfAdvPanel') || !_cf.advOpen) return;
    const adv = {};
    if (val('cfMinTuition')) adv.min_tuition = val('cfMinTuition');
    if (chk('cfRequireTuition')) adv.require_tuition = true;
    if (chk('cfNoAppFee')) adv.no_app_fee = true;
    if (chk('cfScholarships')) adv.scholarships_only = true;
    if (val('cfIelts')) adv.max_ielts = val('cfIelts');
    if (val('cfToefl')) adv.max_toefl = val('cfToefl');
    if (val('cfGre')) adv.gre = val('cfGre');
    if (chk('cfTestsUnknown')) adv.tests_include_unknown = true;
    if (val('cfIntake')) adv.intake = val('cfIntake');
    if (val('cfDuration')) adv.max_duration = val('cfDuration');
    if (chk('cfHasDeadline')) adv.has_deadline = true;
    if (val('cfQsRank')) adv.max_qs_rank = val('cfQsRank');
    if (val('cfUniType')) adv.uni_type = val('cfUniType');
    if (val('cfCity')) adv.city = val('cfCity');
    if (chk('cfVerifiedOnly')) adv.verified_only = true;
    const sortSel = val('cfSort');
    if (sortSel && sortSel !== 'rank') adv.sort = sortSel;
    _cf.adv = adv;
}


// Browse-filter number guard (Max/Min tuition, TOEFL). type="number" min="0" only disables
// the stepper — a typed "-10000" still submits, and the server then silently ignored it,
// so the page looked like it had accepted the value. Returns "" or the first problem; also
// paints the offending box. Mirrors the server rule (course_catalog.normalize_catalog_filters
// drops out-of-range numbers instead of clamping them to the nearest bound).
function cfFilterNumberProblem() {
  const checks = [
    ["cfMaxTuition", "Max tuition", 0, 10000000, "enter an amount in local currency, e.g. 25000"],
    ["cfMinTuition", "Min tuition", 0, 10000000, "enter an amount in local currency, e.g. 10000"],
    ["cfToefl", "TOEFL iBT", 40, 120, "enter your score between 40 and 120"],
  ];
  let problem = "";
  checks.forEach(([id, label, lo, hi, hint]) => {
    const el = document.getElementById(id);
    if (!el) return;
    const raw = String(el.value || "").trim();
    let bad = "";
    if (raw) {
      const n = Number(raw);
      if (!Number.isFinite(n)) bad = `${label} must be a number — ${hint}.`;
      else if (n < 0) bad = `${label} can't be negative — ${hint}.`;
      else if (n < lo || n > hi) bad = `${label} must be between ${lo} and ${hi} — ${hint}.`;
    }
    el.style.borderColor = bad ? "#be123c" : "";
    el.setAttribute("aria-invalid", bad ? "true" : "false");
    if (bad && !problem) { problem = bad; try { el.focus(); } catch (e) { /* ignore */ } }
  });
  return problem;
}

function cfSelectApply() { cfApply(); }
function cfApplyAdv() { cfApply(); }

function cfApply() {
    const problem = cfFilterNumberProblem();
    const msgEl = document.getElementById('cfFilterMsg');
    if (msgEl) { msgEl.textContent = problem; msgEl.style.display = problem ? 'block' : 'none'; }
    if (problem) return;
    cfReadBasicInputs();
    cfReadAdvInputs();
    _cf.offset = 0; _cf.universities = []; _cf.expanded = {};
    // Re-render the whole browse shell (from the state just read) so the chips row
    // AND the Advanced-filters count badge both reflect what was applied.
    cfRenderBrowse();
    cfLoadBrowse(false);
}

function cfRemoveFilter(key) {
    // Capture typed-but-unapplied inputs first — removing one chip must not silently
    // discard the search text the user was about to apply.
    cfReadBasicInputs();
    cfReadAdvInputs();
    delete _cf.adv[key];
    _cf.offset = 0; _cf.universities = []; _cf.expanded = {};
    cfRenderBrowse();
    cfLoadBrowse(false);
}

function cfClearAdv() {
    cfReadBasicInputs();
    _cf.adv = {};
    _cf.offset = 0; _cf.universities = []; _cf.expanded = {};
    cfRenderBrowse();
    cfLoadBrowse(false);
}

async function cfLoadBrowse(append) {
    const box = document.getElementById('cfResults');
    if (!box) return;
    if (!append) box.innerHTML = '<div style="padding:1.5rem;color:#64748b">Searching the catalog…</div>';
    const seq = ++_cf.seq;  // stale-response guard: a slow older request must not clobber a newer one
    const params = new URLSearchParams();
    params.set('country', _cf.country);
    if (_cf.level) params.set('level', _cf.level);
    if (_cf.discipline) params.set('discipline', _cf.discipline);
    if (_cf.q) params.set('q', _cf.q);
    if (_cf.maxTuition) params.set('max_tuition', _cf.maxTuition);
    for (const k of CF_ADV_KEYS) {
        const v = _cf.adv[k];
        if (v === undefined || v === '' || v === false) continue;
        params.set(k, v === true ? '1' : String(v));
    }
    if (_cf.adv.sort) params.set('sort', _cf.adv.sort);
    if (append) params.set('offset', String(_cf.offset));
    let data;
    try {
        data = await coursesFetch(`/catalog?${params.toString()}`);
    } catch (e) {
        if (seq === _cf.seq && box) box.innerHTML = `<div style="padding:1.5rem;color:#be123c">${escapeHtml(e.message || 'Could not search the catalog.')}</div>`;
        return;
    }
    if (seq !== _cf.seq) return;
    _cf.total = data.total_universities || 0;
    _cf.hasMore = Boolean(data.has_more);
    _cf.universities = append ? _cf.universities.concat(data.universities || []) : (data.universities || []);
    _cf.offset = (data.offset || 0) + (data.universities || []).length;
    cfRenderResults();
}

function cfRenderResults() {
    const box = document.getElementById('cfResults');
    if (!box) return;
    const unis = _cf.universities;
    if (!unis.length) {
        const filtered = cfActiveAdvCount() > 0 || _cf.q || _cf.level || _cf.discipline || _cf.maxTuition;
        box.innerHTML = CF_CARD(filtered
            ? `<div style="color:#64748b;font-size:13.5px">No matches for these filters. <button onclick="cfClearAdv()" style="background:none;border:none;color:#4f46e5;font-weight:700;cursor:pointer">Clear all filters</button></div>`
            : `<div style="color:#64748b;font-size:13.5px">Nothing here yet — our research agent is still enriching this destination. Check back soon or try the AI shortlist tab.</div>`);
        return;
    }
    const cards = unis.map((u, i) => cfUniCardHtml(u, i)).join('');
    box.innerHTML = `
      <div style="font-size:12.5px;color:#64748b;margin:0 0 10px">Showing ${unis.length} of ${_cf.total} universities</div>
      ${cards}
      ${_cf.hasMore ? `<div style="text-align:center;margin-top:14px"><button onclick="cfLoadBrowse(true)" style="background:#f1f5f9;border:1px solid #e2e8f0;border-radius:10px;padding:10px 22px;font-weight:700;color:#334155;cursor:pointer">Load more</button></div>` : ''}`;
}

function cfUniCardHtml(u, idx) {
    const expanded = _cf.expanded[idx] !== undefined ? _cf.expanded[idx] : idx < 3;
    const fresh = cfDaysAgo(u.last_verified_at);
    const badge = u.last_verified_at
        ? `<span style="font-size:11px;font-weight:700;color:#065f46;background:rgba(6,95,70,.08);border-radius:999px;padding:2px 9px">✓ Verified ${fresh}d ago</span>`
        : `<span style="font-size:11px;font-weight:700;color:#b45309;background:rgba(180,83,9,.08);border-radius:999px;padding:2px 9px">⏳ Enriching soon</span>`;
    const site = cfSafeUrl(u.website_url);
    const ranks = [];
    if (u.qs_world_rank) ranks.push(`QS ${escapeHtml(u.qs_world_rank)}`);
    if (u.national_rank) ranks.push(`#${escapeHtml(u.national_rank)} national`);
    const courses = u.courses || [];
    const rows = courses.map((c) => {
        const scores = [c.ielts_requirement ? `IELTS ${c.ielts_requirement}` : '', c.toefl_requirement ? `TOEFL ${c.toefl_requirement}` : ''].filter(Boolean).join(' / ');
        const url = cfSafeUrl(c.course_url);
        return `<tr style="border-top:1px solid #f1f5f9">
            <td style="padding:7px 10px 7px 0;min-width:180px"><div style="font-weight:600;color:#0f172a;font-size:12.5px">${escapeHtml(c.course_name || '')}</div>
              <div style="font-size:11px;color:#94a3b8">${escapeHtml([c.discipline, c.duration].filter(Boolean).join(' · '))}</div></td>
            <td style="padding:7px 10px 7px 0;font-size:12px;color:#334155;white-space:nowrap">${escapeHtml(cfLevelLabel(c.degree_level))}</td>
            <td style="padding:7px 10px 7px 0;font-size:12px;color:#334155">${escapeHtml(c.annual_tuition || '—')}</td>
            <td style="padding:7px 10px 7px 0;font-size:12px;color:#334155">${escapeHtml((c.intakes || []).join(', ') || '—')}</td>
            <td style="padding:7px 10px 7px 0;font-size:12px;color:#334155">${escapeHtml(scores || '—')}</td>
            <td style="padding:7px 10px 7px 0;font-size:12px;color:#334155">${escapeHtml(c.application_deadline || '—')}</td>
            <td style="padding:7px 10px 7px 0;font-size:12px;color:#334155">${escapeHtml(c.application_fee || '—')}</td>
            <td style="padding:7px 0;font-size:12px;white-space:nowrap">${url ? `<a href="${escapeAttr(url)}" target="_blank" rel="noopener" style="color:#4f46e5;font-weight:600">Page ↗</a>` : ''}</td>
          </tr>`;
    }).join('');
    return CF_CARD(`
        <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:flex-start">
          <div style="min-width:0">
            <div style="font-weight:800;color:#0f172a;font-size:15px">${escapeHtml(u.name || '')}</div>
            <div style="font-size:12px;color:#64748b">${escapeHtml([u.city, u.university_type].filter(Boolean).join(' · '))}</div>
          </div>
          <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
            ${ranks.map((r) => `<span style="font-size:11px;font-weight:700;color:#b45309;background:rgba(180,83,9,.08);border-radius:999px;padding:2px 9px">🏆 ${r}</span>`).join('')}
            ${badge}
          </div>
        </div>
        ${u.summary ? `<div style="font-size:12.5px;color:#334155;margin-top:8px">${escapeHtml(u.summary)}</div>` : ''}
        <div style="display:flex;gap:14px;flex-wrap:wrap;margin-top:6px;font-size:12px;color:#64748b">
          ${u.tuition_note ? `<span>💰 ${escapeHtml(u.tuition_note)}</span>` : ''}
          ${u.scholarships_note ? `<span>🎓 ${escapeHtml(u.scholarships_note)}</span>` : ''}
          ${site ? `<a href="${escapeAttr(site)}" target="_blank" rel="noopener" style="color:#4f46e5;font-weight:600">Official website ↗</a>` : ''}
        </div>
        ${courses.length ? `
          <button onclick="cfToggleUni(${idx})" style="margin-top:10px;background:none;border:none;color:#4f46e5;font-weight:700;font-size:12.5px;cursor:pointer;padding:0">
            ${expanded ? '▾ Hide' : '▸ Show'} ${courses.length} matching course${courses.length === 1 ? '' : 's'}</button>
          <div style="display:${expanded ? 'block' : 'none'};overflow-x:auto;margin-top:6px">
            <table style="width:100%;border-collapse:collapse;min-width:760px">
              <thead><tr style="font-size:10.5px;text-transform:uppercase;letter-spacing:.04em;color:#94a3b8;text-align:left">
                <th style="padding:0 10px 4px 0">Course</th><th style="padding:0 10px 4px 0">Level</th><th style="padding:0 10px 4px 0">Tuition/yr</th>
                <th style="padding:0 10px 4px 0">Intakes</th><th style="padding:0 10px 4px 0">Scores</th><th style="padding:0 10px 4px 0">Deadline</th>
                <th style="padding:0 10px 4px 0">App. fee</th><th></th></tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>` : '<div style="margin-top:10px;font-size:12px;color:#94a3b8">Courses for this university are still being researched.</div>'}
    `, 'margin-bottom:12px');
}

function cfToggleUni(idx) {
    _cf.expanded[idx] = !(_cf.expanded[idx] !== undefined ? _cf.expanded[idx] : idx < 3);
    cfRenderResults();
}

// --------------------------- AI shortlist tab ------------------------------

function cfRenderAI() {
    const p = document.getElementById('cfPanel');
    if (!p) return;
    const m = _cfMeta || {};
    const ent = m.entitlement || {};
    const locked = Boolean(ent.locked);
    const aiAvailable = m.ai_available !== false;
    const opt = (v, label, cur) => `<option value="${escapeHtml(String(v))}"${String(cur) === String(v) ? ' selected' : ''}>${escapeHtml(label)}</option>`;
    const levelOpts = ['<option value="">Any level</option>'].concat((m.degree_levels || []).map((l) => opt(l.key, l.label, _cf.ai.level))).join('');
    const discOpts = [`<option value="">${(m.disciplines || []).length ? 'Pick a subject area…' : 'Subject areas unavailable'}</option>`].concat((m.disciplines || []).map((d) => opt(d, d, _cf.ai.discipline))).join('');
    const selected = cfCountry(_cf.country) || {};
    const code = _cf.country || 'US';
    const budgetHint = ({ US: 'e.g. $30,000', UK: 'e.g. £22,000', CA: 'e.g. C$25,000', AU: 'e.g. A$35,000', DE: 'e.g. €12,000' })[code] || 'e.g. your annual budget (local currency)';
    const scoresHint = ({ US: 'e.g. IELTS 7.5, GRE 320', UK: 'e.g. IELTS 7.0', CA: 'e.g. IELTS 7.0', AU: 'e.g. IELTS 7.0, PTE 65', DE: 'e.g. IELTS 6.5, TestDaF 4' })[code] || 'e.g. IELTS 7.0';
    const gpaHint = ({ US: 'e.g. 3.6/4.0', UK: 'e.g. 2:1 or AAB', CA: 'e.g. 3.6/4.0 or 85%', AU: 'e.g. 75% or GPA 5.5/7', DE: 'e.g. 1.7 (German scale)' })[code] || 'e.g. your GPA or grade average';

    p.innerHTML = `
      ${CF_CARD(`
        <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:12px">
          <div>
            <div style="font-weight:800;font-size:16px;color:#0f172a">Rilono AI Course Shortlist</div>
            <div style="font-size:12.5px;color:#64748b">Personalized to your profile and shortlist history — built from verified catalog data for ${escapeHtml(selected.name || code)}.</div>
          </div>
          <span style="font-size:12px;font-weight:700;color:${locked ? '#b45309' : '#065f46'}">${escapeHtml(cfEntitlementText(ent))}</span>
        </div>
        ${!aiAvailable ? '<div style="color:#b45309;font-size:13px">Rilono AI recommendations are not available right now.</div>' : `
        <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px">
          <div>${CF_LBL('Subject area <span style="color:#be123c">*</span>')}<select id="cfAiDiscipline" style="${CF_INP}">${discOpts}</select></div>
          <div>${CF_LBL('Specific course or specialisation <span style="color:#94a3b8;font-weight:600">(optional)</span>')}<input id="cfAiField" maxlength="120" value="${escapeAttr(_cf.ai.field)}" placeholder="e.g. MBA in Finance, Machine Learning" style="${CF_INP}"></div>
          <div>${CF_LBL('Study level')}<select id="cfAiLevel" style="${CF_INP}">${levelOpts}</select></div>
          <div>${CF_LBL('Annual budget')}<input id="cfAiBudget" maxlength="60" value="${escapeAttr(_cf.ai.budget)}" placeholder="${budgetHint}" style="${CF_INP}"></div>
          <div>${CF_LBL('GPA / grades')}<input id="cfAiGpa" maxlength="60" value="${escapeAttr(_cf.ai.gpa)}" placeholder="${gpaHint}" style="${CF_INP}"></div>
          <div>${CF_LBL('Test scores')}<input id="cfAiScores" maxlength="160" value="${escapeAttr(_cf.ai.scores)}" placeholder="${scoresHint}" style="${CF_INP}"></div>
          <div>${CF_LBL('Notes / preferences')}<input id="cfAiNotes" maxlength="300" value="${escapeAttr(_cf.ai.notes)}" placeholder="e.g. co-op, scholarships, big city" style="${CF_INP}"></div>
        </div>
        <div style="display:flex;align-items:center;gap:12px;margin-top:14px;flex-wrap:wrap">
          <button id="cfAiRunBtn" onclick="cfRunRecommend()" style="background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;border:none;border-radius:10px;padding:10px 18px;font-weight:700;cursor:pointer">Generate shortlist</button>
          <span id="cfAiMsg" style="font-size:13px;color:#be123c"></span>
        </div>
        ${locked ? `<div style="margin-top:10px;font-size:12.5px;color:#64748b">${ent.tier === 'pass' ? 'You have used all your Course Finder runs on this pass.' : `You have used your ${ent.limit === 1 ? 'free Course Finder run' : `${ent.limit} free Course Finder runs`}.`} <a href="/visa-pass" onclick="handleUpgradeToPro('course_finder'); return false;" style="color:#9aa0ff;font-weight:600">Get the Visa Success Pass</a>.</div>` : ''}
        ${!locked && ent.tier === 'free' && ent.free_visible_results > 0 ? `<div style="margin-top:10px;font-size:12.5px;color:#64748b">Free plan: your top ${ent.free_visible_results} pick${ent.free_visible_results === 1 ? '' : 's'} are shown in full — the Visa Success Pass reveals every pick.</div>` : ''}
        `}
      `)}
      <div id="cfActiveRec" style="margin-top:14px">${_cf.activeRec ? cfActiveRecHtml(_cf.activeRec) : ''}</div>
      <div id="cfHistory" style="margin-top:14px"></div>`;
}

function cfReadAiInputs() {
    const val = (id) => ((document.getElementById(id) || {}).value || '').trim();
    _cf.ai = {
        field: val('cfAiField'), level: val('cfAiLevel'), discipline: val('cfAiDiscipline'),
        budget: val('cfAiBudget'), gpa: val('cfAiGpa'), scores: val('cfAiScores'), notes: val('cfAiNotes'),
    };
}


// Annual budget sanity rule, mirrored server-side (course_catalog.normalize_budget): the box
// stays free text because real budgets come as "£22,000", "USD 40k" or "₹15–25 L / year",
// but it must contain a positive amount — "-10000" and "abc" used to go straight to the model.
const CF_BUDGET_WORDS = new Set(["per", "year", "yr", "annual", "annually", "approx", "approximately", "about", "around",
  "upto", "up", "to", "max", "maximum", "min", "minimum", "lakh", "lakhs", "lac", "lacs", "crore", "crores", "cr", "k", "l",
  "m", "mn", "million", "thousand", "usd", "gbp", "cad", "aud", "eur", "inr", "nzd", "sgd", "aed", "pln", "sek", "chf",
  "jpy", "rs", "dollars", "pounds", "euros", "rupees",
    "a", "c", "s", "nz", "us", "hk", "ca", "au", "uk", "dh", "dhs", "rm"]);
function cfBudgetProblem(raw) {
  const text = String(raw || "").trim().replace(/\s+/g, " ");
  if (!text) return "";
  if (/^[-−–]/.test(text)) return "Budget can't be negative — enter the annual amount, e.g. 30000 or £22,000.";
  const nums = text.match(/\d[\d,]*(?:\.\d+)?/g);
  if (!nums) return "Enter the annual budget as an amount, e.g. 30000 or £22,000.";
  for (const n of nums) {
    const v = parseFloat(n.replace(/,/g, ""));
    if (!(v > 0)) return "Budget must be more than zero — enter the annual amount, e.g. 30000.";
    if (v > 100000000) return "That budget looks wrong — enter the annual amount, e.g. 30000.";
  }
  const words = text.match(/[A-Za-z]+/g) || [];
  if (words.some((w) => !CF_BUDGET_WORDS.has(w.toLowerCase())) || /[^0-9A-Za-z\s,.\-–\/()$£€₹¥₩₪₱₫฿]/.test(text)) {
    return "Enter the annual budget as an amount (optionally with a currency), e.g. 30000, £22,000 or USD 40k.";
  }
  return "";
}

async function cfRunRecommend() {
    cfReadAiInputs();
    const btn = document.getElementById('cfAiRunBtn');
    const msg = document.getElementById('cfAiMsg');
    const vocabulary = !!((_cfMeta && _cfMeta.disciplines) || []).length;
    if (vocabulary ? !_cf.ai.discipline : !_cf.ai.field) {
        if (msg) msg.textContent = vocabulary ? 'Pick a subject area first.' : 'Enter your field of study.';
        return;
    }
    if (_cf.ai.discipline === 'Other' && !_cf.ai.field) {
        if (msg) msg.textContent = 'For “Other”, add the specific course you mean.';
        return;
    }
    const budgetProblem = cfBudgetProblem(_cf.ai.budget);
    if (budgetProblem) { if (msg) msg.textContent = budgetProblem; return; }
    if (msg) msg.textContent = '';
    if (btn) btn.disabled = true;
    const progress = startAiProgress((t) => { if (btn) btn.textContent = t; }, 'Building your shortlist…');
    try {
        const res = await coursesFetch('/recommend', {
            method: 'POST',
            timeoutMs: CF_AI_TIMEOUT_MS,
            body: {
                country_code: _cf.country,
                degree_level: _cf.ai.level || null,
                discipline: _cf.ai.discipline || null,
                field_of_study: _cf.ai.field || null,
                budget: _cf.ai.budget || null,
                gpa: _cf.ai.gpa || null,
                test_scores: _cf.ai.scores || null,
                notes: _cf.ai.notes || null,
                max_results: 6,
            },
        });
        _cf.activeRec = res.rec || null;
        _cf.savedIdx = {};
        if (res.entitlement && _cfMeta) _cfMeta.entitlement = res.entitlement;
        // The run takes 30-150s and the user may have switched to Browse (both tabs
        // share #cfPanel) — only repaint when the AI tab is still the active one;
        // the updated state renders on the next cfSetTab('ai') either way.
        if (_cf.tab === 'ai') { cfRenderAI(); cfLoadHistory(); }
        else showMessage('Your Course Finder shortlist is ready — open the AI shortlist tab.', 'success');
    } catch (e) {
        if (e.status === 402) {
            // The banner said "N left" — refresh the entitlement so it and the
            // upsell note agree with the 402 the server just returned.
            try { _cfMeta = await coursesFetch('/meta'); } catch (ignored) { /* keep stale meta */ }
            if (_cf.tab === 'ai') cfRenderAI();
        }
        const text = e.status === 402
            ? 'Limit reached — get the Visa Pass for more Course Finder runs.'
            : (e.message || 'Could not generate a shortlist.');
        // Re-query the message node: cfRenderAI() above (or a tab switch mid-run)
        // detaches the one captured at click time. Off-tab errors go to the global
        // toast so a 402/timeout is never silent.
        const liveMsg = document.getElementById('cfAiMsg');
        if (_cf.tab === 'ai' && liveMsg) liveMsg.textContent = text;
        else if (_cf.tab !== 'ai') showMessage(text, 'error');
        // A timed-out run may still have completed (and consumed quota) server-side —
        // refresh history so a metered result is never invisible.
        if (_cf.tab === 'ai') cfLoadHistory();
    } finally {
        progress.stop();
        const liveBtn = document.getElementById('cfAiRunBtn');
        if (liveBtn) { liveBtn.disabled = false; liveBtn.textContent = 'Generate shortlist'; }
    }
}

// Free tier: the server returns every pick past the visible window as {locked, fit_level}
// only — nothing here is real data, so the blur is cosmetic on top of a real gate. The fit
// pill stays readable as the teaser; the body is deliberately worded as "hidden", never as
// a plausible sentence about the course (find-in-page and reader mode see through blur).
function cfLockedRecCardHtml(it, index, rec) {
    const fit = CF_FIT[it.fit_level];
    const pill = fit
        ? `<span title="${escapeAttr(fit.hint)}" style="font-size:10.5px;font-weight:700;color:#fff;background:${fit.color};border-radius:999px;padding:3px 10px">${fit.label}</span>`
        : '';
    const level = cfLevelLabel(rec && rec.degree_level) || 'Program';
    const chip = (t) => `<span style="font-size:11px;background:#f1f5f9;color:#334155;border-radius:999px;padding:2px 9px">${t}</span>`;
    return `<div role="group" aria-label="Hidden pick ${index + 1}" style="background:#ffffff;border:1px dashed #cbd5e1;border-radius:14px;padding:14px 16px">
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">${pill}<span style="font-size:10.5px;font-weight:700;color:#64748b">🔒 Pick ${index + 1}</span></div>
        <div style="position:relative">
          <div aria-hidden="true" style="filter:blur(5px);user-select:none;pointer-events:none">
            <div style="font-weight:700;color:#0f172a;margin-top:6px">${escapeHtml(level)} — name hidden</div>
            <div style="font-size:12.5px;color:#64748b">University hidden · Location hidden</div>
            <div style="font-size:12.5px;color:#334155;margin-top:6px">Why this pick fits your profile is hidden on the free plan. Unlock the pass to read the reasoning, fees, intakes and entry requirements.</div>
            <div style="font-size:12px;color:#64748b;margin-top:6px">Tuition hidden · Intakes hidden · Deadline hidden</div>
            <div style="display:flex;gap:5px;flex-wrap:wrap;margin-top:7px">${chip('Requirement hidden')}${chip('Requirement hidden')}</div>
          </div>
          <div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;padding:12px;text-align:center;background:linear-gradient(180deg,rgba(255,255,255,.3),rgba(255,255,255,.88))">
            <div style="font-weight:800;color:#0f172a;font-size:13px">Hidden on the free plan</div>
            <a href="/visa-pass" onclick="handleUpgradeToPro('course_finder'); return false;" aria-label="Get the Visa Success Pass to unlock pick ${index + 1}" style="background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;border-radius:9px;padding:7px 14px;font-weight:700;font-size:12px;text-decoration:none">Unlock with the Visa Success Pass</a>
          </div>
        </div>
      </div>`;
}

// One purchase banner, rendered as a full-width grid row between the picks the student
// got and the ones they didn't — so they see their real results first.
function cfLockedBannerHtml(rec) {
    const n = rec.locked_count;
    return `<div style="grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;background:linear-gradient(135deg,rgba(99,102,241,.08),rgba(168,85,247,.08));border:1px solid rgba(99,102,241,.25);border-radius:12px;padding:10px 14px">
        <div style="font-size:13px;color:#0f172a"><strong>🔒 ${n} more pick${n === 1 ? '' : 's'} hidden on the free plan.</strong> The Visa Success Pass unlocks every pick in this shortlist — and in the ones you run next.</div>
        <a href="/visa-pass" onclick="handleUpgradeToPro('course_finder'); return false;" style="background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;border-radius:9px;padding:8px 16px;font-weight:700;font-size:12.5px;text-decoration:none;white-space:nowrap">Get the Visa Success Pass</a>
      </div>`;
}

function cfActiveRecHtml(rec) {
    const items = rec.recommendations || [];
    const srcBadge = rec.catalog_based
        ? '<span style="font-size:11px;font-weight:700;color:#065f46;background:rgba(6,95,70,.08);border-radius:999px;padding:2px 9px">✓ Catalog data</span>'
        : '<span style="font-size:11px;font-weight:700;color:#1d4ed8;background:rgba(29,78,216,.08);border-radius:999px;padding:2px 9px">🌐 Live research</span>';
    const cards = items.map((it, i) => {
        if (it && it.locked) return cfLockedRecCardHtml(it, i, rec);
        const fit = CF_FIT[it.fit_level] || CF_FIT.match;
        const site = cfSafeUrl(it.website_url);
        const page = cfSafeUrl(it.course_url);
        const facts = [it.annual_tuition, it.intakes ? `Intakes: ${it.intakes}` : '', it.application_deadline ? `Deadline: ${it.application_deadline}` : '', it.application_fee ? `Fee: ${it.application_fee}` : '']
            .filter(Boolean).map((f) => `<span>${escapeHtml(f)}</span>`).join(' · ');
        const saved = Boolean(_cf.savedIdx[i]);
        return `<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:14px;padding:14px 16px">
            <div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap">
              <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
                <span title="${escapeAttr(fit.hint)}" style="font-size:10.5px;font-weight:700;color:#fff;background:${fit.color};border-radius:999px;padding:3px 10px">${fit.label}</span>
                ${it.in_catalog ? '<span style="font-size:10.5px;font-weight:700;color:#065f46">✓ Verified</span>' : '<span style="font-size:10.5px;font-weight:700;color:#b45309" title="Double-check details on the official page">Verify on official page</span>'}
                ${it.qs_world_rank ? `<span style="font-size:10.5px;color:#b45309;font-weight:700">🏆 QS ${escapeHtml(it.qs_world_rank)}</span>` : ''}
              </div>
            </div>
            <div style="font-weight:700;color:#0f172a;margin-top:6px">${escapeHtml(it.course_name || '')}</div>
            <div style="font-size:12.5px;color:#64748b">${escapeHtml([it.university_name, it.location].filter(Boolean).join(' · '))}</div>
            ${it.why_recommended ? `<div style="font-size:12.5px;color:#334155;margin-top:6px">${escapeHtml(it.why_recommended)}</div>` : ''}
            ${facts ? `<div style="font-size:12px;color:#64748b;margin-top:6px">${facts}</div>` : ''}
            ${(it.key_requirements && it.key_requirements.length) ? `<div style="display:flex;gap:5px;flex-wrap:wrap;margin-top:7px">${it.key_requirements.map((r) => `<span style="font-size:11px;background:#f1f5f9;color:#334155;border-radius:999px;padding:2px 9px">${escapeHtml(r)}</span>`).join('')}</div>` : ''}
            <div style="display:flex;gap:12px;align-items:center;margin-top:10px;flex-wrap:wrap">
              ${page ? `<a href="${escapeAttr(page)}" target="_blank" rel="noopener" style="font-size:12px;color:#4f46e5;font-weight:700">Course page ↗</a>` : ''}
              ${site ? `<a href="${escapeAttr(site)}" target="_blank" rel="noopener" style="font-size:12px;color:#4f46e5;font-weight:700">Website ↗</a>` : ''}
              <button onclick="cfSaveRecItem(${i})" ${saved ? 'disabled' : ''} style="margin-left:auto;background:${saved ? '#dcfce7' : '#f1f5f9'};color:${saved ? '#065f46' : '#0f172a'};border:1px solid #e2e8f0;border-radius:9px;padding:7px 14px;font-weight:700;font-size:12px;cursor:${saved ? 'default' : 'pointer'}">${saved ? '✓ Added' : '+ Add to my shortlist'}</button>
            </div>
          </div>`;
    });
    const firstLocked = items.findIndex((it) => it && it.locked);
    if (rec.locked_count > 0 && firstLocked >= 0) cards.splice(firstLocked, 0, cfLockedBannerHtml(rec));
    return CF_CARD(`
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px">
          <div style="font-weight:800;font-size:15px;color:#0f172a">Your shortlist${rec.query && rec.query.field_of_study ? ` — ${escapeHtml(rec.query.field_of_study)}` : ''}</div>
          ${srcBadge}
        </div>
        ${rec.summary ? `<div style="font-size:13px;color:#334155;margin-bottom:12px">${escapeHtml(rec.summary)}</div>` : ''}
        <div style="font-size:12px;color:#64748b;margin:0 0 10px">High / Medium / Low chance is Rilono AI's estimate from the profile you entered — not an admission decision. A good shortlist mixes all three.</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px">${cards.join('')}</div>`);
}

async function cfSaveRecItem(index) {
    const rec = _cf.activeRec;
    if (!rec) return;
    try {
        const res = await coursesFetch(`/recs/${rec.id}/save`, { method: 'POST', body: { index } });
        _cf.savedIdx[index] = true;
        const el = document.getElementById('cfActiveRec');
        if (el) el.innerHTML = cfActiveRecHtml(rec);
        showMessage(res.already_saved ? 'Already on your shortlist.' : 'Added to your shortlist.', 'success');
    } catch (e) {
        showMessage(e.message || 'Could not save to your shortlist.', 'error');
        // 402 here means the pass lapsed since this shortlist was fetched unmasked —
        // re-fetch so the cards the server now hides stop looking saveable.
        if (e.status === 402 && rec.id) cfOpenRec(rec.id);
    }
}

async function cfLoadHistory() {
    const el = document.getElementById('cfHistory');
    if (!el) return;
    let data;
    try {
        data = await coursesFetch('/recs?limit=20');
    } catch (e) { return; }
    _cf.recs = data.recs || [];
    if (!_cf.recs.length) { el.innerHTML = ''; return; }
    const rows = _cf.recs.map((r) => {
        const when = r.created_at ? new Date(r.created_at).toLocaleDateString() : '';
        const bits = [r.country_code, cfLevelLabel(r.degree_level), r.discipline, (r.query || {}).field_of_study]
            .filter(Boolean).map((b) => escapeHtml(String(b))).join(' · ');
        return `<div onclick="cfOpenRec(${r.id})" style="display:flex;justify-content:space-between;gap:10px;padding:10px 0;border-bottom:1px solid #f1f5f9;cursor:pointer">
            <div style="min-width:0">
              <div style="font-weight:600;color:#0f172a;font-size:13px">${bits || 'Course shortlist'}</div>
              <div style="font-size:11.5px;color:#94a3b8">${r.locked_count > 0 ? `${r.count - r.locked_count} of ${r.count} picks visible` : `${r.count} picks`} · ${r.catalog_based ? 'catalog data' : 'live research'}</div>
            </div>
            <span style="font-size:11.5px;color:#94a3b8;white-space:nowrap">${escapeHtml(when)}</span>
          </div>`;
    }).join('');
    el.innerHTML = CF_CARD(`
        <div style="font-weight:800;font-size:14px;color:#0f172a;margin-bottom:4px">Your past shortlists</div>
        <div style="font-size:12px;color:#64748b;margin-bottom:6px">Every run is saved — a metered shortlist is never lost.</div>
        ${rows}`);
}

// A pass bought mid-session: the open shortlist was served masked, so re-fetch it (the
// server now reveals every pick) and refresh the entitlement chip + disclosure line.
// Called from the subscription-change notifier; a no-op if Course Finder was never opened.
async function cfOnPassActivated() {
    try {
        if (_cfMeta) _cfMeta = await coursesFetch('/meta');
        if (_cf.activeRec && _cf.activeRec.locked_count > 0 && _cf.activeRec.id) {
            const data = await coursesFetch(`/recs/${_cf.activeRec.id}`);
            if (data && data.rec) _cf.activeRec = data.rec;
        }
        if (_cf.tab === 'ai' && document.getElementById('cfPanel')) { cfRenderAI(); cfLoadHistory(); }
    } catch (e) { /* the next tab open re-fetches anyway */ }
}

async function cfOpenRec(recId) {
    try {
        const data = await coursesFetch(`/recs/${recId}`);
        _cf.activeRec = data.rec || null;
        _cf.savedIdx = {};
        const el = document.getElementById('cfActiveRec');
        if (el) {
            el.innerHTML = _cf.activeRec ? cfActiveRecHtml(_cf.activeRec) : '';
            el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    } catch (e) { showMessage(e.message || 'Could not open that shortlist.', 'error'); }
}

// Per-destination heading for the dashboard journey tracker.
const JOURNEY_HEADINGS = {
    US: '🎓 Your US study-abroad journey',
    UK: '🎓 Your UK study-abroad journey',
    CA: '🎓 Your Canada study-abroad journey',
    AU: '🎓 Your Australia study-abroad journey',
    DE: '🎓 Your Germany study-abroad journey',
};
function updateVisaJourneyHeading() {
    const el = document.getElementById('visaJourneyHeading');
    if (!el) return;
    const code = (currentUser && currentUser.destination_country_code) || 'US';
    el.textContent = JOURNEY_HEADINGS[code] || '🎓 Your study-abroad journey';
}

// Per-destination phrases for the AI assistant copy. US keeps its F-1 wording; other countries adapt.
const VISA_JOURNEY_PHRASE = { US: 'F-1 visa', UK: 'UK student visa', CA: 'Canada study permit', AU: 'Australian student visa', DE: 'German student visa' };
function currentVisaJourneyPhrase() {
    const code = (currentUser && currentUser.destination_country_code) || 'US';
    return VISA_JOURNEY_PHRASE[code] || 'student visa';
}
// Country-aware "current stage" examples for AI prompts (US: I-20/DS-160… ; CA: LOA/PAL… ;
// AU: CoE/GS… ) — pulled from COPILOT_TAB_COPY so we never show US F-1 stage names to a
// UK/CA/AU/DE student. Evaluated at call time (COPILOT_TAB_COPY is defined just below).
function currentVisaStagesPhrase() {
    const code = (currentUser && currentUser.destination_country_code) || 'US';
    return (COPILOT_TAB_COPY[code] || COPILOT_TAB_COPY.US).stages;
}
// Shorter visa prefix used inside the interviews module (the sidebar is narrow).
// Title-case twin of VISA_JOURNEY_PHRASE / VISA_INTERVIEW_CONTEXT — the page headers must name
// the visa exactly the way the coaching placeholder, chat tooltip and AI persona do.
const VISA_INTERVIEW_PREFIX = { US: 'F-1 Visa', UK: 'UK Student Visa', CA: 'Canada Study Permit', AU: 'Australian Student Visa', DE: 'German Student Visa' };

// Rilono Copilot tab + AI-chat welcome copy per destination (the HTML defaults to US F-1 wording).
const COPILOT_TAB_COPY = {
    US: {
        what1: "Rilono Copilot is a Chrome side-panel assistant for students navigating F-1 visa applications. It helps you move through active forms step by step with context-aware guidance.",
        what2: "It focuses on application workflows like DS-160, university I-20 requests, and related health/onboarding forms, while helping you maintain answer consistency and submission accuracy.",
        where: ['DS-160 and visa appointment workflows', 'University I-20 request portals', 'Health and onboarding forms in your F-1 journey', 'Any application pages where you need guided field-by-field help'],
        stages: 'I-20, DS-160, fees, or interview',
    },
    UK: {
        what1: "Rilono Copilot is a Chrome side-panel assistant for students navigating the UK Student visa application. It helps you move through active forms step by step with context-aware guidance.",
        what2: "It focuses on application workflows like the GOV.UK Student visa form, CAS details and the IHS payment, while helping you maintain answer consistency and submission accuracy.",
        where: ['GOV.UK Student visa application pages', 'CAS details and sponsor information', 'IHS payment and financial-evidence steps', 'Any application pages where you need guided field-by-field help'],
        stages: 'CAS, visa application, IHS, or interview',
    },
    CA: {
        what1: "Rilono Copilot is a Chrome side-panel assistant for students navigating the Canada study permit application. It helps you move through active forms step by step with context-aware guidance.",
        what2: "It focuses on application workflows like IRCC's IMM 1294 form, LOA and PAL details, and GIC / proof-of-funds steps, while helping you maintain answer consistency and submission accuracy.",
        where: ['IRCC secure account and IMM 1294 study-permit forms', 'LOA and Provincial Attestation Letter (PAL) details', 'GIC and proof-of-funds steps', 'Any application pages where you need guided field-by-field help'],
        stages: 'LOA, PAL, proof of funds, or biometrics',
    },
    AU: {
        what1: "Rilono Copilot is a Chrome side-panel assistant for students navigating the Australia Subclass 500 student visa application. It helps you move through active forms step by step with context-aware guidance.",
        what2: "It focuses on application workflows like the ImmiAccount Subclass 500 form, CoE and OSHC details, and your Genuine Student answers, while helping you maintain answer consistency and submission accuracy.",
        where: ['ImmiAccount Subclass 500 application pages', 'CoE and OSHC details', 'Genuine Student (GS) responses', 'Any application pages where you need guided field-by-field help'],
        stages: 'CoE, GS statement, OSHC, or lodgement',
    },
    DE: {
        what1: "Rilono Copilot is a Chrome side-panel assistant for students navigating the German student visa (National Visa Type D) application. It helps you move through active forms step by step with context-aware guidance.",
        what2: "It focuses on application workflows like the VIDEX national-visa form, university admission and blocked-account (Sperrkonto) steps, and APS verification, while helping you maintain answer consistency and submission accuracy.",
        where: ['VIDEX national-visa application pages', 'uni-assist and university admission portals', 'Blocked account (Sperrkonto) and health-insurance steps', 'Any application pages where you need guided field-by-field help'],
        stages: 'admission, blocked account, APS, or appointment',
    },
};
function updateVisaSectionLabels() {
    const code = (currentUser && currentUser.destination_country_code) || 'US';
    const setText = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
    const label = 'Interview Prep';
    setText('visaNavLabel', label);
    setText('visaSectionHeading', label);

    // Interviews module titles carry the destination's visa name; the sidebar sub-nav
    // does NOT — it sits under "Interview Prep" in a narrow column, and "UK Student Visa
    // Interview Prep (Rilono AI)" / "UK Student Visa Mock Interview (Rilono AI)" wrapped
    // to three lines each and repeated the visa name three times on one screen.
    const prefix = VISA_INTERVIEW_PREFIX[code] || 'Student Visa';
    setText('subnavLabelPrep', 'Guided Prep (Rilono AI)');
    setText('subnavLabelMock', 'Mock Interview (Rilono AI)');
    setText('prepModuleTitle', `🎯 ${prefix} Interview Prep (Rilono AI)`);
    setText('mockModuleTitle', `🧠 ${prefix} Mock Interview (Rilono AI)`);
    setText('prepCoachingPlaceholder', `Start Prep Session to begin a guided ${currentVisaJourneyPhrase()} interview coaching flow.`);
    // Experiences tab: US keeps consular interview wording; other destinations get
    // applicant-experience wording about their own visa process.
    const expLabel = code === 'US' ? 'Recent Interview Experiences' : 'Recent Applicant Experiences';
    setText('subnavLabelExperiences', expLabel);
    setText('experiencesModuleTitle', `📚 ${expLabel}`);

    // Rilono Copilot tab copy (the HTML defaults to US F-1 wording).
    const cop = COPILOT_TAB_COPY[code] || COPILOT_TAB_COPY.US;
    setText('copilotWhatCopy1', cop.what1);
    setText('copilotWhatCopy2', cop.what2);
    const whereEl = document.getElementById('copilotWhereList');
    if (whereEl) whereEl.innerHTML = cop.where.map((w) => `<li>${escapeHtml(w)}</li>`).join('');

    // AI-chat welcome "current stage" hint (floating chat + Rilono AI tab copies).
    document.querySelectorAll('.ai-stage-hint').forEach((el) => {
        el.textContent = `Tell me your current stage (${cop.stages}), and I'll suggest your best next step.`;
    });

    // Keep the floating assistant tooltip on-brand for the student's destination.
    try {
        if (Array.isArray(floatingChatMessages) && floatingChatMessages.length) {
            floatingChatMessages[0] = `Hey! I'm Rilono AI Assistant. Let's talk about your ${currentVisaJourneyPhrase()} journey.`;
        }
    } catch (e) { /* floatingChatMessages not initialized yet */ }
    updateSettingsCountryLabel();
}

const COUNTRY_DISPLAY = {
    US: { flag: '🇺🇸', name: 'United States' },
    UK: { flag: '🇬🇧', name: 'United Kingdom' },
    CA: { flag: '🇨🇦', name: 'Canada' },
    AU: { flag: '🇦🇺', name: 'Australia' },
    DE: { flag: '🇩🇪', name: 'Germany' },
};

function updateSettingsCountryLabel() {
    const el = document.getElementById('settingsCurrentCountry');
    if (!el || !currentUser) return;
    const code = currentUser.destination_country_code || 'US';
    const d = COUNTRY_DISPLAY[code] || { flag: '', name: code };
    // Country renders immediately; the visa-type label is appended once the
    // onboarding catalog (which owns the human-readable labels) is available.
    el.textContent = ` Currently: ${d.flag} ${d.name}.`;
    const visaKey = currentUser.visa_type_key || '';
    if (!visaKey) return;
    void ensureOnboardingCatalog().then((cat) => {
        const country = ((cat && cat.countries) || []).find((c) => c.code === code);
        const visa = country && (country.visa_types || []).find((v) => v.key === visaKey);
        // Guard against a stale async update if the user/country changed meanwhile.
        if (visa && currentUser && (currentUser.destination_country_code || 'US') === code) {
            el.textContent = ` Currently: ${d.flag} ${d.name} · ${visa.label}.`;
        }
    });
}

async function ensureOnboardingCatalog() {
    if (_onboardingCatalog && _onboardingCatalog.countries) return _onboardingCatalog;
    try {
        const r = await fetch(`${API_BASE}/api/onboarding/catalog`, { credentials: 'include' });
        _onboardingCatalog = await r.json();
    } catch (e) { _onboardingCatalog = { countries: [] }; }
    return _onboardingCatalog;
}

// Change destination country from Settings — requires an emailed OTP, then re-scopes
// the whole dashboard and prunes country-specific documents server-side.
async function openCountryChangeModal() {
    if (!currentUser) { showMessage('Please login first.', 'error'); return; }
    if (document.getElementById('countryChangeOverlay')) return;
    const cat = await ensureOnboardingCatalog();
    const countries = (cat && cat.countries) || [];
    const curCode = currentUser.destination_country_code || 'US';
    const curName = (COUNTRY_DISPLAY[curCode] || {}).name || curCode;

    const inp = 'width:100%;box-sizing:border-box;background:#fff;border:1px solid #e2e8f0;border-radius:11px;color:#0f172a;font-size:14px;padding:11px 12px';
    const lbl = (t) => `<div style="font-size:12px;font-weight:700;color:#64748b;margin:0 0 6px">${t}</div>`;
    // Name the CURRENT country's signature documents (not always US I-20/DS-160) so the
    // "will be removed" warning is accurate for whichever destination the student is on.
    const CC_DOC_EXAMPLES = { US: 'I-20, DS-160, SEVIS receipt', UK: 'CAS, IHS receipt', CA: 'LOA, PAL, biometrics receipt', AU: 'CoE, OSHC, Genuine Student answers', DE: 'admission letter, blocked-account proof' };
    const curDocExamples = CC_DOC_EXAMPLES[curCode] || 'your country-specific enrolment and visa documents';
    const countryOpts = countries.map((c) => `<option value="${escapeHtml(c.code)}"${c.code === curCode ? ' selected' : ''}>${(c.flag_emoji || '')} ${escapeHtml(c.name)}</option>`).join('');

    const overlay = document.createElement('div');
    overlay.id = 'countryChangeOverlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:11200;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(5,6,15,.8);backdrop-filter:blur(6px);overflow-y:auto';
    overlay.innerHTML = `
      <div style="width:min(520px,100%);background:#fff;border:1px solid #e2e8f0;border-radius:20px;box-shadow:0 30px 90px rgba(0,0,0,.5);overflow:hidden;color:#0f172a">
        <div style="padding:24px 26px 6px">
          <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#64748b;font-weight:700">Profile · Destination</div>
          <h2 style="margin:8px 0 4px;font-size:22px;font-weight:800">Change destination country</h2>
          <p style="margin:0;font-size:13.5px;color:#64748b">Currently <strong>${escapeHtml(curName)}</strong>. Pick your new destination — we'll email a code to confirm.</p>
        </div>
        <div style="padding:16px 26px 4px">
          <div style="margin-bottom:12px">${lbl('New destination country')}<select id="ccCountry" style="${inp}">${countryOpts}</select></div>
          <div style="margin-bottom:12px">${lbl('Visa type')}<select id="ccVisa" style="${inp}"></select></div>
          <div style="background:#fef9c3;border:1px solid #fde68a;border-radius:10px;padding:10px 12px;font-size:12.5px;color:#854d0e;line-height:1.5">
            Your <strong>passport and personal documents</strong> (transcripts, test scores, finances, SOP) are kept. Documents specific to ${escapeHtml(curName)} — like ${escapeHtml(curDocExamples)} — will be <strong>removed</strong>.
          </div>
          <div id="ccOtpRow" style="display:none;margin-top:12px">${lbl('Enter the 6-digit code we emailed you')}<input id="ccCode" inputmode="numeric" maxlength="6" placeholder="••••••" style="${inp};letter-spacing:8px;text-align:center;font-size:18px"></div>
        </div>
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 26px 22px">
          <button id="ccCancel" style="border:none;background:transparent;color:#64748b;font-size:14px;font-weight:600;cursor:pointer">Cancel</button>
          <div style="display:flex;align-items:center;gap:10px">
            <span id="ccMsg" style="font-size:12.5px;color:#be123c;max-width:170px"></span>
            <button id="ccAction" style="border:none;border-radius:11px;padding:11px 20px;font-size:14px;font-weight:700;color:#fff;background:linear-gradient(135deg,#6366f1,#a855f7);cursor:pointer">Send code</button>
          </div>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';

    const countrySel = overlay.querySelector('#ccCountry');
    const visaSel = overlay.querySelector('#ccVisa');
    const otpRow = overlay.querySelector('#ccOtpRow');
    const codeInput = overlay.querySelector('#ccCode');
    const action = overlay.querySelector('#ccAction');
    const msg = overlay.querySelector('#ccMsg');
    let codeSent = false;

    const fillVisa = () => {
        const c = countries.find((x) => x.code === countrySel.value);
        visaSel.innerHTML = c ? c.visa_types.map((v) => `<option value="${escapeHtml(v.key)}"${v.default ? ' selected' : ''}>${escapeHtml(v.label)}</option>`).join('') : '';
    };
    const resetToSend = () => { codeSent = false; otpRow.style.display = 'none'; action.textContent = 'Send code'; msg.textContent = ''; };
    fillVisa();
    countrySel.addEventListener('change', () => { fillVisa(); resetToSend(); });
    visaSel.addEventListener('change', resetToSend);

    const close = () => { overlay.remove(); document.body.style.overflow = ''; };
    overlay.querySelector('#ccCancel').addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

    const authHeaders = (authToken && authToken !== COOKIE_AUTH_SENTINEL) ? { 'Authorization': `Bearer ${authToken}` } : {};

    action.addEventListener('click', async () => {
        msg.textContent = '';
        if (!codeSent) {
            if (countrySel.value === (currentUser.destination_country_code || '') && visaSel.value === (currentUser.visa_type_key || '')) {
                msg.textContent = 'That is already your destination.'; return;
            }
            action.disabled = true; action.textContent = 'Sending…';
            try {
                const res = await fetch(`${API_BASE}/api/profile/country/request-code`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders }, credentials: 'include',
                    body: JSON.stringify({ destination_country_code: countrySel.value, visa_type_key: visaSel.value }),
                });
                const data = await res.json().catch(() => ({}));
                if (res.status === 401) { showMessage('Session expired. Please login again.', 'error'); close(); logout(); return; }
                if (!res.ok) { msg.textContent = (data && data.detail) || 'Could not send code.'; action.disabled = false; action.textContent = 'Send code'; return; }
                codeSent = true; otpRow.style.display = 'block'; action.disabled = false; action.textContent = 'Confirm change'; codeInput.focus();
                showMessage('We emailed a confirmation code to your account email.', 'success');
            } catch (e) { msg.textContent = 'Network error.'; action.disabled = false; action.textContent = 'Send code'; }
        } else {
            const code = (codeInput.value || '').replace(/\D/g, '');
            if (code.length !== 6) { msg.textContent = 'Enter the 6-digit code.'; return; }
            action.disabled = true; action.textContent = 'Confirming…';
            try {
                const res = await fetch(`${API_BASE}/api/profile/country/confirm`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders }, credentials: 'include',
                    body: JSON.stringify({ code }),
                });
                const data = await res.json().catch(() => ({}));
                if (res.status === 401) { showMessage('Session expired. Please login again.', 'error'); close(); logout(); return; }
                if (!res.ok) { msg.textContent = (data && data.detail) || 'Could not confirm.'; action.disabled = false; action.textContent = 'Confirm change'; return; }
                if (data && data.destination_country_code) currentUser = data;
                close();
                const newName = (COUNTRY_DISPLAY[countrySel.value] || {}).name || countrySel.value;
                showMessage(`Destination updated to ${newName}. Reloading your dashboard…`, 'success');
                // A country change re-scopes the entire dashboard (journey, checklist, AI); a
                // reload guarantees every panel reflects the new country with no stale state.
                setTimeout(() => window.location.reload(), 900);
            } catch (e) { msg.textContent = 'Network error.'; action.disabled = false; action.textContent = 'Confirm change'; }
        }
    });
}

function showDashboard(skipURLUpdate = false) {
    if (!currentUser) {
        showMessage('Please login to view dashboard', 'error');
        showLogin();
        return;
    }
    syncDocumentTitle('/dashboard');
    if (needsOnboarding()) {
        showOnboardingWizard();
        return;
    }
    updateVisaJourneyHeading();
    updateVisaSectionLabels();
    hideAllSections();
    document.getElementById('dashboardSection').style.display = 'block';
    const navbar = document.querySelector('.navbar');
    const footer = document.querySelector('footer');
    if (navbar) navbar.style.display = 'none';
    if (footer) footer.style.display = 'none';
    document.body.classList.add('dashboard-active');
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
    updateDashHeaderUser();
    if (typeof maybeShowHeardAbout === 'function') queuePostLoginPrompt(maybeShowHeardAbout);
    if (typeof loadVisaDecisionPrompt === 'function') void loadVisaDecisionPrompt();

    // Set default tab to overview if no tab is active
    const activeTab = document.querySelector('.dashboard-tab.active');
    if (!activeTab) {
        switchDashboardTab('overview');
    }

    if (!skipURLUpdate) {
        updateURL('/dashboard', false);
    }
}

function showSubscription(skipURLUpdate = false) {
    if (!currentUser) {
        showMessage('Please login to manage your subscription', 'error');
        showLogin();
        return;
    }

    showDashboard(true);
    switchDashboardTab('subscription');

    if (!skipURLUpdate) {
        updateURL('/subscription', false);
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

        const nextSubscription = await response.json();
        const previousSubscription = currentSubscription;
        currentSubscription = nextSubscription;
        maybeAddSubscriptionChangeNotifications(previousSubscription, currentSubscription);
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

function formatWindowUsageText(used, limit, metricLabel, windowHours = 24) {
    if (limit < 0) {
        return `${metricLabel}: Unlimited`;
    }
    return `${metricLabel} (${windowHours}h): ${used}/${limit} used`;
}

function formatSubscriptionDateTime(value) {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '-';
    return date.toLocaleString();
}

function getSubscriptionNotifyStorageKeyForUser(userId) {
    if (!userId) return null;
    return `rilono_subscription_notify_state_${userId}`;
}

function readStoredSubscriptionNotifyState(userId) {
    const key = getSubscriptionNotifyStorageKeyForUser(userId);
    if (!key) return null;
    try {
        const raw = localStorage.getItem(key);
        return raw ? JSON.parse(raw) : null;
    } catch (error) {
        console.warn('Failed to read subscription notification state:', error);
        return null;
    }
}

function writeStoredSubscriptionNotifyState(userId, snapshot) {
    const key = getSubscriptionNotifyStorageKeyForUser(userId);
    if (!key) return;
    try {
        if (snapshot) {
            localStorage.setItem(key, JSON.stringify(snapshot));
        } else {
            localStorage.removeItem(key);
        }
    } catch (error) {
        console.warn('Failed to persist subscription notification state:', error);
    }
}

function buildSubscriptionNotifySnapshot(subscription) {
    if (!subscription) return null;
    return {
        plan: subscription.is_pro ? 'pro' : 'free',
        status: String(subscription.status || 'active').toLowerCase(),
        autoRenewEnabled: typeof subscription.auto_renew_enabled === 'boolean'
            ? subscription.auto_renew_enabled
            : null,
        endsAt: subscription.ends_at || null,
        nextRenewalAt: subscription.next_renewal_at || null,
        referralBonusActive: Boolean(subscription.referral_bonus_active),
        latestPaymentStatus: String(subscription.latest_payment_status || '').toLowerCase(),
        latestPaymentAmountPaise: Number(subscription.latest_payment_amount_paise || 0),
        // NOT defaulted to INR. `latest_payment_amount_paise` is minor units of the row's
        // OWN currency, so guessing "INR" stamps a ₹ on what may be cents — a ~80× misquote
        // in a notification the buyer reads right after being charged. An absent currency
        // means "unknown", and an unknown-currency amount is simply not shown.
        latestPaymentCurrency: String(subscription.latest_payment_currency || '').toUpperCase()
    };
}

function mergeSubscriptionNotifySnapshots(previousSnapshot, nextSnapshot) {
    if (!nextSnapshot) return null;
    if (!previousSnapshot) return nextSnapshot;

    const merged = { ...nextSnapshot };

    // Some endpoints return partial subscription payloads and omit renewal/payment metadata.
    // Preserve known values so follow-up /me fetches do not emit duplicate transition notifications.
    if (merged.autoRenewEnabled === null && typeof previousSnapshot.autoRenewEnabled === 'boolean') {
        merged.autoRenewEnabled = previousSnapshot.autoRenewEnabled;
    }
    if (!merged.nextRenewalAt && previousSnapshot.nextRenewalAt) {
        merged.nextRenewalAt = previousSnapshot.nextRenewalAt;
    }
    if (!merged.latestPaymentStatus && previousSnapshot.latestPaymentStatus) {
        merged.latestPaymentStatus = previousSnapshot.latestPaymentStatus;
        merged.latestPaymentAmountPaise = previousSnapshot.latestPaymentAmountPaise;
        merged.latestPaymentCurrency = previousSnapshot.latestPaymentCurrency;
    }

    return merged;
}

function syncSubscriptionNotificationStateUser() {
    const activeUserId = currentUser?.id ? String(currentUser.id) : null;
    if (activeUserId === subscriptionNotifyStateUserId) {
        return;
    }
    subscriptionNotifyStateUserId = activeUserId;
    runtimeSubscriptionNotifyState = activeUserId
        ? readStoredSubscriptionNotifyState(activeUserId)
        : null;
}

function maybeAddSubscriptionChangeNotifications(previousSubscription, nextSubscription) {
    syncSubscriptionNotificationStateUser();
    const activeUserId = subscriptionNotifyStateUserId;
    if (!activeUserId) return;

    // Prefer runtime snapshot to avoid stale "previous" values from overlapping async loads.
    const previousSnapshot = runtimeSubscriptionNotifyState
        || buildSubscriptionNotifySnapshot(previousSubscription);
    const rawNextSnapshot = buildSubscriptionNotifySnapshot(nextSubscription);
    const nextSnapshot = mergeSubscriptionNotifySnapshots(previousSnapshot, rawNextSnapshot);

    if (!nextSnapshot) {
        runtimeSubscriptionNotifyState = null;
        writeStoredSubscriptionNotifyState(activeUserId, null);
        return;
    }

    if (!previousSnapshot) {
        runtimeSubscriptionNotifyState = nextSnapshot;
        writeStoredSubscriptionNotifyState(activeUserId, nextSnapshot);
        return;
    }

    const prevEncoded = JSON.stringify(previousSnapshot);
    const nextEncoded = JSON.stringify(nextSnapshot);
    if (prevEncoded === nextEncoded) {
        runtimeSubscriptionNotifyState = nextSnapshot;
        writeStoredSubscriptionNotifyState(activeUserId, nextSnapshot);
        return;
    }

    const accessUntilText = nextSnapshot.endsAt ? formatSubscriptionDateTime(nextSnapshot.endsAt) : '';

    if (previousSnapshot.plan !== nextSnapshot.plan) {
        if (nextSnapshot.plan === 'pro') {
            cfOnPassActivated();
            addNotification(
                'Visa Success Pass Active',
                'Your Visa Success Pass is now active. Premium features are unlocked.',
                'success'
            );
        } else {
            addNotification(
                'Plan Changed',
                'Your account is now on Free Plan.',
                'warning'
            );
        }
    }

    if (previousSnapshot.autoRenewEnabled !== nextSnapshot.autoRenewEnabled && nextSnapshot.plan === 'pro') {
        if (nextSnapshot.autoRenewEnabled === false) {
            addNotification(
                'Auto-Renew Disabled',
                accessUntilText
                    ? `Auto-renew is cancelled. Pro access continues until ${accessUntilText}.`
                    : 'Auto-renew is cancelled for your Pro plan.',
                'warning'
            );
        } else if (nextSnapshot.autoRenewEnabled === true) {
            addNotification(
                'Auto-Renew Enabled',
                'Your Pro auto-renew is enabled again.',
                'success'
            );
        }
    }

    if (previousSnapshot.status !== nextSnapshot.status) {
        if (nextSnapshot.status === 'active') {
            addNotification('Subscription Active', 'Your subscription status is active.', 'success');
        } else if (nextSnapshot.status === 'canceled') {
            addNotification(
                'Subscription Cancellation Scheduled',
                accessUntilText
                    ? `Your subscription will end on ${accessUntilText}.`
                    : 'Your subscription cancellation is scheduled.',
                'warning'
            );
        } else {
            addNotification(
                'Subscription Status Updated',
                `Your subscription status is now ${nextSnapshot.status}.`,
                'info'
            );
        }
    }

    if (!previousSnapshot.referralBonusActive && nextSnapshot.referralBonusActive) {
        addNotification(
            'Referral Bonus Applied',
            'Your free 30-day Visa Success Pass from a referral is now active on your account.',
            'success'
        );
    }

    if (previousSnapshot.latestPaymentStatus !== nextSnapshot.latestPaymentStatus && nextSnapshot.latestPaymentStatus) {
        // "Paise" is the legacy field name — the row holds minor units of its OWN currency,
        // so cents on a USD payment. Let the formatter apply the right exponent, and drop
        // the amount entirely when the currency is unknown: "Payment verified" with no
        // figure is correct, "(₹12.99)" for a $12.99 charge is not.
        const paymentAmount = (nextSnapshot.latestPaymentAmountPaise > 0 && nextSnapshot.latestPaymentCurrency)
            ? formatMoneyMinor(nextSnapshot.latestPaymentAmountPaise, nextSnapshot.latestPaymentCurrency)
            : '';
        const paymentText = paymentAmount ? ` (${paymentAmount})` : '';
        if (['verified', 'captured', 'paid', 'authorized'].includes(nextSnapshot.latestPaymentStatus)) {
            addNotification('Payment Verified', `Subscription payment verified${paymentText}.`, 'success');
        } else if (['failed', 'cancelled', 'refunded'].includes(nextSnapshot.latestPaymentStatus)) {
            addNotification('Payment Update', `Latest payment status: ${nextSnapshot.latestPaymentStatus}${paymentText}.`, 'error');
        } else {
            addNotification('Payment Update', `Latest payment status: ${nextSnapshot.latestPaymentStatus}${paymentText}.`, 'info');
        }
    }

    if (previousSnapshot.nextRenewalAt !== nextSnapshot.nextRenewalAt && nextSnapshot.autoRenewEnabled && nextSnapshot.nextRenewalAt) {
        addNotification(
            'Renewal Date Updated',
            `Your next renewal is on ${formatSubscriptionDateTime(nextSnapshot.nextRenewalAt)}.`,
            'info'
        );
    }

    if (previousSnapshot.endsAt !== nextSnapshot.endsAt && !nextSnapshot.autoRenewEnabled && nextSnapshot.endsAt) {
        addNotification(
            'Access Period Updated',
            `Your Visa Success Pass is active until ${formatSubscriptionDateTime(nextSnapshot.endsAt)}.`,
            'info'
        );
    }

    // Do not emit a generic fallback notification.
    // Only explicit, user-meaningful subscription changes should create notifications.

    runtimeSubscriptionNotifyState = nextSnapshot;
    writeStoredSubscriptionNotifyState(activeUserId, nextSnapshot);
}

function updatePricingFocusMode(isJourneyPassActive) {
    const pricingGridEl = document.querySelector('#pricingSection .pricing-grid');
    if (!pricingGridEl) return;
    pricingGridEl.classList.toggle('pricing-grid-journey-focus', Boolean(isJourneyPassActive));
}

function updateSubscriptionUI() {
    const planNameEl = document.getElementById('dashboardPlanName');
    const aiUsageEl = document.getElementById('dashboardPlanUsage');
    const chatUploadUsageEl = document.getElementById('dashboardChatUploadUsage');
    const uploadUsageEl = document.getElementById('dashboardUploadUsage');
    const prepUsageEl = document.getElementById('dashboardPrepUsage');
    const mockUsageEl = document.getElementById('dashboardMockUsage');
    const sidebarUpgradeButton = document.getElementById('dashboardUpgradeButton');
    const profileUpgradeButton = document.getElementById('profileSubscriptionUpgradeBtn');
    const profileSwitchMonthlyButton = document.getElementById('profileSubscriptionSwitchMonthlyBtn');
    const profileSwitchJourneyButton = document.getElementById('profileSubscriptionSwitchJourneyBtn');
    const profileCancelButton = document.getElementById('profileSubscriptionCancelBtn');
    const profileSwitchHintEl = document.getElementById('profileSubscriptionSwitchHint');
    const profilePlanEl = document.getElementById('profileSubscriptionPlan');
    const profileStatusEl = document.getElementById('profileSubscriptionStatus');
    const profileAutoRenewEl = document.getElementById('profileSubscriptionAutoRenew');
    const profileRenewalLabelEl = document.getElementById('profileSubscriptionRenewalLabel');
    const profileRenewalValueEl = document.getElementById('profileSubscriptionRenewalValue');
    const profileEndsLabelEl = document.getElementById('profileSubscriptionEndsLabel');
    const profileEndsAtEl = document.getElementById('profileSubscriptionEndsAt');
    const profileStartedAtEl = document.getElementById('profileSubscriptionStartedAt');
    const profileLatestPaymentEl = document.getElementById('profileSubscriptionLatestPayment');
    const profileReferralInfoEl = document.getElementById('profileSubscriptionReferralInfo');
    const profileEmailCardEl = document.getElementById('profileEmailNotificationsCard');
    const profileEmailInfoEl = document.getElementById('profileEmailNotificationsText');
    const profileUsageAiEl = document.getElementById('profileSubscriptionUsageAi');
    const profileUsageChatUploadsEl = document.getElementById('profileSubscriptionUsageChatUploads');
    const profileUsageUploadsEl = document.getElementById('profileSubscriptionUsageUploads');
    const profileUsagePrepEl = document.getElementById('profileSubscriptionUsagePrep');
    const profileUsageMockEl = document.getElementById('profileSubscriptionUsageMock');
    const profileEnableEmailButton = document.getElementById('profileEmailNotificationsEnableBtn');
    const profileMarketingCardEl = document.getElementById('profileMarketingEmailsCard');
    const profileMarketingTextEl = document.getElementById('profileMarketingEmailsText');
    const profileMarketingToggleBtn = document.getElementById('profileMarketingEmailsToggleBtn');
    const copilotInstallCtaWrap = document.getElementById('copilotInstallCtaWrap');
    const copilotFreeUpgradePrompt = document.getElementById('copilotFreeUpgradePrompt');
    const copilotUpgradeProBtn = document.getElementById('copilotUpgradeProBtn');
    const copilotUpgradeJourneyBtn = document.getElementById('copilotUpgradeJourneyBtn');

    const setCopilotPlanPromptState = (showUpgradePrompt) => {
        if (copilotInstallCtaWrap) {
            copilotInstallCtaWrap.style.display = showUpgradePrompt ? 'none' : 'flex';
        }
        if (copilotFreeUpgradePrompt) {
            copilotFreeUpgradePrompt.style.display = showUpgradePrompt ? 'grid' : 'none';
        }
        if (copilotUpgradeProBtn) {
            copilotUpgradeProBtn.disabled = !PRO_UPGRADE_ENABLED;
            copilotUpgradeProBtn.textContent = PRO_UPGRADE_ENABLED ? 'Get the Visa Success Pass' : 'Coming Soon';
        }
        if (copilotUpgradeJourneyBtn) {
            // Single one-time pass now — hide the second (recurring) CTA.
            copilotUpgradeJourneyBtn.style.display = 'none';
        }
    };

    if (!currentSubscription) {
        updatePricingFocusMode(false);
        setCopilotPlanPromptState(true);
        if (planNameEl) planNameEl.textContent = 'Free';
        if (aiUsageEl) aiUsageEl.textContent = 'AI: 0/25 used';
        if (chatUploadUsageEl) chatUploadUsageEl.textContent = 'AI Chat Uploads (24h): 0/7 used';
        if (uploadUsageEl) uploadUsageEl.textContent = 'Uploads: 0/5 used';
        if (prepUsageEl) prepUsageEl.textContent = 'Prep: 0/3 used';
        if (mockUsageEl) mockUsageEl.textContent = 'Mock: 0/2 used';
        [sidebarUpgradeButton, profileUpgradeButton].filter(Boolean).forEach((button) => {
            button.disabled = !PRO_UPGRADE_ENABLED;
            button.textContent = PRO_UPGRADE_ENABLED ? 'Get the Visa Success Pass' : 'Coming Soon';
            button.style.opacity = PRO_UPGRADE_ENABLED ? '1' : '0.75';
            button.style.cursor = PRO_UPGRADE_ENABLED ? 'pointer' : 'not-allowed';
        });
        if (profilePlanEl) profilePlanEl.textContent = 'Free Plan';
        if (profileStatusEl) profileStatusEl.textContent = 'Active';
        if (profileAutoRenewEl) profileAutoRenewEl.textContent = 'N/A';
        if (profileRenewalLabelEl) profileRenewalLabelEl.textContent = 'Access Until';
        if (profileRenewalValueEl) profileRenewalValueEl.textContent = '-';
        if (profileEndsLabelEl) profileEndsLabelEl.textContent = 'Plan Type';
        if (profileEndsAtEl) profileEndsAtEl.textContent = '-';
        if (profileStartedAtEl) profileStartedAtEl.textContent = '-';
        if (profileLatestPaymentEl) profileLatestPaymentEl.textContent = '-';
        if (profileReferralInfoEl) profileReferralInfoEl.textContent = 'Referral bonus: Not active';
        if (profileEmailCardEl) profileEmailCardEl.style.display = 'none';
        if (profileEmailInfoEl) profileEmailInfoEl.textContent = '';
        if (profileUsageAiEl) profileUsageAiEl.textContent = 'AI: 0/25 used';
        if (profileUsageChatUploadsEl) profileUsageChatUploadsEl.textContent = 'AI Chat Uploads (24h): 0/7 used';
        if (profileUsageUploadsEl) profileUsageUploadsEl.textContent = 'Uploads: 0/5 used';
        if (profileUsagePrepEl) profileUsagePrepEl.textContent = 'Prep: 0/3 used';
        if (profileUsageMockEl) profileUsageMockEl.textContent = 'Mock: 0/2 used';
        if (profileSwitchMonthlyButton) {
            profileSwitchMonthlyButton.style.display = 'inline-flex';
            profileSwitchMonthlyButton.style.gridColumn = '';
            profileSwitchMonthlyButton.disabled = !PRO_UPGRADE_ENABLED;
            profileSwitchMonthlyButton.textContent = PRO_UPGRADE_ENABLED ? 'Get the Visa Success Pass' : 'Coming Soon';
        }
        if (profileSwitchJourneyButton) {
            // Single one-time pass now — hide the second (recurring) CTA.
            profileSwitchJourneyButton.style.display = 'none';
        }
        if (profileCancelButton) profileCancelButton.style.display = 'none';
        if (profileSwitchHintEl) {
            profileSwitchHintEl.style.display = 'block';
            profileSwitchHintEl.textContent = PRO_UPGRADE_ENABLED
                ? 'Get the one-time Visa Success Pass to unlock premium access.'
                : 'Paid plans are currently unavailable.';
        }
        if (profileEnableEmailButton) profileEnableEmailButton.disabled = false;
        return;
    }

    const isPro = Boolean(currentSubscription.is_pro);
    const accessSourceText = String(currentSubscription.access_source || '');
    const isJourneyPassActive = isPro && accessSourceText.toLowerCase().includes('journey pass');
    const subscriptionStatus = (currentSubscription.status || '').toLowerCase();
    const isLegacyRecurring = Boolean(currentSubscription.recurring_subscription_id);
    const autoRenewEnabled = isLegacyRecurring && currentSubscription.auto_renew_enabled === true;
    const planLabel = isPro ? (isLegacyRecurring ? 'Legacy Pro' : 'Visa Pass') : 'Free';
    const chatUploadWindowHours = Number(currentSubscription.rilono_ai_chat_upload_window_hours) || 24;

    updatePricingFocusMode(isJourneyPassActive);
    setCopilotPlanPromptState(!isPro);

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
    if (chatUploadUsageEl) {
        chatUploadUsageEl.textContent = formatWindowUsageText(
            currentSubscription.rilono_ai_chat_uploads_used ?? 0,
            currentSubscription.rilono_ai_chat_uploads_limit ?? 7,
            'AI Chat Uploads',
            chatUploadWindowHours
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

    if (profilePlanEl) {
        profilePlanEl.textContent = isPro
            ? (isLegacyRecurring ? 'Legacy Recurring Plan' : 'Visa Success Pass')
            : 'Free Plan';
    }
    if (profileStatusEl) profileStatusEl.textContent = currentSubscription.status || 'active';
    if (profileAutoRenewEl) {
        profileAutoRenewEl.textContent = isLegacyRecurring
            ? (autoRenewEnabled ? 'Auto-renew on' : 'Auto-renew off')
            : (isPro ? 'One-time' : 'N/A');
    }
    if (profileRenewalLabelEl) {
        profileRenewalLabelEl.textContent = isLegacyRecurring && autoRenewEnabled
            ? 'Next Renewal'
            : 'Access Until';
    }
    if (profileRenewalValueEl) {
        const relevantDate = isLegacyRecurring && autoRenewEnabled
            ? (currentSubscription.next_renewal_at || currentSubscription.ends_at)
            : currentSubscription.ends_at;
        profileRenewalValueEl.textContent = formatSubscriptionDateTime(relevantDate);
    }
    if (profileEndsLabelEl) {
        profileEndsLabelEl.textContent = 'Plan Type';
    }
    if (profileEndsAtEl) {
        profileEndsAtEl.textContent = isLegacyRecurring
            ? (autoRenewEnabled ? 'Legacy recurring subscription' : 'Legacy subscription (cancellation scheduled)')
            : (isPro ? 'One-time pass (no renewal)' : '-');
    }
    let activatedAt = currentSubscription.started_at;
    if (isPro && currentSubscription.latest_payment_verified_at) {
        const startedTimestamp = Date.parse(currentSubscription.started_at || '');
        const latestVerifiedTimestamp = Date.parse(currentSubscription.latest_payment_verified_at || '');
        if (Number.isFinite(latestVerifiedTimestamp)
            && (!Number.isFinite(startedTimestamp) || latestVerifiedTimestamp > startedTimestamp)) {
            activatedAt = currentSubscription.latest_payment_verified_at;
        }
    }
    if (profileStartedAtEl) profileStartedAtEl.textContent = formatSubscriptionDateTime(activatedAt);
    if (profileLatestPaymentEl) {
        const hasPaymentAmount = currentSubscription.latest_payment_amount_paise !== null
            && currentSubscription.latest_payment_amount_paise !== undefined;
        if (hasPaymentAmount && currentSubscription.latest_payment_currency) {
            // Minor units of the payment's own currency (see the field-name note above).
            const amountMinor = Number(currentSubscription.latest_payment_amount_paise);
            const status = String(currentSubscription.latest_payment_status || '').toLowerCase() || 'created';
            profileLatestPaymentEl.textContent = `${formatMoneyMinor(amountMinor, currentSubscription.latest_payment_currency)} (${status})`;
        } else {
            profileLatestPaymentEl.textContent = currentSubscription.latest_payment_status || '-';
        }
    }
    if (profileReferralInfoEl) {
        if (currentSubscription.referral_bonus_active) {
            const grantedAt = formatSubscriptionDateTime(currentSubscription.referral_bonus_granted_at);
            profileReferralInfoEl.textContent = `Referral bonus active: free 30-day Visa Success Pass granted on ${grantedAt}.`;
        } else if (currentSubscription.referral_bonus_granted_at) {
            profileReferralInfoEl.textContent = `Referral bonus used on ${formatSubscriptionDateTime(currentSubscription.referral_bonus_granted_at)}.`;
        } else {
            profileReferralInfoEl.textContent = 'Referral bonus: Not active';
        }
    }
    const emailNotificationsEnabled = currentSubscription.email_notifications_enabled !== false;
    if (profileEmailCardEl) {
        profileEmailCardEl.style.display = emailNotificationsEnabled ? 'none' : 'block';
    }
    if (profileEmailInfoEl) {
        profileEmailInfoEl.textContent = emailNotificationsEnabled
            ? ''
            : 'Email notifications are currently disabled for this account.';
    }
    if (profileEnableEmailButton) {
        profileEnableEmailButton.disabled = false;
    }
    renderMarketingEmailPreference();
    if (profileUsageAiEl) profileUsageAiEl.textContent = formatUsageText(currentSubscription.ai_messages_used, currentSubscription.ai_messages_limit, 'AI');
    if (profileUsageChatUploadsEl) {
        profileUsageChatUploadsEl.textContent = formatWindowUsageText(
            currentSubscription.rilono_ai_chat_uploads_used ?? 0,
            currentSubscription.rilono_ai_chat_uploads_limit ?? 7,
            'AI Chat Uploads',
            chatUploadWindowHours
        );
    }
    if (profileUsageUploadsEl) profileUsageUploadsEl.textContent = formatUsageText(currentSubscription.document_uploads_used, currentSubscription.document_uploads_limit, 'Uploads');
    if (profileUsagePrepEl) profileUsagePrepEl.textContent = formatUsageText(currentSubscription.prep_sessions_used, currentSubscription.prep_sessions_limit, 'Prep');
    if (profileUsageMockEl) profileUsageMockEl.textContent = formatUsageText(currentSubscription.mock_interviews_used, currentSubscription.mock_interviews_limit, 'Mock');

    if (profileSwitchMonthlyButton) {
        profileSwitchMonthlyButton.style.display = 'inline-flex';
        profileSwitchMonthlyButton.style.gridColumn = '1 / -1';
        if (!PRO_UPGRADE_ENABLED) {
            profileSwitchMonthlyButton.disabled = true;
            profileSwitchMonthlyButton.textContent = 'Coming Soon';
        } else if (isPro) {
            profileSwitchMonthlyButton.disabled = true;
            profileSwitchMonthlyButton.textContent = 'Visa Success Pass active';
        } else {
            profileSwitchMonthlyButton.disabled = false;
            profileSwitchMonthlyButton.textContent = 'Get the Visa Success Pass';
        }
    }
    // Legacy "Journey Pass" switch button is retired (single product = the Visa Success Pass).
    // The element no longer exists in the DOM; keep it hidden if an old cached page still has it.
    if (profileSwitchJourneyButton) {
        profileSwitchJourneyButton.style.display = 'none';
    }

    if (profileSwitchHintEl) {
        profileSwitchHintEl.style.display = 'block';
        if (!PRO_UPGRADE_ENABLED) {
            profileSwitchHintEl.textContent = 'The Visa Success Pass is currently unavailable.';
        } else if (!isPro) {
            // Quote the buyer's own currency, or no price at all — "₹999" in front of
            // someone who will be charged $12.99 is a misquote, not a rounding difference.
            const passPrice = passPriceDisplay(currentPassCurrency());
            profileSwitchHintEl.textContent = `${passPrice ? `One-time ${passPrice}` : 'One-time payment'} · 30 days of unlimited access. No subscription, no auto-renew.`;
        } else if (isLegacyRecurring) {
            profileSwitchHintEl.textContent = autoRenewEnabled
                ? 'This is a legacy recurring subscription. Cancel auto-renew below to stop future charges.'
                : 'Legacy auto-renew is off. Access continues through the current paid period.';
        } else {
            profileSwitchHintEl.textContent = '';
            profileSwitchHintEl.style.display = 'none';
        }
    }

    if (profileCancelButton) {
        profileCancelButton.style.display = isLegacyRecurring && autoRenewEnabled ? 'inline-flex' : 'none';
        profileCancelButton.disabled = false;
        profileCancelButton.textContent = 'Cancel Legacy Auto-Renew';
    }

    [sidebarUpgradeButton, profileUpgradeButton].filter(Boolean).forEach((button) => {
        const canUpgrade = !isPro && PRO_UPGRADE_ENABLED;
        button.disabled = !canUpgrade;
        if (isPro) {
            button.textContent = isLegacyRecurring ? 'Legacy subscription active' : 'Visa Success Pass active';
        } else {
            button.textContent = canUpgrade ? 'Get the Visa Success Pass' : 'Coming Soon';
        }
        button.style.opacity = canUpgrade || isPro ? '0.8' : '0.75';
        button.style.cursor = canUpgrade ? 'pointer' : 'not-allowed';
    });
}

async function cancelLegacyRecurringSubscription() {
    const cancelButton = document.getElementById('profileSubscriptionCancelBtn');
    const isCancelable = Boolean(
        currentSubscription?.recurring_subscription_id
        && currentSubscription?.auto_renew_enabled === true
    );
    if (!isCancelable) {
        showMessage('No active recurring subscription was found.', 'error');
        return;
    }

    const confirmed = await confirmDialog(
        'You will not be charged for another cycle, and access will continue through the current paid period.',
        { title: 'Cancel legacy auto-renew?', okText: 'Yes, cancel auto-renew', cancelText: 'Keep it', danger: false }
    );
    if (!confirmed) return;

    if (cancelButton) {
        cancelButton.disabled = true;
        cancelButton.textContent = 'Canceling auto-renew...';
    }

    const headers = {};
    if (authToken && authToken !== COOKIE_AUTH_SENTINEL) {
        headers.Authorization = `Bearer ${authToken}`;
    }

    try {
        const response = await fetch(`${API_BASE}/api/subscription/cancel`, {
            method: 'POST',
            headers,
            credentials: 'include'
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.detail || 'Could not cancel auto-renew.');
        }

        const previousSubscription = currentSubscription;
        currentSubscription = data;
        maybeAddSubscriptionChangeNotifications(previousSubscription, currentSubscription);
        updateSubscriptionUI();
        showMessage('Auto-renew canceled. Your access continues through the current paid period.', 'success');
    } catch (error) {
        showMessage(error instanceof Error ? error.message : 'Could not cancel auto-renew.', 'error');
        if (cancelButton) {
            cancelButton.disabled = false;
            cancelButton.textContent = 'Cancel Legacy Auto-Renew';
        }
    }
}

function extractErrorDetailText(detail) {
    if (typeof detail === 'string') {
        return detail;
    }
    if (Array.isArray(detail)) {
        return detail
            .map((entry) => {
                if (typeof entry === 'string') return entry;
                if (entry && typeof entry === 'object') {
                    const loc = Array.isArray(entry.loc) ? entry.loc.join('.') : '';
                    const msg = entry.msg ? String(entry.msg) : JSON.stringify(entry);
                    return loc ? `${loc}: ${msg}` : msg;
                }
                return String(entry);
            })
            .join(', ');
    }
    if (detail && typeof detail === 'object') {
        return String(detail.detail || detail.message || JSON.stringify(detail));
    }
    return String(detail || '');
}

function resolveFeatureLabelFromLimitMessage(detailText = '') {
    const text = String(detailText || '').toLowerCase();
    if (text.includes('message limit')) return 'Rilono AI messages';
    if (text.includes('chat upload limit')) return 'Rilono AI chat uploads';
    if (text.includes('chat upload')) return 'Rilono AI chat uploads';
    if (text.includes('upload limit')) return 'document uploads';
    if (text.includes('prep limit')) return 'interview prep sessions';
    if (text.includes('mock interview limit')) return 'mock interview sessions';
    return 'this feature';
}

function isFreePlanExhaustedError(statusCode, detailText = '') {
    if (Number(statusCode) !== 403) return false;
    const text = String(detailText || '').toLowerCase();
    return text.includes('free plan') && text.includes('limit');
}

function getRilonoAiPublicErrorMessage(statusCode, detailText = '') {
    if (isFreePlanExhaustedError(statusCode, detailText)) {
        return detailText || RILONO_AI_PUBLIC_ERROR_MESSAGE;
    }
    return RILONO_AI_PUBLIC_ERROR_MESSAGE;
}

function openPlanLimitModal(detailText = '') {
    const modal = document.getElementById('planLimitModal');
    const titleEl = document.getElementById('planLimitModalTitle');
    const bodyEl = document.getElementById('planLimitModalText');
    if (!modal) return;

    const featureLabel = resolveFeatureLabelFromLimitMessage(detailText);
    if (titleEl) {
        titleEl.textContent = `${featureLabel} exhausted`;
    }
    if (bodyEl) {
        bodyEl.textContent = detailText
            || `You have used all free usage for ${featureLabel}. Get the Visa Success Pass to continue instantly.`;
    }
    modal.style.display = 'flex';
}

function closePlanLimitModal() {
    const modal = document.getElementById('planLimitModal');
    if (!modal) return;
    modal.style.display = 'none';
}

async function upgradeFromPlanLimitModal() {
    closePlanLimitModal();
    await handleUpgradeToPro();
}

function maybeShowPlanLimitPopup(statusCode, detailText = '') {
    if (!isFreePlanExhaustedError(statusCode, detailText)) {
        return false;
    }
    openPlanLimitModal(detailText);
    return true;
}

function normalizeCouponCode(rawValue = '') {
    return String(rawValue || '').trim().toUpperCase().replace(/[^A-Z0-9_-]/g, '');
}

// Rilono's single paid product: the one-time Visa Success Pass (30 days), priced per
// currency from app/money.py PRICE_BOOK. A clean in-app checkout — no separate page, no
// feature/quota re-listing.
async function openVisaPassCheckout() {
    const modal = document.getElementById('checkoutLaunchModal');
    if (!modal) { await startVisaPassPayment(); return; }
    checkoutLaunchResolver = null; // never fire the legacy recurring resolver
    const couponField = document.getElementById('checkoutLaunchCouponCode');
    if (couponField) couponField.value = '';
    const continueBtn = document.getElementById('checkoutLaunchContinueBtn');
    if (continueBtn) {
        continueBtn.disabled = false;
        continueBtn.textContent = 'Continue to pay';
        continueBtn.onclick = () => startVisaPassPayment();
    }
    // Paint the best synchronous guess before the modal appears, so the first frame is
    // never a price in a currency this buyer will not be charged.
    renderCheckoutLaunchAmount(currentPassCurrency());
    modal.style.display = 'flex';

    // The currency control belongs on the buy surface itself: what the buyer picks here is
    // the currency hint sent to /api/pass/checkout, and the price shown is the exact
    // ladder entry the server will charge for it.
    await ensurePassPriceOptions();
    const currency = await resolvePassCurrency();
    const currencySelect = document.getElementById('checkoutLaunchCurrency');
    renderPassCurrencySelect(currencySelect, currency);
    if (currencySelect) {
        currencySelect.onchange = () => renderCheckoutLaunchAmount(setPassCurrency(currencySelect.value));
    }
    renderCheckoutLaunchAmount(currency);
}

// The modal amount, from the ladder while the buyer is still choosing and then from the
// server's own `amount_display` once the order exists — a coupon or the referral discount
// makes the two differ, and the server's figure is the one that gets charged.
function renderCheckoutLaunchAmount(currencyCode, serverDisplay = '') {
    const amountEl = document.getElementById('checkoutLaunchAmount');
    if (!amountEl) return;
    const display = serverDisplay || passPriceDisplay(currencyCode);
    amountEl.textContent = display ? `${display} / one-time` : 'One-time payment';
}

// Razorpay: "Your international payment will fail if you send us a dummy email id and
// phone number of the customer." So the contact details come from the server verbatim
// (the real name/email/phone on the account) and a blank field is DROPPED rather than
// filled with a placeholder — Checkout then asks the buyer for it.
// https://razorpay.com/docs/payments/international-payments/?preferred-country=IN
function passCheckoutPrefill(prefill) {
    const out = {};
    ['name', 'email', 'contact'].forEach((key) => {
        const value = String(prefill?.[key] ?? '').trim();
        if (value) out[key] = value;
    });
    return out;
}

async function startVisaPassPayment() {
    const continueBtn = document.getElementById('checkoutLaunchContinueBtn');
    const setBtn = (txt, disabled) => { if (continueBtn) { continueBtn.textContent = txt; continueBtn.disabled = disabled; } };
    setBtn('Opening checkout…', true);

    // Optional coupon (admin-issued per-account offer or a public code). Validated
    // and priced entirely server-side.
    const couponInput = document.getElementById('checkoutLaunchCouponCode');
    const couponCode = String(couponInput?.value || '').trim().toUpperCase();
    // Currency is a HINT only. The server looks the price up in its own book and answers
    // with the amount it will actually charge — we never send an amount.
    const currency = normalizePassCurrency(
        document.getElementById('checkoutLaunchCurrency')?.value || currentPassCurrency()
    );

    let data;
    try {
        const response = await fetch(`${API_BASE}/api/pass/checkout`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${authToken}` },
            body: JSON.stringify({
                ...(couponCode ? { coupon_code: couponCode } : {}),
                ...(currency ? { currency } : {}),
            }),
        });
        data = await response.json().catch(() => ({}));
        if (!response.ok) { showMessage(data.detail || 'Could not start checkout.', 'error'); setBtn('Continue to pay', false); if (couponCode) couponInput?.focus(); return; }
    } catch (ex) {
        showMessage('Could not start checkout. Please try again.', 'error'); setBtn('Continue to pay', false); return;
    }

    // Show what the server priced, in the currency it resolved — not what we guessed.
    // The fallback is the ORDER's own amount, never passPriceDisplay(): once a coupon or
    // the referral discount has been applied the ladder list price is higher than what is
    // being charged, and re-quoting the list price here would overstate the bill.
    // `> 0` rather than isFinite: `Number(null)` is 0, and an "unavailable"/"already_active"
    // response carries no amount at all — rendering "$0 / one-time" off a missing field
    // would be a worse quote than leaving the ladder price up.
    const serverAmountDisplay = data.amount_display
        || (Number(data.amount) > 0 && data.currency
            ? formatMoneyMinor(data.amount, data.currency)
            : '');
    if (serverAmountDisplay) {
        renderCheckoutLaunchAmount(data.currency, serverAmountDisplay);
    }

    if (data.coupon_code && data.coupon_discount > 0) {
        const payable = serverAmountDisplay || formatMoneyMinor(data.amount, data.currency);
        showMessage(`Coupon ${data.coupon_code} applied — ${data.coupon_percent_off}% off. You pay ${payable}.`, 'success');
    }

    if (data.action === 'already_active') {
        closeCheckoutLaunchModal(false);
        await loadSubscriptionStatus(true);
        showMessage(data.message || 'Your Visa Success Pass is already active.', 'success');
        return;
    }
    if (data.action !== 'checkout') {
        showMessage(data.message || 'Online payment is being enabled. Please try again shortly.', 'error');
        setBtn('Continue to pay', false); return;
    }
    if (typeof window.Razorpay !== 'function') {
        showMessage('Razorpay failed to load. Please refresh and try again.', 'error'); setBtn('Continue to pay', false); return;
    }

    const rzp = new window.Razorpay({
        key: data.razorpay_key_id,
        // No amount/currency here on purpose. The order already carries both, and repeating
        // them lets a cached page and an updated server disagree — Checkout then fails the
        // payment on the mismatch. static/pay.html relies on order_id the same way.
        order_id: data.order_id,
        name: 'Rilono',
        description: (data.product_label || 'Visa Success Pass') + ' (' + (data.duration_days || 30) + ' days)',
        prefill: passCheckoutPrefill(data.prefill),
        theme: { color: '#6366f1' },
        handler: async function (resp) {
            try {
                const vr = await fetch(`${API_BASE}/api/pass/verify`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${authToken}` },
                    body: JSON.stringify({
                        razorpay_order_id: resp.razorpay_order_id,
                        razorpay_payment_id: resp.razorpay_payment_id,
                        razorpay_signature: resp.razorpay_signature,
                    }),
                });
                const vd = await vr.json().catch(() => ({}));
                if (!vr.ok) {
                    // 409 = payment still confirming (server says "no need to pay again")
                    // — reassure, don't alarm; the webhook activates the pass on its own.
                    showMessage(vd.detail || 'Payment verification failed.', vr.status === 409 ? 'success' : 'error');
                    return;
                }
                await loadSubscriptionStatus(true);
                showMessage(vd.message || 'Visa Success Pass activated! 🎉', 'success');
            } catch (ex) {
                showMessage('Payment verification failed: ' + (ex.message || ''), 'error');
            }
        },
    });
    rzp.on('payment.failed', () => showMessage('Payment was not completed.', 'error'));
    closeCheckoutLaunchModal(false);
    setBtn('Continue to pay', false);
    rzp.open();
}

async function handleUpgradeToPro(source = '', preferredPricingModel = PRICING_MODEL_MONTHLY) {
    if (!authToken) {
        showRegister();
        return;
    }

    // Single paid product: open the simple in-app Visa Success Pass checkout.
    await openVisaPassCheckout();
    return;

    const requestedPricingModel = normalizePricingModel(preferredPricingModel);

    if (proUpgradeInFlight) {
        return;
    }

    const subscriptionStatus = String(currentSubscription?.status || '').toLowerCase();
    const isJourneyPassActive = String(currentSubscription?.access_source || '').toLowerCase().includes('journey pass');
    if (currentSubscription?.is_pro && isJourneyPassActive && requestedPricingModel === PRICING_MODEL_MONTHLY) {
        showMessage('Your Visa Success Pass is already active.', 'error');
        return;
    }
    const activePricingModel = currentSubscription?.is_pro
        ? (isJourneyPassActive ? PRICING_MODEL_SIX_MONTH : PRICING_MODEL_MONTHLY)
        : null;
    const hasAutoRenewInfo = typeof currentSubscription?.auto_renew_enabled === 'boolean';
    const canRenewExistingPro = Boolean(
        currentSubscription?.is_pro
        && !isJourneyPassActive
        && (
            !hasAutoRenewInfo
            || (hasAutoRenewInfo && currentSubscription.auto_renew_enabled === false)
            || subscriptionStatus === 'canceled'
        )
    );
    const canSwitchPaidModel = Boolean(
        currentSubscription?.is_pro
        && activePricingModel
        && requestedPricingModel !== activePricingModel
    );
    if (currentSubscription?.is_pro && !canRenewExistingPro && !canSwitchPaidModel) {
        showMessage(
            isJourneyPassActive
                ? 'Your Visa Success Pass is already active.'
                : 'Your account already has an active paid plan.',
            'success'
        );
        return;
    }

    if (!PRO_UPGRADE_ENABLED) {
        showMessage('Pro upgrades are coming soon. Payment integration is pending.', 'error');
        return;
    }

    proUpgradeInFlight = true;
    const dashboardUpgradeButton = document.getElementById('dashboardUpgradeButton');
    const profileUpgradeButton = document.getElementById('profileSubscriptionUpgradeBtn');
    const profileSwitchMonthlyButton = document.getElementById('profileSubscriptionSwitchMonthlyBtn');
    const profileSwitchJourneyButton = document.getElementById('profileSubscriptionSwitchJourneyBtn');
    const pricingMonthlyUpgradeButton = document.getElementById('pricingProUpgradeButton');
    const pricingSixMonthUpgradeButton = document.getElementById('pricingProSixMonthUpgradeButton');
    const upgradeButtons = [
        dashboardUpgradeButton,
        profileUpgradeButton,
        profileSwitchMonthlyButton,
        profileSwitchJourneyButton,
        pricingMonthlyUpgradeButton,
        pricingSixMonthUpgradeButton
    ].filter(Boolean);
    upgradeButtons.forEach((button) => {
        button.dataset.prevText = button.textContent;
        button.disabled = true;
        button.textContent = 'Opening checkout...';
    });

    try {
        const launchResult = await openCheckoutLaunchModal({
            pricingModel: requestedPricingModel
        });
        if (!launchResult?.proceed) {
            showMessage('Upgrade cancelled.', 'error');
            return;
        }

        const selectedPricingModel = normalizePricingModel(launchResult.pricingModel || requestedPricingModel);
        const couponCode = normalizeCouponCode(launchResult.couponCode);
        const response = await fetch(`${API_BASE}/api/subscription/upgrade`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                coupon_code: couponCode || null,
                pricing_model: selectedPricingModel
            }),
        });

        const data = await response.json();
        if (!response.ok) {
            showMessage(data.detail || 'Failed to upgrade subscription', 'error');
            return;
        }

        if (data.action === 'already_pro') {
            currentSubscription = data.subscription || currentSubscription;
            updateSubscriptionUI();
            showMessage(data.message || 'Your account already has an active paid plan.', 'success');
            return;
        }

        if (data.action === 'coupon_activated') {
            currentSubscription = data.subscription || currentSubscription;
            updateSubscriptionUI();
            showMessage(
                data.message || data.coupon_applied_text || 'Coupon applied successfully. Pro is now active.',
                'success'
            );
            if (document.getElementById('pricingSection')?.style.display === 'block') {
                showPricing(true);
            }
            return;
        }

        if (data.action === 'contact_support') {
            showMessage(data.message || 'Visa Success Pass billing is not available right now. Please contact support.', 'error');
            showContact();
            return;
        }

        if (data.action !== 'razorpay_checkout') {
            showMessage('Unable to start Visa Success Pass checkout right now. Please try again.', 'error');
            return;
        }

        if (typeof window.Razorpay !== 'function') {
            showMessage('Razorpay Checkout failed to load. Please refresh and try again.', 'error');
            return;
        }

        const options = {
            key: data.key_id,
            description: data.description || 'Rilono Visa Success Pass',
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

        if (data.coupon_applied_text) {
            showMessage(data.coupon_applied_text, 'success');
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

    const fallbackPricingModel = normalizePricingModel(modal?.dataset?.activePricingModel || PRICING_MODEL_MONTHLY);

    const resolver = checkoutLaunchResolver;
    checkoutLaunchResolver = null;
    if (resolver) {
        if (typeof shouldProceed === 'object' && shouldProceed !== null) {
            resolver(shouldProceed);
        } else {
            resolver({ proceed: Boolean(shouldProceed), couponCode: '', pricingModel: fallbackPricingModel });
        }
    }
}

async function openCheckoutLaunchModal({ pricingModel = PRICING_MODEL_MONTHLY } = {}) {
    const modal = document.getElementById('checkoutLaunchModal');
    if (!modal) {
        return { proceed: true, couponCode: '', pricingModel: normalizePricingModel(pricingModel) };
    }

    const config = getPricingModelConfig(pricingModel);
    modal.dataset.activePricingModel = config.id;

    const planNameEl = document.getElementById('checkoutLaunchPlanName');
    const amountEl = document.getElementById('checkoutLaunchAmount');
    const modeEl = document.getElementById('checkoutLaunchMode');
    const continueBtn = document.getElementById('checkoutLaunchContinueBtn');
    const couponInput = document.getElementById('checkoutLaunchCouponCode');

    if (!continueBtn) {
        return { proceed: true, couponCode: '', pricingModel: config.id };
    }

    if (planNameEl) {
        planNameEl.textContent = config.label;
    }
    if (amountEl) {
        amountEl.textContent = `${formatCurrencyAmount(config.amountInr, 'INR')} ${config.cycleLabel.replace('/', '/ ')}`;
    }
    if (modeEl) {
        modeEl.textContent = config.autoRenewText;
    }

    if (couponInput) {
        couponInput.value = '';
        couponInput.focus();
    }

    modal.style.display = 'flex';

    return new Promise((resolve) => {
        checkoutLaunchResolver = resolve;
        continueBtn.onclick = () => {
            closeCheckoutLaunchModal({
                proceed: true,
                couponCode: normalizeCouponCode(couponInput?.value || ''),
                pricingModel: config.id
            });
        };
    });
}

async function upgradeToProFromPricing(pricingModel = PRICING_MODEL_MONTHLY) {
    if (!authToken) {
        showRegister();
        return;
    }
    await handleUpgradeToPro('pricing', pricingModel);
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
            // 409 = payment still confirming; the webhook completes activation.
            showMessage(
                data.detail || 'Payment verification failed. Please contact support.',
                response.status === 409 ? 'success' : 'error'
            );
            return;
        }

        const previousSubscription = currentSubscription;
        currentSubscription = data;
        maybeAddSubscriptionChangeNotifications(previousSubscription, currentSubscription);
        updateSubscriptionUI();
        showMessage('Payment successful — your Visa Success Pass is now active.', 'success');
        if (document.getElementById('pricingSection')?.style.display === 'block') {
            showPricing(true);
        }
    } catch (error) {
        console.error('Razorpay payment verification failed:', error);
        showMessage('Payment was received but verification failed. Please contact support.', 'error');
    }
}

async function handleEnableEmailNotifications() {
    if (!authToken) {
        showLogin();
        return;
    }

    const enableBtn = document.getElementById('profileEmailNotificationsEnableBtn');
    if (enableBtn) {
        enableBtn.disabled = true;
        enableBtn.textContent = 'Enabling...';
    }

    try {
        const response = await fetch(`${API_BASE}/api/profile/email-notifications/subscribe`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            showMessage(data.detail || 'Failed to enable email notifications.', 'error');
            return;
        }

        if (currentSubscription) {
            currentSubscription.email_notifications_enabled = true;
        }
        if (currentUser) {
            currentUser.email_notifications_enabled = true;
        }

        await loadSubscriptionStatus(true);
        updateSubscriptionUI();
        showMessage('Email notifications are enabled again.', 'success');
    } catch (error) {
        console.error('Enable email notifications failed:', error);
        showMessage('Failed to enable email notifications. Please try again.', 'error');
    } finally {
        if (enableBtn) {
            enableBtn.disabled = false;
            enableBtn.textContent = 'Enable Email Notifications';
        }
    }
}

function renderMarketingEmailPreference() {
    const card = document.getElementById('profileMarketingEmailsCard');
    if (!card) return;
    if (!currentUser) {
        card.style.display = 'none';
        return;
    }
    card.style.display = 'block';
    const subscribed = currentUser.marketing_emails_consent === true;
    const text = document.getElementById('profileMarketingEmailsText');
    const btn = document.getElementById('profileMarketingEmailsToggleBtn');
    if (text) {
        text.textContent = subscribed
            ? "You're subscribed to product tips, journey updates and occasional offers. You can unsubscribe anytime."
            : "Get product tips, journey updates and occasional offers by email. You can unsubscribe anytime.";
    }
    if (btn) {
        btn.disabled = false;
        btn.textContent = subscribed ? 'Unsubscribe' : 'Subscribe';
    }
}

async function handleToggleMarketingEmails() {
    if (!authToken) {
        showLogin();
        return;
    }
    const btn = document.getElementById('profileMarketingEmailsToggleBtn');
    const currentlySubscribed = !!(currentUser && currentUser.marketing_emails_consent === true);
    const nextEnabled = !currentlySubscribed;
    if (btn) {
        btn.disabled = true;
        btn.textContent = nextEnabled ? 'Subscribing...' : 'Unsubscribing...';
    }
    try {
        const response = await fetch(`${API_BASE}/api/auth/marketing-emails/preference`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ enabled: nextEnabled })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            showMessage(data.detail || 'Could not update your marketing email preference.', 'error');
            return;
        }
        if (currentUser) {
            currentUser.marketing_emails_consent = data.marketing_emails_consent === true;
        }
        showMessage(nextEnabled ? 'Subscribed to marketing emails.' : 'Unsubscribed from marketing emails.', 'success');
    } catch (error) {
        console.error('Marketing email preference update failed:', error);
        showMessage('Could not update your marketing email preference. Please try again.', 'error');
    } finally {
        renderMarketingEmailPreference();
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
        const previousSubscription = currentSubscription;
        currentSubscription = data;
        maybeAddSubscriptionChangeNotifications(previousSubscription, currentSubscription);
        updateSubscriptionUI();
        return true;
    } catch (error) {
        console.error('Session quota check failed:', error);
        showMessage('Unable to validate session quota. Please try again.', 'error');
        return false;
    }
}

async function loadF1VisaNews() {
    if (!authToken) return;

    const newsContainer = document.getElementById('newsContainer');
    const metaInfo = document.getElementById('newsMetaInfo');
    if (!newsContainer || !metaInfo) return;

    if (newsRequestInFlight) return;
    newsRequestInFlight = true;

    newsContainer.innerHTML = '<div class="news-loading">Loading visa news...</div>';

    try {
        const response = await fetch(`${API_BASE}/api/news/f1-latest`, {
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
            const emptyDest = (data.destination_name || '').replace(/^the /, '');
            newsContainer.innerHTML = `<div class="news-loading">No recent ${escapeHtml(emptyDest || 'visa')} student-visa updates yet. Check back soon.</div>`;
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
            : '';
        const destName = (data.destination_name || '').replace(/^the /, '');
        const destPrefix = destName ? `${destName} student-visa news` : 'Visa news';
        metaInfo.textContent = fetchedText
            ? `${destPrefix} · Last updated: ${fetchedText}`
            : `${destPrefix} · ${data.count || 0} updates`;
    } catch (error) {
        console.error('Error loading F1 visa news:', error);
        newsContainer.innerHTML = '<div class="news-loading">Unable to load visa news right now. Please try again shortly.</div>';
        metaInfo.textContent = 'Failed to load updates';
    } finally {
        newsRequestInFlight = false;
    }
}

// The experiences feed is scoped to the user's DESTINATION visa. Only the US flow
// has consular interviews with per-consulate filters; every other destination
// (AU/UK/CA/DE) fetches experiences about its own visa process, filtered by the
// applicant's home country alone.
function visaExperienceIsUSFlow() {
    return (((currentUser && currentUser.destination_country_code) || 'US') === 'US');
}

const VISA_EXPERIENCE_INTRO_COPY = {
    US: 'Select a country and one or more consulates to fetch recent interview experiences discussed by users online.',
    UK: 'Select your home country to fetch recent UK Student visa experiences (credibility interviews, decision timelines) shared by applicants online.',
    CA: 'Select your home country to fetch recent Canada study permit experiences (biometrics, IRCC interviews, decision timelines) shared by applicants online.',
    AU: 'Select your home country to fetch recent Australia Subclass 500 experiences (Genuine Student interviews, grant timelines) shared by applicants online.',
    DE: 'Select your home country to fetch recent German student visa experiences (embassy appointments, decision timelines) shared by applicants online.',
};

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
    const residenceCountry = (currentUser && currentUser.current_residence_country) || '';
    const country = (savedCountry && VISA_INTERVIEW_CONSULATE_MAP[savedCountry] && savedCountry)
        || (VISA_INTERVIEW_CONSULATE_MAP[residenceCountry] && residenceCountry)
        || 'India';
    countrySelect.value = country;

    const isUSFlow = visaExperienceIsUSFlow();
    const consulateField = document.querySelector('.visa-experience-field-consulates');
    if (consulateField) consulateField.style.display = isUSFlow ? '' : 'none';
    const introCopy = document.getElementById('visaExperienceIntroCopy');
    if (introCopy) {
        const code = (currentUser && currentUser.destination_country_code) || 'US';
        introCopy.textContent = VISA_EXPERIENCE_INTRO_COPY[code] || VISA_EXPERIENCE_INTRO_COPY.US;
    }

    if (isUSFlow) {
        const savedConsulates = JSON.parse(localStorage.getItem(`visaExperienceConsulates:${country}`) || '[]');
        renderVisaConsulateOptions(country, Array.isArray(savedConsulates) ? savedConsulates : []);
    }

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
    if (!visaExperienceIsUSFlow()) return;
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
    const isUSFlow = visaExperienceIsUSFlow();
    const consulates = isUSFlow ? getSelectedVisaConsulates() : [];
    if (isUSFlow) {
        if (consulates.length === 0) {
            showMessage('Select at least one consulate to fetch experiences.', 'error');
            visaInterviewRequestInFlight = false;
            return;
        }
        persistVisaConsulateSelection();
    } else {
        localStorage.setItem('visaExperienceCountry', country);
    }

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
            container.innerHTML = isUSFlow
                ? '<div class="visa-experience-state"><span class="vxs-icon">🔍</span><p>No interview experiences found for these consulates yet.<span>Try selecting more consulates, or check back a little later.</span></p></div>'
                : '<div class="visa-experience-state"><span class="vxs-icon">🔍</span><p>No recent applicant experiences found yet.<span>Try a different home country, or check back a little later.</span></p></div>';
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
        metaInfo.textContent = isUSFlow
            ? `${country} • ${consulates.length} consulate(s) • Updated ${fetchedText} (${cacheText})`
            : `${country} • Updated ${fetchedText} (${cacheText})`;
    } catch (error) {
        console.error('Error loading F1 interview experiences:', error);
        container.innerHTML = '<div class="visa-experience-state visa-experience-state-error"><span class="vxs-icon">⚠️</span><p>Couldn\'t load interview experiences right now.<span>Check your connection and tap "Fetch Latest Experiences" to retry.</span></p></div>';
        metaInfo.textContent = "Couldn't fetch experiences";
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
            bottomSpeakId: 'visaPrepSpeakBottomBtn',
            stopId: 'visaPrepStopBtn',
            finishId: null,
            assistantLabel: 'Prep Coach'
        };
    }
    return {
        statusId: 'visaMockInterviewStatus',
        logId: 'visaMockInterviewLog',
        startSelector: '#visaMockStartBtn',
        bottomSpeakId: 'visaMockSpeakBottomBtn',
        stopId: null,
        finishId: 'visaMockFinishBtn',
        assistantLabel: 'Visa Officer'
    };
}

function getVisaInterviewState(mode) {
    return mode === 'prep' ? visaPrepInterviewState : visaMockInterviewState;
}

function getVisaInterviewPanel(mode) {
    return document.getElementById(mode === 'prep' ? 'visaPrepPanel' : 'visaMockPanel');
}

function getVisaInterviewFullscreenButton(mode) {
    return document.getElementById(mode === 'prep' ? 'visaPrepFullscreenBtn' : 'visaMockFullscreenBtn');
}

function isVisaInterviewPanelFullscreen(mode) {
    const panel = getVisaInterviewPanel(mode);
    return Boolean(panel && document.fullscreenElement === panel);
}

async function requestVisaInterviewFullscreen(mode) {
    const panel = getVisaInterviewPanel(mode);
    if (!panel) {
        return;
    }
    if (document.fullscreenElement !== panel) {
        try {
            await panel.requestFullscreen();
        } catch (error) {
            console.warn('Could not enable fullscreen:', error);
        }
    }
    if (mode === 'prep') {
        renderPrepInterviewModeUI();
    } else {
        renderMockInterviewModeUI();
    }
}

function renderVisaInterviewFullscreenCta(mode) {
    const btn = getVisaInterviewFullscreenButton(mode);
    if (!btn) {
        return;
    }
    const state = getVisaInterviewState(mode);
    const shouldShow = (state.active || state.pending) && !isVisaInterviewPanelFullscreen(mode);
    btn.style.display = shouldShow ? 'inline-flex' : 'none';
}

function formatInterviewElapsedTime(elapsedMs) {
    const totalSeconds = Math.max(0, Math.floor((elapsedMs || 0) / 1000));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;

    if (hours > 0) {
        return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    }
    return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function renderMockInterviewTimer() {
    const timerEl = document.getElementById('visaMockInterviewTimer');
    if (!timerEl) return;
    const label = visaMockInterviewState.reportGenerationStartedAt !== null ? 'Interview' : 'Time';
    timerEl.textContent = `${label}: ${formatInterviewElapsedTime(visaMockInterviewState.elapsedMs)}`;
}

function getMockReportProgressStage(elapsedMs) {
    const elapsedSeconds = Math.max(0, Math.floor((elapsedMs || 0) / 1000));
    return MOCK_REPORT_PROGRESS_STAGES.reduce((currentStage, stage) => (
        elapsedSeconds >= stage.afterSeconds ? stage : currentStage
    ), MOCK_REPORT_PROGRESS_STAGES[0]);
}

function updateMockReportGenerationProgress() {
    const state = visaMockInterviewState;
    if (state.reportGenerationStartedAt === null) return;

    state.reportGenerationElapsedMs = Math.max(0, Date.now() - state.reportGenerationStartedAt);
    const stage = getMockReportProgressStage(state.reportGenerationElapsedMs);
    const elapsedLabel = formatInterviewElapsedTime(state.reportGenerationElapsedMs);
    const progressEl = document.getElementById('visaMockReportProgress');
    const progressTextEl = document.getElementById('visaMockReportProgressText');
    if (progressEl) progressEl.style.display = 'inline-flex';
    if (progressTextEl) progressTextEl.textContent = `Report: ${elapsedLabel}`;

    setVisaInterviewStatus('mock', `Generating report · ${stage.label}`);
    const logEl = document.getElementById('visaMockInterviewLog');
    const generatingItem = logEl ? logEl.querySelector('.visa-mock-log-item.report-generating') : null;
    if (generatingItem) {
        const stageEl = generatingItem.querySelector('[data-report-progress-stage]');
        const elapsedEl = generatingItem.querySelector('[data-report-progress-elapsed]');
        if (stageEl) stageEl.textContent = `${stage.label}…`;
        if (elapsedEl) elapsedEl.textContent = `${elapsedLabel} elapsed · This usually takes 15–30 seconds.`;
    }
}

function startMockReportGenerationProgress() {
    stopMockReportGenerationProgress();
    const state = visaMockInterviewState;
    state.reportGenerationElapsedMs = 0;
    state.reportGenerationStartedAt = Date.now();
    renderMockInterviewTimer();
    updateMockReportGenerationProgress();
    state.reportProgressIntervalId = window.setInterval(
        updateMockReportGenerationProgress,
        MOCK_INTERVIEW_TIMER_INTERVAL_MS
    );
}

function stopMockReportGenerationProgress() {
    const state = visaMockInterviewState;
    if (state.reportGenerationStartedAt !== null) {
        state.reportGenerationElapsedMs = Math.max(0, Date.now() - state.reportGenerationStartedAt);
    }
    if (state.reportProgressIntervalId) {
        window.clearInterval(state.reportProgressIntervalId);
        state.reportProgressIntervalId = null;
    }
    state.reportGenerationStartedAt = null;
    const progressEl = document.getElementById('visaMockReportProgress');
    if (progressEl) progressEl.style.display = 'none';
    renderMockInterviewTimer();
    return state.reportGenerationElapsedMs;
}

function updateMockInterviewElapsed() {
    const state = visaMockInterviewState;
    if (state.timerStartedAt !== null) {
        state.elapsedMs = Math.max(0, Date.now() - state.timerStartedAt);
    }
    renderMockInterviewTimer();
}

function startMockInterviewTimer() {
    const state = visaMockInterviewState;
    if (state.timerStartedAt === null) {
        state.timerStartedAt = Date.now() - (state.elapsedMs || 0);
    }
    if (state.timerIntervalId) {
        return;
    }
    updateMockInterviewElapsed();
    state.timerIntervalId = window.setInterval(updateMockInterviewElapsed, MOCK_INTERVIEW_TIMER_INTERVAL_MS);
}

function stopMockInterviewTimer() {
    const state = visaMockInterviewState;
    if (state.timerStartedAt !== null) {
        state.elapsedMs = Math.max(0, Date.now() - state.timerStartedAt);
        state.timerStartedAt = null;
    }
    if (state.timerIntervalId) {
        window.clearInterval(state.timerIntervalId);
        state.timerIntervalId = null;
    }
    renderMockInterviewTimer();
}

function resetMockInterviewTimer() {
    stopMockInterviewTimer();
    visaMockInterviewState.elapsedMs = 0;
    renderMockInterviewTimer();
}

function setVisaInterviewStatus(mode, statusText) {
    const cfg = getVisaInterviewSessionConfig(mode);
    const statusEl = document.getElementById(cfg.statusId);
    if (statusEl) {
        statusEl.textContent = statusText;
        const isGenerating = /generating (?:final )?report/i.test(statusText);
        statusEl.classList.toggle('report-generating-badge', isGenerating);
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
    const isReportGenerating = role === 'system' && /generating final/i.test(text);
    item.className = `visa-mock-log-item ${role}${isReportGenerating ? ' report-generating' : ''}`;
    if (mode === 'prep' && role === 'assistant') {
        item.innerHTML = formatPrepInterviewLogHtml(text);
    } else if (isReportGenerating) {
        item.innerHTML = `
            <span class="report-generating-spinner" aria-hidden="true"></span>
            <span class="report-generating-copy">
                <span data-report-progress-stage>${escapeHtml(text)}</span>
                <small data-report-progress-elapsed>00:00 elapsed · This usually takes 15–30 seconds.</small>
            </span>
        `;
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

function normalizeMicPermissionState(rawState) {
    if (rawState === 'granted' || rawState === 'denied' || rawState === 'prompt') {
        return rawState;
    }
    if (rawState === 'unsupported') {
        return 'unsupported';
    }
    return 'unknown';
}

function setVisaInterviewMicPermission(mode, nextPermission, shouldRender = true) {
    const state = getVisaInterviewState(mode);
    const normalized = normalizeMicPermissionState(nextPermission);
    if (state.micPermission === normalized) {
        return;
    }
    state.micPermission = normalized;
    if (shouldRender) {
        updateVisaInterviewControls(mode);
    }
}

function getVisaInterviewMicStatusModel(mode) {
    const state = getVisaInterviewState(mode);
    const speechSupported = Boolean(getSpeechRecognitionConstructor());
    if (!speechSupported) {
        return {
            text: 'Mic unsupported in this browser',
            toneClass: 'is-unsupported'
        };
    }

    const micPermission = normalizeMicPermissionState(state.micPermission);
    if (micPermission === 'denied') {
        return {
            text: 'Mic blocked: enable browser permission',
            toneClass: 'is-blocked'
        };
    }
    if (micPermission === 'prompt') {
        return {
            text: 'Mic permission required: enable it in browser',
            toneClass: 'is-pending'
        };
    }
    if (state.listening) {
        return {
            text: 'Mic connected: Listening',
            toneClass: 'is-listening'
        };
    }
    if (micPermission === 'granted') {
        return {
            text: 'Mic connected',
            toneClass: 'is-connected'
        };
    }
    if (state.channel === 'chat') {
        return {
            text: 'Mic idle in chat mode',
            toneClass: ''
        };
    }

    return {
        text: 'Mic status checking...',
        toneClass: 'is-pending'
    };
}

function renderVisaInterviewMicStatus(mode, statusEl, textEl) {
    if (!statusEl || !textEl) {
        return;
    }
    const state = getVisaInterviewState(mode);
    const shouldShow = state.active && state.channel === 'voice';
    statusEl.style.display = shouldShow ? 'inline-flex' : 'none';
    if (!shouldShow) {
        return;
    }

    const model = getVisaInterviewMicStatusModel(mode);
    textEl.textContent = model.text;
    statusEl.classList.remove('is-connected', 'is-listening', 'is-pending', 'is-blocked', 'is-unsupported');
    if (model.toneClass) {
        statusEl.classList.add(model.toneClass);
    }
}

async function refreshVisaInterviewMicPermission(mode) {
    const state = getVisaInterviewState(mode);
    if (state.micPermissionCheckPromise) {
        return state.micPermissionCheckPromise;
    }

    state.micPermissionCheckPromise = (async () => {
        const speechSupported = Boolean(getSpeechRecognitionConstructor());
        if (!speechSupported) {
            setVisaInterviewMicPermission(mode, 'unsupported', false);
            return state.micPermission;
        }

        if (!navigator.permissions || typeof navigator.permissions.query !== 'function') {
            setVisaInterviewMicPermission(mode, 'unknown', false);
            return state.micPermission;
        }

        try {
            if (!state.micPermissionStatus) {
                state.micPermissionStatus = await navigator.permissions.query({ name: 'microphone' });
                state.micPermissionStatus.onchange = () => {
                    setVisaInterviewMicPermission(mode, state.micPermissionStatus ? state.micPermissionStatus.state : 'unknown');
                };
            }
            setVisaInterviewMicPermission(mode, state.micPermissionStatus.state, false);
        } catch (error) {
            setVisaInterviewMicPermission(mode, 'unknown', false);
        }

        return state.micPermission;
    })().finally(() => {
        state.micPermissionCheckPromise = null;
        updateVisaInterviewControls(mode);
    });

    return state.micPermissionCheckPromise;
}

function bindVisaInterviewChatComposer(mode) {
    const isPrep = mode === 'prep';
    const form = document.getElementById(isPrep ? 'visaPrepChatComposer' : 'visaMockChatComposer');
    const input = document.getElementById(isPrep ? 'visaPrepChatInput' : 'visaMockChatInput');

    if (form && form.dataset.interviewSubmitBound !== '1') {
        form.dataset.interviewSubmitBound = '1';
        form.addEventListener('submit', (event) => {
            event.preventDefault();
            if (isPrep) {
                void sendPrepInterviewChatAnswer();
            } else {
                void sendMockInterviewChatAnswer();
            }
        });
    }

    if (input && input.dataset.interviewInputBound !== '1') {
        input.dataset.interviewInputBound = '1';
        input.addEventListener('input', () => {
            if (isPrep) {
                renderPrepInterviewModeUI();
            } else {
                renderMockInterviewModeUI();
            }
        });
    }
}

function updateVisaInterviewControls(mode) {
    const cfg = getVisaInterviewSessionConfig(mode);
    const state = getVisaInterviewState(mode);
    const startBtn = document.querySelector(cfg.startSelector);
    const bottomSpeakBtn = cfg.bottomSpeakId ? document.getElementById(cfg.bottomSpeakId) : null;
    const stopBtn = document.getElementById(cfg.stopId);
    const finishBtn = cfg.finishId ? document.getElementById(cfg.finishId) : null;
    const speechSupported = Boolean(getSpeechRecognitionConstructor());
    const micBlocked = state.micPermission === 'denied';

    if (startBtn) {
        if (mode === 'mock' || mode === 'prep') {
            startBtn.disabled = state.active || state.pending;
        } else {
            startBtn.disabled = !speechSupported || state.active || state.pending;
        }
    }
    if (bottomSpeakBtn) {
        const autoVoiceMode = state.active && state.channel === 'voice';
        bottomSpeakBtn.disabled = autoVoiceMode || micBlocked || !speechSupported || !state.active || state.pending || state.listening;
        bottomSpeakBtn.title = micBlocked ? 'Microphone is blocked in browser settings.' : '';
    }
    if (stopBtn) {
        stopBtn.disabled = !state.active && !state.pending;
    }
    if (finishBtn) {
        if (state.finishRequested) {
            // The user asked to finish while the officer was still replying — the finish is
            // queued and will run once the reply completes.
            finishBtn.disabled = true;
            finishBtn.textContent = 'Finishing…';
            finishBtn.title = 'Your report will generate as soon as the officer finishes replying.';
        } else if (state.reportGenerating) {
            finishBtn.disabled = true;
            finishBtn.textContent = 'Finish & Report';
            finishBtn.title = '';
        } else {
            // Keep it clickable while the officer is replying (state.pending) so the click
            // queues the finish instead of being silently swallowed; only truly disable it
            // when there is nothing to finish yet.
            finishBtn.disabled = (!state.active && state.history.length === 0);
            finishBtn.textContent = 'Finish & Report';
            finishBtn.title = state.pending ? 'The officer is replying — click to end after this reply.' : '';
        }
    }
    if (mode === 'mock') {
        renderMockInterviewModeUI();
    } else if (mode === 'prep') {
        renderPrepInterviewModeUI();
    }
}

function renderMockInterviewModeUI() {
    bindVisaInterviewChatComposer('mock');
    const modePicker = document.getElementById('visaMockModePicker');
    const chatComposer = document.getElementById('visaMockChatComposer');
    const chatInput = document.getElementById('visaMockChatInput');
    const chatSendBtn = document.getElementById('visaMockChatSendBtn');
    const startBtn = document.getElementById('visaMockStartBtn');
    const secondaryControls = document.getElementById('visaMockSecondaryControls');
    const bottomSpeakBtn = document.getElementById('visaMockSpeakBottomBtn');
    const micStatusEl = document.getElementById('visaMockMicStatus');
    const micStatusTextEl = document.getElementById('visaMockMicStatusText');
    const modeBadge = document.getElementById('visaMockModeBadge');
    const guide = document.getElementById('visaMockInterviewGuide');
    const state = visaMockInterviewState;
    if (!chatComposer || !chatInput || !chatSendBtn) {
        return;
    }

    const showPicker = !state.active && !state.pending && state.showModePicker;
    if (modePicker) modePicker.style.display = showPicker ? 'grid' : 'none';
    const showSecondaryControls = state.active || state.pending || state.history.length > 0;
    if (secondaryControls) secondaryControls.style.display = showSecondaryControls ? 'flex' : 'none';
    if (startBtn) {
        startBtn.textContent = state.active
            ? 'Interview Running'
            : (showPicker ? 'Cancel Mode Selection' : (state.history.length > 0 ? 'Start New Interview' : 'Start Interview'));
    }

    const chatModeActive = state.active && state.channel === 'chat';
    const voiceModeActive = state.active && state.channel === 'voice';
    chatComposer.style.display = state.active ? 'flex' : 'none';
    chatComposer.classList.toggle('voice-mode', state.channel === 'voice');
    chatInput.disabled = !chatModeActive || state.pending;
    chatInput.placeholder = state.channel === 'voice'
        ? 'Voice mode active. Mic listens automatically after each question.'
        : 'Type your interview answer...';
    chatSendBtn.style.display = chatModeActive ? 'inline-flex' : 'none';
    chatSendBtn.disabled = !chatModeActive || state.pending || !chatInput.value.trim();
    if (bottomSpeakBtn) {
        bottomSpeakBtn.style.display = voiceModeActive ? 'inline-flex' : 'none';
        bottomSpeakBtn.classList.toggle('is-listening', state.listening);
        bottomSpeakBtn.textContent = voiceModeActive
            ? (state.listening ? 'Mic Listening...' : 'Mic Auto-On')
            : 'Speak Answer';
    }
    renderVisaInterviewMicStatus('mock', micStatusEl, micStatusTextEl);
    renderVisaInterviewFullscreenCta('mock');

    if (state.channel === 'voice') {
        if (modeBadge) {
            modeBadge.textContent = 'Mode: Voice';
            modeBadge.classList.remove('visa-hub-tag-mode-chat');
            modeBadge.classList.add('visa-hub-tag-mode-voice');
        }
        if (guide) {
            guide.textContent = state.active
                ? 'Mic is always on for responses. Just speak when the officer finishes asking.'
                : 'Click Start Interview and choose Voice to run a microphone-based simulation.';
        }
    } else if (state.channel === 'chat') {
        if (modeBadge) {
            modeBadge.textContent = 'Mode: Chat';
            modeBadge.classList.remove('visa-hub-tag-mode-voice');
            modeBadge.classList.add('visa-hub-tag-mode-chat');
        }
        if (guide) {
            guide.textContent = state.active
                ? 'Type and send each answer below.'
                : 'Click Start Interview and choose Chat to run a typed interview simulation.';
        }
    } else {
        if (modeBadge) {
            modeBadge.textContent = 'Mode: not selected';
            modeBadge.classList.remove('visa-hub-tag-mode-voice', 'visa-hub-tag-mode-chat');
        }
        if (guide) guide.textContent = 'Click Start Interview, choose Voice or Chat, then proceed question by question. The Rilono AI officer closes the interview when complete.';
    }

    if (state.active && state.channel === 'voice' && state.micPermission === 'unknown' && !state.micPermissionStatus && !state.micPermissionCheckPromise) {
        void refreshVisaInterviewMicPermission('mock');
    }

    if (chatModeActive && !state.pending) {
        requestAnimationFrame(() => chatInput.focus());
    }
}

function renderPrepInterviewModeUI() {
    bindVisaInterviewChatComposer('prep');
    const modePicker = document.getElementById('visaPrepModePicker');
    const chatComposer = document.getElementById('visaPrepChatComposer');
    const chatInput = document.getElementById('visaPrepChatInput');
    const chatSendBtn = document.getElementById('visaPrepChatSendBtn');
    const startBtn = document.getElementById('visaPrepStartBtn');
    const secondaryControls = document.getElementById('visaPrepSecondaryControls');
    const bottomSpeakBtn = document.getElementById('visaPrepSpeakBottomBtn');
    const micStatusEl = document.getElementById('visaPrepMicStatus');
    const micStatusTextEl = document.getElementById('visaPrepMicStatusText');
    const modeBadge = document.getElementById('visaPrepModeBadge');
    const guide = document.getElementById('visaPrepInterviewGuide');
    const state = visaPrepInterviewState;
    if (!chatComposer || !chatInput || !chatSendBtn) {
        return;
    }

    const showPicker = !state.active && !state.pending && state.showModePicker;
    if (modePicker) modePicker.style.display = showPicker ? 'grid' : 'none';
    const showSecondaryControls = state.active || state.pending || state.history.length > 0;
    if (secondaryControls) secondaryControls.style.display = showSecondaryControls ? 'flex' : 'none';
    if (startBtn) {
        startBtn.textContent = state.active
            ? 'Prep Running'
            : (showPicker ? 'Cancel Mode Selection' : (state.history.length > 0 ? 'Start New Prep Session' : 'Start Prep Session'));
    }

    const chatModeActive = state.active && state.channel === 'chat';
    const voiceModeActive = state.active && state.channel === 'voice';
    chatComposer.style.display = state.active ? 'flex' : 'none';
    chatComposer.classList.toggle('voice-mode', state.channel === 'voice');
    chatInput.disabled = !chatModeActive || state.pending;
    chatInput.placeholder = state.channel === 'voice'
        ? 'Voice mode active. Mic listens automatically after each question.'
        : 'Type your prep answer...';
    chatSendBtn.style.display = chatModeActive ? 'inline-flex' : 'none';
    chatSendBtn.disabled = !chatModeActive || state.pending || !chatInput.value.trim();
    if (bottomSpeakBtn) {
        bottomSpeakBtn.style.display = voiceModeActive ? 'inline-flex' : 'none';
        bottomSpeakBtn.classList.toggle('is-listening', state.listening);
        bottomSpeakBtn.textContent = voiceModeActive
            ? (state.listening ? 'Mic Listening...' : 'Mic Auto-On')
            : 'Speak Answer';
    }
    renderVisaInterviewMicStatus('prep', micStatusEl, micStatusTextEl);
    renderVisaInterviewFullscreenCta('prep');

    if (state.channel === 'voice') {
        if (modeBadge) {
            modeBadge.textContent = 'Mode: Voice';
            modeBadge.classList.remove('visa-hub-tag-mode-chat');
            modeBadge.classList.add('visa-hub-tag-mode-voice');
        }
        if (guide) {
            guide.textContent = state.active
                ? 'Mic is always on for responses. Speak naturally after each question; Rilono AI will coach and continue.'
                : 'Click Start Prep Session and choose Voice to practice with microphone input.';
        }
    } else if (state.channel === 'chat') {
        if (modeBadge) {
            modeBadge.textContent = 'Mode: Chat';
            modeBadge.classList.remove('visa-hub-tag-mode-voice');
            modeBadge.classList.add('visa-hub-tag-mode-chat');
        }
        if (guide) {
            guide.textContent = state.active
                ? 'Type and send each answer below. Rilono AI gives feedback on every turn.'
                : 'Click Start Prep Session and choose Chat to practice in typed mode.';
        }
    } else {
        if (modeBadge) {
            modeBadge.textContent = 'Mode: not selected';
            modeBadge.classList.remove('visa-hub-tag-mode-voice', 'visa-hub-tag-mode-chat');
        }
        if (guide) guide.textContent = 'Choose Voice or Chat mode to start your prep session. You will get feedback after each answer.';
    }

    if (state.active && state.channel === 'voice' && state.micPermission === 'unknown' && !state.micPermissionStatus && !state.micPermissionCheckPromise) {
        void refreshVisaInterviewMicPermission('prep');
    }

    if (chatModeActive && !state.pending) {
        requestAnimationFrame(() => chatInput.focus());
    }
}

function initializeVisaInterviewUI(mode) {
    bindVisaInterviewChatComposer(mode);
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
    void refreshVisaInterviewMicPermission(mode);
}

function initializeVisaPrepInterviewUI() {
    initializeVisaInterviewUI('prep');
}

function initializeVisaMockInterviewUI() {
    initializeVisaInterviewUI('mock');
    if (visaMockInterviewState.active) {
        startMockInterviewTimer();
    } else {
        stopMockInterviewTimer();
    }
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
    if (!utteranceText) {
        return;
    }

    const consulate = visaMockInterviewState.consulate && visaMockInterviewState.active;

    // Consulate Window + Visa Success Pass: accent-matched neural officer voice.
    // ANY failure (no Pass, no creds, timeout) falls through to browser TTS below.
    if (consulate) {
        visaMockInterviewState.officerSpeaking = true;
        updateConsulateOrb();
        try {
            const spoke = await playOfficerNeuralAudio(utteranceText);
            if (spoke) {
                return;
            }
        } finally {
            if (!window.speechSynthesis || !window.speechSynthesis.speaking) {
                visaMockInterviewState.officerSpeaking = false;
            }
            updateConsulateOrb();
            armConsulateNudge();
        }
    }

    if (!window.speechSynthesis) {
        return;
    }

    await new Promise((resolve) => {
        try {
            window.speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance(utteranceText);
            // Match the officer's accent to the destination (an "Australian Home
            // Affairs officer" must not speak US English when the browser has an
            // en-AU voice). DE officers still speak English in the simulation.
            // Fall back through destination accent → en-US → any English voice.
            const OFFICER_TTS_LANG = { US: 'en-US', UK: 'en-GB', CA: 'en-CA', AU: 'en-AU', DE: 'en-GB' };
            const destCode = (currentUser && currentUser.destination_country_code) || 'US';
            const targetLang = OFFICER_TTS_LANG[destCode] || 'en-US';
            utterance.lang = targetLang;
            utterance.rate = consulate ? 1.05 : 1;   // officers are brisk
            utterance.pitch = consulate ? 0.9 : 1;   // slightly lower register
            const voices = window.speechSynthesis.getVoices();
            const wantPrefix = targetLang.toLowerCase();
            const preferredVoice = voices.find((voice) => voice.lang && voice.lang.toLowerCase().startsWith(wantPrefix))
                || voices.find((voice) => voice.lang && voice.lang.toLowerCase().startsWith('en-us'))
                || voices.find((voice) => voice.lang && voice.lang.toLowerCase().startsWith('en'));
            if (preferredVoice) {
                utterance.voice = preferredVoice;
            }
            const done = () => {
                if (consulate) {
                    visaMockInterviewState.officerSpeaking = false;
                    updateConsulateOrb();
                    armConsulateNudge();
                }
                resolve();
            };
            if (consulate) { visaMockInterviewState.officerSpeaking = true; updateConsulateOrb(); }
            utterance.onend = done;
            utterance.onerror = done;
            window.speechSynthesis.speak(utterance);
        } catch (error) {
            if (consulate) { visaMockInterviewState.officerSpeaking = false; }
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
    let receivedFinalAnswer = false;
    let shouldAutoRestart = false;
    state.recognition = recognition;
    recognition.lang = 'en-US';
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    recognition.continuous = false;

    recognition.onstart = () => {
        state.listening = true;
        setVisaInterviewMicPermission(mode, 'granted', false);
        setVisaInterviewStatus(mode, 'Listening...');
        updateVisaInterviewControls(mode);
    };

    recognition.onerror = (event) => {
        state.listening = false;
        updateVisaInterviewControls(mode);
        if (!state.active) return;
        const autoVoiceMode = state.channel === 'voice';
        if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
            setVisaInterviewMicPermission(mode, 'denied', false);
            setVisaInterviewStatus(mode, 'Mic blocked');
            appendVisaInterviewLog(mode, 'system', 'Microphone access is blocked. Enable browser mic permission and try again.');
            updateVisaInterviewControls(mode);
            return;
        }
        if (event.error === 'no-speech') {
            if (autoVoiceMode) {
                shouldAutoRestart = true;
                setVisaInterviewStatus(mode, 'Listening...');
                return;
            }
            setVisaInterviewStatus(mode, 'No speech detected');
            appendVisaInterviewLog(mode, 'system', 'No speech detected. Click "Speak Answer" and try again.');
            return;
        }
        if (autoVoiceMode && (event.error === 'aborted' || event.error === 'network')) {
            shouldAutoRestart = true;
            setVisaInterviewStatus(mode, 'Listening...');
            return;
        }
        setVisaInterviewStatus(mode, 'Mic error');
        appendVisaInterviewLog(mode, 'system', `Mic error: ${event.error}. Try again.`);
    };

    recognition.onend = () => {
        state.listening = false;
        updateVisaInterviewControls(mode);
        if (state.active && !state.pending && state.channel === 'voice' && (shouldAutoRestart || !receivedFinalAnswer)) {
            setVisaInterviewStatus(mode, 'Listening...');
            window.setTimeout(() => {
                if (state.active && !state.pending && !state.listening && state.channel === 'voice') {
                    listenVisaInterviewAnswer(mode);
                }
            }, 250);
            return;
        }
        if (state.active && !state.pending) {
            setVisaInterviewStatus(mode, 'Ready for answer');
        }
    };

    recognition.onresult = async (event) => {
        let finalTranscript = '';
        let interimTranscript = '';

        for (let i = event.resultIndex; i < event.results.length; ++i) {
            if (event.results[i].isFinal) {
                finalTranscript += event.results[i][0].transcript;
            } else {
                interimTranscript += event.results[i][0].transcript;
            }
        }

        const answer = finalTranscript.trim();
        if (answer) {
            receivedFinalAnswer = true;
            appendVisaInterviewLog(mode, 'user', `Student: ${answer}`);
            await sendVisaInterviewTurn(mode, answer, false);
        }
    };

    try {
        recognition.start();
    } catch (error) {
        state.listening = false;
        const name = (error && error.name) ? String(error.name).toLowerCase() : '';
        if (name.includes('notallowed') || name.includes('security')) {
            setVisaInterviewMicPermission(mode, 'denied', false);
        }
        updateVisaInterviewControls(mode);
        setVisaInterviewStatus(mode, 'Mic start failed');
        appendVisaInterviewLog(mode, 'system', 'Could not start microphone. Allow mic permission and try again.');
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
        ? 'Start the prep session now. Ask the first interview question.'
        : 'Start the mock interview now. Ask your first visa-officer question only.';
    const instruction = mode === 'prep' ? visaPrepInterviewInstruction() : visaMockInterviewInstruction();
    const userTurnContent = isInitialTurn ? initialTurnPrompt : `Student answer: ${studentMessage}`;
    const geminiMessage = `${instruction}\n\n${userTurnContent}`;

    const conversationWindow = 200;
    const conversationHistory = state.history.slice(-conversationWindow);
    conversationHistory.push({
        role: 'user',
        content: studentMessage
    });

    let shouldAutoFinish = false;
    let shouldAutoListen = false;

    try {
        const response = await aiFetch(`${API_BASE}/api/ai-chat/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                message: geminiMessage,
                conversation_history: conversationHistory,
                source: mode === 'prep' ? 'visa_prep' : 'mock_interview'
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
        const retainedHistoryWindow = 200;
        if (state.history.length > retainedHistoryWindow) {
            state.history = state.history.slice(-retainedHistoryWindow);
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
            stopMockInterviewTimer();
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
                shouldAutoListen = true;
                setVisaInterviewStatus(mode, 'Listening...');
            }
        }
    } catch (error) {
        console.error('Voice interview error:', error);
        clearVisaInterviewPendingBubble(mode);
        appendVisaInterviewLog(mode, 'system', RILONO_AI_PUBLIC_ERROR_MESSAGE);
        setVisaInterviewStatus(mode, 'Error');
    } finally {
        clearVisaInterviewPendingBubble(mode);
        state.pending = false;
        updateVisaInterviewControls(mode);
        // Honor a Finish requested while the officer was replying: run it now that the reply
        // is done, and don't kick off voice auto-listen for a turn we're about to end.
        const finishQueued = mode === 'mock' && state.finishRequested;
        if (shouldAutoListen && state.active && state.channel === 'voice' && !finishQueued) {
            setVisaInterviewStatus(mode, 'Listening...');
            listenVisaInterviewAnswer(mode);
        }
        if (mode === 'mock' && (shouldAutoFinish || finishQueued)) {
            state.finishRequested = false;
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

function clampMockReportPercentage(value) {
    if (!Number.isFinite(value)) {
        return null;
    }
    return Math.max(0, Math.min(100, Math.round(value)));
}

function normalizeMockReportSectionTitle(rawTitle) {
    const normalized = String(rawTitle || '').trim().toLowerCase().replace(/[:\-–—\s]+$/, '');
    if (!normalized) {
        return null;
    }
    if (/^decision drivers?$/.test(normalized)) {
        return 'Decision Drivers';
    }
    if (/^strengths?$/.test(normalized)) {
        return 'Strengths';
    }
    if (/^risk areas?$/.test(normalized)) {
        return 'Risk Areas';
    }
    if (/^top improvements before real interview$/.test(normalized) || /^top improvements?$/.test(normalized) || /^improvements before real interview$/.test(normalized)) {
        return 'Top Improvements Before Real Interview';
    }
    if (/^rilono ai note$/.test(normalized) || /^note$/.test(normalized)) {
        return 'Rilono AI Note';
    }
    return null;
}

function parseMockInterviewReportModel(reportText) {
    const text = normalizeMockInterviewReportText(reportText);
    if (!text) {
        return {
            approval: null,
            rejection: null,
            introParagraphs: [],
            sections: []
        };
    }

    const lines = text.split('\n');
    const sectionOrder = [];
    const sectionItemsByTitle = {};
    const introParagraphs = [];
    let activeSectionTitle = null;
    let approval = null;
    let rejection = null;

    const ensureSection = (title) => {
        if (!sectionItemsByTitle[title]) {
            sectionItemsByTitle[title] = [];
            sectionOrder.push(title);
        }
    };

    const pushLineToCurrentScope = (value) => {
        if (!value) return;
        if (activeSectionTitle) {
            ensureSection(activeSectionTitle);
            sectionItemsByTitle[activeSectionTitle].push(value);
            return;
        }
        introParagraphs.push(value);
    };

    for (const rawLine of lines) {
        const line = rawLine.trim();
        if (!line) {
            continue;
        }

        let normalized = line
            .replace(/^\d+\)\s*/, '')
            .replace(/^\d+\.\s*/, '')
            .trim();

        const metricMatch = normalized.match(/^(Approval Probability|Rejection Probability)\s*:?\s*(\d{1,3})%/i);
        if (metricMatch) {
            const metricValue = clampMockReportPercentage(Number.parseInt(metricMatch[2], 10));
            if (metricValue !== null) {
                if (/approval/i.test(metricMatch[1])) {
                    approval = metricValue;
                } else {
                    rejection = metricValue;
                }
            }
            continue;
        }

        const sectionMatch = normalized.match(/^(Decision Drivers|Strengths|Risk Areas|Top Improvements(?: Before Real Interview)?|Improvements Before Real Interview|Rilono AI Note|Note)\s*:?\s*(.*)$/i);
        if (sectionMatch) {
            activeSectionTitle = normalizeMockReportSectionTitle(sectionMatch[1]);
            if (!activeSectionTitle) {
                activeSectionTitle = null;
                continue;
            }
            ensureSection(activeSectionTitle);
            const trailingContent = sectionMatch[2].trim();
            if (trailingContent) {
                sectionItemsByTitle[activeSectionTitle].push(trailingContent);
            }
            continue;
        }

        if (/^[-•]\s+/.test(normalized)) {
            normalized = normalized.replace(/^[-•]\s+/, '').trim();
        }
        pushLineToCurrentScope(normalized);
    }

    if (approval === null && rejection !== null) {
        approval = clampMockReportPercentage(100 - rejection);
    } else if (rejection === null && approval !== null) {
        rejection = clampMockReportPercentage(100 - approval);
    }

    const sections = sectionOrder.map((title) => ({
        title,
        items: sectionItemsByTitle[title] || []
    }));

    return {
        approval,
        rejection,
        introParagraphs,
        sections
    };
}

function getMockReportVerdictModel(approvalValue, rejectionValue) {
    if (!Number.isFinite(approvalValue) && !Number.isFinite(rejectionValue)) {
        return {
            label: 'Outcome not available',
            note: 'Complete the full mock session to generate confidence scores.',
            toneClass: 'is-neutral'
        };
    }

    const effectiveApproval = Number.isFinite(approvalValue)
        ? approvalValue
        : clampMockReportPercentage(100 - rejectionValue);
    const effectiveRejection = Number.isFinite(rejectionValue)
        ? rejectionValue
        : clampMockReportPercentage(100 - approvalValue);

    if (effectiveApproval >= 70 && effectiveRejection <= 30) {
        return {
            label: 'Strong approval outlook',
            note: 'Your current answers show a solid visa narrative with lower rejection risk.',
            toneClass: 'is-positive'
        };
    }
    if (effectiveApproval >= 45 && effectiveApproval <= 69) {
        return {
            label: 'Balanced but improvable',
            note: 'You have potential, but key sections need sharper and more consistent responses.',
            toneClass: 'is-moderate'
        };
    }
    return {
        label: 'High rejection risk',
        note: 'Focus on the risk areas below before your real interview attempt.',
        toneClass: 'is-critical'
    };
}

function buildMockInterviewMetricCard(label, value, toneClass, helperText) {
    const safeValue = Number.isFinite(value) ? clampMockReportPercentage(value) : null;
    const displayValue = safeValue === null ? 'N/A' : `${safeValue}%`;
    const meterValue = safeValue === null ? 0 : safeValue;

    return (
        `<div class="visa-mock-report-metric-card ${toneClass}" style="--metric-value:${meterValue}%;">` +
        `<div class="visa-mock-report-metric-label">${escapeHtml(label)}</div>` +
        `<div class="visa-mock-report-metric-value">${escapeHtml(displayValue)}</div>` +
        `<div class="visa-mock-report-metric-meter"><span class="visa-mock-report-metric-fill"></span></div>` +
        `<div class="visa-mock-report-metric-helper">${escapeHtml(helperText)}</div>` +
        `</div>`
    );
}

function buildMockInterviewReportHtml(reportText) {
    const model = parseMockInterviewReportModel(reportText);
    if (!model.introParagraphs.length && !model.sections.length && !Number.isFinite(model.approval) && !Number.isFinite(model.rejection)) {
        return '<p class="visa-mock-report-paragraph">No report content available.</p>';
    }

    const approvalValue = Number.isFinite(model.approval) ? model.approval : null;
    const rejectionValue = Number.isFinite(model.rejection) ? model.rejection : null;
    const verdict = getMockReportVerdictModel(approvalValue, rejectionValue);
    const introHtml = model.introParagraphs.length
        ? `<div class="visa-mock-report-summary">${model.introParagraphs.map((line) => `<p class="visa-mock-report-paragraph">${escapeHtml(line)}</p>`).join('')}</div>`
        : '';
    const metricCards = [
        buildMockInterviewMetricCard('Approval Probability', approvalValue, 'visa-mock-report-metric-card-approval', 'Likelihood of approval based on this mock transcript.'),
        buildMockInterviewMetricCard('Rejection Probability', rejectionValue, 'visa-mock-report-metric-card-rejection', 'Risk estimate you should reduce before the actual interview.')
    ];

    const sectionClassByTitle = {
        'Decision Drivers': 'section-drivers',
        Strengths: 'section-strengths',
        'Risk Areas': 'section-risks',
        'Top Improvements Before Real Interview': 'section-improvements',
        'Rilono AI Note': 'section-note'
    };
    const sectionCards = model.sections.map((section) => {
        const sectionClass = sectionClassByTitle[section.title] || 'section-generic';
        const sectionItemsHtml = section.items.length
            ? `<ul class="visa-mock-report-list">${section.items.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`
            : '<p class="visa-mock-report-paragraph">No additional points were generated for this section.</p>';

        return (
            `<section class="visa-mock-report-section-card ${sectionClass}">` +
            `<div class="visa-mock-report-section-head">` +
            `<h4 class="visa-mock-report-section-title">${escapeHtml(section.title)}</h4>` +
            `<span class="visa-mock-report-section-count">${section.items.length || 0} point${section.items.length === 1 ? '' : 's'}</span>` +
            `</div>` +
            `${sectionItemsHtml}` +
            `</section>`
        );
    });

    return (
        `<div class="visa-mock-report-shell">` +
        `${introHtml}` +
        `<div class="visa-mock-report-overview">` +
        `<div class="visa-mock-report-verdict ${verdict.toneClass}">` +
        `<div class="visa-mock-report-verdict-label">Overall Outlook</div>` +
        `<div class="visa-mock-report-verdict-value">${escapeHtml(verdict.label)}</div>` +
        `<div class="visa-mock-report-verdict-note">${escapeHtml(verdict.note)}</div>` +
        `</div>` +
        `<div class="visa-mock-report-metrics">${metricCards.join('')}</div>` +
        `</div>` +
        `<div class="visa-mock-report-sections">${sectionCards.join('')}</div>` +
        `</div>`
    );
}

function renderVisaMockInterviewReport(reportText) {
    const reportEl = document.getElementById('visaMockInterviewReport');
    if (!reportEl) return;
    reportEl.style.display = 'block';
    const generatedLabel = new Date().toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
    reportEl.innerHTML = `
        <div class="visa-mock-report-header">
            <div class="visa-mock-report-title-wrap">
                <div class="visa-mock-report-title">Final Interview Report</div>
                <div class="visa-mock-report-subtitle">Actionable evaluation generated from your full mock interview transcript.</div>
                <div class="visa-mock-report-generated-at">Generated ${escapeHtml(generatedLabel)}</div>
            </div>
            <button type="button" class="btn btn-secondary visa-mock-report-download-btn" onclick="downloadMockInterviewReportPdf()">
                📥 Download PDF
            </button>
        </div>
        <div class="visa-mock-report-body">${buildMockInterviewReportHtml(reportText)}</div>
    `;
    // Consulate Window: the decision-slip moment — colored slip slides across the
    // window before the student reads the full report below it.
    showConsulateVerdictSlip(reportText);
}

function downloadMockInterviewReportPdf() {
    const reportEl = document.getElementById('visaMockInterviewReport');
    if (!reportEl) return;

    const bodyContent = reportEl.querySelector('.visa-mock-report-body');
    if (!bodyContent) return;

    const printWindow = window.open('', '_blank', 'width=800,height=900');
    if (!printWindow) {
        showMessage('Please allow pop-ups to download the PDF.', 'error');
        return;
    }

    const now = new Date();
    const dateStr = now.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
    const timeStr = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });

    printWindow.document.write(`<!DOCTYPE html>
<html>
<head>
    <title>Rilono - Mock Interview Report</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        @page { size: A4; margin: 10mm; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            color: #e2e8f0;
            padding: 1.2rem;
            line-height: 1.55;
            max-width: 800px;
            margin: 0 auto;
            position: relative;
            background:
                radial-gradient(circle at 10% 0%, rgba(15, 118, 110, 0.23), transparent 40%),
                radial-gradient(circle at 90% 10%, rgba(37, 99, 235, 0.2), transparent 44%),
                linear-gradient(180deg, #0b1b3a, #081a31);
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }
        .pdf-watermark {
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%) rotate(-28deg);
            font-size: 4.6rem;
            font-weight: 800;
            letter-spacing: 0.28rem;
            text-transform: uppercase;
            color: rgba(147, 197, 253, 0.11);
            pointer-events: none;
            user-select: none;
            white-space: nowrap;
            z-index: 0;
        }
        .pdf-shell {
            position: relative;
            z-index: 1;
            border: 1px solid rgba(45, 212, 191, 0.32);
            border-radius: 14px;
            background:
                radial-gradient(circle at 10% 0%, rgba(15, 118, 110, 0.18), transparent 42%),
                radial-gradient(circle at 85% 10%, rgba(30, 64, 175, 0.2), transparent 46%),
                linear-gradient(180deg, rgba(5, 20, 46, 0.96), rgba(7, 30, 58, 0.93));
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04), 0 10px 24px rgba(2, 6, 23, 0.34);
            padding: 0.95rem;
        }
        .pdf-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 0.8rem;
            border-bottom: 1px solid rgba(56, 189, 248, 0.26);
            padding-bottom: 0.7rem;
            margin-bottom: 0.85rem;
        }
        .pdf-header-left {
            display: grid;
            gap: 0.18rem;
            max-width: 70%;
        }
        .pdf-title {
            font-size: 1.28rem;
            font-weight: 800;
            color: #e0f2fe;
            letter-spacing: 0.01em;
        }
        .pdf-subtitle {
            color: #a5f3fc;
            font-size: 0.78rem;
            line-height: 1.35;
        }
        .pdf-header-right {
            display: grid;
            gap: 0.22rem;
            justify-items: end;
        }
        .pdf-meta {
            font-size: 0.74rem;
            color: #cbd5e1;
        }
        .pdf-brand {
            font-size: 0.72rem;
            color: #ccfbf1;
            border: 1px solid rgba(45, 212, 191, 0.4);
            border-radius: 999px;
            padding: 0.12rem 0.45rem;
            background: rgba(13, 148, 136, 0.22);
            font-weight: 700;
        }
        .pdf-body {
            display: grid;
            gap: 0.9rem;
        }
        .visa-mock-report-shell {
            display: grid;
            gap: 0.9rem;
        }
        .visa-mock-report-summary {
            border: 1px solid rgba(125, 211, 252, 0.24);
            border-radius: 0.82rem;
            background: rgba(15, 23, 42, 0.34);
            padding: 0.7rem 0.8rem;
            display: grid;
            gap: 0.4rem;
        }
        .visa-mock-report-overview {
            display: grid;
            grid-template-columns: 1fr 1.5fr;
            gap: 0.66rem;
            align-items: stretch;
        }
        .visa-mock-report-verdict {
            border: 1px solid rgba(148, 163, 184, 0.32);
            border-radius: 0.8rem;
            background: rgba(15, 23, 42, 0.58);
            padding: 0.72rem;
            display: grid;
            gap: 0.28rem;
        }
        .visa-mock-report-verdict-label {
            font-size: 0.68rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #94a3b8;
            font-weight: 700;
        }
        .visa-mock-report-verdict-value {
            font-size: 1rem;
            font-weight: 800;
            color: #f8fafc;
            line-height: 1.25;
        }
        .visa-mock-report-verdict-note {
            font-size: 0.76rem;
            line-height: 1.42;
            color: #cbd5e1;
        }
        .visa-mock-report-verdict.is-positive {
            border-color: rgba(34, 197, 94, 0.42);
            background: linear-gradient(145deg, rgba(6, 78, 59, 0.62), rgba(15, 23, 42, 0.62));
        }
        .visa-mock-report-verdict.is-moderate {
            border-color: rgba(245, 158, 11, 0.44);
            background: linear-gradient(145deg, rgba(120, 53, 15, 0.54), rgba(15, 23, 42, 0.62));
        }
        .visa-mock-report-verdict.is-critical {
            border-color: rgba(248, 113, 113, 0.42);
            background: linear-gradient(145deg, rgba(127, 29, 29, 0.52), rgba(15, 23, 42, 0.62));
        }
        .visa-mock-report-verdict.is-neutral {
            border-color: rgba(148, 163, 184, 0.34);
            background: linear-gradient(145deg, rgba(30, 41, 59, 0.7), rgba(15, 23, 42, 0.62));
        }
        .visa-mock-report-metrics {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.6rem;
        }
        .visa-mock-report-metric-card {
            --metric-value: 0%;
            border: 1px solid rgba(148, 163, 184, 0.3);
            border-radius: 0.8rem;
            background: rgba(15, 23, 42, 0.54);
            padding: 0.68rem 0.72rem;
            display: grid;
            gap: 0.32rem;
        }
        .visa-mock-report-metric-card-approval {
            border-color: rgba(16, 185, 129, 0.38);
            background: linear-gradient(150deg, rgba(5, 46, 22, 0.52), rgba(15, 23, 42, 0.58));
        }
        .visa-mock-report-metric-card-rejection {
            border-color: rgba(248, 113, 113, 0.36);
            background: linear-gradient(150deg, rgba(69, 10, 10, 0.48), rgba(15, 23, 42, 0.58));
        }
        .visa-mock-report-metric-label {
            color: #94a3b8;
            font-size: 0.68rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-weight: 700;
        }
        .visa-mock-report-metric-value {
            color: #ecfeff;
            font-size: 1.2rem;
            font-weight: 800;
            line-height: 1.2;
        }
        .visa-mock-report-metric-meter {
            height: 0.42rem;
            border-radius: 999px;
            background: rgba(148, 163, 184, 0.2);
            overflow: hidden;
        }
        .visa-mock-report-metric-fill {
            display: block;
            width: var(--metric-value);
            height: 100%;
            border-radius: inherit;
        }
        .visa-mock-report-metric-card-approval .visa-mock-report-metric-fill {
            background: linear-gradient(90deg, #34d399, #2dd4bf);
        }
        .visa-mock-report-metric-card-rejection .visa-mock-report-metric-fill {
            background: linear-gradient(90deg, #f59e0b, #ef4444);
        }
        .visa-mock-report-metric-helper {
            color: rgba(203, 213, 225, 0.82);
            font-size: 0.69rem;
            line-height: 1.32;
        }
        .visa-mock-report-sections {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.62rem;
        }
        .visa-mock-report-section-card {
            --section-accent: #38bdf8;
            border: 1px solid rgba(148, 163, 184, 0.25);
            border-radius: 0.82rem;
            background: rgba(15, 23, 42, 0.45);
            padding: 0.66rem 0.74rem;
            display: grid;
            gap: 0.48rem;
            position: relative;
            overflow: hidden;
        }
        .visa-mock-report-section-card::before {
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
            background: var(--section-accent);
            opacity: 0.9;
        }
        .visa-mock-report-section-card.section-drivers { --section-accent: #38bdf8; }
        .visa-mock-report-section-card.section-strengths { --section-accent: #22c55e; }
        .visa-mock-report-section-card.section-risks { --section-accent: #ef4444; }
        .visa-mock-report-section-card.section-improvements {
            --section-accent: #f59e0b;
            grid-column: 1 / -1;
        }
        .visa-mock-report-section-card.section-note {
            --section-accent: #a78bfa;
            grid-column: 1 / -1;
        }
        .visa-mock-report-section-head {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 0.5rem;
        }
        .visa-mock-report-section-title {
            margin: 0;
            font-size: 0.9rem;
            color: #dbeafe;
            font-weight: 700;
            letter-spacing: 0.01em;
        }
        .visa-mock-report-section-count {
            font-size: 0.65rem;
            color: #94a3b8;
            border: 1px solid rgba(148, 163, 184, 0.35);
            border-radius: 999px;
            padding: 0.12rem 0.42rem;
            white-space: nowrap;
        }
        .visa-mock-report-paragraph {
            margin: 0;
            color: #e2e8f0;
            line-height: 1.5;
            font-size: 0.84rem;
        }
        .visa-mock-report-list {
            margin: 0;
            padding: 0;
            list-style: none;
            color: #e2e8f0;
            display: grid;
            gap: 0.34rem;
        }
        .visa-mock-report-list li {
            line-height: 1.46;
            padding-left: 0.95rem;
            position: relative;
            font-size: 0.82rem;
        }
        .visa-mock-report-list li::before {
            content: "";
            position: absolute;
            left: 0.04rem;
            top: 0.5rem;
            width: 0.32rem;
            height: 0.32rem;
            border-radius: 999px;
            background: var(--section-accent);
            box-shadow: 0 0 0 2px rgba(148, 163, 184, 0.22);
        }
        .pdf-footer {
            margin-top: 0.9rem;
            padding-top: 0.55rem;
            border-top: 1px solid rgba(148, 163, 184, 0.3);
            font-size: 0.75rem;
            color: #a5b4fc;
            text-align: center;
        }
        @media print {
            body { padding: 0; }
            .pdf-watermark { color: rgba(147, 197, 253, 0.14); }
        }
    </style>
</head>
<body>
    <div class="pdf-watermark">RILONO AI</div>
    <div class="pdf-shell">
        <div class="pdf-header">
            <div class="pdf-header-left">
                <div class="pdf-title">Mock Interview Report</div>
                <div class="pdf-subtitle">Actionable evaluation generated from your full mock interview transcript.</div>
            </div>
            <div class="pdf-header-right">
                <div class="pdf-meta">${dateStr} at ${timeStr}</div>
                <div class="pdf-brand">Generated by Rilono AI</div>
            </div>
        </div>
        <div class="pdf-body">${bodyContent.innerHTML}</div>
        <div class="pdf-footer">This report was generated by Rilono AI Mock Interview. For educational purposes only.</div>
    </div>
</body>
</html>`);
    printWindow.document.close();

    setTimeout(() => {
        printWindow.focus();
        printWindow.print();
    }, 400);
}

async function finishVoiceMockInterview() {
    const state = visaMockInterviewState;
    if (state.reportGenerating) {
        // A report is already being generated — ignore repeat clicks.
        return;
    }
    if (state.pending) {
        // The officer is still replying. Queue the finish and reflect it in the UI rather than
        // silently swallowing the click (which made the button feel broken). The queued finish
        // runs automatically once the reply completes (see sendVisaInterviewTurn's finally).
        if (state.history.length === 0) {
            showMessage('No mock interview history found. Start the interview first.', 'error');
            return;
        }
        if (!state.finishRequested) {
            state.finishRequested = true;
            appendVisaInterviewLog('mock', 'system', "Got it — I'll generate your final report as soon as the officer finishes the current reply.");
        }
        setVisaInterviewStatus('mock', 'Ending after the officer replies…');
        updateVisaInterviewControls('mock');
        return;
    }
    if (state.history.length === 0) {
        showMessage('No mock interview history found. Start the interview first.', 'error');
        return;
    }

    stopVisaInterviewRecognition('mock');
    state.active = false;
    stopMockInterviewTimer();
    state.finishRequested = false;
    state.reportGenerating = true;
    state.pending = true;
    updateVisaInterviewControls('mock');
    appendVisaInterviewLog('mock', 'system', 'Generating final report…');
    startMockReportGenerationProgress();

    let reportSucceeded = false;
    try {
        const transcript = buildVisaInterviewTranscript(state.history);
        const reportPrompt = `${visaMockReportInstruction()}\n\nInterview transcript:\n${transcript}`;
        const response = await aiFetch(`${API_BASE}/api/ai-chat/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                message: reportPrompt,
                conversation_history: [],
                source: 'mock_interview_report'
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
        reportSucceeded = true;
        const reportElapsedMs = stopMockReportGenerationProgress();
        const reportElapsedLabel = formatInterviewElapsedTime(reportElapsedMs);

        /* Convert the "generating" log item into a "done" state */
        const logEl = document.getElementById('visaMockInterviewLog');
        if (logEl) {
            const genItem = logEl.querySelector('.visa-mock-log-item.report-generating');
            if (genItem) {
                genItem.classList.remove('report-generating');
                genItem.classList.add('report-done');
                genItem.innerHTML = `<span class="report-done-icon">✓</span><span>Report generated successfully in ${escapeHtml(reportElapsedLabel)}.</span>`;
            }
        }

        appendVisaInterviewLog('mock', 'assistant', 'Visa Officer: Final report is ready below.');
        void loadSubscriptionStatus(true);
    } catch (error) {
        console.error('Mock report generation error:', error);
        stopMockReportGenerationProgress();
        const logEl = document.getElementById('visaMockInterviewLog');
        const genItem = logEl ? logEl.querySelector('.visa-mock-log-item.report-generating') : null;
        if (genItem) genItem.remove();
        appendVisaInterviewLog('mock', 'system', RILONO_AI_PUBLIC_ERROR_MESSAGE);
        setVisaInterviewStatus('mock', 'Report error');
    } finally {
        stopMockReportGenerationProgress();
        state.pending = false;
        state.reportGenerating = false;
        state.finishRequested = false;
        if (window.speechSynthesis) {
            window.speechSynthesis.cancel();
        }
        if (reportSucceeded) {
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

// The mock interview is grounded in the student's uploaded documents, so its realism is
// only as good as those documents. These are the core documents an officer's questions
// hinge on — if none is present-and-valid, we warn before grounding a stressful interview
// in missing/placeholder data (e.g. a "passport" that failed validation).
function interviewCoreDocRequirements() {
    const code = (currentUser && currentUser.destination_country_code) || 'US';
    const reqs = [{ type: 'passport', label: 'Passport' }];
    if (code === 'US') {
        reqs.push({ type: 'form-i20-signed', label: 'Form I-20' });
    } else if (Array.isArray(requiredDocumentTypeValues) && requiredDocumentTypeValues.includes('university-admission-letter')) {
        reqs.push({ type: 'university-admission-letter', label: 'University admission letter' });
    }
    return reqs;
}

// For each core requirement, flag it when there's no VALID (is_valid === true) document of
// that type: 'missing' (none uploaded) vs 'invalid' (uploaded but failed/awaiting validation).
function findInterviewDocGaps(documents, requirements) {
    const gaps = [];
    for (const req of requirements) {
        const matching = (documents || []).filter((d) => (d.document_type || '') === req.type);
        if (!matching.length) {
            gaps.push({ label: req.label, status: 'missing' });
        } else if (!matching.some((d) => d.is_valid === true)) {
            gaps.push({ label: req.label, status: 'invalid' });
        }
    }
    return gaps;
}

function showInterviewDocWarningModal(gaps) {
    return new Promise((resolve) => {
        const existing = document.getElementById('interviewDocWarnOverlay');
        if (existing) existing.remove();
        const overlay = document.createElement('div');
        overlay.id = 'interviewDocWarnOverlay';
        overlay.style.cssText = 'position:fixed;inset:0;z-index:100000;background:rgba(15,23,42,0.55);display:flex;align-items:center;justify-content:center;padding:20px;font-family:inherit;';
        const rows = gaps.map((g) => `<li style="margin:5px 0;"><strong style="color:#0f172a;">${escapeHtml(g.label)}</strong> <span style="color:#64748b;">— ${g.status === 'missing' ? 'not uploaded' : 'didn’t pass validation'}</span></li>`).join('');
        overlay.innerHTML = `
          <div role="dialog" aria-modal="true" style="max-width:460px;width:100%;background:#fff;border-radius:16px;box-shadow:0 24px 60px rgba(2,6,23,0.4);overflow:hidden;">
            <div style="padding:20px 24px;background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;">
              <div style="font-size:12px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;opacity:.9;">Before you begin</div>
              <div style="font-size:19px;font-weight:800;margin-top:4px;">Start without valid documents?</div>
            </div>
            <div style="padding:22px 24px;color:#334155;font-size:14.5px;line-height:1.6;">
              <p style="margin:0 0 12px;">This mock interview is grounded in the documents in your account, so the officer's questions are only as realistic as what you've uploaded. We couldn't find a valid:</p>
              <ul style="margin:0 0 14px;padding-left:20px;">${rows}</ul>
              <p style="margin:0;color:#64748b;">Realism will be reduced and the officer may question missing or placeholder details. You can add valid documents first, or continue anyway.</p>
            </div>
            <div style="display:flex;gap:10px;justify-content:flex-end;padding:16px 24px;border-top:1px solid #eef2f7;">
              <button id="ivDocAddBtn" style="padding:10px 16px;border-radius:10px;border:1px solid #e2e8f0;background:#fff;color:#0f172a;font-weight:600;cursor:pointer;">Add documents</button>
              <button id="ivDocContinueBtn" style="padding:10px 16px;border-radius:10px;border:none;background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;font-weight:700;cursor:pointer;">Continue anyway</button>
            </div>
          </div>`;
        document.body.appendChild(overlay);
        const done = (val) => { overlay.remove(); resolve(val); };
        overlay.querySelector('#ivDocContinueBtn').onclick = () => done(true);
        overlay.querySelector('#ivDocAddBtn').onclick = () => {
            done(false);
            try { switchDashboardTab('documents'); } catch (e) { /* stay put */ }
        };
        overlay.addEventListener('click', (e) => { if (e.target === overlay) done(false); });
    });
}

// In-app styled confirm/prompt dialogs — replace the native window.confirm/alert/prompt
// browser popups (which show an ugly "<host> says" chrome) with on-brand modals.
// confirmDialog(message, opts) -> Promise<boolean>;  promptDialog(message, opts) -> Promise<string|null>.
function confirmDialog(message, opts) {
    opts = opts || {};
    const title = opts.title || 'Please confirm';
    const okText = opts.okText || 'Confirm';
    const cancelText = opts.cancelText || 'Cancel';
    const danger = opts.danger !== false; // default to destructive styling (most uses are deletes)
    const okBg = danger ? 'linear-gradient(135deg,#ef4444,#dc2626)' : 'linear-gradient(135deg,#6366f1,#a855f7)';
    return new Promise((resolve) => {
        const existing = document.getElementById('appConfirmOverlay');
        if (existing) existing.remove();
        const overlay = document.createElement('div');
        overlay.id = 'appConfirmOverlay';
        overlay.style.cssText = 'position:fixed;inset:0;z-index:100010;background:rgba(15,23,42,0.55);display:flex;align-items:center;justify-content:center;padding:20px;font-family:inherit;';
        overlay.innerHTML =
            '<div role="dialog" aria-modal="true" style="max-width:440px;width:100%;background:#fff;border-radius:16px;box-shadow:0 24px 60px rgba(2,6,23,0.4);overflow:hidden;">' +
                '<div style="padding:22px 24px 16px;">' +
                    '<div style="font-size:18px;font-weight:800;color:#0f172a;">' + escapeHtml(title) + '</div>' +
                    '<p style="margin:10px 0 0;color:#475569;font-size:14.5px;line-height:1.6;">' + escapeHtml(message).replace(/\n/g, '<br>') + '</p>' +
                '</div>' +
                '<div style="display:flex;gap:10px;justify-content:flex-end;padding:14px 24px 20px;">' +
                    '<button id="appCfmCancel" style="padding:10px 18px;border-radius:10px;border:1px solid #e2e8f0;background:#fff;color:#0f172a;font-weight:600;cursor:pointer;">' + escapeHtml(cancelText) + '</button>' +
                    '<button id="appCfmOk" style="padding:10px 18px;border-radius:10px;border:none;background:' + okBg + ';color:#fff;font-weight:700;cursor:pointer;">' + escapeHtml(okText) + '</button>' +
                '</div>' +
            '</div>';
        document.body.appendChild(overlay);
        let settled = false;
        const done = (val) => {
            if (settled) return; settled = true;
            document.removeEventListener('keydown', onKey, true);
            overlay.remove();
            resolve(val);
        };
        function onKey(e) {
            if (e.key === 'Escape') { e.stopPropagation(); done(false); }
            else if (e.key === 'Enter') { e.preventDefault(); done(true); }
        }
        overlay.querySelector('#appCfmOk').onclick = () => done(true);
        overlay.querySelector('#appCfmCancel').onclick = () => done(false);
        overlay.addEventListener('click', (e) => { if (e.target === overlay) done(false); });
        document.addEventListener('keydown', onKey, true);
        const ok = overlay.querySelector('#appCfmOk'); if (ok) ok.focus();
    });
}

function promptDialog(message, opts) {
    opts = opts || {};
    const title = opts.title || 'Enter a value';
    const okText = opts.okText || 'OK';
    const placeholder = opts.placeholder || '';
    const value = opts.value || '';
    const inputType = opts.type || 'text';
    return new Promise((resolve) => {
        const existing = document.getElementById('appPromptOverlay');
        if (existing) existing.remove();
        const overlay = document.createElement('div');
        overlay.id = 'appPromptOverlay';
        overlay.style.cssText = 'position:fixed;inset:0;z-index:100010;background:rgba(15,23,42,0.55);display:flex;align-items:center;justify-content:center;padding:20px;font-family:inherit;';
        overlay.innerHTML =
            '<div role="dialog" aria-modal="true" style="max-width:440px;width:100%;background:#fff;border-radius:16px;box-shadow:0 24px 60px rgba(2,6,23,0.4);overflow:hidden;">' +
                '<form id="appPromptForm"><div style="padding:22px 24px 8px;">' +
                    '<div style="font-size:18px;font-weight:800;color:#0f172a;">' + escapeHtml(title) + '</div>' +
                    '<p style="margin:10px 0 12px;color:#475569;font-size:14.5px;line-height:1.6;">' + escapeHtml(message) + '</p>' +
                    '<input id="appPromptInput" type="' + escapeHtml(inputType) + '" placeholder="' + escapeHtml(placeholder) + '" value="' + escapeHtml(value) + '" style="width:100%;box-sizing:border-box;padding:11px 13px;border:1px solid #e2e8f0;border-radius:10px;font-size:14.5px;color:#0f172a;outline:none;">' +
                '</div>' +
                '<div style="display:flex;gap:10px;justify-content:flex-end;padding:14px 24px 20px;">' +
                    '<button type="button" id="appPromptCancel" style="padding:10px 18px;border-radius:10px;border:1px solid #e2e8f0;background:#fff;color:#0f172a;font-weight:600;cursor:pointer;">Cancel</button>' +
                    '<button type="submit" id="appPromptOk" style="padding:10px 18px;border-radius:10px;border:none;background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;font-weight:700;cursor:pointer;">' + escapeHtml(okText) + '</button>' +
                '</div></form>' +
            '</div>';
        document.body.appendChild(overlay);
        let settled = false;
        const done = (val) => {
            if (settled) return; settled = true;
            document.removeEventListener('keydown', onKey, true);
            overlay.remove();
            resolve(val);
        };
        function onKey(e) { if (e.key === 'Escape') { e.stopPropagation(); done(null); } }
        overlay.querySelector('#appPromptForm').onsubmit = (e) => { e.preventDefault(); done(overlay.querySelector('#appPromptInput').value); };
        overlay.querySelector('#appPromptCancel').onclick = () => done(null);
        overlay.addEventListener('click', (e) => { if (e.target === overlay) done(null); });
        document.addEventListener('keydown', onKey, true);
        const inp = overlay.querySelector('#appPromptInput'); if (inp) inp.focus();
    });
}

// Returns true if the interview may proceed. Fail-open: a fetch/parse problem never blocks
// the student (they've paid/queued a session) — the warning is a courtesy, not a hard gate.
async function ensureInterviewDocumentsOrConfirm() {
    let docs = null;
    try {
        const r = await fetch(`${API_BASE}/api/documents/my-documents`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        if (r.ok) {
            const parsed = await r.json();
            if (Array.isArray(parsed)) docs = parsed;
        }
    } catch (e) { /* fail-open */ }
    if (!docs) return true;
    const gaps = findInterviewDocGaps(docs, interviewCoreDocRequirements());
    if (!gaps.length) return true;
    return showInterviewDocWarningModal(gaps);
}

async function beginMockInterview(channel) {
    if (channel !== 'voice' && channel !== 'chat') {
        return;
    }
    // Pre-interview document check — warn (don't hard-block) before grounding a realistic,
    // stressful mock interview in missing/invalid core documents. Runs BEFORE fullscreen and
    // BEFORE any session/credit is consumed, so cancelling costs the student nothing.
    const mayProceed = await ensureInterviewDocumentsOrConfirm();
    if (!mayProceed) {
        visaMockInterviewState.showModePicker = false;
        renderMockInterviewModeUI();
        return;
    }
    visaMockInterviewState.channel = channel;
    visaMockInterviewState.showModePicker = false;
    renderMockInterviewModeUI();

    const mockPanel = document.getElementById('visaMockPanel');
    if (mockPanel && !document.fullscreenElement) {
        try {
            await mockPanel.requestFullscreen();
        } catch (err) {
            console.warn('Could not enable fullscreen:', err);
        }
    }

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

    const prepPanel = document.getElementById('visaPrepPanel');
    if (prepPanel && !document.fullscreenElement) {
        try {
            await prepPanel.requestFullscreen();
        } catch (err) {
            console.warn('Could not enable fullscreen:', err);
        }
    }

    await startVoiceInterviewSession('prep', { channel });
}

// ===================== The Consulate Window (US voice mock interview) =====================
// Presents the voice mock interview as stepping up to an embassy window: dark booth, a
// speaking orb instead of chat bubbles, an accent-matched neural officer voice (Pass perk),
// pressure mechanics, and a decision-slip verdict reveal. US-only launch; stylized motifs
// only (deliberately NOT a real government seal) + persistent "simulation" disclaimer.

const CONSULATE_STRICTNESS_POOL = [
    'brisk and procedural — moves fast, cuts off rambling',
    'skeptical and probing — questions every claim twice',
    'stern and unimpressed — gives nothing away, zero small talk'
];

function isConsulateEligible(channel) {
    const dest = (currentUser && currentUser.destination_country_code) || 'US';
    return channel === 'voice' && dest === 'US';
}

function clientHasVisaPass() {
    return String((currentSubscription && currentSubscription.plan) || '').toLowerCase() === 'pro';
}

function enterConsulateMode() {
    const st = visaMockInterviewState;
    const panel = document.getElementById('visaMockPanel');
    if (!panel) return;
    st.consulate = true;
    st.windowNumber = 1 + Math.floor(Math.random() * 9);
    st.strictness = CONSULATE_STRICTNESS_POOL[Math.floor(Math.random() * CONSULATE_STRICTNESS_POOL.length)];
    panel.classList.add('consulate-active');
    panel.classList.remove('transcript-expanded');

    let booth = document.getElementById('consulateBooth');
    if (booth) booth.remove();
    booth = document.createElement('div');
    booth.id = 'consulateBooth';
    booth.className = 'consulate-booth';
    const voiceChip = clientHasVisaPass()
        ? '<span class="consulate-voice-chip pass">Immersive officer voice</span>'
        : '<span class="consulate-voice-chip">Standard voice · <a href="/visa-pass" target="_blank" rel="noopener">Pass unlocks the real officer voice</a></span>';
    booth.innerHTML = `
        <div class="consulate-stripes" aria-hidden="true"><i></i><i></i><i></i></div>
        <div class="consulate-plate-row">
            <div class="consulate-crest" aria-hidden="true">★</div>
            <div class="consulate-plate">
                <div class="consulate-plate-title">U.S. Consular Officer</div>
                <div class="consulate-plate-sub">Window ${st.windowNumber} · Nonimmigrant Visa Unit</div>
            </div>
            ${voiceChip}
        </div>
        <div class="consulate-orb-zone">
            <div id="consulateOrb" class="consulate-orb idle" aria-hidden="true"><span class="consulate-orb-core"></span></div>
            <div id="consulateOrbStatus" class="consulate-orb-status" role="status" aria-live="polite">Waiting room…</div>
            <div id="consulateNudge" class="consulate-nudge" style="display:none">The officer is waiting for your answer.</div>
        </div>
        <div class="consulate-footer-row">
            <span class="consulate-disclaimer">Simulation · Practice only · Not affiliated with any government agency</span>
            <button type="button" class="consulate-transcript-toggle" onclick="toggleConsulateTranscript()">Transcript ▾</button>
        </div>`;
    const headerline = panel.querySelector('.visa-mock-headerline');
    if (headerline && headerline.nextSibling) {
        panel.insertBefore(booth, headerline.nextSibling);
    } else {
        panel.prepend(booth);
    }
    if (st.orbIntervalId) clearInterval(st.orbIntervalId);
    st.orbIntervalId = setInterval(updateConsulateOrb, 500);
    updateConsulateOrb();
}

function exitConsulateMode() {
    const st = visaMockInterviewState;
    if (st.orbIntervalId) { clearInterval(st.orbIntervalId); st.orbIntervalId = null; }
    clearConsulateNudge();
    st.consulate = false;
    st.officerSpeaking = false;
    const panel = document.getElementById('visaMockPanel');
    if (panel) panel.classList.remove('consulate-active', 'transcript-expanded');
    const booth = document.getElementById('consulateBooth');
    if (booth) booth.remove();
    const intro = document.getElementById('consulateIntro');
    if (intro) intro.remove();
    const slip = document.getElementById('consulateSlip');
    if (slip) slip.remove();
}

function toggleConsulateTranscript() {
    const panel = document.getElementById('visaMockPanel');
    if (!panel) return;
    const expanded = panel.classList.toggle('transcript-expanded');
    const btn = panel.querySelector('.consulate-transcript-toggle');
    if (btn) btn.textContent = expanded ? 'Transcript ▴' : 'Transcript ▾';
}

// The 5-second waiting-room beat before the first question — manufactures the real
// step-up-to-the-window tension. Resolves when the overlay finishes.
function runConsulateIntro() {
    const panel = document.getElementById('visaMockPanel');
    const st = visaMockInterviewState;
    if (!panel || !st.consulate) return Promise.resolve();
    const old = document.getElementById('consulateIntro');
    if (old) old.remove();
    const overlay = document.createElement('div');
    overlay.id = 'consulateIntro';
    overlay.className = 'consulate-intro';
    overlay.innerHTML = `
        <div class="consulate-intro-inner">
            <div class="consulate-intro-crest" aria-hidden="true">★</div>
            <div class="consulate-intro-title">U.S. Consulate — Nonimmigrant Visas</div>
            <div class="consulate-intro-line" id="consulateIntroLine">Now serving: Window ${st.windowNumber}</div>
            <div class="consulate-intro-disclaimer">Simulation · Practice only</div>
        </div>`;
    panel.appendChild(overlay);
    const lineEl = () => document.getElementById('consulateIntroLine');
    return new Promise((resolve) => {
        setTimeout(() => { const el = lineEl(); if (el) el.textContent = 'Have your passport and I-20 ready.'; }, 1500);
        setTimeout(() => { const el = lineEl(); if (el) el.textContent = 'Please step forward.'; }, 3000);
        setTimeout(() => {
            overlay.classList.add('fade-out');
            setTimeout(() => { overlay.remove(); resolve(); }, 450);
        }, 4200);
    });
}

function updateConsulateOrb() {
    const st = visaMockInterviewState;
    const orb = document.getElementById('consulateOrb');
    const status = document.getElementById('consulateOrbStatus');
    if (!orb || !status || !st.consulate) return;
    let mode = 'idle';
    let label = 'Awaiting the officer…';
    const browserSpeaking = !!(window.speechSynthesis && window.speechSynthesis.speaking);
    if (st.officerSpeaking || browserSpeaking) {
        mode = 'speaking'; label = 'The officer is speaking…';
    } else if (st.pending) {
        mode = 'thinking'; label = 'The officer is reviewing your file…';
    } else if (st.listening) {
        mode = 'listening'; label = 'Listening — answer now';
    } else if (!st.active) {
        mode = 'idle'; label = 'Session ended';
    }
    // Speaking/thinking/listening all cancel the "officer is waiting" nudge.
    if (mode !== 'idle') clearConsulateNudge(false);
    orb.className = `consulate-orb ${mode}${document.getElementById('consulateNudge')?.style.display !== 'none' ? ' nudged' : ''}`;
    status.textContent = label;
}

// Pressure mechanic: officers judge hesitation. If the student freezes after the officer
// finishes speaking, surface a calm-but-firm nudge (visual only — no extra AI cost).
function armConsulateNudge() {
    const st = visaMockInterviewState;
    if (!st.consulate || st.channel !== 'voice') return;
    clearConsulateNudge();
    st.nudgeTimerId = setTimeout(() => {
        if (!st.consulate || !st.active || st.pending || st.officerSpeaking) return;
        const nudge = document.getElementById('consulateNudge');
        const orb = document.getElementById('consulateOrb');
        if (nudge) nudge.style.display = 'block';
        if (orb) orb.classList.add('nudged');
    }, 12000);
}

function clearConsulateNudge(cancelTimer = true) {
    const st = visaMockInterviewState;
    if (cancelTimer && st.nudgeTimerId) { clearTimeout(st.nudgeTimerId); st.nudgeTimerId = null; }
    const nudge = document.getElementById('consulateNudge');
    if (nudge && nudge.style.display !== 'none') nudge.style.display = 'none';
    const orb = document.getElementById('consulateOrb');
    if (orb) orb.classList.remove('nudged');
}

// Neural officer voice (Visa Success Pass perk). Any failure falls back to browser TTS —
// the interview must never break because of voice infrastructure.
async function playOfficerNeuralAudio(text) {
    if (!clientHasVisaPass()) return false;
    try {
        const r = await aiFetch(`${API_BASE}/api/ai-chat/tts/officer`, {
            method: 'POST',
            headers: sopAuthHeaders({ 'Content-Type': 'application/json' }),
            credentials: 'include',
            body: JSON.stringify({ text, country: 'US' })
        }, 22000);
        if (!r.ok) return false;
        const data = await r.json().catch(() => ({}));
        if (data.fallback || !data.audio) return false;
        await new Promise((resolve) => {
            const audio = new Audio(`data:audio/mp3;base64,${data.audio}`);
            audio.onended = resolve;
            audio.onerror = resolve;
            audio.play().catch(() => resolve());
        });
        return true;
    } catch (e) {
        return false; // timeout / network — browser TTS takes over
    }
}

// Decision-slip verdict reveal: the dramatic, screenshot-worthy end beat.
function showConsulateVerdictSlip(reportText) {
    const st = visaMockInterviewState;
    const panel = document.getElementById('visaMockPanel');
    if (!st.consulate || !panel) return;
    const match = /Approval\s+Probability[:\s]*([0-9]{1,3})/i.exec(reportText || '');
    if (!match) return;
    const approval = Math.max(0, Math.min(100, parseInt(match[1], 10)));
    const approved = approval >= 50;
    const old = document.getElementById('consulateSlip');
    if (old) old.remove();
    const overlay = document.createElement('div');
    overlay.id = 'consulateSlip';
    overlay.className = 'consulate-slip-overlay';
    overlay.innerHTML = `
        <div class="consulate-slip ${approved ? 'approved' : 'refused'}">
            <div class="consulate-slip-header">U.S. Consulate · Window ${st.windowNumber || ''}</div>
            <div class="consulate-slip-verdict">${approved ? 'LIKELY APPROVED' : 'LIKELY REFUSED'}</div>
            <div class="consulate-slip-pct">${approval}% approval probability</div>
            <div class="consulate-slip-note">Practice simulation — not an official decision</div>
        </div>`;
    overlay.addEventListener('click', () => overlay.remove());
    panel.appendChild(overlay);
    setTimeout(() => {
        overlay.classList.add('fade-out');
        setTimeout(() => overlay.remove(), 600);
    }, 3600);
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
    if (useVoiceInput) {
        const micPermission = await refreshVisaInterviewMicPermission(mode);
        if (micPermission === 'denied') {
            showMessage('Microphone is blocked in your browser. Enable mic access and try again.', 'error');
            initializeVisaInterviewUI(mode);
            return;
        }
    }

    const sessionType = mode === 'prep' ? 'prep' : 'mock';
    const quotaAllowed = await consumeInterviewSession(sessionType);
    if (!quotaAllowed) {
        initializeVisaInterviewUI(mode);
        return;
    }

    if (mode === 'prep') {
        stopVoicePrepInterview(true, false);
        state.channel = options.channel || 'voice';
        state.showModePicker = false;
    } else {
        stopVoiceMockInterview(true, false);
        state.channel = options.channel || 'voice';
        state.showModePicker = false;
    }

    state.active = true;
    state.pending = false;
    state.finishRequested = false;
    state.reportGenerating = false;
    state.history = [];
    hideFloatingChatPopupImmediate();
    if (mode === 'mock') {
        resetMockInterviewTimer();
        startMockInterviewTimer();
    }

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
        appendVisaInterviewLog('mock', 'system', 'Session started.');
    }

    setVisaInterviewStatus(mode, 'Starting interview...');
    updateVisaInterviewControls(mode);

    // The Consulate Window: US voice mock becomes the embassy-booth experience —
    // booth chrome + a short waiting-room beat before the officer's first question.
    if (mode === 'mock' && isConsulateEligible(state.channel)) {
        enterConsulateMode();
        await runConsulateIntro();
        if (!state.active) return; // user bailed during the intro
    }

    const readyMessage = mode === 'prep'
        ? 'I am ready for my visa interview prep session.'
        : 'I am ready for my visa mock interview.';
    await sendVisaInterviewTurn(mode, readyMessage, true);
}

async function startVoicePrepInterview() {
    await beginPrepInterview('voice');
}

async function startVoiceMockInterview() {
    await beginMockInterview('voice');
}

function stopVoiceMockInterview(silent = false, shouldExitFullscreen = true) {
    exitConsulateMode();
    clearVisaInterviewPendingBubble('mock');
    stopVisaInterviewRecognition('mock');
    stopMockInterviewTimer();
    visaMockInterviewState.active = false;
    visaMockInterviewState.pending = false;
    visaMockInterviewState.finishRequested = false;
    visaMockInterviewState.reportGenerating = false;
    visaMockInterviewState.channel = null;
    visaMockInterviewState.showModePicker = false;
    if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
    }
    if (shouldExitFullscreen && document.fullscreenElement) {
        document.exitFullscreen().catch(err => console.warn(err));
    }
    setVisaInterviewStatus('mock', 'Stopped');
    updateVisaInterviewControls('mock');

    if (!silent) {
        appendVisaInterviewLog('mock', 'system', 'Session stopped. Click "Finish & Report" to generate the final result.');
    }
}

function stopVoicePrepInterview(silent = false, shouldExitFullscreen = true) {
    clearVisaInterviewPendingBubble('prep');
    stopVisaInterviewRecognition('prep');
    visaPrepInterviewState.active = false;
    visaPrepInterviewState.pending = false;
    visaPrepInterviewState.channel = null;
    visaPrepInterviewState.showModePicker = false;
    if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
    }
    if (shouldExitFullscreen && document.fullscreenElement) {
        document.exitFullscreen().catch(err => console.warn(err));
    }
    setVisaInterviewStatus('prep', 'Stopped');
    updateVisaInterviewControls('prep');
    if (!silent) {
        appendVisaInterviewLog('prep', 'system', 'Prep session stopped.');
    }
}

function setVisaSubNavVisibility(isVisible) {
    const subNav = document.getElementById('visaSubNav');
    const isMobileDashboardNav = window.matchMedia(`(max-width: ${MOBILE_NAV_BREAKPOINT}px)`).matches;
    const showInlineSubNav = isVisible && !isMobileDashboardNav;
    if (subNav) {
        subNav.style.display = showInlineSubNav ? 'grid' : 'none';
    }

    const visaNavItem = document.querySelector('.nav-item[data-tab="visa"]');
    if (visaNavItem) {
        visaNavItem.classList.toggle('expanded', showInlineSubNav);
    }

    const caret = document.getElementById('visaNavCaret');
    if (caret) {
        caret.textContent = showInlineSubNav ? '▴' : '▾';
    }
}

// Universities sub-panel (Shortlist & Recommendations / SOP Studio) — mirrors the
// visa interviews sub-nav so the main sidebar stays uncluttered.
function setUniSubNavVisibility(isVisible) {
    const subNav = document.getElementById('uniSubNav');
    const isMobileDashboardNav = window.matchMedia(`(max-width: ${MOBILE_NAV_BREAKPOINT}px)`).matches;
    const showInlineSubNav = isVisible && !isMobileDashboardNav;
    if (subNav) {
        subNav.style.display = showInlineSubNav ? 'grid' : 'none';
    }
    const uniNavItem = document.querySelector('.nav-item[data-tab="universities"]');
    if (uniNavItem) {
        uniNavItem.classList.toggle('expanded', showInlineSubNav);
    }
}

function toggleVisaDashboardNav() {
    const visaTab = document.getElementById('dashboardTab-visa');
    const subNav = document.getElementById('visaSubNav');
    const isVisaTabActive = Boolean(visaTab?.classList.contains('active'));
    const isExpanded = Boolean(subNav && subNav.style.display !== 'none');

    if (isVisaTabActive && isExpanded) {
        setVisaSubNavVisibility(false);
        return;
    }

    switchDashboardTab('visa');
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
    document.querySelectorAll('.visa-mobile-subnav-btn').forEach(button => {
        button.classList.toggle('active', button.dataset.visaSubtab === targetSubTab);
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

function resetAdminUsersState(resetFilters = false) {
    adminUsersState.loading = false;
    adminUsersState.page = 1;
    adminUsersState.pageSize = ADMIN_USERS_PAGE_SIZE;
    adminUsersState.total = 0;
    adminUsersState.rows = [];
    if (resetFilters) {
        adminUsersState.search = ADMIN_USERS_DEFAULT_FILTERS.search;
        adminUsersState.status = ADMIN_USERS_DEFAULT_FILTERS.status;
        adminUsersState.role = ADMIN_USERS_DEFAULT_FILTERS.role;
        const searchInput = document.getElementById('adminUsersSearchInput');
        const statusInput = document.getElementById('adminUsersStatusFilter');
        const roleInput = document.getElementById('adminUsersRoleFilter');
        if (searchInput) searchInput.value = ADMIN_USERS_DEFAULT_FILTERS.search;
        if (statusInput) statusInput.value = ADMIN_USERS_DEFAULT_FILTERS.status;
        if (roleInput) roleInput.value = ADMIN_USERS_DEFAULT_FILTERS.role;
    }
}

function formatAdminDateTime(value) {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '-';
    return date.toLocaleString();
}

function getAdminRoleLabel(user) {
    if (user?.is_developer) return 'Developer';
    if (user?.is_admin) return 'Admin';
    return 'Student';
}

function renderAdminUsersSummary() {
    const summaryEl = document.getElementById('adminUsersSummary');
    if (!summaryEl) return;
    if (adminUsersState.total <= 0) {
        summaryEl.textContent = 'No users found for the selected filters.';
        return;
    }
    const start = ((adminUsersState.page - 1) * adminUsersState.pageSize) + 1;
    const end = Math.min(adminUsersState.total, start + adminUsersState.rows.length - 1);
    summaryEl.textContent = `Showing ${start}-${end} of ${adminUsersState.total} users`;
}

function renderAdminUsersPagination() {
    const prevBtn = document.getElementById('adminUsersPrevBtn');
    const nextBtn = document.getElementById('adminUsersNextBtn');
    const pageInfo = document.getElementById('adminUsersPageInfo');
    const searchBtn = document.getElementById('adminUsersSearchBtn');
    const totalPages = Math.max(1, Math.ceil(adminUsersState.total / adminUsersState.pageSize));

    if (pageInfo) {
        pageInfo.textContent = `Page ${adminUsersState.page} of ${totalPages}`;
    }
    if (prevBtn) {
        prevBtn.disabled = adminUsersState.loading || adminUsersState.page <= 1;
    }
    if (nextBtn) {
        nextBtn.disabled = adminUsersState.loading || adminUsersState.page >= totalPages;
    }
    if (searchBtn) {
        searchBtn.disabled = adminUsersState.loading;
    }
}

function renderAdminUsersMessageRow(message) {
    const bodyEl = document.getElementById('adminUsersTableBody');
    if (!bodyEl) return;
    bodyEl.innerHTML = `
        <tr>
            <td colspan="7" class="admin-users-empty-cell">${escapeHtml(message)}</td>
        </tr>
    `;
}

function renderAdminUsersTable() {
    const bodyEl = document.getElementById('adminUsersTableBody');
    if (!bodyEl) return;

    const users = adminUsersState.rows || [];
    if (!users.length) {
        renderAdminUsersMessageRow('No users found for these filters.');
        return;
    }

    const rows = users.map((user) => {
        const roleLabel = getAdminRoleLabel(user);
        const statusLabel = user.is_active ? 'Active' : 'Inactive';
        const verifiedLabel = user.email_verified ? 'Verified' : 'Pending';
        const displayName = user.full_name || user.username || user.email || 'Unknown user';
        const userMeta = [user.email, user.university].filter(Boolean).join(' • ');
        const canManagePrivileged = Boolean(currentUser?.is_developer);
        const isOwnAccount = Number(currentUser?.id) === Number(user.id);
        const isPrivilegedTarget = Boolean(user.is_admin || user.is_developer);
        const canManageUser = !isOwnAccount && (!isPrivilegedTarget || canManagePrivileged);
        const disableAttr = canManageUser ? '' : 'disabled';
        const manageHint = isOwnAccount
            ? 'You cannot modify your own account.'
            : (isPrivilegedTarget && !canManagePrivileged ? 'Only developers can manage admin/developer accounts.' : '');
        const manageTitle = manageHint ? ` title="${escapeHtml(manageHint)}"` : '';
        const toggleLabel = user.is_active ? 'Deactivate' : 'Activate';
        const toggleClass = user.is_active ? 'btn-danger' : 'btn-secondary';
        const nextActiveLiteral = user.is_active ? 'false' : 'true';
        const deleteEmailParam = JSON.stringify(user.email || 'this user');

        return `
            <tr>
                <td>
                    <div class="admin-user-primary">${escapeHtml(displayName)}</div>
                    <div class="admin-user-meta">${escapeHtml(userMeta || '-')}</div>
                </td>
                <td><span class="admin-role-chip">${escapeHtml(roleLabel)}</span></td>
                <td><span class="admin-status-chip ${user.is_active ? 'is-active' : 'is-inactive'}">${statusLabel}</span></td>
                <td>${verifiedLabel}</td>
                <td>${escapeHtml(formatAdminDateTime(user.created_at))}</td>
                <td>${escapeHtml(formatAdminDateTime(user.last_login_at))}</td>
                <td>
                    <div class="admin-users-actions">
                        <button type="button" class="btn ${toggleClass} admin-action-btn"
                            onclick="updateAdminUserStatus(${user.id}, ${nextActiveLiteral})" ${disableAttr}${manageTitle}>
                            ${toggleLabel}
                        </button>
                        <button type="button" class="btn btn-danger admin-action-btn"
                            onclick='deleteAdminUser(${user.id}, ${deleteEmailParam})' ${disableAttr}${manageTitle}>
                            Delete
                        </button>
                    </div>
                </td>
            </tr>
        `;
    });

    bodyEl.innerHTML = rows.join('');
}

function setAdminActionButtonsDisabled(disabled) {
    document.querySelectorAll('.admin-action-btn').forEach((btn) => {
        btn.disabled = disabled;
    });
}

async function loadAdminUsers(resetPage = false) {
    if (!authToken || !hasAdminConsoleAccess()) {
        renderAdminUsersMessageRow('Admin access required.');
        return;
    }

    const searchInput = document.getElementById('adminUsersSearchInput');
    const statusInput = document.getElementById('adminUsersStatusFilter');
    const roleInput = document.getElementById('adminUsersRoleFilter');

    if (resetPage) {
        adminUsersState.page = 1;
    }
    adminUsersState.search = (searchInput?.value || '').trim();
    adminUsersState.status = (statusInput?.value || ADMIN_USERS_DEFAULT_FILTERS.status).trim().toLowerCase();
    adminUsersState.role = (roleInput?.value || ADMIN_USERS_DEFAULT_FILTERS.role).trim().toLowerCase();
    adminUsersState.loading = true;
    renderAdminUsersMessageRow('Loading users...');
    renderAdminUsersPagination();

    try {
        const params = new URLSearchParams();
        params.set('page', String(adminUsersState.page));
        params.set('page_size', String(adminUsersState.pageSize));
        params.set('status', adminUsersState.status);
        params.set('role', adminUsersState.role);
        if (adminUsersState.search) {
            params.set('search', adminUsersState.search);
        }

        const response = await fetch(`${API_BASE}/api/admin/users?${params.toString()}`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        const payload = await response.json().catch(() => ({}));

        if (!response.ok) {
            const errorMessage = payload.detail || 'Failed to load users';
            adminUsersState.total = 0;
            adminUsersState.rows = [];
            renderAdminUsersMessageRow(errorMessage);
            renderAdminUsersSummary();
            if (response.status === 401 || response.status === 403) {
                showMessage(errorMessage, 'error');
            }
            return;
        }

        adminUsersState.total = Number(payload.total) || 0;
        adminUsersState.rows = Array.isArray(payload.users) ? payload.users : [];

        const totalPages = Math.max(1, Math.ceil(adminUsersState.total / adminUsersState.pageSize));
        if (adminUsersState.page > totalPages) {
            adminUsersState.page = totalPages;
            await loadAdminUsers(false);
            return;
        }

        renderAdminUsersTable();
        renderAdminUsersSummary();
    } catch (error) {
        console.error('Error loading admin users:', error);
        adminUsersState.total = 0;
        adminUsersState.rows = [];
        renderAdminUsersMessageRow('Failed to load users. Please try again.');
        renderAdminUsersSummary();
    } finally {
        adminUsersState.loading = false;
        renderAdminUsersPagination();
    }
}

function handleAdminUsersFilterSubmit(event) {
    event.preventDefault();
    adminUsersState.page = 1;
    void loadAdminUsers();
}

function resetAdminUsersFilters() {
    resetAdminUsersState(true);
    void loadAdminUsers(true);
}

function changeAdminUsersPage(delta) {
    const totalPages = Math.max(1, Math.ceil(adminUsersState.total / adminUsersState.pageSize));
    const nextPage = adminUsersState.page + Number(delta || 0);
    if (nextPage < 1 || nextPage > totalPages || adminUsersState.loading) {
        return;
    }
    adminUsersState.page = nextPage;
    void loadAdminUsers();
}

async function updateAdminUserStatus(userId, nextIsActive) {
    if (!authToken || !hasAdminConsoleAccess()) return;
    setAdminActionButtonsDisabled(true);

    try {
        const response = await fetch(`${API_BASE}/api/admin/users/${userId}/status`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ is_active: Boolean(nextIsActive) })
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            showMessage(payload.detail || 'Failed to update user status.', 'error');
            return;
        }

        showMessage(`User ${nextIsActive ? 'activated' : 'deactivated'} successfully.`, 'success');
        await loadAdminUsers(false);
    } catch (error) {
        console.error('Error updating user status:', error);
        showMessage('Failed to update user status.', 'error');
    } finally {
        setAdminActionButtonsDisabled(false);
    }
}

async function deleteAdminUser(userId, userEmail = 'this user') {
    if (!authToken || !hasAdminConsoleAccess()) return;
    if (!(await confirmDialog(`${userEmail} will be permanently deleted. This cannot be undone.`, { title: 'Delete user?', okText: 'Delete' }))) {
        return;
    }

    setAdminActionButtonsDisabled(true);
    try {
        const response = await fetch(`${API_BASE}/api/admin/users/${userId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            showMessage(payload.detail || 'Failed to delete user account.', 'error');
            return;
        }

        showMessage(`Deleted ${userEmail} successfully.`, 'success');
        if (adminUsersState.rows.length === 1 && adminUsersState.page > 1) {
            adminUsersState.page -= 1;
        }
        await loadAdminUsers(false);
    } catch (error) {
        console.error('Error deleting user account:', error);
        showMessage('Failed to delete user account.', 'error');
    } finally {
        setAdminActionButtonsDisabled(false);
    }
}

function switchDashboardTab(tabName) {
    // The standalone Universities page was folded into Course Finder: its saved shortlist is
    // Course Finder's "My shortlist" tab and its AI recommendations duplicated the AI shortlist.
    if (tabName === 'universities') { tabName = 'courses'; _cf.tab = 'shortlist'; }
    if (tabName === 'admin' && !hasAdminConsoleAccess()) {
        showMessage('Admin access required.', 'error');
        tabName = 'overview';
    }

    if (tabName !== 'visa' && (visaMockInterviewState.active || visaMockInterviewState.listening || visaMockInterviewState.pending)) {
        stopVoiceMockInterview(true);
    }
    if (tabName !== 'visa' && (visaPrepInterviewState.active || visaPrepInterviewState.listening || visaPrepInterviewState.pending)) {
        stopVoicePrepInterview(true);
    }
    closeExpandedChatView();

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
    // SOP Studio and Course Finder live under the Universities parent (no nav item of their own).
    if (tabName === 'sop' || tabName === 'courses') {
        const uniNav = document.querySelector('.nav-item[data-tab="universities"]');
        if (uniNav) uniNav.classList.add('active');
    }

    setVisaSubNavVisibility(tabName === 'visa');
    setUniSubNavVisibility(tabName === 'universities' || tabName === 'sop' || tabName === 'courses');
    document.querySelectorAll('#uniSubNav .visa-subnav-item').forEach((item) => {
        item.classList.toggle('active', item.dataset.uniSubtab === tabName);
    });

    // Load data for specific tabs
    if (tabName === 'documents') {
        loadMyDocuments();
    } else if (tabName === 'overview') {
        loadDashboardStats();
    } else if (tabName === 'profile') {
        loadProfile();
    } else if (tabName === 'settings') {
        loadProfile();
        hideDeleteAccountReveal();  // always start collapsed when entering Settings
    } else if (tabName === 'referral') {
        loadReferralSummary();
        renderReferralPromotions();
    } else if (tabName === 'subscription') {
        void loadSubscriptionStatus(true);
    } else if (tabName === 'visa') {
        loadDashboardStats();
        switchVisaSubTab(currentVisaSubTab);
    } else if (tabName === 'records') {
        initializeRilonoAiChat();
    } else if (tabName === 'universities') {
        loadUniversityShortlist();
    } else if (tabName === 'courses') {
        loadCourseFinder();
    } else if (tabName === 'sop') {
        loadSopStudio();
    } else if (tabName === 'news') {
        loadF1VisaNews();
    } else if (tabName === 'admin') {
        loadAdminUsers();
    }

    // Keep the address bar on the tab's own deep link (bookmark/refresh/back-safe).
    // Skipped while handleRoute drives the switch (isNavigating) to avoid double writes.
    const deepPath = DASHBOARD_TAB_TO_PATH[tabName];
    if (deepPath) {
        syncDocumentTitle(deepPath);
    }
    if (deepPath && !isNavigating && window.location.pathname !== deepPath) {
        updateURL(deepPath, false);
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
    void initializePricingSelector();
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

// ---------------------------------------------------------------------------
// Visa Success Pass pricing (multi-currency)
// ---------------------------------------------------------------------------

// The server owns both the ladder and the amount. This only caches the ladder that
// /api/pass/status already returned, so switching currency is instant and so the client
// never computes a price of its own. Anonymous visitors keep the mirrored ladder above —
// /api/pass/status needs a session.
async function ensurePassPriceOptions() {
    if (passPriceOptionsPromise) return passPriceOptionsPromise;
    if (!authToken) return passPriceOptions;

    passPriceOptionsPromise = (async () => {
        try {
            const response = await fetch(`${API_BASE}/api/pass/status`, {
                headers: { 'Authorization': `Bearer ${authToken}` }
            });
            if (!response.ok) {
                throw new Error(`Pass status request failed: ${response.status}`);
            }
            const data = await response.json();
            const options = (data?.entitlements?.pass?.price_options || []).filter(
                (option) => option && option.currency && Number.isFinite(Number(option.amount_minor))
            );
            if (options.length) {
                passPriceOptions = options.map((option) => ({
                    currency: String(option.currency).toUpperCase(),
                    amount_minor: Number(option.amount_minor),
                    // Keep the server's own rendering: the paywall, the order and the
                    // receipt email then read character-for-character the same.
                    display: String(option.display || '')
                }));
                // The server may price fewer currencies than the mirrored ladder. Drop a
                // choice it no longer sells so the buyer is re-detected onto one it does,
                // instead of sitting on a currency with no price.
                if (selectedPassCurrency && !passPriceOptionFor(selectedPassCurrency)) {
                    selectedPassCurrency = null;
                }
            }
        } catch (error) {
            console.warn('Using the built-in Visa Success Pass price ladder:', error);
        }
        return passPriceOptions;
    })();

    return passPriceOptionsPromise;
}

function passPriceOptionFor(currencyCode) {
    const code = String(currencyCode || '').trim().toUpperCase();
    return passPriceOptions.find((option) => option.currency === code) || null;
}

function passPriceDisplay(currencyCode) {
    const option = passPriceOptionFor(currencyCode);
    if (!option) return '';
    return option.display || formatMoneyMinor(option.amount_minor, option.currency);
}

// A currency is usable only if the ladder has a price for it. Anything else — JPY, a stale
// saved choice, a region we do not price — is refused rather than coerced: quoting a price
// we would not charge is exactly the bug this replaces.
function normalizePassCurrency(rawCode) {
    const code = String(rawCode || '').trim().toUpperCase();
    return passPriceOptionFor(code) ? code : '';
}

function readSavedPassCurrency() {
    try {
        return normalizePassCurrency(localStorage.getItem(PASS_CURRENCY_STORAGE_KEY));
    } catch (error) {
        return '';  // storage blocked
    }
}

// Synchronous guess from browser locale/timezone alone. It exists so the first painted
// frame is never a price in a currency this visitor will not be charged: the geo lookup in
// resolvePassCurrency() is a network round-trip, and ₹999 sitting in front of a US buyer
// for 200ms is still a misquote. Deliberately NOT persisted — only the buyer's own choice
// and the confirmed detection are.
function guessPassCurrencyFromBrowser() {
    try {
        const langs = (navigator.languages && navigator.languages.length) ? navigator.languages : [navigator.language];
        for (const lang of langs) {
            const match = String(lang || '').match(/[-_]([A-Za-z]{2})\b/);
            const code = match && normalizePassCurrency(PRICING_COUNTRY_TO_CURRENCY[String(match[1]).toUpperCase()]);
            if (code) return code;
        }
    } catch (error) { /* no locale region */ }
    try {
        const tz = (Intl.DateTimeFormat().resolvedOptions().timeZone) || '';
        return normalizePassCurrency(PRICING_COUNTRY_TO_CURRENCY[PRICING_TZ_COUNTRY[tz]]);
    } catch (error) { /* no timezone */ }
    return '';
}

// Synchronous best guess, for copy rendered before the async detection settles.
function currentPassCurrency() {
    return selectedPassCurrency || readSavedPassCurrency() || guessPassCurrencyFromBrowser();
}

async function resolvePassCurrency() {
    if (selectedPassCurrency) return selectedPassCurrency;
    const saved = readSavedPassCurrency();
    if (saved) {
        selectedPassCurrency = saved;
        return saved;
    }
    // CDN geo header → browser locale → timezone, the same detection the pricing page has
    // always used. It only decides which price to show FIRST; the buyer can change it, and
    // the charge is priced server-side either way.
    const detectedCountry = await detectPricingCountry();
    const detected = normalizePassCurrency(PRICING_COUNTRY_CONFIG[detectedCountry]?.currency);
    selectedPassCurrency = detected
        || normalizePassCurrency(PASS_CURRENCY_FALLBACK)
        || (passPriceOptions[0]?.currency || '');
    return selectedPassCurrency;
}

function setPassCurrency(currencyCode) {
    const code = normalizePassCurrency(currencyCode);
    if (!code) return selectedPassCurrency;
    selectedPassCurrency = code;
    try {
        localStorage.setItem(PASS_CURRENCY_STORAGE_KEY, code);
    } catch (error) { /* storage blocked */ }
    return code;
}

// One renderer for both currency selectors (pricing page and paywall) so the lists and the
// prices on them cannot drift apart.
function renderPassCurrencySelect(selectEl, currencyCode) {
    if (!selectEl) return;
    selectEl.innerHTML = passPriceOptions
        .map((option) => {
            const label = `${option.currency} · ${option.display || formatMoneyMinor(option.amount_minor, option.currency)}`;
            return `<option value="${escapeHtml(option.currency)}">${escapeHtml(label)}</option>`;
        })
        .join('');
    if (currencyCode) selectEl.value = currencyCode;
}

async function initializePricingSelector() {
    const currencySelect = document.getElementById('pricingCurrencySelect');
    if (!currencySelect) return;

    // Paint the locale guess first, then refine once the server ladder and the geo lookup
    // land — so the card never shows a currency this visitor will not be charged in.
    updatePricingByCurrency(currentPassCurrency());
    await ensurePassPriceOptions();
    const currency = await resolvePassCurrency();
    renderPassCurrencySelect(currencySelect, currency);
    updatePricingByCurrency(currency);
}

function handlePricingCurrencyChange(currencyCode) {
    updatePricingByCurrency(setPassCurrency(currencyCode));
}

function updatePricingByCurrency(currencyCode) {
    const currency = normalizePassCurrency(currencyCode)
        || currentPassCurrency()
        || normalizePassCurrency(PASS_CURRENCY_FALLBACK);
    const priceDisplay = passPriceDisplay(currency);
    const freePriceEl = document.getElementById('pricingFreePrice');
    const passPriceEl = document.getElementById('pricingPassPrice');
    const passBillingNoteEl = document.getElementById('pricingPassBillingNote');
    const hintEl = document.getElementById('pricingCurrencyHint');

    if (freePriceEl) {
        freePriceEl.innerHTML = `${escapeHtml(formatMoneyMinor(0, currency))}<span>/month</span>`;
    }
    if (passPriceEl) {
        // No "≈" anywhere: this is the price, not a conversion of ₹999. With no ladder
        // entry for this currency, say nothing — leaving whatever number was rendered for
        // the PREVIOUS currency in place is how a card ends up quoting ₹999 to a USD buyer.
        passPriceEl.innerHTML = priceDisplay
            ? `${escapeHtml(priceDisplay)}<span>/ one-time</span>`
            : '<span>One-time payment</span>';
    }
    if (passBillingNoteEl) {
        // The only figure that can still move is the buyer's own bank's cross-border
        // conversion, so say precisely that instead of the old "billed in INR" promise.
        passBillingNoteEl.textContent = priceDisplay
            ? `Charged in ${currency} — you pay exactly ${priceDisplay}. A card issued in another currency is converted by your bank at its own rate.`
            : '';
        passBillingNoteEl.style.display = passBillingNoteEl.textContent ? 'block' : 'none';
    }
    if (hintEl) {
        hintEl.textContent = 'Each currency has its own fixed price — nothing is converted at checkout.';
    }

    // Enterprise card. Plans are priced per currency in ENTERPRISE_PLAN_LADDER_FALLBACK;
    // with no ladder entry for this currency, fall back to INR for THIS card only (the
    // INR markup is the no-JS fallback, so re-rendering it in INR is always safe).
    // "+ GST" is INR-only: every other currency is a zero-rated export, so the listed
    // price is exactly what is charged.
    const enterpriseCurrency = ENTERPRISE_PLAN_LADDER_FALLBACK[currency] ? currency : 'INR';
    const enterprisePlans = ENTERPRISE_PLAN_LADDER_FALLBACK[enterpriseCurrency];
    const enterprisePriceEl = document.getElementById('pricingEnterprisePrice');
    if (enterprisePriceEl && enterprisePlans) {
        const enterpriseSuffix = enterpriseCurrency === 'INR' ? '&nbsp;/month + GST' : '&nbsp;/month';
        enterprisePriceEl.innerHTML =
            `${escapeHtml(formatMoneyMinor(enterprisePlans.plan_starter, enterpriseCurrency))}<span>${enterpriseSuffix}</span>`;
    }
    const enterpriseTierEls = {
        plan_starter: document.getElementById('pricingEnterpriseTierStarter'),
        plan_growth: document.getElementById('pricingEnterpriseTierGrowth'),
        plan_scale: document.getElementById('pricingEnterpriseTierScale')
    };
    Object.keys(enterpriseTierEls).forEach((planKey) => {
        const tierEl = enterpriseTierEls[planKey];
        if (tierEl && enterprisePlans) {
            tierEl.textContent = formatMoneyMinor(enterprisePlans[planKey], enterpriseCurrency);
        }
    });
}

// The single money formatter for the student app. `minor` is an integer in the MINOR unit
// of `currencyCode` (paise for INR, cents for USD): 1299 is $12.99 or ₹12.99 depending
// entirely on the code, so the two must always travel together. Never divide by 100 here —
// a zero-decimal currency would be shown 100× too small.
function formatMoneyMinor(minor, currencyCode) {
    const code = String(currencyCode || '').trim().toUpperCase();
    const exponent = CURRENCY_MINOR_UNIT_EXPONENT[code] ?? 2;
    return formatCurrencyAmount(Number(minor || 0) / Math.pow(10, exponent), code);
}

// Symbols must match CURRENCY_SYMBOLS in app/money.py exactly. Intl picks its own
// locale-dependent glyphs ("CA$17.99", "SGD 16.99") which disagree with what the server
// renders ("C$17.99", "S$16.99") — and the anonymous pricing page formats locally while
// the paywall modal shows the server's string, so the same visitor would see the same
// price written two ways one click apart.
const CURRENCY_SYMBOL_OVERRIDES = {
    INR: '₹', USD: '$', GBP: '£', EUR: '€', CAD: 'C$', AUD: 'A$', AED: 'AED ', SGD: 'S$'
};

// Major-unit formatter. Whole amounts drop their decimals to match money.format_money(),
// so "₹999" on the paywall matches "₹999" on the receipt.
function formatCurrencyAmount(amount, currencyCode) {
    const code = String(currencyCode || '').trim().toUpperCase();
    const exponent = CURRENCY_MINOR_UNIT_EXPONENT[code] ?? 2;
    const value = Number(amount || 0);
    const fractionDigits = (exponent > 0 && !Number.isInteger(value)) ? exponent : 0;
    const override = CURRENCY_SYMBOL_OVERRIDES[code];
    if (override) {
        const body = value.toLocaleString(code === 'INR' ? 'en-IN' : 'en-US', {
            minimumFractionDigits: fractionDigits,
            maximumFractionDigits: fractionDigits
        });
        return `${override}${body}`;
    }
    try {
        return new Intl.NumberFormat(code === 'INR' ? 'en-IN' : undefined, {
            style: 'currency',
            currency: code,
            minimumFractionDigits: fractionDigits,
            maximumFractionDigits: fractionDigits
        }).format(value);
    } catch (error) {
        // Intl throws on an unknown/blank code. Fall back to the CODE, never to "$" — a
        // rupee amount wearing a dollar sign misquotes the price by ~80×. With no code at
        // all, print the bare number: an unlabelled amount is honest, a guessed one is not.
        return code ? `${code} ${value.toFixed(fractionDigits)}` : value.toFixed(fractionDigits);
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

function showDPA(skipURLUpdate = false) {
    hideAllSections();
    const section = document.getElementById('dpaSection');
    if (section) section.style.display = 'block';
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (!skipURLUpdate) {
        updateURL('/dpa', false);
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

async function showEmailUnsubscribe(skipURLUpdate = false) {
    hideAllSections();
    const section = document.getElementById('emailUnsubscribeSection');
    if (!section) return;
    section.style.display = 'block';
    window.scrollTo({ top: 0, behavior: 'smooth' });

    const loadingEl = document.getElementById('emailUnsubLoading');
    const invalidEl = document.getElementById('emailUnsubInvalid');
    const contentEl = document.getElementById('emailUnsubContent');
    const successEl = document.getElementById('emailUnsubSuccess');
    const actionsEl = document.getElementById('emailUnsubActions');
    const formEl = document.getElementById('emailUnsubscribeForm');
    const alreadyEl = document.getElementById('emailUnsubAlready');
    const emailEl = document.getElementById('emailUnsubEmail');
    const tokenInput = document.getElementById('emailUnsubToken');
    const reasonInput = document.getElementById('emailUnsubReason');
    const invalidReasonEl = document.getElementById('emailUnsubInvalidReason');
    const quickReasonContainer = document.getElementById('emailUnsubQuickReasons');

    if (loadingEl) loadingEl.style.display = 'block';
    if (invalidEl) invalidEl.style.display = 'none';
    if (contentEl) contentEl.style.display = 'none';
    if (successEl) successEl.style.display = 'none';
    if (actionsEl) actionsEl.style.display = 'none';
    if (formEl) formEl.style.display = 'none';
    if (alreadyEl) alreadyEl.style.display = 'none';
    if (invalidReasonEl) invalidReasonEl.textContent = '';
    if (reasonInput) reasonInput.value = '';
    if (quickReasonContainer) {
        quickReasonContainer.querySelectorAll('.email-unsub-reason-chip').forEach((chip) => {
            chip.classList.remove('active');
        });
    }

    const token = (new URLSearchParams(window.location.search).get('token') || '').trim();
    if (tokenInput) tokenInput.value = token;

    if (!token) {
        if (loadingEl) loadingEl.style.display = 'none';
        if (invalidEl) {
            invalidEl.textContent = 'Invalid unsubscribe link. Please use the latest link from your email.';
            invalidEl.style.display = 'block';
        }
        if (!skipURLUpdate) updateURL('/unsubscribe-email', false);
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/auth/email-notifications/unsubscribe-preview?token=${encodeURIComponent(token)}`);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.detail || 'Invalid or expired unsubscribe link.');
        }

        if (emailEl) emailEl.textContent = data.email || 'your account';
        if (contentEl) contentEl.style.display = 'block';
        if (actionsEl) actionsEl.style.display = data.subscribed ? 'flex' : 'none';
        if (alreadyEl) alreadyEl.style.display = data.subscribed ? 'none' : 'block';
    } catch (error) {
        if (invalidEl) {
            invalidEl.textContent = error.message || 'Invalid or expired unsubscribe link.';
            invalidEl.style.display = 'block';
        }
    } finally {
        if (loadingEl) loadingEl.style.display = 'none';
    }

    if (!skipURLUpdate) {
        updateURL(`/unsubscribe-email?token=${encodeURIComponent(token)}`, false);
    }
}

function openEmailUnsubscribeReasonForm() {
    const actionsEl = document.getElementById('emailUnsubActions');
    const formEl = document.getElementById('emailUnsubscribeForm');
    if (actionsEl) actionsEl.style.display = 'none';
    if (formEl) formEl.style.display = 'block';
}

function handleEmailUnsubQuickReasonClick(event) {
    const chip = event.target.closest('.email-unsub-reason-chip');
    if (!chip) return;

    const reasonInput = document.getElementById('emailUnsubReason');
    const invalidReasonEl = document.getElementById('emailUnsubInvalidReason');
    const container = document.getElementById('emailUnsubQuickReasons');
    if (invalidReasonEl) invalidReasonEl.textContent = '';

    if (container) {
        container.querySelectorAll('.email-unsub-reason-chip').forEach((item) => {
            item.classList.remove('active');
        });
    }
    chip.classList.add('active');

    const selectedReason = (chip.dataset.reason || '').trim();
    if (!reasonInput) return;

    if (selectedReason) {
        reasonInput.value = selectedReason;
    } else {
        reasonInput.value = '';
        reasonInput.focus();
    }
}

function cancelEmailUnsubscribeFlow() {
    if (currentUser) {
        showDashboard();
        return;
    }
    showHomepage();
}

async function handleEmailUnsubscribeSubmit(e) {
    e.preventDefault();

    const token = (document.getElementById('emailUnsubToken')?.value || '').trim();
    const reason = (document.getElementById('emailUnsubReason')?.value || '').trim();
    const invalidReasonEl = document.getElementById('emailUnsubInvalidReason');
    const formEl = document.getElementById('emailUnsubscribeForm');
    const successEl = document.getElementById('emailUnsubSuccess');
    const actionsEl = document.getElementById('emailUnsubActions');

    if (invalidReasonEl) invalidReasonEl.textContent = '';

    if (!token) {
        showMessage('Invalid unsubscribe token. Please use the link from your email.', 'error');
        return;
    }
    if (reason.length < 3) {
        if (invalidReasonEl) invalidReasonEl.textContent = 'Please share a short reason before unsubscribing.';
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/auth/email-notifications/unsubscribe`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token, reason }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.detail || 'Unable to unsubscribe right now.');
        }

        if (formEl) formEl.style.display = 'none';
        if (actionsEl) actionsEl.style.display = 'none';
        if (successEl) successEl.style.display = 'block';
        showMessage('You have unsubscribed from email notifications.', 'success');
    } catch (error) {
        showMessage(error.message || 'Unable to unsubscribe right now.', 'error');
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
    closeExpandedChatView();
    closeMobileNav();
    pauseRilonoProductReel(false);
    document.querySelectorAll('.section').forEach(section => {
        section.style.display = 'none';
    });
    const navbar = document.querySelector('.navbar');
    const footer = document.querySelector('footer');
    if (navbar) navbar.style.display = '';
    if (footer) footer.style.display = '';
    document.body.classList.remove('dashboard-active');
    const pageContainer = document.querySelector('.container');
    if (pageContainer) {
        pageContainer.classList.remove('homepage-layout');
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
            // Hold the one-time prompts back so the confirmation above is readable first, and so
            // they open one at a time instead of stacking. Must precede showDashboard(), which
            // queues the "How did you hear about us?" prompt.
            holdPostLoginPrompts();
            showDashboard();
            renderReferralPromotions();
            // Auto-show the referral promo ONCE per browser, then never again (no login nagging).
            // Skipped entirely while onboarding is pending: the wizard owns the screen, and the
            // nudge would burn its one showing on a modal buried underneath it.
            if (!referralPromoSeen() && !needsOnboarding()) {
                queuePostLoginPrompt(() => {
                    // Preconditions are re-checked HERE, not at queue time — the user can sign out
                    // during the wait, and this must never render their referral code onto a
                    // logged-out page. Bailing also leaves the flag unset, so it returns next time.
                    if (!currentUser || !authToken) return;
                    // Mark it seen only when it actually opens — if the queue drops it (an earlier
                    // prompt was left open), the nudge is simply offered again next sign-in.
                    markReferralPromoSeen();
                    openReferralPromoModal();
                });
            }
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

            // Unverified account → route into the OTP step with a fresh code.
            if (data.detail && data.detail.includes('verify your email')) {
                const email = document.getElementById('loginEmail').value.trim();
                showMessage('Your email needs verifying — we just sent you a 6-digit code.', 'error');
                showRegister();
                showRegisterOtpStep(email);
                resendOtp();
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

    const ageInput = document.getElementById('registerAgeConsent');
    const ageConfirmed = Boolean(ageInput && ageInput.checked);
    if (!ageConfirmed) {
        showMessage('Please confirm you are 18 or older, or that a parent/guardian agrees on your behalf.', 'error');
        return;
    }

    // Get form values and convert empty strings to null
    const getValue = (id) => {
        const value = document.getElementById(id).value.trim();
        return value === '' ? null : value;
    };

    const marketingInput = document.getElementById('registerMarketingConsent');
    const marketingEmailsConsent = Boolean(marketingInput && marketingInput.checked);

    const userData = {
        email: getValue('registerEmail'),
        password: getValue('registerPassword'),
        full_name: getValue('registerFullName'),
        university: getValue('registerUniversity'),
        current_residence_country: getValue('registerCountry'),
        referral_code: getValue('registerReferralCode'),
        accepted_terms_privacy: acceptedTermsPrivacy,
        age_confirmed: ageConfirmed,
        marketing_emails_consent: marketingEmailsConsent
        // Username is optional - will be auto-generated from email on backend
    };
    const confirmPassword = getValue('registerPasswordConfirm');

    // Validate required fields
    if (!userData.current_residence_country) {
        showMessage('Please select your current country of residence.', 'error');
        return;
    }
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

    // Open signup: a university email is no longer required (university is optional and
    // collected later via onboarding / profile). Any valid email may register.

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

    // Attach first-touch acquisition attribution (where this visitor came from).
    try {
        if (typeof window.getRilonoAttribution === 'function') {
            Object.assign(userData, window.getRilonoAttribution());
        }
    } catch (e) { /* attribution is best-effort — never block signup */ }

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
            showMessage('Account created — check your email for a 6-digit code.', 'success');
            // Reset Turnstile widget (single-use token)
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
            // Step 2: collect the OTP, then auto-login into the onboarding tiles.
            showRegisterOtpStep(email);
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

// ---------------------------------------------------------------------------
// Stepped signup: Step 2 (email OTP) → auto-login → onboarding tiles
// ---------------------------------------------------------------------------
function showRegisterOtpStep(email) {
    window.__pendingOtpEmail = (email || '').trim();
    const form = document.getElementById('registerForm');
    const otpStep = document.getElementById('registerOtpStep');
    const social = document.getElementById('socialAuthRegister');
    const divider = document.getElementById('socialAuthRegisterDivider');
    const note = document.getElementById('socialConsentNoteRegister');
    const loginSwitch = document.getElementById('registerLoginSwitch');
    const target = document.getElementById('otpEmailTarget');
    if (form) form.style.display = 'none';
    if (social) social.style.display = 'none';
    if (divider) divider.style.display = 'none';
    if (note) note.style.display = 'none';
    if (loginSwitch) loginSwitch.style.display = 'none';
    if (otpStep) otpStep.style.display = 'block';
    if (target) target.textContent = window.__pendingOtpEmail;
    const otpInput = document.getElementById('registerOtpInput');
    const otpError = document.getElementById('otpError');
    if (otpError) otpError.style.display = 'none';
    if (otpInput) { otpInput.value = ''; setTimeout(() => otpInput.focus(), 60); }
}

function backToRegisterStep1() {
    const form = document.getElementById('registerForm');
    const otpStep = document.getElementById('registerOtpStep');
    const social = document.getElementById('socialAuthRegister');
    const divider = document.getElementById('socialAuthRegisterDivider');
    const note = document.getElementById('socialConsentNoteRegister');
    const loginSwitch = document.getElementById('registerLoginSwitch');
    if (otpStep) otpStep.style.display = 'none';
    if (form) form.style.display = '';
    const hasSocial = social && social.children.length > 0;
    // Clear the inline display so CSS `.social-auth:empty { display:none }` governs an
    // empty container; if the async providers fetch finishes later, renderSocialButtons
    // will populate + reveal it without a stale inline none blocking it.
    if (social) social.style.display = '';
    if (divider) divider.style.display = hasSocial ? '' : 'none';
    if (note) note.style.display = hasSocial ? '' : 'none';
    if (loginSwitch) loginSwitch.style.display = '';
}

async function handleVerifyOtp() {
    const otpInput = document.getElementById('registerOtpInput');
    const otpError = document.getElementById('otpError');
    const btn = document.getElementById('verifyOtpBtn');
    const email = (window.__pendingOtpEmail || '').trim();
    const code = ((otpInput && otpInput.value) || '').replace(/\D/g, '');
    const showOtpError = (msg) => { if (otpError) { otpError.textContent = msg; otpError.style.display = 'block'; } };
    if (otpError) otpError.style.display = 'none';
    if (!email) { showOtpError('Something went wrong — please go back and re-enter your email.'); return; }
    if (code.length !== 6) { showOtpError('Enter the 6-digit code from your email.'); return; }

    if (btn) { btn.disabled = true; btn.textContent = 'Verifying...'; }
    try {
        const response = await fetch(`${API_BASE}/api/auth/verify-otp`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ email, code }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const detail = data && data.detail;
            showOtpError(typeof detail === 'string' ? detail : 'Invalid or expired code.');
            return;
        }
        // Server set the session cookie; load the user and head into onboarding.
        authToken = COOKIE_AUTH_SENTINEL;
        persistAuthToken(authToken);
        let ok = await checkAuth();
        if (!ok && data.access_token) {
            authToken = data.access_token;
            persistAuthToken(authToken);
            ok = await checkAuth();
        }
        if (!ok) { showOtpError('Verified, but sign-in failed. Please try logging in.'); return; }
        showMessage('Email verified — welcome to Rilono!', 'success');
        if (otpInput) otpInput.value = '';
        // Dashboard render triggers the onboarding wizard (onboarding not yet completed).
        showDashboard();
    } catch (e) {
        console.error('OTP verify error:', e);
        showOtpError('Could not verify right now. Please try again.');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Verify & continue'; }
    }
}

async function resendOtp() {
    const email = (window.__pendingOtpEmail || '').trim();
    if (!email) return;
    try {
        await fetch(`${API_BASE}/api/auth/resend-otp`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email }),
        });
        showMessage('A new code is on its way.', 'success');
    } catch (e) {
        showMessage('Could not resend the code. Please try again.', 'error');
    }
}

async function logout() {
    // Await the server so the session cookie is cleared + invalidated BEFORE the user
    // can navigate again (otherwise a quick "Login" click could re-use a live cookie).
    try {
        await fetch(`${API_BASE}/api/auth/logout`, {
            method: 'POST',
            credentials: 'include',
        });
    } catch (e) {
        // Network error — local state is still cleared below; the cookie/session is
        // also invalidated server-side on the next successful logout/login.
    }
    authToken = null;
    persistAuthToken(null);
    discardLegacyNotificationStorage();
    // Drop the in-memory E2E master key so the next user must re-enter their passphrase.
    try { if (typeof RilonoE2E !== 'undefined') RilonoE2E.lock(); } catch (_) {}
    currentUser = null;
    currentSubscription = null;
    runtimeSubscriptionNotifyState = null;
    subscriptionNotifyStateUserId = null;
    closeReferralPromoModal();
    // Cancel any post-login prompt still awaiting its turn — it belongs to the session just ended.
    postLoginPromptQueue.length = 0;
    postLoginQuietUntil = 0;
    floatingChatOpen = false;
    rilonoAiConversationHistory = [];  // Clear shared chat history
    clearRilonoAiSessionAttachments(false);
    rilonoAiAttachmentRegistry = new Map();
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
    const forgotWidget = document.getElementById('turnstile-forgot-password');
    const turnstileToken = getAuthTurnstileToken(forgotWidget, 'forgotPassword');

    if (!email) {
        showMessage('Please enter your email address', 'error');
        return;
    }

    if (turnstileSiteKey && !turnstileToken) {
        showMessage('Please complete the security verification.', 'error');
        return;
    }

    try {
        const payload = { email: email };
        if (turnstileToken) {
            payload.cf_turnstile_token = turnstileToken;
        }
        const response = await fetch(`${API_BASE}/api/auth/forgot-password`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (response.ok) {
            showMessage(data.message || 'Your password reset request has been received.', 'success');
            // Show success message in the form
            document.getElementById('forgotPasswordSection').innerHTML = `
                <div class="auth-card">
                    <div style="text-align: center;">
                        <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--success-color);">✓</div>
                        <h2 style="margin-bottom: 1rem;">Check Your Email</h2>
                        <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                            If an account exists for <strong>${escapeHtml(email)}</strong> and email can be delivered,
                            a password reset link should arrive shortly. Check your inbox and spam folder.
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
    } finally {
        if (turnstileSiteKey && forgotWidget && window.turnstile) {
            try {
                const widgetId = turnstileWidgetIds.forgotPassword || forgotWidget;
                window.turnstile.reset(widgetId);
            } catch (resetError) {
                // noop
            }
        }
    }
}

async function handleResetPassword(e) {
    e.preventDefault();
    const token = document.getElementById('resetToken').value;
    const newPassword = document.getElementById('resetPasswordNew').value;
    const confirmPassword = document.getElementById('resetPasswordConfirm').value;
    const resetWidget = document.getElementById('turnstile-reset-password');
    const turnstileToken = getAuthTurnstileToken(resetWidget, 'resetPassword');

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

    if (turnstileSiteKey && !turnstileToken) {
        showMessage('Please complete the security verification.', 'error');
        return;
    }

    try {
        const payload = {
            token: token,
            new_password: newPassword
        };
        if (turnstileToken) {
            payload.cf_turnstile_token = turnstileToken;
        }
        const response = await fetch(`${API_BASE}/api/auth/reset-password`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload)
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
    } finally {
        if (turnstileSiteKey && resetWidget && window.turnstile) {
            try {
                const widgetId = turnstileWidgetIds.resetPassword || resetWidget;
                window.turnstile.reset(widgetId);
            } catch (resetError) {
                // noop
            }
        }
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

    const getItems = () => Array.from(dropdownList.querySelectorAll('.dropdown-item[data-value]'));

    function selectItem(item) {
        if (!item || item.classList.contains('rule-hidden')) return;
        const value = item.dataset.value || '';
        if (!value) return;

        searchInput.value = item.textContent.trim();
        hiddenInput.value = value;

        getItems().forEach(i => i.classList.remove('selected', 'highlighted'));
        item.classList.add('selected');

        documentTypeDropdown.classList.remove('open');
    }

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
            getItems().forEach(item => item.classList.remove('selected'));
        }
    });

    // Handle item selection. The document catalog can be re-rendered after login/profile
    // personalization, so delegate clicks instead of binding only to the initial items.
    // Suppress the default mousedown behavior on an item so a click-with-micro-drag can't
    // turn into a text selection (which was silently swallowing the click) and so the
    // search input doesn't blur before the click lands.
    dropdownList.addEventListener('mousedown', (event) => {
        if (event.target.closest('.dropdown-item[data-value]')) event.preventDefault();
    });
    dropdownList.addEventListener('click', (event) => {
        const item = event.target.closest('.dropdown-item[data-value]');
        if (!item || !dropdownList.contains(item)) return;
        selectItem(item);
    });

    // Close dropdown on click outside
    document.addEventListener('click', (e) => {
        if (!documentTypeDropdown.contains(e.target)) {
            documentTypeDropdown.classList.remove('open');

            // If no valid selection, clear the input
            if (!hiddenInput.value && searchInput.value) {
                // Try to find an exact match
                const matchingItem = getItems().find(
                    item => (
                        item.textContent.trim().toLowerCase() === searchInput.value.trim().toLowerCase() &&
                        !item.classList.contains('rule-hidden')
                    )
                );
                if (matchingItem) {
                    selectItem(matchingItem);
                } else {
                    searchInput.value = '';
                }
            }
        }
    });

    // Handle keyboard navigation
    searchInput.addEventListener('keydown', (e) => {
        const visibleItems = getItems().filter(item => !item.classList.contains('hidden') && !item.classList.contains('rule-hidden'));
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
                selectItem(highlightedItem);
            } else if (visibleItems.length === 1) {
                selectItem(visibleItems[0]);
            }
        } else if (e.key === 'Escape') {
            documentTypeDropdown.classList.remove('open');
        }
    });

    function filterItems(searchTerm) {
        let hasResults = false;
        getItems().forEach(item => {
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
        getItems().forEach(item => item.classList.remove('highlighted'));
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
        getItems,
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
    if (!(await confirmDialog('This item will be permanently deleted.', { title: 'Delete item?', okText: 'Delete' }))) return;

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
            <div class="conversation-item ${unreadClass}" onclick="openConversationFromCard(this)" data-item-id="${conv.item.id}" data-other-user-id="${conv.other_user.id}" data-other-username="${escapeHtml(conv.other_user.username)}" data-item-title="${escapeHtml(conv.item.title)}">
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

function openConversationFromCard(cardEl) {
    if (!cardEl?.dataset) return;

    const itemId = Number.parseInt(cardEl.dataset.itemId || '', 10);
    const otherUserId = Number.parseInt(cardEl.dataset.otherUserId || '', 10);
    if (!Number.isFinite(itemId) || !Number.isFinite(otherUserId)) return;

    const otherUsername = cardEl.dataset.otherUsername || '';
    const itemTitle = cardEl.dataset.itemTitle || '';
    openConversation(itemId, otherUserId, otherUsername, itemTitle);
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

    if (!(await confirmDialog('This will permanently delete all messages in this conversation. This cannot be undone.', { title: 'Delete conversation?', okText: 'Delete' }))) {
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
    document.getElementById('profileVisaCaseStatus').value = profile.visa_case_status || '';
    document.getElementById('profileCurrentSituationStory').value = profile.current_situation_story || '';
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

/* ===================== Visa-decision outcome capture ===================== */
function outcomeAuthHeaders(json = false) {
    const h = {};
    if (typeof authToken !== 'undefined' && authToken) h['Authorization'] = `Bearer ${authToken}`;
    if (json) h['Content-Type'] = 'application/json';
    return h;
}

async function loadVisaDecisionPrompt() {
    const card = document.getElementById('visaDecisionPromptCard');
    if (!card) return;
    try {
        const res = await fetch(`${API_BASE}/api/outcomes/status`, { headers: outcomeAuthHeaders(), credentials: 'same-origin' });
        if (!res.ok) { card.style.display = 'none'; return; }
        const data = await res.json().catch(() => ({}));
        if (!data || !data.prompt_eligible) { card.style.display = 'none'; return; }
        renderVisaDecisionPrompt(card);
    } catch (e) {
        card.style.display = 'none';
    }
}

function renderVisaDecisionPrompt(card) {
    card.innerHTML = `
        <div class="dashboard-widget decision-capture">
            <div class="widget-content" style="padding:1.25rem 1.5rem;">
                <div class="decision-capture-row">
                    <div>
                        <h3 style="margin:0 0 4px;">🎓 Did you get your visa decision?</h3>
                        <p style="margin:0;color:#64748b;font-size:.9rem;">Let us know how it went — it helps us improve, and it stays private to your account.</p>
                    </div>
                    <div class="decision-capture-btns">
                        <button type="button" class="decision-btn approve" data-decision="approved">✅ Approved</button>
                        <button type="button" class="decision-btn refuse" data-decision="refused">❌ Refused</button>
                        <button type="button" class="decision-btn ghost" data-decision="__snooze">Not yet</button>
                    </div>
                </div>
            </div>
        </div>`;
    card.style.display = 'block';
    card.querySelectorAll('.decision-btn').forEach((btn) => {
        btn.addEventListener('click', () => submitVisaDecision(btn.getAttribute('data-decision'), card));
    });
}

async function submitVisaDecision(decision, card) {
    try {
        if (decision === '__snooze') {
            await fetch(`${API_BASE}/api/outcomes/snooze`, { method: 'POST', headers: outcomeAuthHeaders(), credentials: 'same-origin' });
            card.style.display = 'none';
            return;
        }
        const res = await fetch(`${API_BASE}/api/outcomes/visa-decision`, {
            method: 'POST', headers: outcomeAuthHeaders(true), credentials: 'same-origin',
            body: JSON.stringify({ decision }),
        });
        if (!res.ok) { showMessage('Could not save that — please try again.', 'error'); return; }
        card.style.display = 'none';
        if (decision === 'approved') showMessage('Congratulations! 🎉 So glad Rilono was part of your journey.', 'success');
        else showMessage('Thanks for letting us know. Your next attempt can go better — we’re here to help.', 'success');
    } catch (e) {
        showMessage('Could not save that — please try again.', 'error');
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

// The referral promo modal is a one-time nudge — auto-shown once (per browser), then never
// again, so it stops being repetitive nagging on every login. The referral details always
// remain available in the Referral tab.
function referralPromoSeen() {
    try { return localStorage.getItem('rilono_referral_promo_seen') === '1'; } catch (e) { return false; }
}
function markReferralPromoSeen() {
    try { localStorage.setItem('rilono_referral_promo_seen', '1'); } catch (e) { /* private mode */ }
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

// Intake options per destination (mirrors enterprise_catalog student_intakes so values
// match what onboarding saves). The HTML shipped US semesters only; every destination
// rebuilds its own list — an AU student picks February/July/November, not "Fall".
const DOCUMENTATION_INTAKES = {
    US: ['Spring', 'Summer', 'Fall'],
    CA: ['January', 'May', 'September'],
    UK: ['January', 'September'],
    AU: ['February', 'July', 'November'],
    DE: ['Summer Semester', 'Winter Semester'],
};

function populateDocumentationIntakeOptions() {
    const intakeSelect = document.getElementById('documentationIntake');
    if (!intakeSelect) return;
    const code = (currentUser && currentUser.destination_country_code) || 'US';
    const intakes = DOCUMENTATION_INTAKES[code] || DOCUMENTATION_INTAKES.US;
    const previous = intakeSelect.value;
    intakeSelect.innerHTML = '<option value="">Select Intake</option>'
        + intakes.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('');
    if (previous && intakes.includes(previous)) intakeSelect.value = previous;
}

// Saved intakes may be bare ("February") from this form or materialized ("February 2027")
// from onboarding — split off a trailing year so both display correctly.
function splitIntakeValue(rawIntake) {
    const value = String(rawIntake || '').trim();
    const match = value.match(/^(.*?)\s+(20\d{2})$/);
    if (match) return { intake: match[1].trim(), year: match[2] };
    return { intake: value, year: '' };
}

function applyDocumentationPreferenceValues(rawIntake, rawYear) {
    const intakeSelect = document.getElementById('documentationIntake');
    const yearSelect = document.getElementById('documentationYear');
    const parts = splitIntakeValue(rawIntake);
    if (intakeSelect && parts.intake) {
        const hasOption = Array.from(intakeSelect.options).some((o) => o.value === parts.intake);
        if (hasOption) intakeSelect.value = parts.intake;
    }
    const year = String(rawYear || parts.year || '').trim();
    if (yearSelect && year) {
        const hasYear = Array.from(yearSelect.options).some((o) => o.value === year);
        if (hasYear) yearSelect.value = year;
    }
}

async function loadDocumentationPreferences() {
    // The journey destination is authoritative for the country field and the intake
    // list; saved values may be stale after the user changes countries.
    const countryInput = document.getElementById('documentationCountry');
    const destinationCode = (currentUser && currentUser.destination_country_code) || '';
    const destinationName = (COUNTRY_DISPLAY[destinationCode] || {}).name || '';
    if (countryInput && destinationName) {
        countryInput.value = destinationName;
    }
    populateDocumentationIntakeOptions();

    if (!authToken) return;
    try {
        const response = await fetch(`${API_BASE}/api/profile/documentation-preferences`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const prefs = await response.json();
        applyDocumentationPreferenceValues(prefs.intake, prefs.year);
    } catch (error) {
        console.error('Error loading documentation preferences:', error);
        // Fall back to localStorage
        const localPrefs = localStorage.getItem('documentationPreferences');
        if (localPrefs) {
            try {
                const prefs = JSON.parse(localPrefs);
                applyDocumentationPreferenceValues(prefs.intake, prefs.year);
            } catch (parseError) { /* corrupted local prefs — ignore */ }
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
            healthBadge.style.color = '#065f46';
        } else if (healthScore >= 70) {
            healthBadge.textContent = 'Good';
            healthBadge.style.background = 'rgba(99, 102, 241, 0.15)';
            healthBadge.style.borderColor = 'rgba(99, 102, 241, 0.35)';
            healthBadge.style.color = '#4338ca';
        } else if (healthScore >= 50) {
            healthBadge.textContent = 'Fair';
            healthBadge.style.background = 'rgba(245, 158, 11, 0.15)';
            healthBadge.style.borderColor = 'rgba(245, 158, 11, 0.35)';
            healthBadge.style.color = '#92400e';
        } else {
            healthBadge.textContent = 'Needs Attention';
            healthBadge.style.background = 'rgba(239, 68, 68, 0.15)';
            healthBadge.style.borderColor = 'rgba(239, 68, 68, 0.35)';
            healthBadge.style.color = '#b91c1c';
        }
    }

    // Persist per-widget state, wire the clickable stat tiles, and render the detail view
    // (recent notes by default, or the selected category's documents when a tile is clicked).
    const listId = config.validationListId;
    const previous = documentHealthWidgetState[listId];
    documentHealthWidgetState[listId] = {
        documents,
        config,
        selected: (totalUploaded > 0 && previous) ? previous.selected : null,
    };
    wireDocumentHealthStatTiles(config);
    renderDocumentHealthDetail(listId);
}

// --- Document Health: clickable stat tiles + per-category detail view ---
// Each stat tile (Uploaded, Validated, Needs Review, …) is a filter: clicking it reveals the
// documents in that bucket in the list area below. Document names come from the country-aware
// catalog (formatDocumentType), so the detail is personalised per destination automatically.
const documentHealthWidgetState = {};

function documentHealthCategories(config) {
    return [
        { key: 'uploaded', valueId: config.totalUploadedId, label: 'Uploaded', filter: (docs) => docs },
        { key: 'unique-types', valueId: config.uniqueTypesId, label: 'Unique Types', kind: 'types' },
        { key: 'validated', valueId: config.validatedCountId, label: 'Validated', filter: (docs) => docs.filter((d) => d.is_valid === true) },
        { key: 'needs-review', valueId: config.needsReviewCountId, label: 'Needs Review', filter: (docs) => docs.filter((d) => d.is_valid === false) },
        { key: 'pending', valueId: config.pendingValidationCountId, label: 'Pending Validation', filter: (docs) => docs.filter((d) => d.is_valid === null || d.is_valid === undefined) },
        { key: 'processed', valueId: config.processedCountId, label: 'Processed', filter: (docs) => docs.filter((d) => d.is_processed === true) },
    ];
}

function healthStatusBadge(doc) {
    if (doc.is_valid === true) {
        return { label: 'Valid', style: 'background: rgba(16, 185, 129, 0.18); color: #065f46; border: 1px solid rgba(16, 185, 129, 0.45);' };
    }
    if (doc.is_valid === false) {
        return { label: 'Needs Review', style: 'background: rgba(239, 68, 68, 0.18); color: #b91c1c; border: 1px solid rgba(239, 68, 68, 0.45);' };
    }
    return { label: 'Pending', style: 'background: rgba(148, 163, 184, 0.18); color: #475569; border: 1px solid rgba(148, 163, 184, 0.45);' };
}

function healthDocumentRowHtml(doc, config) {
    const badge = healthStatusBadge(doc);
    const name = doc.document_type ? formatDocumentType(doc.document_type) : (doc.original_filename || 'Document');
    const encodedDocumentType = encodeURIComponent(doc.document_type || '');
    const documentId = Number.isFinite(doc.id) ? doc.id : 0;
    return `
        <div class="overview-health-item overview-health-item-clickable" onclick="jumpToDocumentInDocumentsTab(${documentId}, '${encodedDocumentType}')" title="${escapeHtml(config.listItemTitle || 'Open document')}">
            <div class="overview-health-item-name">${escapeHtml(name)}</div>
            <div class="overview-health-item-status" style="${badge.style}">${badge.label}</div>
        </div>`;
}

function healthTypeRowHtml(type, docs, config) {
    const name = formatDocumentType(type);
    const count = docs.length;
    const first = docs[0];
    const encodedDocumentType = encodeURIComponent(type || '');
    const documentId = first && Number.isFinite(first.id) ? first.id : 0;
    return `
        <div class="overview-health-item overview-health-item-clickable" onclick="jumpToDocumentInDocumentsTab(${documentId}, '${encodedDocumentType}')" title="${escapeHtml(config.listItemTitle || 'Open document')}">
            <div class="overview-health-item-name">${escapeHtml(name)}</div>
            <div class="overview-health-item-status overview-health-count">${count} file${count === 1 ? '' : 's'}</div>
        </div>`;
}

function healthCategoryEmptyHtml(categoryKey) {
    const journey = (typeof currentVisaJourneyPhrase === 'function') ? currentVisaJourneyPhrase() : 'student visa';
    const messages = {
        'validated': `No ${journey} documents have passed validation yet.`,
        'needs-review': `Nothing needs review — no ${journey} documents failed validation.`,
        'pending': 'No documents are waiting on validation right now.',
        'processed': 'No documents have finished processing yet.',
        'unique-types': 'No document types uploaded yet.',
    };
    const message = messages[categoryKey] || 'No documents in this category yet.';
    return `<div class="overview-health-empty">${escapeHtml(message)}</div>`;
}

function healthResetControlHtml(listId) {
    return `<button type="button" class="overview-health-reset" onclick="clearDocumentHealthCategory('${listId}')">Show recent</button>`;
}

function wireDocumentHealthStatTiles(config) {
    const state = documentHealthWidgetState[config.validationListId];
    const interactive = Boolean(state && state.documents.length > 0);
    documentHealthCategories(config).forEach((cat) => {
        const valueEl = document.getElementById(cat.valueId);
        const tile = valueEl ? valueEl.closest('.overview-health-stat') : null;
        if (!tile) return;
        if (interactive) {
            tile.classList.add('overview-health-stat-clickable');
            tile.setAttribute('role', 'button');
            tile.setAttribute('tabindex', '0');
            tile.dataset.healthCategory = cat.key;
            tile.setAttribute('title', `View ${cat.label.toLowerCase()} documents`);
            tile.onclick = () => selectDocumentHealthCategory(config.validationListId, cat.key);
            tile.onkeydown = (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    selectDocumentHealthCategory(config.validationListId, cat.key);
                }
            };
        } else {
            tile.classList.remove('overview-health-stat-clickable', 'is-active');
            tile.removeAttribute('role');
            tile.removeAttribute('tabindex');
            tile.removeAttribute('title');
            tile.onclick = null;
            tile.onkeydown = null;
        }
    });
}

function selectDocumentHealthCategory(listId, category) {
    const state = documentHealthWidgetState[listId];
    if (!state) return;
    state.selected = state.selected === category ? null : category;
    renderDocumentHealthDetail(listId);
}

function clearDocumentHealthCategory(listId) {
    const state = documentHealthWidgetState[listId];
    if (!state) return;
    state.selected = null;
    renderDocumentHealthDetail(listId);
}

function renderDocumentHealthDetail(listId) {
    const state = documentHealthWidgetState[listId];
    if (!state) return;
    const { documents, config } = state;
    const listContainer = document.getElementById(listId);
    if (!listContainer) return;
    const wrap = listContainer.closest('.overview-health-list-wrap');
    const titleEl = wrap ? wrap.querySelector('.overview-health-list-title') : null;
    const categories = documentHealthCategories(config);

    // Reflect the active tile.
    categories.forEach((cat) => {
        const valueEl = document.getElementById(cat.valueId);
        const tile = valueEl ? valueEl.closest('.overview-health-stat') : null;
        if (tile) tile.classList.toggle('is-active', state.selected === cat.key);
    });

    // Default view: recent validation notes.
    if (!state.selected) {
        if (titleEl) titleEl.textContent = 'Recent Validation Notes';
        if (documents.length === 0) {
            listContainer.innerHTML = '<div class="overview-health-empty">No documents uploaded yet.</div>';
            return;
        }
        const recent = [...documents]
            .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
            .slice(0, 5);
        listContainer.innerHTML = recent.map((doc) => healthDocumentRowHtml(doc, config)).join('');
        return;
    }

    const category = categories.find((cat) => cat.key === state.selected);
    if (!category) {
        state.selected = null;
        renderDocumentHealthDetail(listId);
        return;
    }

    if (category.kind === 'types') {
        const groups = new Map();
        documents.forEach((doc) => {
            const type = doc.document_type || '';
            if (!type) return;
            if (!groups.has(type)) groups.set(type, []);
            groups.get(type).push(doc);
        });
        const entries = [...groups.entries()];
        if (titleEl) titleEl.innerHTML = `<span>${escapeHtml(category.label)} · ${entries.length}</span>${healthResetControlHtml(listId)}`;
        listContainer.innerHTML = entries.length
            ? entries.map(([type, docs]) => healthTypeRowHtml(type, docs, config)).join('')
            : healthCategoryEmptyHtml(category.key);
        return;
    }

    const filtered = category.filter(documents);
    if (titleEl) titleEl.innerHTML = `<span>${escapeHtml(category.label)} · ${filtered.length}</span>${healthResetControlHtml(listId)}`;
    listContainer.innerHTML = filtered.length
        ? filtered.map((doc) => healthDocumentRowHtml(doc, config)).join('')
        : healthCategoryEmptyHtml(category.key);
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
function getJourneyStageDocumentRows() {
    const sourceRows = (documentTypeCatalog && documentTypeCatalog.length)
        ? documentTypeCatalog
        : FALLBACK_DOCUMENT_TYPES;
    return sourceRows.filter((row) => row && row.value);
}

function buildStageRequirementStats(stageNumber, stageRows, isRuleSatisfied, uploadedDocTypes, validatedDocTypes) {
    const mandatoryRows = stageRows.filter((row) => row.stage_gate_required);
    const groupedRows = {};
    const requirementUnits = [];

    mandatoryRows.forEach((row) => {
        if (!row.stage_gate_group) {
            requirementUnits.push({
                key: `doc:${row.value}`,
                label: getDocumentTypeLabel(row.value),
                rows: [row]
            });
            return;
        }
        if (!groupedRows[row.stage_gate_group]) {
            groupedRows[row.stage_gate_group] = [];
        }
        groupedRows[row.stage_gate_group].push(row);
    });

    Object.entries(groupedRows).forEach(([groupKey, rows]) => {
        const labels = rows.map((row) => getDocumentTypeLabel(row.value));
        requirementUnits.push({
            key: `group:${groupKey}`,
            label: `Any one of: ${labels.join(' or ')}`,
            rows
        });
    });

    const unitsWithStatus = requirementUnits.map((unit) => {
        const uploadedCount = unit.rows.filter((row) => uploadedDocTypes.has(row.value)).length;
        const validatedCount = unit.rows.filter((row) => validatedDocTypes.has(row.value)).length;
        const requiresValidation = unit.rows.some((row) => Boolean(row.stage_gate_requires_validation));
        const satisfied = unit.rows.some((row) => isRuleSatisfied(row));

        let status = 'Missing';
        let statusClass = 'status-missing';
        if (satisfied) {
            status = 'Ready';
            statusClass = 'status-ready';
        } else if (uploadedCount > 0 && requiresValidation) {
            status = 'Needs Validation';
            statusClass = 'status-needs-validation';
        } else if (uploadedCount > 0) {
            status = 'Uploaded';
            statusClass = 'status-uploaded';
        }

        return {
            ...unit,
            uploadedCount,
            validatedCount,
            requiresValidation,
            satisfied,
            status,
            statusClass
        };
    });

    return {
        stageNumber,
        mandatoryTotal: unitsWithStatus.length,
        mandatoryReady: unitsWithStatus.filter((unit) => unit.satisfied).length,
        mandatoryUploaded: unitsWithStatus.filter((unit) => unit.uploadedCount > 0).length,
        mandatoryValidated: unitsWithStatus.filter((unit) => unit.validatedCount > 0).length,
        stageDocTotal: stageRows.length,
        stageDocUploaded: stageRows.filter((row) => uploadedDocTypes.has(row.value)).length,
        stageDocValidated: stageRows.filter((row) => validatedDocTypes.has(row.value)).length,
        items: unitsWithStatus
    };
}

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

    const stageDocumentRows = getJourneyStageDocumentRows();
    let currentStage = 1;
    const stageGateRules = stageDocumentRows.filter((row) => row.stage_gate_required && row.journey_stage);
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
    const stageStatsMap = {};
    orderedStages.forEach((stage) => {
        stageCompletionMap[stage.stage] = isStageComplete(stage.stage);
        const rowsForStage = stageDocumentRows.filter((row) => Number(row.journey_stage) === Number(stage.stage));
        stageStatsMap[stage.stage] = buildStageRequirementStats(
            stage.stage,
            rowsForStage,
            isRuleSatisfied,
            uploadedDocTypes,
            validatedDocTypes
        );
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
        stageStatsMap,
        allStagesComplete,
        completedStageCount,
        progressPercent
    };
}

// UK maintenance-funds calculator (Stage 4) — delegates to the SHARED engine
// (static/uk-maintenance-calc.js) so the figures + math live in ONE place, reused by the
// public tool page and the enterprise CRM. See window.RilonoUkMaintenanceCalc.
function openUkFundsCalculator() {
    if (window.RilonoUkMaintenanceCalc) {
        window.RilonoUkMaintenanceCalc.openModal({ eyebrow: 'UK Student visa \u00b7 Stage 4' });
    } else {
        showMessage('The maintenance calculator could not load. Please refresh and try again.', 'error');
    }
}

function updateVisaJourneyUI(documents) {
    const journeyData = calculateVisaJourneyStage(documents);

    updateVisaJourneyWidget({
        widgetKey: 'overviewJourney',
        progressLineId: 'journeyProgressLine',
        stageIconPrefix: 'stageIcon',
        currentStageEmojiId: 'currentStageEmoji',
        currentStageNameId: 'currentStageName',
        currentStageDescId: 'currentStageDesc',
        nextStepHintId: 'nextStepHint',
        nextStepTextId: 'nextStepText',
        stageInfoCardId: 'currentStageInfo',
        stageMandatorySummaryId: 'currentStageMandatorySummary',
        stageMandatoryListId: 'currentStageMandatoryList',
        stageActionHintId: 'currentStageActionHint'
    }, journeyData);

    updateVisaJourneyWidget({
        widgetKey: 'visaJourneyTab',
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
    const {
        currentStage,
        stageInfo,
        stages,
        stageCompletionMap = {},
        stageStatsMap = {},
        allStagesComplete = false,
        progressPercent
    } = journeyData;

    const widgetKey = config.widgetKey || config.stageIconPrefix || 'journey';
    const stageCount = Array.isArray(stages) ? stages.length : 0;
    if (!stageCount) {
        return;
    }

    const storedSelectedStage = Number(journeyStageSelectionByWidget[widgetKey] || 0);
    const selectedStageExists = stages.some((stage) => Number(stage.stage) === storedSelectedStage);
    const selectedStage = selectedStageExists ? storedSelectedStage : Number(currentStage || 1);
    if (!selectedStageExists) {
        journeyStageSelectionByWidget[widgetKey] = selectedStage;
    }
    const selectedStageInfo = stages.find((stage) => Number(stage.stage) === selectedStage) || stageInfo;

    const progressLine = document.getElementById(config.progressLineId);
    if (progressLine) {
        const normalizedPercent = Math.max(0, Math.min(100, Number(progressPercent) || 0));
        progressLine.style.width = `${(normalizedPercent / 100) * 90}%`;
    }

    // A stage should look completed only when it and all previous stages are completed.
    const sequentialCompletionMap = {};
    let previousSequentialComplete = true;
    for (let i = 1; i <= stageCount; i++) {
        const thisStageComplete = stageCompletionMap[i] === true;
        const isSequentiallyComplete = previousSequentialComplete && thisStageComplete;
        sequentialCompletionMap[i] = isSequentiallyComplete;
        previousSequentialComplete = isSequentiallyComplete;
    }

    for (let i = 1; i <= stageCount; i++) {
        const stageIcon = document.getElementById(`${config.stageIconPrefix}${i}`);
        if (!stageIcon) continue;

        const defaultEmoji = stages[i - 1]?.emoji || '•';
        const stageNode = stageIcon.closest('.journey-stage');
        // Sync each circle's label with the student's country — the dashboard HTML
        // hardcodes the US F-1 labels (I-20, DS-160…), which are wrong for UK/CA/AU.
        const stageLabelEl = stageNode ? stageNode.querySelector('.stage-label') : null;
        if (stageLabelEl && stages[i - 1] && stages[i - 1].name) {
            stageLabelEl.textContent = stages[i - 1].name;
        }
        stageIcon.style.animation = 'none';
        const isCompleted = sequentialCompletionMap[i] === true;
        const isInProgress = !allStagesComplete && i === currentStage && !isCompleted;
        const isSelected = i === selectedStage;

        if (stageNode) {
            stageNode.classList.toggle('journey-stage-selected', isSelected);
            stageNode.onclick = () => {
                journeyStageSelectionByWidget[widgetKey] = i;
                updateVisaJourneyWidget(config, journeyData);
            };
            stageNode.setAttribute('role', 'button');
            stageNode.setAttribute('tabindex', '0');
            stageNode.onkeydown = (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    stageNode.click();
                }
            };
        }

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

        if (isSelected && !isCompleted && !isInProgress) {
            stageIcon.style.boxShadow = '0 0 0 2px rgba(129, 140, 248, 0.45), 0 8px 20px rgba(99, 102, 241, 0.35)';
        }
    }

    const currentStageEmoji = document.getElementById(config.currentStageEmojiId);
    const currentStageName = document.getElementById(config.currentStageNameId);
    const currentStageDesc = document.getElementById(config.currentStageDescId);
    const nextStepText = document.getElementById(config.nextStepTextId);
    const nextStepHint = document.getElementById(config.nextStepHintId);

    if (currentStageEmoji) currentStageEmoji.textContent = selectedStageInfo?.emoji || '•';
    if (currentStageName) currentStageName.textContent = `Stage ${selectedStage}: ${selectedStageInfo?.name || ''}`;
    if (currentStageDesc) currentStageDesc.textContent = selectedStageInfo?.description || '';
    if (nextStepText) nextStepText.textContent = selectedStageInfo?.nextStep || '';

    if (nextStepHint) {
        if (allStagesComplete && selectedStage === currentStage) {
            nextStepHint.innerHTML = '<span style="color: #065f46; font-weight: 600;">🎉 Congratulations! You\'re all set for your journey!</span>';
        } else {
            nextStepHint.innerHTML = `<strong>Next step:</strong> <span id="${config.nextStepTextId}">${escapeHtml(selectedStageInfo?.nextStep || '')}</span>`;
        }
    }

    const selectedStats = stageStatsMap[selectedStage];
    const stageSummaryEl = config.stageMandatorySummaryId ? document.getElementById(config.stageMandatorySummaryId) : null;
    if (stageSummaryEl) {
        if (selectedStats?.mandatoryTotal > 0) {
            stageSummaryEl.textContent =
                `Mandatory ready: ${selectedStats.mandatoryReady}/${selectedStats.mandatoryTotal} • ` +
                `Uploaded: ${selectedStats.mandatoryUploaded}/${selectedStats.mandatoryTotal} • ` +
                `Validated: ${selectedStats.mandatoryValidated}/${selectedStats.mandatoryTotal}`;
        } else {
            stageSummaryEl.textContent = 'No mandatory documents configured for this stage.';
        }
    }

    const stageListEl = config.stageMandatoryListId ? document.getElementById(config.stageMandatoryListId) : null;
    if (stageListEl) {
        if (selectedStats?.items?.length) {
            stageListEl.innerHTML = selectedStats.items
                .map((item) => `
                    <div class="journey-stage-list-item">
                        <div class="journey-stage-list-label">${escapeHtml(item.label)}</div>
                        <span class="journey-stage-list-status ${escapeHtml(item.statusClass)}">${escapeHtml(item.status)}</span>
                    </div>
                `)
                .join('');
        } else {
            stageListEl.innerHTML = '<div class="journey-stage-summary">No mandatory requirements in this stage.</div>';
        }
    }

    const stageInfoCard = config.stageInfoCardId ? document.getElementById(config.stageInfoCardId) : null;
    const stageActionHint = config.stageActionHintId ? document.getElementById(config.stageActionHintId) : null;
    const canJumpToDocuments = selectedStage === 1 && stageInfoCard;

    if (stageInfoCard) {
        if (canJumpToDocuments) {
            stageInfoCard.classList.add('journey-stage-card-clickable');
            stageInfoCard.onclick = () => switchDashboardTab('documents');
        } else {
            stageInfoCard.classList.remove('journey-stage-card-clickable');
            stageInfoCard.onclick = null;
        }
    }

    if (stageActionHint) {
        if (canJumpToDocuments) {
            stageActionHint.style.display = 'block';
            stageActionHint.textContent = 'Tip: Click this stage card to open Documents and upload Stage 1 files.';
        } else {
            stageActionHint.style.display = 'none';
            stageActionHint.textContent = '';
        }
    }

    // UK maintenance-funds calculator — the trickiest part of a UK application (London vs
    // outside, months of living costs, the 28-day rule). Surface it right inside Stage 4
    // (Finances & Healthcare) for UK students only, on whichever journey widget is showing.
    if (stageInfoCard) {
        const isUK = (currentUser && currentUser.destination_country_code) === 'UK';
        let cta = stageInfoCard.querySelector('.uk-funds-cta');
        if (isUK && selectedStage === 4) {
            if (!cta) {
                cta = document.createElement('button');
                cta.type = 'button';
                cta.className = 'uk-funds-cta';
                cta.style.cssText = 'width:100%;margin-top:12px;padding:11px 14px;border:none;border-radius:11px;font-size:13.5px;font-weight:700;color:#fff;background:linear-gradient(135deg,#6366f1,#a855f7);cursor:pointer;box-shadow:0 6px 18px rgba(99,102,241,.28)';
                cta.textContent = '💷 Calculate your exact maintenance funds & 28-day window';
                cta.addEventListener('click', (e) => { e.stopPropagation(); openUkFundsCalculator(); });
                stageInfoCard.appendChild(cta);
            }
            cta.style.display = '';
        } else if (cta) {
            cta.style.display = 'none';
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
        visa_case_status: getValue('profileVisaCaseStatus'),
        current_situation_story: getValue('profileCurrentSituationStory'),
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

    if (!(await confirmDialog('Your pending university change request will be cancelled.', { title: 'Cancel university change?', okText: 'Cancel request', cancelText: 'Keep it' }))) {
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

// Account deletion runs in an IN-APP modal (never native prompt/confirm): the emailed
// OTP forces users to switch tabs to their inbox, and Chrome dismisses native dialogs
// on tab switch — killing the flow right before the code entry.
// Danger-zone two-step reveal: the destructive delete control stays collapsed until the
// user deliberately expands it, so an accidental click during navigation can't reach the
// delete flow. Both functions are harmless/reversible on their own.
function revealDeleteAccount() {
    const reveal = document.getElementById('deleteAccountReveal');
    const trigger = document.getElementById('deleteAccountRevealBtn');
    if (reveal) reveal.style.display = 'block';
    if (trigger) trigger.style.display = 'none';
}
function hideDeleteAccountReveal() {
    const reveal = document.getElementById('deleteAccountReveal');
    const trigger = document.getElementById('deleteAccountRevealBtn');
    if (reveal) reveal.style.display = 'none';
    if (trigger) trigger.style.display = '';
}

function handleDeleteAccount() {
    if (!authToken) {
        showMessage('Please login to delete your account', 'error');
        return;
    }
    const modal = document.getElementById('deleteAccountModal');
    if (!modal) { showMessage('Something went wrong opening the deletion dialog.', 'error'); return; }

    // Reset to step 1 with clean inputs each time it opens.
    const confirmInput = document.getElementById('deleteAccountConfirmInput');
    const otpInput = document.getElementById('deleteAccountOtpInput');
    const continueBtn = document.getElementById('deleteAccountContinueBtn');
    document.getElementById('deleteAccountStep1').style.display = '';
    document.getElementById('deleteAccountStep2').style.display = 'none';
    deleteAccountShowError('');
    confirmInput.value = '';
    otpInput.value = '';
    continueBtn.disabled = true;
    continueBtn.textContent = 'Continue';
    document.getElementById('deleteAccountFinalBtn').disabled = false;
    document.getElementById('deleteAccountEmailLabel').textContent = currentUser?.email || 'your account email';

    // Enable Continue only when the exact confirmation text is typed.
    confirmInput.oninput = () => { continueBtn.disabled = confirmInput.value.trim() !== 'DELETE'; };
    confirmInput.onkeydown = (e) => { if (e.key === 'Enter' && !continueBtn.disabled) deleteAccountRequestCode(); };
    otpInput.onkeydown = (e) => { if (e.key === 'Enter') deleteAccountFinalize(); };

    modal.style.display = 'flex';
    confirmInput.focus();
}

function closeDeleteAccountModal() {
    const modal = document.getElementById('deleteAccountModal');
    if (modal) modal.style.display = 'none';
}

function deleteAccountShowError(message) {
    const box = document.getElementById('deleteAccountError');
    if (!box) return;
    box.textContent = message || '';
    box.style.display = message ? 'block' : 'none';
}

function deleteAccountAuthHeaders() {
    return (authToken && authToken !== COOKIE_AUTH_SENTINEL)
        ? { 'Authorization': `Bearer ${authToken}` } : {};
}

// Email the 6-digit second-factor code, then reveal the OTP step (or, on resend,
// stay there). The modal remains open the whole time — tab away freely.
async function deleteAccountRequestCode(isResend = false) {
    const continueBtn = document.getElementById('deleteAccountContinueBtn');
    const resendBtn = document.getElementById('deleteAccountResendBtn');
    deleteAccountShowError('');
    if (isResend) { resendBtn.disabled = true; resendBtn.textContent = 'Sending…'; }
    else { continueBtn.disabled = true; continueBtn.textContent = 'Sending code…'; }

    try {
        const reqRes = await fetch(`${API_BASE}/api/profile/delete/request-code`, {
            method: 'POST',
            headers: deleteAccountAuthHeaders(),
            credentials: 'include',
        });
        if (!reqRes.ok) {
            const e = await reqRes.json().catch(() => ({}));
            throw new Error(e.detail || 'Could not send the confirmation code. Please try again.');
        }
        document.getElementById('deleteAccountStep1').style.display = 'none';
        document.getElementById('deleteAccountStep2').style.display = '';
        document.getElementById('deleteAccountOtpInput').focus();
        if (isResend) showMessage('A fresh code is on its way to your email.', 'success');
    } catch (error) {
        const msg = error.message || 'Could not send the confirmation code. Please check your connection and try again.';
        if (isResend) deleteAccountShowError(msg); else showMessage(msg, 'error');
    } finally {
        continueBtn.disabled = false;
        continueBtn.textContent = 'Continue';
        if (resendBtn) {
            resendBtn.textContent = "Didn't get it? Resend code";
            // Brief cooldown so the resend link can't be hammered.
            setTimeout(() => { resendBtn.disabled = false; }, 15000);
        }
    }
}

async function deleteAccountFinalize() {
    const otpInput = document.getElementById('deleteAccountOtpInput');
    const finalBtn = document.getElementById('deleteAccountFinalBtn');
    const code = String(otpInput.value || '').trim();
    if (!/^\d{6}$/.test(code)) {
        deleteAccountShowError('Please enter the 6-digit code from your email.');
        otpInput.focus();
        return;
    }

    deleteAccountShowError('');
    finalBtn.disabled = true;
    finalBtn.textContent = 'Deleting…';
    try {
        const response = await fetch(`${API_BASE}/api/profile/`, {
            method: 'DELETE',
            headers: { ...deleteAccountAuthHeaders(), 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ code }),
        });

        if (response.ok || response.status === 204) {
            closeDeleteAccountModal();
            showMessage('Your account and all your data have been permanently erased from our systems. Thank you for using Rilono.', 'success');
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
            // Wrong/expired code etc. — keep the modal open so the user can retry or resend.
            throw new Error(error.detail || 'Failed to delete account');
        }
    } catch (error) {
        console.error('Delete account error:', error);
        deleteAccountShowError(error.message || 'An error occurred while deleting your account. Please try again.');
    } finally {
        finalBtn.disabled = false;
        finalBtn.textContent = 'Delete my account permanently';
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

// NOTE: loadDocumentationPreferences is defined once, earlier in this file (API-backed,
// destination-aware). A second localStorage-only declaration used to live here and
// shadowed it — keep this file to a single definition.

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

// Mirrors the backend's ALLOWED_DOCUMENT_EXTENSIONS (app/routers/documents.py) so users
// get an immediate, friendly rejection instead of discovering it after the passphrase
// prompt + client-side encryption + a failed upload round-trip.
const ALLOWED_DOCUMENT_FILE_EXTENSIONS = ['.pdf', '.doc', '.docx', '.txt', '.jpg', '.jpeg', '.png', '.gif', '.webp'];
function isAllowedDocumentFile(filename) {
    const name = String(filename || '').toLowerCase();
    const dot = name.lastIndexOf('.');
    if (dot < 0) return false;
    return ALLOWED_DOCUMENT_FILE_EXTENSIONS.includes(name.slice(dot));
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
    const documentType = document.getElementById('documentType').value;
    const description = document.getElementById('documentDescription').value.trim();
    const country = document.getElementById('documentationCountry').value;
    const intake = document.getElementById('documentationIntake').value;
    const year = document.getElementById('documentationYear').value ? parseInt(document.getElementById('documentationYear').value) : null;

    if (!fileInput.files || fileInput.files.length === 0) {
        showMessage('Please select a file to upload', 'error');
        return;
    }

    if (!documentType) {
        showMessage('Please select a document type', 'error');
        return;
    }

    const file = fileInput.files[0];

    // Validate the file type EARLY — before the passphrase prompt, encryption and upload.
    // (The picker's `accept` is only a soft hint; "All Files" bypasses it. The backend
    // enforces the same allowlist and would 400, but the user deserves the answer now.)
    if (!isAllowedDocumentFile(file.name)) {
        showMessage('That file type isn\'t supported. Please upload PDF, DOC, DOCX, TXT or an image (JPG, PNG, GIF, WEBP).', 'error');
        return;
    }

    // Validate file size (5MB)
    const maxSize = 5 * 1024 * 1024;
    if (file.size > maxSize) {
        showMessage('File is too large. Maximum size is 5MB', 'error');
        return;
    }

    if (!window.E2E || !E2E.isSupported()) {
        showMessage('Your browser does not support end-to-end encryption. Please use a modern browser over HTTPS.', 'error');
        return;
    }

    // Unlock (or first-time set up) the end-to-end encryption vault. The passphrase and the
    // master key never leave this device — the file is encrypted here before it is uploaded.
    let master;
    try {
        master = await RilonoE2E.ensureReady();
    } catch (err) {
        console.error('E2E unlock error:', err);
        showMessage(err && err.message ? err.message : 'Could not unlock encryption.', 'error');
        return;
    }
    if (!master) return; // user cancelled the passphrase prompt

    // Rilono AI validation runs on EVERY upload — scanning the document is the core of the
    // product, so it is not optional. The plaintext is sent ONCE, in memory; the server runs
    // Gemini and returns the result WITHOUT storing it, then the file is stored end-to-end
    // encrypted. If validation can't complete (e.g. the AI service is briefly unavailable) the
    // document is still stored encrypted and left pending review rather than blocking the upload.
    let aiValidation = null;
    try {
        setDocumentUploadLoading(true, 'Rilono AI is validating (read once, never stored)...', file);
        const vfd = new FormData();
        vfd.append('file', file);
        vfd.append('document_type', documentType);
        vfd.append('consent', 'true');
        const vres = await fetch(`${API_BASE}/api/documents/ai-validate`, {
            method: 'POST', headers: { 'Authorization': `Bearer ${authToken}` }, body: vfd
        });
        if (vres.ok) {
            aiValidation = await vres.json();
        } else {
            const ev = await vres.json().catch(() => ({}));
            showMessage((ev.detail || 'AI validation could not be completed') + ' — storing encrypted, review will be pending.', 'error');
        }
    } catch (err) {
        console.error('AI validate error:', err);
        showMessage('AI validation didn\'t complete — storing the document encrypted, review pending.', 'error');
    }

    try {
        setDocumentUploadLoading(true, 'Encrypting on your device...', file);
        showMessage('Encrypting document on your device...', 'success');

        const fileBytes = new Uint8Array(await file.arrayBuffer());
        const { blob, wrappedDekB64 } = await E2E.encryptBytes(fileBytes, master);

        const formData = new FormData();
        // Only ciphertext + the wrapped key leave the browser — never the plaintext.
        formData.append('file', new Blob([blob], { type: 'application/octet-stream' }), (file.name || 'document') + '.enc');
        formData.append('wrapped_dek', wrappedDekB64);
        formData.append('original_filename', file.name || 'document');
        formData.append('file_type', file.type || 'application/octet-stream');
        formData.append('document_type', documentType);
        if (country) formData.append('country', country);
        if (intake) formData.append('intake', intake);
        if (year) formData.append('year', year);
        if (description) formData.append('description', description);

        // If the user consented and AI returned details, keep the extracted JSON end-to-end
        // encrypted too: encrypt it under the master key and upload only the ciphertext. Only
        // the non-sensitive validity verdict (is_valid) is stored in the clear server-side.
        if (aiValidation) {
            formData.append('is_valid', aiValidation.is_valid ? 'true' : 'false');
            if (aiValidation.details) {
                const extractedBytes = new TextEncoder().encode(JSON.stringify(aiValidation.details));
                const ext = await E2E.encryptBytes(extractedBytes, master);
                formData.append('extracted_blob', new Blob([ext.blob], { type: 'application/octet-stream' }), 'extracted.enc');
                formData.append('extracted_wrapped_dek', ext.wrappedDekB64);
            }
        }

        setDocumentUploadLoading(true, 'Uploading encrypted file...');
        const response = await fetch(`${API_BASE}/api/documents/upload-e2e`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`
            },
            body: formData
        });
        const data = await response.json().catch(() => ({}));

        if (response.ok) {
            const documentName = file.name;
            const docTypeText = documentType ? ` (${documentType})` : '';
            if (aiValidation) {
                // Consent-based AI ran: surface the verdict (details were stored E2E).
                const verdict = aiValidation.is_valid ? 'Rilono AI: Document Validated' : 'Rilono AI: Document Validation Failed';
                const body = `File: ${documentName}${docTypeText}\n\n${aiValidation.message || (aiValidation.is_valid ? 'Document validated successfully.' : 'This document may not match the expected type — please review.')}\n\nStored end-to-end encrypted; extracted details are encrypted on your device.`;
                addNotification(verdict, body, aiValidation.is_valid ? 'success' : 'error', aiValidation.details || null);
                showMessage(aiValidation.is_valid ? 'Validated and stored end-to-end encrypted.' : 'Stored encrypted — AI flagged the document, see notifications.', aiValidation.is_valid ? 'success' : 'error');
            } else {
                addNotification(
                    'Document stored — validation pending',
                    `File: ${documentName}${docTypeText}\n\nEncrypted on your device — our servers only ever hold ciphertext. Rilono AI couldn't validate it just now; re-upload if it stays pending.`,
                    'success',
                    null
                );
                showMessage('Document stored encrypted. AI validation didn\'t complete — please try again.', 'success');
            }

            markE2EChatContextDirty();
            setDocumentUploadLoading(true, 'Upload complete. Syncing your documents...');
            document.getElementById('documentUploadForm').reset();
            // Also reset the searchable dropdown
            document.getElementById('documentType').value = '';
            const dts = document.getElementById('documentTypeSearch');
            if (dts) dts.value = '';
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
                    errorMessage = data.detail.map(err => `${(err.loc || []).join('.')}: ${err.msg}`).join(', ');
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

function resetDocumentUploadPreviewElements() {
    const previewImg = document.getElementById('docUploadPreviewImg');
    const previewFrame = document.getElementById('docUploadPreviewFrame');
    const previewText = document.getElementById('docUploadPreviewText');
    const placeholder = document.getElementById('docUploadPlaceholder');

    if (previewImg) {
        if (previewImg._objectUrl) {
            URL.revokeObjectURL(previewImg._objectUrl);
            previewImg._objectUrl = null;
        }
        previewImg.src = '';
        previewImg.style.display = 'none';
    }
    if (previewFrame) {
        if (previewFrame._objectUrl) {
            URL.revokeObjectURL(previewFrame._objectUrl);
            previewFrame._objectUrl = null;
        }
        previewFrame.removeAttribute('src');
        previewFrame.style.display = 'none';
    }
    if (previewText) {
        previewText.textContent = '';
        previewText.style.display = 'none';
    }
    if (placeholder) {
        placeholder.style.display = 'grid';
    }
}

function updateDocumentUploadPreview(file) {
    if (!file) return;

    const previewImg = document.getElementById('docUploadPreviewImg');
    const previewFrame = document.getElementById('docUploadPreviewFrame');
    const previewText = document.getElementById('docUploadPreviewText');
    const placeholder = document.getElementById('docUploadPlaceholder');
    const extension = (file.name.split('.').pop() || '').toLowerCase();
    const mimeType = (file.type || '').toLowerCase();

    resetDocumentUploadPreviewElements();

    const isImage = mimeType.startsWith('image/') || ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'].includes(extension);
    const isPdf = mimeType === 'application/pdf' || extension === 'pdf';
    const isText =
        mimeType.startsWith('text/')
        || ['txt', 'md', 'json', 'xml', 'yaml', 'yml', 'log'].includes(extension);

    if (isImage && previewImg) {
        const imageUrl = URL.createObjectURL(file);
        previewImg._objectUrl = imageUrl;
        previewImg.src = imageUrl;
        previewImg.style.display = 'block';
        if (placeholder) placeholder.style.display = 'none';
        return;
    }

    if (isPdf && previewFrame) {
        const pdfUrl = URL.createObjectURL(file);
        previewFrame._objectUrl = pdfUrl;
        previewFrame.src = `${pdfUrl}#toolbar=0&navpanes=0&scrollbar=0`;
        previewFrame.style.display = 'block';
        if (placeholder) placeholder.style.display = 'none';
        return;
    }

    if (isText && previewText) {
        const reader = new FileReader();
        reader.onload = () => {
            const rawContent = String(reader.result || '');
            const clippedContent = rawContent.length > 12000
                ? `${rawContent.slice(0, 12000)}\n\n...[preview truncated]`
                : rawContent;
            previewText.textContent = clippedContent;
            previewText.style.display = 'block';
            if (placeholder) placeholder.style.display = 'none';
        };
        reader.onerror = () => {
            if (placeholder) placeholder.style.display = 'grid';
        };
        reader.readAsText(file);
        return;
    }
}

function setDocumentUploadLoading(isLoading, message = '', file = null) {
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

        /* Populate file info and preview if available */
        if (file) {
            const nameEl = document.getElementById('docUploadFileName');
            const metaEl = document.getElementById('docUploadFileMeta');
            if (nameEl) nameEl.textContent = file.name;
            if (metaEl) {
                const ext = file.name.split('.').pop().toUpperCase();
                const sizeMB = (file.size / (1024 * 1024)).toFixed(2);
                metaEl.textContent = `${ext} · ${sizeMB} MB`;
            }
            updateDocumentUploadPreview(file);
        }

        /* Set active step based on message */
        updateDocUploadStep(message);
        if (/scanning|validat|analyz/i.test((message || '').toLowerCase())) {
            if (!documentUploadScanStartedAt) {
                documentUploadScanStartedAt = Date.now();
            }
        }

        if (modalTextEl) {
            modalTextEl.textContent = message || 'Processing document...';
        }
        if (modal) {
            modal.style.display = 'flex';
        }
        return;
    }

    documentUploadInProgress = false;
    documentUploadScanStartedAt = 0;
    const fields = form.querySelectorAll('input, textarea, button, select');
    fields.forEach((field) => {
        field.disabled = false;
    });
    submitButton.textContent = submitButton.dataset.defaultText;

    if (message) {
        if (modalTextEl) {
            modalTextEl.textContent = message;
        }
        updateDocUploadStep(message);
        documentUploadStatusTimer = setTimeout(() => {
            if (modal) {
                modal.style.display = 'none';
            }
            resetDocUploadSteps();
        }, 1200);
    } else {
        if (modal) {
            modal.style.display = 'none';
        }
        resetDocUploadSteps();
    }
}

function updateDocUploadStep(msg) {
    const steps = [
        document.getElementById('docUploadStep1'),
        document.getElementById('docUploadStep2'),
        document.getElementById('docUploadStep3'),
        document.getElementById('docUploadStep4')
    ];
    const scanArea = document.querySelector('.doc-upload-scan-area');
    if (!steps[0]) return;

    let activeIdx = 0;
    const lower = (msg || '').toLowerCase();
    if (/complete|syncing|visible|done/i.test(lower)) {
        activeIdx = 3;
    } else if (/scanning|validat|analyz/i.test(lower)) {
        activeIdx = 2;
    } else if (/upload/i.test(lower)) {
        activeIdx = 1;
    }

    steps.forEach((step, i) => {
        if (!step) return;
        step.classList.remove('active', 'completed');
        if (i < activeIdx) {
            step.classList.add('completed');
        } else if (i === activeIdx) {
            step.classList.add('active');
        }
    });

    /* Add scanning class for AI step animation */
    if (scanArea) {
        scanArea.classList.toggle('scanning', activeIdx === 2);
        scanArea.classList.toggle('complete', activeIdx === 3);
    }
}

function resetDocUploadSteps() {
    const steps = [
        document.getElementById('docUploadStep1'),
        document.getElementById('docUploadStep2'),
        document.getElementById('docUploadStep3'),
        document.getElementById('docUploadStep4')
    ];
    steps.forEach(step => {
        if (step) {
            step.classList.remove('active', 'completed');
        }
    });
    if (steps[0]) steps[0].classList.add('active');
    const scanArea = document.querySelector('.doc-upload-scan-area');
    if (scanArea) {
        scanArea.classList.remove('scanning', 'complete');
    }
    resetDocumentUploadPreviewElements();
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
            statusStyle: 'background: rgba(16, 185, 129, 0.15); color: #065f46; border: 1px solid rgba(16, 185, 129, 0.45);',
            cardStyle: 'border: 1px solid rgba(16, 185, 129, 0.35); background: rgba(16, 185, 129, 0.08);',
            indicatorIcon: '✓',
            indicatorColor: '#065f46',
            reason: '',
            reasonStyle: ''
        };
    }

    if (doc.is_valid === false) {
        return {
            statusLabel: 'Needs Review',
            statusStyle: 'background: rgba(245, 158, 11, 0.15); color: #92400e; border: 1px solid rgba(245, 158, 11, 0.45);',
            cardStyle: 'border: 1px solid rgba(245, 158, 11, 0.35); background: rgba(245, 158, 11, 0.09);',
            indicatorIcon: '!',
            indicatorColor: '#b45309',
            reason: doc.validation_message || 'Validation failed. Please upload the correct document.',
            reasonStyle: 'color: #92400e; background: rgba(245, 158, 11, 0.14); border: 1px solid rgba(245, 158, 11, 0.45); border-radius: 0.6rem; padding: 0.55rem 0.65rem;'
        };
    }

    const isProcessing = doc.is_processed === false;
    return {
        statusLabel: isProcessing ? 'Processing' : 'Pending Validation',
        statusStyle: 'background: rgba(99, 102, 241, 0.15); color: #4338ca; border: 1px solid rgba(99, 102, 241, 0.45);',
        cardStyle: 'border: 1px solid rgba(99, 102, 241, 0.35); background: rgba(99, 102, 241, 0.08);',
        indicatorIcon: '•',
        indicatorColor: '#4338ca',
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
            Your full document checklist for your journey — items you've uploaded appear first.
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
                ? 'background: rgba(239, 68, 68, 0.14); color: #b91c1c; border: 1px solid rgba(239, 68, 68, 0.45);'
                : 'background: rgba(59, 130, 246, 0.14); color: #1d4ed8; border: 1px solid rgba(59, 130, 246, 0.45);')
            : 'background: rgba(148, 163, 184, 0.14); color: #475569; border: 1px solid rgba(148, 163, 184, 0.5);';

        return `
            <div style="margin-top: 0.5rem; display: flex; flex-wrap: wrap; gap: 0.45rem;">
                <span style="font-size: 0.75rem; font-weight: 700; border-radius: 999px; padding: 0.15rem 0.5rem; ${requirementStyle}">
                    ${escapeHtml(requirementText)}
                </span>
                <span style="font-size: 0.75rem; font-weight: 700; border-radius: 999px; padding: 0.15rem 0.5rem; background: rgba(99, 102, 241, 0.14); color: #4338ca; border: 1px solid rgba(99, 102, 241, 0.45);">
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
        const isE2E = !!doc.e2e_scheme;
        const isEncrypted = isE2E || doc.encrypted_file_key || !doc.file_url;
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
                            ${isE2E ? ' • <span style="color: #065f46;">🔒 End-to-end encrypted</span>' : (isEncrypted ? ' • <span style="color: #92400e;">🔒 Encrypted (legacy) — re-upload for end-to-end encryption</span>' : '')}
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
                            ${isE2E ? `
                                <button onclick="downloadE2EFromButton(this)" data-document-id="${doc.id}" data-document-name="${escapeHtml(doc.original_filename || 'document')}" data-file-type="${escapeHtml(doc.file_type || '')}" class="btn btn-primary" style="font-size: 0.875rem; padding: 0.5rem 1rem;">Download</button>
                            ` : isEncrypted ? `
                                <button onclick="downloadEncryptedDocument(${doc.id})" class="btn btn-primary" style="font-size: 0.875rem; padding: 0.5rem 1rem;">Download</button>
                            ` : `
                                <a href="${doc.file_url}" target="_blank" class="btn btn-primary" style="font-size: 0.875rem; padding: 0.5rem 1rem; text-decoration: none; display: inline-block;">View</a>
                                <a href="${API_BASE}/api/documents/${doc.id}/download" class="btn" style="font-size: 0.875rem; padding: 0.5rem 1rem; background: var(--bg-color); border: 1px solid var(--border-color); text-decoration: none; display: inline-block;">Download</a>
                            `}
                            <button onclick="deleteDocumentFromButton(this)" data-document-id="${doc.id}" data-document-name="${escapeHtml(doc.original_filename || 'document')}" class="btn" style="font-size: 0.875rem; padding: 0.5rem 1rem; background: rgba(239, 68, 68, 0.14); color: #b91c1c; border: 1px solid rgba(239, 68, 68, 0.45);">Delete</button>
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
            ? 'background: rgba(239, 68, 68, 0.14); color: #b91c1c; border: 1px solid rgba(239, 68, 68, 0.45);'
            : 'background: rgba(59, 130, 246, 0.14); color: #1d4ed8; border: 1px solid rgba(59, 130, 246, 0.45);';

        cardsHtml += `
            <div data-document-type="${escapeHtml(pendingType.value)}" style="border: 1px solid var(--border-color); border-radius: 0.75rem; padding: 0.95rem 1rem; margin-bottom: 0.75rem; background: var(--bg-secondary);">
                <div style="display: flex; align-items: center; gap: 0.75rem;">
                    <div style="color: #64748b; font-size: 1.15rem; font-weight: bold; flex-shrink: 0;">○</div>
                    <div style="flex: 1;">
                        <div style="font-weight: 600; color: var(--text-primary); margin-bottom: 0.25rem;">
                            ${escapeHtml(pendingType.label)}
                        </div>
                        <div style="font-size: 0.84rem; color: var(--text-secondary); display: inline-flex; align-items: center; gap: 0.35rem;">
                            <span style="display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #d97706;"></span>
                            Not uploaded yet
                        </div>
                        <div style="margin-top: 0.5rem; display: flex; flex-wrap: wrap; gap: 0.45rem;">
                            <span style="font-size: 0.75rem; font-weight: 700; border-radius: 999px; padding: 0.15rem 0.5rem; ${requirementStyle}">
                                ${isMandatory ? 'Mandatory' : 'Optional'}
                            </span>
                            <span style="font-size: 0.75rem; font-weight: 700; border-radius: 999px; padding: 0.15rem 0.5rem; background: rgba(99, 102, 241, 0.14); color: #4338ca; border: 1px solid rgba(99, 102, 241, 0.45);">
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

function deleteDocumentFromButton(buttonEl) {
    if (!buttonEl?.dataset) return;

    const documentId = Number.parseInt(buttonEl.dataset.documentId || '', 10);
    if (!Number.isFinite(documentId)) return;

    const filename = buttonEl.dataset.documentName || 'document';
    deleteDocument(documentId, filename);
}

async function downloadEncryptedDocument(documentId) {
    if (!authToken) {
        showMessage('Please login to download documents', 'error');
        return;
    }

    const password = await promptDialog('Enter your password to decrypt and download this document.', { title: 'Decrypt document', type: 'password', placeholder: 'Your account password', okText: 'Decrypt & download' });
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

// ============================================================================
// Client-side end-to-end encryption (E2E) controller.
// Holds the unlocked master key in memory for the session and drives the
// passphrase setup / unlock / recovery modals. The passphrase and the master
// key NEVER leave the browser; the server only stores opaque wrapped blobs.
// See static/e2e_crypto.js (window.E2E) for the crypto primitives.
// ============================================================================
const RilonoE2E = (function () {
    let master = null;        // Uint8Array, in-memory only (cleared on lock/logout)

    function authHeaders(extra) {
        return Object.assign({ 'Authorization': `Bearer ${authToken}` }, extra || {});
    }

    async function getVault() {
        const r = await fetch(`${API_BASE}/api/e2e/vault`, { headers: authHeaders() });
        if (!r.ok) throw new Error('Could not load your encryption settings.');
        return r.json();
    }

    function makeOverlay() {
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:100000;display:flex;align-items:center;justify-content:center;padding:1rem;';
        const box = document.createElement('div');
        box.style.cssText = 'background:var(--bg-color,#ffffff);color:var(--text-primary,#111);max-width:480px;width:100%;border-radius:14px;padding:1.5rem;box-shadow:0 20px 60px rgba(0,0,0,0.45);border:1px solid var(--border-color,#ddd);font-size:0.95rem;';
        overlay.appendChild(box);
        document.body.appendChild(overlay);
        return { overlay, box, remove() { try { document.body.removeChild(overlay); } catch (_) {} } };
    }

    const inputCss = 'width:100%;padding:.6rem;border-radius:8px;border:1px solid var(--border-color,#ccc);margin-bottom:.5rem;background:var(--bg-tertiary,#fff);color:var(--text-primary,#111);box-sizing:border-box;';
    const rowCss = 'display:flex;gap:.5rem;justify-content:flex-end;margin-top:.75rem;';

    function showRecoveryCode(code) {
        return new Promise((resolve) => {
            const o = makeOverlay();
            o.box.innerHTML = `
                <h3 style="margin:0 0 .5rem;">Save your recovery code</h3>
                <p style="font-size:.9rem;color:var(--text-secondary,#666);margin:.25rem 0 .75rem;">
                  This is the <b>only</b> way to recover your documents if you forget your passphrase.
                  We can't recover it for you. Store it somewhere safe.</p>
                <div style="font-family:monospace;font-size:1.15rem;letter-spacing:1px;text-align:center;padding:.75rem;border:1px dashed var(--border-color,#bbb);border-radius:10px;user-select:all;margin-bottom:.5rem;">${escapeHtml(code)}</div>
                <div style="${rowCss}">
                  <button id="e2eCopy" class="btn" style="padding:.5rem 1rem;">Copy</button>
                  <button id="e2eSaved" class="btn btn-primary" style="padding:.5rem 1rem;">I've saved it</button>
                </div>`;
            o.box.querySelector('#e2eCopy').onclick = () => {
                try { navigator.clipboard.writeText(code); showMessage('Recovery code copied.', 'success'); } catch (_) {}
            };
            o.box.querySelector('#e2eSaved').onclick = () => { o.remove(); resolve(); };
        });
    }

    function runSetup() {
        return new Promise((resolve, reject) => {
            const o = makeOverlay();
            o.box.innerHTML = `
                <h3 style="margin:0 0 .5rem;">Protect your documents with end-to-end encryption</h3>
                <p style="font-size:.9rem;color:var(--text-secondary,#666);margin:.25rem 0 1rem;">
                  Choose an encryption passphrase. It's separate from your login password and
                  <b>never leaves your device</b> — so our servers can only ever store ciphertext.</p>
                <input id="e2eP1" type="password" autocomplete="new-password" placeholder="Encryption passphrase (min 8 chars)" style="${inputCss}">
                <input id="e2eP2" type="password" autocomplete="new-password" placeholder="Confirm passphrase" style="${inputCss}">
                <div id="e2eSetupErr" style="color:#ef4444;font-size:.85rem;min-height:1.1rem;"></div>
                <div style="${rowCss}">
                  <button id="e2eSetupCancel" class="btn" style="padding:.5rem 1rem;">Cancel</button>
                  <button id="e2eSetupGo" class="btn btn-primary" style="padding:.5rem 1rem;">Create</button>
                </div>`;
            const err = o.box.querySelector('#e2eSetupErr');
            o.box.querySelector('#e2eSetupCancel').onclick = () => { o.remove(); resolve(null); };
            o.box.querySelector('#e2eSetupGo').onclick = async () => {
                const p1 = o.box.querySelector('#e2eP1').value;
                const p2 = o.box.querySelector('#e2eP2').value;
                if (!p1 || p1.length < 8) { err.textContent = 'Passphrase must be at least 8 characters.'; return; }
                if (p1 !== p2) { err.textContent = 'Passphrases do not match.'; return; }
                try {
                    const v = await E2E.createVault(p1);
                    const r = await fetch(`${API_BASE}/api/e2e/setup`, {
                        method: 'POST',
                        headers: authHeaders({ 'Content-Type': 'application/json' }),
                        body: JSON.stringify({
                            kdf: v.kdf,
                            wrapped_master_key: v.wrapped_master_key,
                            recovery_wrapped_master_key: v.recovery_wrapped_master_key
                        })
                    });
                    if (!r.ok) {
                        const d = await r.json().catch(() => ({}));
                        err.textContent = (d && d.detail) ? d.detail : 'Could not set up encryption.';
                        return;
                    }
                    o.remove();
                    await showRecoveryCode(v.recoveryCode);
                    resolve(v.masterRaw);
                } catch (e) { reject(e); }
            };
            o.box.querySelector('#e2eP1').focus();
        });
    }

    function runRecovery(vault) {
        return new Promise((resolve) => {
            const o = makeOverlay();
            o.box.innerHTML = `
                <h3 style="margin:0 0 .5rem;">Recover with your recovery code</h3>
                <p style="font-size:.9rem;color:var(--text-secondary,#666);margin:.25rem 0 1rem;">
                  Enter the recovery code you saved at setup, then choose a new passphrase.</p>
                <input id="e2eRC" type="text" autocomplete="off" placeholder="XXXXX-XXXXX-XXXXX-XXXXX" style="${inputCss}">
                <input id="e2eRP1" type="password" autocomplete="new-password" placeholder="New passphrase (min 8 chars)" style="${inputCss}">
                <input id="e2eRP2" type="password" autocomplete="new-password" placeholder="Confirm new passphrase" style="${inputCss}">
                <div id="e2eRecErr" style="color:#ef4444;font-size:.85rem;min-height:1.1rem;"></div>
                <div style="${rowCss}">
                  <button id="e2eRecCancel" class="btn" style="padding:.5rem 1rem;">Cancel</button>
                  <button id="e2eRecGo" class="btn btn-primary" style="padding:.5rem 1rem;">Recover</button>
                </div>`;
            const err = o.box.querySelector('#e2eRecErr');
            o.box.querySelector('#e2eRecCancel').onclick = () => { o.remove(); resolve(null); };
            o.box.querySelector('#e2eRecGo').onclick = async () => {
                const code = o.box.querySelector('#e2eRC').value;
                const p1 = o.box.querySelector('#e2eRP1').value;
                const p2 = o.box.querySelector('#e2eRP2').value;
                if (p1.length < 8) { err.textContent = 'New passphrase must be at least 8 characters.'; return; }
                if (p1 !== p2) { err.textContent = 'Passphrases do not match.'; return; }
                let m;
                try { m = await E2E.unlockWithRecovery(vault, code); }
                catch (_) { err.textContent = 'Incorrect recovery code.'; return; }
                try {
                    const rot = await E2E.rewrapForNewPassphrase(m, p1);
                    const r = await fetch(`${API_BASE}/api/e2e/recover`, {
                        method: 'POST',
                        headers: authHeaders({ 'Content-Type': 'application/json' }),
                        body: JSON.stringify({
                            kdf: rot.kdf,
                            wrapped_master_key: rot.wrapped_master_key,
                            recovery_wrapped_master_key: rot.recovery_wrapped_master_key
                        })
                    });
                    if (!r.ok) { err.textContent = 'Could not save your new passphrase.'; return; }
                    o.remove();
                    await showRecoveryCode(rot.recoveryCode);
                    resolve(m);
                } catch (e) { err.textContent = 'Recovery failed. Please try again.'; }
            };
            o.box.querySelector('#e2eRC').focus();
        });
    }

    function runUnlock(vault) {
        return new Promise((resolve) => {
            const o = makeOverlay();
            o.box.innerHTML = `
                <h3 style="margin:0 0 .5rem;">Unlock your encrypted documents</h3>
                <p style="font-size:.9rem;color:var(--text-secondary,#666);margin:.25rem 0 1rem;">
                  Enter your encryption passphrase. It never leaves your device.</p>
                <input id="e2eUP" type="password" autocomplete="off" placeholder="Encryption passphrase" style="${inputCss}">
                <div id="e2eUErr" style="color:#ef4444;font-size:.85rem;min-height:1.1rem;"></div>
                <div style="${rowCss}">
                  <button id="e2eUCancel" class="btn" style="padding:.5rem 1rem;">Cancel</button>
                  <button id="e2eUGo" class="btn btn-primary" style="padding:.5rem 1rem;">Unlock</button>
                </div>
                <div style="margin-top:.75rem;font-size:.82rem;"><a href="#" id="e2eForgot" style="color:var(--text-secondary,#888);">Forgot passphrase? Use recovery code</a></div>`;
            const err = o.box.querySelector('#e2eUErr');
            const input = o.box.querySelector('#e2eUP');
            const close = (v) => { o.remove(); resolve(v); };
            o.box.querySelector('#e2eUCancel').onclick = () => close(null);
            const go = async () => {
                if (!input.value) { err.textContent = 'Enter your passphrase.'; return; }
                try { close(await E2E.unlockVault(vault, input.value)); }
                catch (_) { err.textContent = 'Incorrect passphrase. Try again.'; }
            };
            o.box.querySelector('#e2eUGo').onclick = go;
            input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') go(); });
            o.box.querySelector('#e2eForgot').onclick = async (ev) => {
                ev.preventDefault();
                const m = await runRecovery(vault);
                if (m) close(m);
            };
            input.focus();
        });
    }

    // Returns the in-memory master key (Uint8Array), prompting setup or unlock as needed.
    // Returns null if the user cancels.
    async function ensureReady() {
        if (master) return master;
        if (!window.E2E || !E2E.isSupported()) {
            throw new Error('This browser does not support end-to-end encryption (needs a modern browser over HTTPS).');
        }
        const vault = await getVault();
        const m = vault && vault.enabled ? await runUnlock(vault) : await runSetup();
        if (m) master = m;
        return m;
    }

    function lock() { master = null; }
    function isUnlocked() { return !!master; }

    return { ensureReady, lock, isUnlocked, getVault, getMaster: () => master };
})();

function downloadE2EFromButton(btn) {
    const id = Number.parseInt(btn.dataset.documentId || '', 10);
    if (!Number.isFinite(id)) return;
    downloadE2EDocument(id, btn.dataset.documentName || 'document', btn.dataset.fileType || '');
}

async function downloadE2EDocument(documentId, filename, fileType) {
    if (!authToken) { showMessage('Please login to download documents', 'error'); return; }
    let master;
    try {
        master = await RilonoE2E.ensureReady();
    } catch (err) {
        showMessage(err && err.message ? err.message : 'Could not unlock encryption.', 'error');
        return;
    }
    if (!master) return; // cancelled
    try {
        showMessage('Fetching and decrypting on your device...', 'success');
        const response = await fetch(`${API_BASE}/api/documents/${documentId}/blob`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        if (!response.ok) {
            const e = await response.json().catch(() => ({}));
            showMessage(e.detail || 'Failed to fetch document.', 'error');
            return;
        }
        const wrappedDek = response.headers.get('X-E2E-Wrapped-Dek');
        if (!wrappedDek) { showMessage('This document is missing its key reference.', 'error'); return; }
        const ciphertext = new Uint8Array(await response.arrayBuffer());
        let plaintext;
        try {
            plaintext = await E2E.decryptBlob(ciphertext, wrappedDek, master);
        } catch (_) {
            showMessage('Could not decrypt this document with your current key.', 'error');
            return;
        }
        const blob = new Blob([plaintext], { type: fileType || 'application/octet-stream' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename || 'document';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        showMessage('Document decrypted on your device and downloaded.', 'success');
    } catch (error) {
        console.error('E2E download error:', error);
        showMessage('An error occurred while downloading the document. Please try again.', 'error');
    }
}

async function deleteDocument(documentId, filename) {
    if (!authToken) {
        showMessage('Please login to delete documents', 'error');
        return;
    }

    // Confirm deletion
    const confirmed = await confirmDialog(`"${filename}" will be permanently deleted from storage. This cannot be undone.`, { title: 'Delete document?', okText: 'Delete' });
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

function getRilonoAiChatFormFromEvent(event) {
    const target = event && event.target;
    if (target && typeof target.closest === 'function') {
        const form = target.closest('.rilono-ai-form[data-main-chat-form="true"]');
        if (form) return form;
    }
    const currentTarget = event && event.currentTarget;
    if (currentTarget && typeof currentTarget.matches === 'function'
        && currentTarget.matches('.rilono-ai-form[data-main-chat-form="true"]')) {
        return currentTarget;
    }
    return null;
}

function handleDelegatedRilonoAiChatSubmit(event) {
    if (event.defaultPrevented || !getRilonoAiChatFormFromEvent(event)) return;
    void handleRilonoAiChatSubmit(event);
}

function getMainChatWelcomeMarkup() {
    return `
        <div class="rilono-ai-message assistant">
            <div class="message-avatar"><svg viewBox="0 0 24 24" width="18" height="18" class="ai-sparkle"><use href="#icon-ai-sparkle"></use></svg></div>
            <div class="message-bubble">
                <p><strong>Welcome! I'm Rilono AI.</strong> I'm here to guide your study-abroad journey with practical, step-by-step help.</p>
                <p>I can help you with:</p>
                <p>• What to upload next (document checklist)</p>
                <p>• Profile and visa-stage gaps you should fix first</p>
                <p>• Mock questions and answer-quality coaching</p>
                <p>• Important deadlines, risks, and updates</p>
                <p>Tell me your current stage (${currentVisaStagesPhrase()}), and I'll suggest your best next step.</p>
            </div>
        </div>
    `;
}

function getFloatingChatWelcomeMarkup() {
    return `
        <div class="chat-welcome-message">
            <div class="chat-avatar"><svg viewBox="0 0 24 24" width="20" height="20" class="ai-sparkle"><use href="#icon-ai-sparkle"></use></svg></div>
            <div class="welcome-bubble">
                <p><strong>Welcome! I'm Rilono AI.</strong></p>
                <p>I can help with documents, visa-stage progress, interview prep, and next actions based on your profile.</p>
                <p>Share your current stage, and I'll guide you step by step.</p>
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

function registerRilonoAiAttachmentMetadata(attachment) {
    const attachmentId = String(attachment?.id || '').trim();
    if (!attachmentId || rilonoAiAttachmentRegistry.has(attachmentId)) {
        return;
    }

    const mimeType = String(attachment?.mime_type || '').trim().toLowerCase();
    const attachmentMeta = {
        id: attachmentId,
        name: String(attachment?.name || 'Attachment').trim() || 'Attachment',
        mime_type: mimeType,
        size_bytes: Number(attachment?.size_bytes || 0),
        preview_url: null
    };

    if (mimeType.startsWith('image/') && attachment?.content_base64) {
        attachmentMeta.preview_url = `data:${mimeType};base64,${attachment.content_base64}`;
    }

    rilonoAiAttachmentRegistry.set(attachmentId, attachmentMeta);
}

function registerRilonoAiAttachmentBatch(attachments) {
    const list = Array.isArray(attachments) ? attachments : [];
    list.forEach((attachment) => registerRilonoAiAttachmentMetadata(attachment));
}

function getRilonoAiMessageAttachmentMetaList(attachmentIds = []) {
    if (!Array.isArray(attachmentIds) || attachmentIds.length === 0) {
        return [];
    }

    const seenIds = new Set();
    const metaList = [];
    attachmentIds.forEach((rawId) => {
        const attachmentId = String(rawId || '').trim();
        if (!attachmentId || seenIds.has(attachmentId)) return;
        seenIds.add(attachmentId);
        const metadata = rilonoAiAttachmentRegistry.get(attachmentId);
        if (metadata) {
            metaList.push(metadata);
        }
    });
    return metaList;
}

function renderRilonoAiUserMessageAttachmentsHtml(attachmentIds = []) {
    const attachments = getRilonoAiMessageAttachmentMetaList(attachmentIds);
    if (attachments.length === 0) {
        return '';
    }

    const cards = attachments.map((attachment) => {
        const name = escapeHtml(attachment.name || 'Attachment');
        const sizeText = escapeHtml(formatRilonoAiAttachmentSize(Number(attachment.size_bytes || 0)));
        const isImage = String(attachment.mime_type || '').startsWith('image/') && attachment.preview_url;
        if (isImage) {
            return `
                <div class="rilono-chat-sent-attachment rilono-chat-sent-attachment-image">
                    <img src="${attachment.preview_url}" alt="${name}" loading="lazy">
                    <div class="rilono-chat-sent-attachment-caption">${name}</div>
                </div>
            `;
        }

        return `
            <div class="rilono-chat-sent-attachment rilono-chat-sent-attachment-file" title="${name}">
                <span class="rilono-chat-sent-file-icon">📄</span>
                <span class="rilono-chat-sent-file-name">${name}</span>
                <span class="rilono-chat-sent-file-size">${sizeText}</span>
            </div>
        `;
    }).join('');

    return `<div class="rilono-chat-sent-attachments">${cards}</div>`;
}

function buildRilonoAiUserBubbleHtml(message, attachmentIds = []) {
    const attachmentMarkup = renderRilonoAiUserMessageAttachmentsHtml(attachmentIds);
    const trimmedMessage = String(message || '').trim();
    const messageMarkup = trimmedMessage ? `<p>${escapeHtml(trimmedMessage)}</p>` : '';
    return `${attachmentMarkup}${messageMarkup}`;
}

function addMessageToRilonoAiChat(message, isUser = false, options = {}) {
    const messagesContainers = getMainChatContainers();
    if (messagesContainers.length === 0) return;

    const attachmentIds = Array.isArray(options.attachmentIds) ? options.attachmentIds : [];
    messagesContainers.forEach((messagesContainer) => {
        const messageDiv = document.createElement('div');
        messageDiv.className = `rilono-ai-message ${isUser ? 'user' : 'assistant'}`;

        if (isUser) {
            const userBubbleHtml = buildRilonoAiUserBubbleHtml(message, attachmentIds);
            messageDiv.innerHTML = `
                <div class="message-avatar">${currentUser?.full_name?.charAt(0) || currentUser?.username?.charAt(0) || 'U'}</div>
                <div class="message-bubble">
                    ${userBubbleHtml}
                </div>
            `;
        } else {
            // Use markdown parser for AI responses
            messageDiv.innerHTML = `
                <div class="message-avatar"><svg viewBox="0 0 24 24" width="18" height="18" class="ai-sparkle"><use href="#icon-ai-sparkle"></use></svg></div>
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
            <div class="message-avatar"><svg viewBox="0 0 24 24" width="18" height="18" class="ai-sparkle"><use href="#icon-ai-sparkle"></use></svg></div>
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
let rilonoAiSessionAttachments = [];
let rilonoAiAttachmentRegistry = new Map();
const RILONO_AI_MAX_SESSION_ATTACHMENTS = 8;
const RILONO_AI_MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024;
const RILONO_AI_MAX_TOTAL_ATTACHMENT_BYTES = 20 * 1024 * 1024;
const RILONO_AI_SUPPORTED_ATTACHMENT_MIME_TYPES = new Set([
    'application/pdf',
    'application/json',
    'application/csv',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/rtf',
    'text/rtf',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/plain',
    'text/markdown',
    'text/csv'
]);
const RILONO_AI_SUPPORTED_ATTACHMENT_EXTENSIONS = new Set([
    'png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'heic', 'heif',
    'pdf', 'txt', 'md', 'csv', 'json', 'doc', 'docx', 'rtf', 'xls', 'xlsx'
]);

function getRilonoAiAttachmentInputs() {
    return Array.from(document.querySelectorAll('.rilono-ai-attachment-input[data-rilono-attachment-input="true"]'));
}

function getRilonoAiAttachmentSessionContainers() {
    return Array.from(document.querySelectorAll('.rilono-ai-attachment-session[data-rilono-attachment-session="true"]'));
}

function getRilonoAiAttachmentTotalBytes() {
    return rilonoAiSessionAttachments.reduce((total, attachment) => total + (attachment.size_bytes || 0), 0);
}

function formatRilonoAiAttachmentSize(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return '0 KB';
    if (bytes >= 1024 * 1024) {
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function getRilonoAiFileExtension(filename) {
    const parts = String(filename || '').toLowerCase().split('.');
    return parts.length > 1 ? parts.pop() : '';
}

function inferRilonoAiMimeType(file) {
    const rawType = String(file?.type || '').trim().toLowerCase();
    if (rawType) {
        return rawType;
    }
    const extension = getRilonoAiFileExtension(file?.name || '');
    const extensionToMime = {
        pdf: 'application/pdf',
        txt: 'text/plain',
        md: 'text/markdown',
        csv: 'text/csv',
        json: 'application/json',
        doc: 'application/msword',
        docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        rtf: 'application/rtf',
        xls: 'application/vnd.ms-excel',
        xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        png: 'image/png',
        jpg: 'image/jpeg',
        jpeg: 'image/jpeg',
        webp: 'image/webp',
        gif: 'image/gif',
        bmp: 'image/bmp',
        heic: 'image/heic',
        heif: 'image/heif'
    };
    return extensionToMime[extension] || 'application/octet-stream';
}

function isRilonoAiAttachmentSupported(file, mimeType) {
    if (!file) return false;
    if (String(mimeType || '').startsWith('image/')) return true;
    if (RILONO_AI_SUPPORTED_ATTACHMENT_MIME_TYPES.has(mimeType)) return true;
    const extension = getRilonoAiFileExtension(file.name || '');
    return RILONO_AI_SUPPORTED_ATTACHMENT_EXTENSIONS.has(extension);
}

function createRilonoAiAttachmentId() {
    const timestamp = Date.now().toString(36);
    const random = Math.random().toString(36).slice(2, 9);
    return `att_${timestamp}_${random}`;
}

function readFileAsBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
            const result = String(reader.result || '');
            const base64Index = result.indexOf(',');
            if (base64Index === -1) {
                reject(new Error('Invalid file encoding'));
                return;
            }
            resolve(result.slice(base64Index + 1));
        };
        reader.onerror = () => reject(new Error('Failed to read file'));
        reader.readAsDataURL(file);
    });
}

async function addFilesToRilonoAiSession(files, source = 'upload') {
    const pendingFiles = Array.isArray(files) ? files.filter(Boolean) : [];
    if (pendingFiles.length === 0) return;

    const acceptedAttachments = [];
    let totalBytes = getRilonoAiAttachmentTotalBytes();

    for (const file of pendingFiles) {
        if (rilonoAiSessionAttachments.length + acceptedAttachments.length >= RILONO_AI_MAX_SESSION_ATTACHMENTS) {
            showMessage(`You can attach up to ${RILONO_AI_MAX_SESSION_ATTACHMENTS} files per chat session.`, 'error');
            break;
        }

        const mimeType = inferRilonoAiMimeType(file);
        if (!isRilonoAiAttachmentSupported(file, mimeType)) {
            showMessage(`Unsupported file type: ${file.name || 'attachment'}`, 'error');
            continue;
        }

        if ((file.size || 0) > RILONO_AI_MAX_ATTACHMENT_BYTES) {
            showMessage(`"${file.name || 'Attachment'}" is too large (max ${formatRilonoAiAttachmentSize(RILONO_AI_MAX_ATTACHMENT_BYTES)}).`, 'error');
            continue;
        }

        if (totalBytes + (file.size || 0) > RILONO_AI_MAX_TOTAL_ATTACHMENT_BYTES) {
            showMessage(`Total attached size cannot exceed ${formatRilonoAiAttachmentSize(RILONO_AI_MAX_TOTAL_ATTACHMENT_BYTES)}.`, 'error');
            break;
        }

        const duplicate = rilonoAiSessionAttachments.some((attachment) => (
            attachment.name === (file.name || '')
            && attachment.size_bytes === (file.size || 0)
            && attachment.mime_type === mimeType
        )) || acceptedAttachments.some((attachment) => (
            attachment.name === (file.name || '')
            && attachment.size_bytes === (file.size || 0)
            && attachment.mime_type === mimeType
        ));
        if (duplicate) {
            continue;
        }

        try {
            const base64Content = await readFileAsBase64(file);
            const fallbackExtension = mimeType.startsWith('image/') ? mimeType.split('/')[1] || 'png' : 'bin';
            const normalizedName = (file.name || `attachment-${Date.now()}.${fallbackExtension}`).trim().slice(0, 200);
            acceptedAttachments.push({
                id: createRilonoAiAttachmentId(),
                name: normalizedName || `attachment-${Date.now()}`,
                mime_type: mimeType,
                size_bytes: file.size || 0,
                content_base64: base64Content,
                source
            });
            totalBytes += (file.size || 0);
        } catch (error) {
            console.error('Failed to read attachment:', error);
            showMessage(`Failed to process "${file.name || 'attachment'}". Please try again.`, 'error');
        }
    }

    if (acceptedAttachments.length > 0) {
        registerRilonoAiAttachmentBatch(acceptedAttachments);
        rilonoAiSessionAttachments = rilonoAiSessionAttachments.concat(acceptedAttachments);
        renderRilonoAiSessionAttachments();
        const verb = source === 'paste' ? 'Pasted' : 'Attached';
        showMessage(`${verb} ${acceptedAttachments.length} file${acceptedAttachments.length === 1 ? '' : 's'} to this chat session.`, 'success');
    }
}

function removeRilonoAiSessionAttachment(attachmentId) {
    const beforeCount = rilonoAiSessionAttachments.length;
    rilonoAiSessionAttachments = rilonoAiSessionAttachments.filter((attachment) => attachment.id !== attachmentId);
    if (rilonoAiSessionAttachments.length !== beforeCount) {
        renderRilonoAiSessionAttachments();
    }
}

function clearRilonoAiSessionAttachments(showToast = true) {
    if (rilonoAiSessionAttachments.length === 0) {
        renderRilonoAiSessionAttachments();
        return;
    }
    rilonoAiSessionAttachments = [];
    renderRilonoAiSessionAttachments();
    if (showToast) {
        showMessage('Removed all chat session attachments.', 'success');
    }
}

function renderRilonoAiSessionAttachments() {
    const containers = getRilonoAiAttachmentSessionContainers();
    if (containers.length === 0) return;

    if (rilonoAiSessionAttachments.length === 0) {
        containers.forEach((container) => {
            container.classList.remove('has-items');
            container.innerHTML = '';
        });
        return;
    }

    const totalBytesLabel = formatRilonoAiAttachmentSize(getRilonoAiAttachmentTotalBytes());
    const chipsHtml = rilonoAiSessionAttachments.map((attachment) => `
        <span class="rilono-ai-attachment-chip" title="${escapeHtml(attachment.name)}">
            <span class="rilono-ai-attachment-chip-name">${escapeHtml(attachment.name)}</span>
            <button type="button" class="rilono-ai-attachment-chip-remove"
                onclick="removeRilonoAiSessionAttachment('${attachment.id}')" aria-label="Remove ${escapeHtml(attachment.name)}">×</button>
        </span>
    `).join('');

    const content = `
        <div class="rilono-ai-attachment-header">
            <div class="rilono-ai-attachment-meta">${rilonoAiSessionAttachments.length} attached • ${totalBytesLabel} • Session only</div>
            <button type="button" class="rilono-ai-attachment-clear" onclick="clearRilonoAiSessionAttachments(true)">Clear all</button>
        </div>
        <div class="rilono-ai-attachment-list">${chipsHtml}</div>
    `;

    containers.forEach((container) => {
        container.classList.add('has-items');
        container.innerHTML = content;
    });
}

function initializeRilonoAiAttachmentInputs() {
    const inputs = getRilonoAiAttachmentInputs();
    inputs.forEach((input) => {
        if (input.dataset.boundAttachmentInput === '1') return;
        input.dataset.boundAttachmentInput = '1';
        input.addEventListener('change', async (event) => {
            const selectedFiles = Array.from(event.target.files || []);
            event.target.value = '';
            await addFilesToRilonoAiSession(selectedFiles, 'upload');
        });
    });
}

function handleRilonoAiInputPaste(event) {
    const clipboardItems = Array.from(event.clipboardData?.items || []);
    const fileItems = clipboardItems.filter((item) => item.kind === 'file');
    if (fileItems.length === 0) {
        return;
    }

    const files = fileItems.map((item, index) => {
        const rawFile = item.getAsFile();
        if (!rawFile) return null;
        if (rawFile.name) return rawFile;
        const mimeType = inferRilonoAiMimeType(rawFile);
        const extension = mimeType.startsWith('image/') ? (mimeType.split('/')[1] || 'png') : 'bin';
        return new File(
            [rawFile],
            `pasted-file-${Date.now()}-${index + 1}.${extension}`,
            { type: mimeType, lastModified: Date.now() }
        );
    }).filter(Boolean);

    if (files.length > 0) {
        event.preventDefault();
        void addFilesToRilonoAiSession(files, 'paste');
    }
}

function initializeRilonoAiPasteHandlers() {
    const textareas = Array.from(document.querySelectorAll('.rilono-ai-input'));
    const floatingInput = document.getElementById('floatingChatInput');
    if (floatingInput) {
        textareas.push(floatingInput);
    }

    textareas.forEach((textarea) => {
        if (!textarea || textarea.dataset.boundAttachmentPaste === '1') return;
        textarea.dataset.boundAttachmentPaste = '1';
        textarea.addEventListener('paste', handleRilonoAiInputPaste);
    });
}

function initializeRilonoAiAttachmentUi() {
    initializeRilonoAiAttachmentInputs();
    initializeRilonoAiPasteHandlers();
    renderRilonoAiSessionAttachments();
}

function dequeueRilonoAiSessionAttachmentsForSend() {
    if (rilonoAiSessionAttachments.length === 0) {
        return [];
    }
    const attachmentsToSend = rilonoAiSessionAttachments.map((attachment) => ({ ...attachment }));
    rilonoAiSessionAttachments = [];
    renderRilonoAiSessionAttachments();
    return attachmentsToSend;
}

function restoreRilonoAiSessionAttachments(attachments = []) {
    if (!Array.isArray(attachments) || attachments.length === 0) {
        return;
    }
    const existingById = new Map();
    rilonoAiSessionAttachments.forEach((attachment) => {
        const id = String(attachment?.id || '').trim();
        if (id) existingById.set(id, attachment);
    });
    attachments.forEach((attachment) => {
        const id = String(attachment?.id || '').trim();
        if (id && existingById.has(id)) return;
        rilonoAiSessionAttachments.push(attachment);
    });
    renderRilonoAiSessionAttachments();
}

function getRilonoAiMessageAttachmentIdsFromList(attachments = []) {
    const seen = new Set();
    const ids = [];
    (Array.isArray(attachments) ? attachments : []).forEach((attachment) => {
        const attachmentId = String(attachment?.id || '').trim();
        if (!attachmentId || seen.has(attachmentId)) return;
        seen.add(attachmentId);
        ids.push(attachmentId);
    });
    return ids;
}

// Cached extracted text from the user's END-TO-END-ENCRYPTED documents, decrypted in the
// browser. Only populated when the vault is unlocked this session; the AI otherwise sees
// metadata only. Rebuilt lazily and marked dirty after each new E2E upload.
let rilonoE2EDocContextCache = '';
let rilonoE2EContextDirty = true;
function markE2EChatContextDirty() { rilonoE2EContextDirty = true; }

async function ensureE2EChatContext() {
    // Never force a passphrase prompt just to chat: if the vault is locked, share nothing.
    if (typeof RilonoE2E === 'undefined' || !RilonoE2E.isUnlocked()) {
        rilonoE2EDocContextCache = '';
        return '';
    }
    if (!rilonoE2EContextDirty) return rilonoE2EDocContextCache;
    try {
        const master = RilonoE2E.getMaster();
        if (!master) { rilonoE2EDocContextCache = ''; return ''; }
        const docs = await fetch(`${API_BASE}/api/documents/my-documents`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        }).then(r => r.ok ? r.json() : []);
        const e2eDocs = (docs || []).filter(d => d.e2e_scheme && d.is_processed);
        const parts = [];
        for (const d of e2eDocs) {
            try {
                const res = await fetch(`${API_BASE}/api/documents/${d.id}/extracted-blob`, {
                    headers: { 'Authorization': `Bearer ${authToken}` }
                });
                if (!res.ok) continue;
                const wdek = res.headers.get('X-E2E-Wrapped-Dek');
                if (!wdek) continue;
                const ct = new Uint8Array(await res.arrayBuffer());
                const plain = await E2E.decryptBlob(ct, wdek, master);
                const text = new TextDecoder().decode(plain);
                parts.push(`Document: ${d.original_filename || 'document'} (${d.document_type || ''})\n${text}`);
            } catch (_) { /* skip any doc that fails to decrypt */ }
        }
        rilonoE2EDocContextCache = parts.join('\n\n---\n\n').slice(0, 60000);
        rilonoE2EContextDirty = false;
    } catch (_) {
        rilonoE2EDocContextCache = '';
    }
    return rilonoE2EDocContextCache;
}

function getRilonoAiChatRequestPayload(message, attachmentsOverride = null) {
    const attachmentsToSend = Array.isArray(attachmentsOverride)
        ? attachmentsOverride
        : rilonoAiSessionAttachments;
    const payload = {
        message: message,
        conversation_history: rilonoAiConversationHistory.slice(-200),
        source: 'rilono_ai_chat'
    };

    if (rilonoE2EDocContextCache) {
        payload.e2e_document_context = rilonoE2EDocContextCache;
    }

    if (attachmentsToSend.length > 0) {
        payload.session_attachments = attachmentsToSend.map((attachment) => ({
            id: attachment.id,
            name: attachment.name,
            mime_type: attachment.mime_type,
            size_bytes: attachment.size_bytes,
            content_base64: attachment.content_base64
        }));
    }

    return payload;
}

async function handleRilonoAiChatSubmit(e) {
    const form = getRilonoAiChatFormFromEvent(e);
    if (!form) return;
    e.preventDefault();
    const input = form ? form.querySelector('.rilono-ai-input') : null;
    if (!input) return;
    const message = input.value.trim();

    if (!message) return;

    if (!authToken) {
        showMessage('Please login to chat with Rilono AI', 'error');
        return;
    }

    const attachmentsForSend = dequeueRilonoAiSessionAttachmentsForSend();
    const sentAttachmentIds = getRilonoAiMessageAttachmentIdsFromList(attachmentsForSend);

    // Add user message to both chats
    addMessageToRilonoAiChat(message, true, { attachmentIds: sentAttachmentIds });
    addMessageToFloatingChat(message, true, { attachmentIds: sentAttachmentIds });

    // Add to shared conversation history
    rilonoAiConversationHistory.push({
        role: 'user',
        content: message,
        attachment_ids: sentAttachmentIds
    });

    input.value = '';
    autoResizeRilonoAiInput(input);

    // Show typing indicator
    showRilonoAiTypingIndicator();

    try {
        // Share decrypted E2E-document context if the vault is unlocked (metadata-only otherwise).
        await ensureE2EChatContext();
        // Call the AI chat API
        const response = await aiFetch(`${API_BASE}/api/ai-chat/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify(getRilonoAiChatRequestPayload(message, attachmentsForSend))
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

            // Keep only last 200 messages in history
            if (rilonoAiConversationHistory.length > 200) {
                rilonoAiConversationHistory = rilonoAiConversationHistory.slice(-200);
            }

            // Add to both chats
            addMessageToRilonoAiChat(aiResponse, false);
            addMessageToFloatingChat(aiResponse, false);
            void loadSubscriptionStatus(true);
        } else {
            const errorData = await response.json().catch(() => ({}));
            const errorMsg = extractErrorDetailText(errorData.detail) || 'Failed to get response from Rilono AI';
            restoreRilonoAiSessionAttachments(attachmentsForSend);
            maybeShowPlanLimitPopup(response.status, errorMsg);
            addMessageToRilonoAiChat(getRilonoAiPublicErrorMessage(response.status, errorMsg), false);
            if (response.status === 403) {
                void loadSubscriptionStatus(true);
            }
        }
    } catch (error) {
        restoreRilonoAiSessionAttachments(attachmentsForSend);
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
✅ Study-abroad application guidance
✅ Profile completion tracking
✅ Answering questions about your uploaded documents
✅ General visa process information

You can ask me about:
• What documents you need
• Your profile completion status
• Visa application steps
• Document requirements
• Any other questions about your study-abroad journey

What would you like to know?`;
    } else {
        return `I understand you're asking about "${userMessage}". 

I'm here to help with your study-abroad documentation and application process. I can assist with:
• Document requirements and checklists
• Profile completion status
• Study-abroad application guidance
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
    initializeRilonoAiAttachmentUi();
    // Sync messages from shared history
    syncMainChatFromHistory();
}

// Floating Chat Widget Functions
let floatingChatOpen = false;
// Note: floatingChatConversationHistory removed - using shared rilonoAiConversationHistory instead

function updateRilonoExpandButton(widgetId, expanded) {
    const buttons = document.querySelectorAll(`.rilono-ai-expand-btn[data-expand-target="${widgetId}"]`);
    buttons.forEach((button) => {
        button.classList.toggle('is-expanded', expanded);
        button.textContent = expanded ? '↙ Exit Full View' : '⤢ Full View';
        button.title = expanded ? 'Exit Full View' : 'Full View';
        button.setAttribute('aria-pressed', expanded ? 'true' : 'false');
    });
}

function updateFloatingExpandButton(expanded) {
    const button = document.getElementById('floatingChatExpandBtn');
    if (!button) return;
    button.classList.toggle('is-expanded', expanded);
    button.textContent = expanded ? '↙' : '⤢';
    button.title = expanded ? 'Exit Full View' : 'Full View';
    button.setAttribute('aria-pressed', expanded ? 'true' : 'false');
}

function syncChatExpandBackdrop() {
    const backdrop = document.getElementById('chatExpandBackdrop');
    const hasExpandedView = Boolean(expandedChatWidgetId || floatingChatExpanded);
    if (backdrop) {
        // Keep backdrop disabled to avoid stacking-context glitches over expanded chat.
        backdrop.style.display = 'none';
        backdrop.classList.remove('visible');
    }
    document.body.classList.toggle('chat-expanded-lock', hasExpandedView);
}

function mountExpandedChatWidget(widget) {
    if (!widget || expandedChatPlaceholder) return;
    expandedChatOriginalParent = widget.parentElement;
    expandedChatPlaceholder = document.createComment('expanded-chat-placeholder');
    if (expandedChatOriginalParent) {
        expandedChatOriginalParent.insertBefore(expandedChatPlaceholder, widget);
    }
    document.body.appendChild(widget);
}

function restoreExpandedChatWidget(widget) {
    if (!widget) return;
    if (expandedChatPlaceholder && expandedChatPlaceholder.parentNode) {
        expandedChatPlaceholder.parentNode.insertBefore(widget, expandedChatPlaceholder);
        expandedChatPlaceholder.remove();
    } else if (expandedChatOriginalParent) {
        expandedChatOriginalParent.appendChild(widget);
    }
    expandedChatPlaceholder = null;
    expandedChatOriginalParent = null;
}

function closeExpandedChatView() {
    if (expandedChatWidgetId) {
        const expandedWidget = document.getElementById(expandedChatWidgetId);
        if (expandedWidget) {
            expandedWidget.classList.remove('chat-expanded');
            restoreExpandedChatWidget(expandedWidget);
        }
        updateRilonoExpandButton(expandedChatWidgetId, false);
        expandedChatWidgetId = null;
    }

    if (floatingChatExpanded) {
        const floatingChatWindow = document.getElementById('floatingChatWindow');
        if (floatingChatWindow) {
            floatingChatWindow.classList.remove('chat-expanded');
        }
        floatingChatExpanded = false;
        updateFloatingExpandButton(false);
    }

    syncChatExpandBackdrop();
}

function toggleRilonoAiExpand(widgetId) {
    const widget = document.getElementById(widgetId);
    if (!widget) return;

    const shouldExpand = expandedChatWidgetId !== widgetId;

    if (expandedChatWidgetId && expandedChatWidgetId !== widgetId) {
        const previous = document.getElementById(expandedChatWidgetId);
        if (previous) {
            previous.classList.remove('chat-expanded');
            restoreExpandedChatWidget(previous);
        }
        updateRilonoExpandButton(expandedChatWidgetId, false);
        expandedChatWidgetId = null;
    }

    if (shouldExpand) {
        if (floatingChatExpanded) {
            const floatingChatWindow = document.getElementById('floatingChatWindow');
            if (floatingChatWindow) {
                floatingChatWindow.classList.remove('chat-expanded');
            }
            floatingChatExpanded = false;
            updateFloatingExpandButton(false);
        }

        mountExpandedChatWidget(widget);
        widget.classList.add('chat-expanded');
        expandedChatWidgetId = widgetId;
        updateRilonoExpandButton(widgetId, true);

        const messages = widget.querySelector('.rilono-ai-messages');
        if (messages) {
            messages.scrollTop = messages.scrollHeight;
        }

        const input = widget.querySelector('.rilono-ai-input');
        setTimeout(() => input?.focus(), 60);
    } else {
        widget.classList.remove('chat-expanded');
        restoreExpandedChatWidget(widget);
        expandedChatWidgetId = null;
        updateRilonoExpandButton(widgetId, false);
    }

    syncChatExpandBackdrop();
}

function toggleFloatingChatExpand() {
    const chatWindow = document.getElementById('floatingChatWindow');
    if (!chatWindow || chatWindow.style.display === 'none') return;

    const shouldExpand = !floatingChatExpanded;

    if (shouldExpand) {
        if (expandedChatWidgetId) {
            const previous = document.getElementById(expandedChatWidgetId);
            if (previous) {
                previous.classList.remove('chat-expanded');
            }
            updateRilonoExpandButton(expandedChatWidgetId, false);
            expandedChatWidgetId = null;
        }

        chatWindow.classList.add('chat-expanded');
        floatingChatExpanded = true;

        const messages = document.getElementById('floatingChatMessages');
        if (messages) {
            messages.scrollTop = messages.scrollHeight;
        }
        setTimeout(() => document.getElementById('floatingChatInput')?.focus(), 60);
    } else {
        chatWindow.classList.remove('chat-expanded');
        floatingChatExpanded = false;
    }

    updateFloatingExpandButton(floatingChatExpanded);
    syncChatExpandBackdrop();
}

function toggleFloatingChat() {
    const widget = document.getElementById('floatingAiChatWidget');
    const chatWindow = document.getElementById('floatingChatWindow');
    const chatToggle = document.getElementById('floatingChatToggle');
    const messagesContainer = document.getElementById('floatingChatMessages');

    // Toggle the state
    floatingChatOpen = !floatingChatOpen;

    // Dismiss popup if open
    if (window.closeFloatingChatPopup) {
        window.closeFloatingChatPopup();
    }

    // If closing, hide window and show toggle button
    if (!floatingChatOpen) {
        closeExpandedChatView();
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
        updateFloatingExpandButton(false);
        initializeRilonoAiAttachmentUi();
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

    // Always render intro as pinned first message.
    messagesContainer.innerHTML = getFloatingChatWelcomeMarkup();

    // Rebuild messages from shared history
    for (const msg of rilonoAiConversationHistory) {
        addMessageToFloatingChat(
            msg.content,
            msg.role === 'user',
            { attachmentIds: msg.attachment_ids || [] }
        );
    }

    scrollFloatingChatToBottom();
}

// Sync main Rilono AI chat UI from shared conversation history
function syncMainChatFromHistory() {
    const messagesContainers = getMainChatContainers();
    if (messagesContainers.length === 0) return;

    messagesContainers.forEach((messagesContainer) => {
        // Keep intro pinned as first message in every main chat panel.
        messagesContainer.innerHTML = getMainChatWelcomeMarkup();
    });

    // Rebuild messages from shared history in all main chat panels
    for (const msg of rilonoAiConversationHistory) {
        addMessageToRilonoAiChat(
            msg.content,
            msg.role === 'user',
            { attachmentIds: msg.attachment_ids || [] }
        );
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

function addMessageToFloatingChat(message, isUser = false, options = {}) {
    const messagesContainer = document.getElementById('floatingChatMessages');
    if (!messagesContainer) return;  // Guard: container might not exist

    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message ${isUser ? 'user' : 'assistant'}`;
    const attachmentIds = Array.isArray(options.attachmentIds) ? options.attachmentIds : [];

    if (!isUser) {
        const avatar = document.createElement('div');
        avatar.className = 'chat-avatar';
        avatar.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" class="ai-sparkle"><use href="#icon-ai-sparkle"></use></svg>';
        messageDiv.appendChild(avatar);
    }

    const bubble = document.createElement('div');
    bubble.className = 'chat-message-bubble';

    if (isUser) {
        // User messages: text + sent-attachment preview block (if any)
        bubble.innerHTML = buildRilonoAiUserBubbleHtml(message, attachmentIds);
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

    const attachmentsForSend = dequeueRilonoAiSessionAttachmentsForSend();
    const sentAttachmentIds = getRilonoAiMessageAttachmentIdsFromList(attachmentsForSend);

    // Add user message to both chats
    addMessageToFloatingChat(message, true, { attachmentIds: sentAttachmentIds });
    addMessageToRilonoAiChat(message, true, { attachmentIds: sentAttachmentIds });

    // Add to shared conversation history
    rilonoAiConversationHistory.push({
        role: 'user',
        content: message,
        attachment_ids: sentAttachmentIds
    });

    input.value = '';
    autoResizeFloatingChatInput(input);

    // Show typing indicator
    showFloatingChatTyping();

    try {
        // Share decrypted E2E-document context if the vault is unlocked (metadata-only otherwise).
        await ensureE2EChatContext();
        // Call the AI chat API
        const response = await aiFetch(`${API_BASE}/api/ai-chat/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify(getRilonoAiChatRequestPayload(message, attachmentsForSend))
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

            // Keep only last 200 messages in history
            if (rilonoAiConversationHistory.length > 200) {
                rilonoAiConversationHistory = rilonoAiConversationHistory.slice(-200);
            }

            // Add to both chats
            addMessageToFloatingChat(aiResponse, false);
            addMessageToRilonoAiChat(aiResponse, false);
            void loadSubscriptionStatus(true);
        } else {
            const errorData = await response.json().catch(() => ({}));
            const errorMsg = extractErrorDetailText(errorData.detail) || 'Failed to get response from Rilono AI';
            restoreRilonoAiSessionAttachments(attachmentsForSend);
            maybeShowPlanLimitPopup(response.status, errorMsg);
            addMessageToFloatingChat(getRilonoAiPublicErrorMessage(response.status, errorMsg), false);
            if (response.status === 403) {
                void loadSubscriptionStatus(true);
            }
        }
    } catch (error) {
        restoreRilonoAiSessionAttachments(attachmentsForSend);
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
        initializeRilonoAiAttachmentUi();
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

document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
        closeExpandedChatView();
    }
});

function handleGalleryKeyPress(e) {
    const modal = document.getElementById('imageGalleryModal');
    if (modal.style.display === 'none') return;

    switch (e.key) {
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

// ==============================================
// Floating Chat Popup Messages Logic
// ==============================================
const floatingChatMessages = [
    "Hey! I'm Rilono AI Assistant. Let's talk about your study-abroad journey.",
    "Need help tracking your document progress?",
    "I can validate your enrolment and financial documents instantly.",
    "Ready to practise? Let's run through your likely visa questions."
];

let popupMessageInterval;
let currentPopupIndex = 0;
let isPopupDismissed = false;
// The teaser is a gentle discovery hint, NOT a recurring interruption: show it at most a
// couple of times per session, well spaced, never over a form the user is filling, and never
// again once dismissed (persisted across reloads).
const MAX_TEASERS_PER_SESSION = 2;
let teaserShowCount = 0;

function teaserPermanentlyOff() {
    try { return localStorage.getItem('rilono_chat_teaser_off') === '1'; } catch (e) { return false; }
}
function persistTeaserOff() {
    try { localStorage.setItem('rilono_chat_teaser_off', '1'); } catch (e) { /* private mode */ }
}

function isVisaInterviewInProgress() {
    return Boolean(
        visaMockInterviewState.active
        || visaMockInterviewState.pending
        || visaMockInterviewState.listening
        || visaPrepInterviewState.active
        || visaPrepInterviewState.pending
        || visaPrepInterviewState.listening
    );
}

function hideFloatingChatPopupImmediate() {
    const popup = document.getElementById('floatingChatPopup');
    if (!popup) {
        return;
    }
    popup.classList.remove('show');
    popup.style.display = 'none';
}

function initializeFloatingChatPopup() {
    const popup = document.getElementById('floatingChatPopup');
    const toggle = document.getElementById('floatingChatToggle');
    if (!popup || !toggle) return;
    if (teaserPermanentlyOff()) return;   // dismissed before — never nag again

    // Nudge at most a couple of times, well apart (45s), first after a calmer 12s delay.
    popupMessageInterval = setInterval(rotatePopupMessage, 45000);
    setTimeout(rotatePopupMessage, 12000);
}

function rotatePopupMessage() {
    if (isPopupDismissed || isVisaInterviewInProgress()) {
        hideFloatingChatPopupImmediate();
        return;
    }

    // Stop after a couple of gentle nudges — never an endless loop.
    if (teaserShowCount >= MAX_TEASERS_PER_SESSION) {
        if (popupMessageInterval) { clearInterval(popupMessageInterval); popupMessageInterval = null; }
        return;
    }

    // Never pop over a form the user is actively filling (e.g. the "Get recommendations" or
    // "Submit" inputs) — that's the intrusive click-blocking case. Retry on the next cycle.
    const active = document.activeElement;
    if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA'
                   || active.tagName === 'SELECT' || active.isContentEditable)) {
        return;
    }

    // Don't show if the chat widget itself isn't fully visible or if the chat window is already open
    const widget = document.getElementById('floatingAiChatWidget');
    const windowEl = document.getElementById('floatingChatWindow');
    if (!widget || !windowEl || widget.style.display === 'none' || windowEl.style.display !== 'none') {
        return;
    }

    const popup = document.getElementById('floatingChatPopup');
    const messageEl = document.getElementById('popupMessageText');
    if (!popup || !messageEl) return;

    // Hide current message smoothly
    popup.classList.remove('show');

    setTimeout(() => {
        if (isPopupDismissed || windowEl.style.display !== 'none' || isVisaInterviewInProgress()) return;

        // Change text
        messageEl.textContent = floatingChatMessages[currentPopupIndex];

        // Show
        popup.style.display = 'flex';

        // Force reflow
        void popup.offsetWidth;

        popup.classList.add('show');
        teaserShowCount += 1;

        currentPopupIndex = (currentPopupIndex + 1) % floatingChatMessages.length;

        // Hide after 6 seconds automatically
        setTimeout(() => {
            if (popup.classList.contains('show')) {
                popup.classList.remove('show');
                setTimeout(() => {
                    if (!popup.classList.contains('show')) {
                        popup.style.display = 'none';
                    }
                }, 400); // Wait for transition
            }
        }, 6000);

    }, 400); // Wait for hide transition
}

window.closeFloatingChatPopup = function (e) {
    if (e) {
        e.stopPropagation();
    }
    isPopupDismissed = true;
    persistTeaserOff();   // remember across reloads — don't nag on the next page load
    if (popupMessageInterval) {
        clearInterval(popupMessageInterval);
        popupMessageInterval = null;
    }
    const popup = document.getElementById('floatingChatPopup');
    if (popup) {
        popup.classList.remove('show');
        setTimeout(() => {
            popup.style.display = 'none';
        }, 400);
    }
};


function scrollToChromeExtension() {
    const section = document.getElementById('chromeExtensionSection');
    const homepage = document.getElementById('homepageSection');
    if (homepage && homepage.style.display === 'none') {
        showHomepage();
    }
    if (section) {
        setTimeout(() => {
            section.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 100);
    }
}

/* ===================================================================
   "How did you hear about us?" — one-time post-signup prompt (B2C).
   Shown once on the dashboard for a signed-in student who hasn't
   answered yet. Self-contained (injects its own markup + styles).
   =================================================================== */
let __hauShown = false;
function __hauHeaders() {
    const h = { 'Content-Type': 'application/json' };
    if (typeof authToken !== 'undefined' && authToken && authToken !== COOKIE_AUTH_SENTINEL) {
        h.Authorization = `Bearer ${authToken}`;
    }
    return h;
}
async function maybeShowHeardAbout() {
    if (__hauShown) return;
    if (typeof authToken === 'undefined' || !authToken) return;
    try {
        const r = await fetch(`${API_BASE}/api/onboarding/heard-about`, { headers: __hauHeaders(), credentials: 'include' });
        if (!r.ok) return;
        const d = await r.json();
        if (d.answered) return;
        __hauShown = true;
        __renderHeardAbout(d.options || []);
    } catch (e) { /* best-effort — never block the dashboard */ }
}
function __hauEsc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[m])); }
async function __hauSend(source, detail) {
    try {
        await fetch(`${API_BASE}/api/onboarding/heard-about`, {
            method: 'POST', headers: __hauHeaders(), credentials: 'include',
            body: JSON.stringify({ source: source, detail: detail || null }),
        });
    } catch (e) { /* best-effort */ }
}
function __renderHeardAbout(options) {
    if (document.getElementById('hauOverlay')) return;
    if (!document.getElementById('hauStyle')) {
        const st = document.createElement('style');
        st.id = 'hauStyle';
        st.textContent = `
        #hauOverlay{position:fixed;inset:0;z-index:100000;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(15,23,42,.5);backdrop-filter:blur(4px);animation:hauFade .2s ease}
        @keyframes hauFade{from{opacity:0}to{opacity:1}}
        .hau-card{width:100%;max-width:440px;background:#fff;border-radius:20px;padding:28px 26px;box-shadow:0 30px 80px rgba(15,23,42,.28);font-family:inherit;animation:hauPop .28s cubic-bezier(.2,1.4,.4,1)}
        @keyframes hauPop{from{opacity:0;transform:translateY(14px) scale(.98)}to{opacity:1;transform:none}}
        .hau-emoji{font-size:34px;line-height:1}
        .hau-card h3{margin:10px 0 6px;font-size:1.35rem;font-weight:800;color:#0f172a;letter-spacing:-.02em}
        .hau-card p{margin:0 0 18px;color:#64748b;font-size:.95rem;line-height:1.5}
        .hau-card select,.hau-card input{width:100%;padding:12px 14px;border:1.5px solid #d6d9ea;border-radius:12px;font-size:15px;color:#0f172a;background:#f8fafc;outline:none;font-family:inherit}
        .hau-card select:focus,.hau-card input:focus{border-color:#6366f1;background:#fff;box-shadow:0 0 0 4px rgba(99,102,241,.14)}
        .hau-card input{margin-top:10px}
        .hau-actions{display:flex;align-items:center;gap:12px;margin-top:20px}
        .hau-submit{flex:1;border:0;cursor:pointer;padding:13px 18px;border-radius:12px;font-size:15px;font-weight:800;color:#fff;background:linear-gradient(135deg,#6366f1,#a855f7,#ec4899);box-shadow:0 10px 24px rgba(99,102,241,.34);transition:filter .15s,transform .08s}
        .hau-submit:hover{filter:brightness(1.05)} .hau-submit:active{transform:translateY(1px)} .hau-submit:disabled{opacity:.6;cursor:not-allowed}
        .hau-skip{background:none;border:0;color:#94a3b8;font-weight:700;font-size:.9rem;cursor:pointer;padding:6px}
        .hau-skip:hover{color:#475569}`;
        document.head.appendChild(st);
    }
    const opts = ['<option value="" disabled selected>Select an option…</option>']
        .concat(options.map(o => `<option value="${__hauEsc(o.id)}">${__hauEsc(o.label)}</option>`)).join('');
    const wrap = document.createElement('div');
    wrap.id = 'hauOverlay';
    wrap.innerHTML = `
      <div class="hau-card" role="dialog" aria-modal="true" aria-label="How did you hear about us">
        <div class="hau-emoji">📣</div>
        <h3>How did you hear about us?</h3>
        <p>Quick one — it helps us reach more students like you. (Optional)</p>
        <select id="hauSelect">${opts}</select>
        <input id="hauOther" type="text" maxlength="200" placeholder="Tell us a bit more…" style="display:none">
        <div class="hau-actions">
          <button id="hauSubmit" class="hau-submit" disabled>Submit</button>
          <button id="hauSkip" class="hau-skip" type="button">Skip for now</button>
        </div>
      </div>`;
    document.body.appendChild(wrap);
    const sel = wrap.querySelector('#hauSelect');
    const other = wrap.querySelector('#hauOther');
    const submit = wrap.querySelector('#hauSubmit');
    const close = () => { wrap.remove(); };
    sel.addEventListener('change', () => {
        submit.disabled = !sel.value;
        other.style.display = sel.value === 'other' ? 'block' : 'none';
    });
    submit.addEventListener('click', () => {
        if (!sel.value) return;
        __hauSend(sel.value, sel.value === 'other' ? (other.value || '').trim() : null);
        close();
        if (typeof showMessage === 'function') showMessage('Thanks for letting us know! 🙌', 'success');
    });
    wrap.querySelector('#hauSkip').addEventListener('click', () => { __hauSend('skip'); close(); });
}
