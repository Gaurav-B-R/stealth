/* ===========================================================================
   Rilono Enterprise — Study-Abroad Consultancy CRM frontend
   =========================================================================== */
(function () {
  "use strict";

  const API = "/api/enterprise";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  const state = {
    me: null,
    perms: { can_view_data: true, can_edit_data: false, can_manage_users: false },
    // Granular access control. `caps` null means "everything" (the workspace owner, whose
    // capability list comes back as ["*"]); a Set means exactly those keys. `access` is the
    // resolved role/scope payload; `branches` are the offices this member can see.
    caps: null,
    access: null,
    branches: [],
    subscription: null,
    credits: null,
    catalog: null,
    view: "dashboard",
    clients: [],
    statusCounts: {},
    filters: { status: "", category: "", country: "", q: "", branch_id: "" },
    // Monthly-only since 2026-08-02 (no annual tier is sold); kept so the /billing
    // request body stays shaped the way the server expects.
    billingCycle: "monthly",
    activeClient: null,
    cal: null,
  };

  const enterpriseTurnstile = {
    siteKey: "",
    widgets: { signup: null, login: null, forgot: null },
    loadingPromise: null,
    loadFailed: false,
  };

  const turnstileRefs = {
    signup: { wrap: "#entTurnstileSignupWrap", widget: "#entTurnstileSignup", hint: "#entTurnstileSignupHint" },
    login: { wrap: "#entTurnstileLoginWrap", widget: "#entTurnstileLogin", hint: "#entTurnstileLoginHint" },
    forgot: { wrap: "#entTurnstileForgotWrap", widget: "#entTurnstileForgot", hint: "#entTurnstileForgotHint" },
  };

  /* ---------------- utils ---------------- */
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  // Today in the READER's zone, for min/max on date pickers. Local, not toISOString(),
  // which is UTC and hands a counsellor in IST yesterday's date all evening. These are
  // picker hints only — the server bounds every date against the ORG's calendar.
  function isoToday() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  function initials(name) {
    const p = String(name || "").trim().split(/\s+/);
    return ((p[0] || "")[0] || "") + ((p[1] || "")[0] || "") || (String(name || "?")[0] || "?");
  }
  function avatarColor(seed) {
    const colors = [["#6366f1", "#8b5cf6"], ["#0ea5e9", "#22d3ee"], ["#f59e0b", "#f97316"],
      ["#10b981", "#34d399"], ["#ec4899", "#f43f5e"], ["#8b5cf6", "#6366f1"], ["#0d9488", "#14b8a6"]];
    let h = 0; for (const ch of String(seed || "x")) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return colors[h % colors.length];
  }
  const CLIENT_HERO_THEMES = Object.freeze({
    US: { key: "us", code: "US" },
    CA: { key: "ca", code: "CA" },
    UK: { key: "uk", code: "UK" },
    AU: { key: "au", code: "AU" },
    DE: { key: "de", code: "DE" },
    IE: { key: "ie", code: "IE" },
    FR: { key: "fr", code: "FR" },
    ES: { key: "es", code: "ES" },
    NL: { key: "nl", code: "NL" },
    AE: { key: "ae", code: "AE" },
    PL: { key: "pl", code: "PL" },
    NZ: { key: "nz", code: "NZ" },
    SG: { key: "sg", code: "SG" },
    IT: { key: "it", code: "IT" },
    SE: { key: "se", code: "SE" },
  });
  function clientHeroTheme(client) {
    let code = String(client.destination_country_code || client.country?.code || "").trim().toUpperCase();
    if (code === "GB") code = "UK";
    return CLIENT_HERO_THEMES[code] || { key: "intl", code: code || "INTL" };
  }
  // How prominently to surface the mock-interview feature, by destination. Whether a real
  // visa interview happens drives the emphasis — the feature is ALWAYS available (tab +
  // send flow), we only change how hard we push it:
  //   standard — US F-1: mandatory consular interview. FR: the Campus France entretien
  //              pédagogique is compulsory for every Études en France applicant — academic
  //              rather than consular, but it always happens → push it ("Recommended", CTA).
  //   possible — UK: occasional credibility interview. AE: the decisive conversation is a
  //              university admissions panel, not a visa officer. PL: the consul may summon a
  //              credibility interview — frequent from Delhi/Mumbai, never universal. NZ: no
  //              interview step exists in the INZ process, but phone/video verification hits a
  //              meaningful minority of South-Asian files. IT: the VAC visit is lodgement +
  //              prints, but DM 850/2011 Art. 4(2) lets the consulate summon a credibility
  //              colloquio → available, not badged.
  //   rare     — CA study permit (SOP is the "interview"), AU subclass 500 (Genuine Student is
  //              written), DE Type-D (embassy intake, not an adjudicating interview), IE,
  //              ES Type-D (consular, but the file decides), NL (the recognised sponsor files
  //              with the IND and no one interviews the student), SG (ICA decides the Student's
  //              Pass on the written SOLAR file; admission panels exist only at a handful of
  //              programmes, unlike AE where the panel is the universal gate), SE
  //              (Migrationsverket decides on the written file — an
  //              embassy interview is tasked only on doubted study intent) → shown as "Optional".
  // Unknown/blank codes default to "standard" (fail open — never hide the feature for a
  // destination we haven't classified). Mirrors the per-country gating already used for the
  // UK maintenance-funds card.
  const INTERVIEW_RELEVANCE = Object.freeze({
    US: "standard", UK: "possible", CA: "rare", AU: "rare", DE: "rare", IE: "rare",
    FR: "standard", ES: "rare", NL: "rare", AE: "possible",
    PL: "possible", NZ: "possible", SG: "rare", IT: "possible", SE: "rare",
  });
  function interviewRelevance(client) {
    let code = String((client && client.destination_country_code) || "").trim().toUpperCase();
    if (code === "GB") code = "UK";
    return INTERVIEW_RELEVANCE[code] || "standard";
  }
  // Parse a stored date value into a Date. A DATE-ONLY string (YYYY-MM-DD) is read as
  // LOCAL midnight, not UTC: `new Date("2026-09-15")` would otherwise be UTC midnight,
  // and toLocaleDateString() then shifts it back a day for any viewer west of UTC (all
  // US timezones) — the "Sep 14 vs 09/15" bug. Critical for visa dates (interview /
  // travel / passport expiry). Full datetimes (containing "T") stay timezone-aware.
  function parseDateValue(iso) {
    if (!iso) return null;
    const s = String(iso).trim();
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
    if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    const d = new Date(s);
    return isNaN(d) ? null : d;
  }
  function fmtDate(iso) {
    if (!iso) return "—";
    const d = parseDateValue(iso);
    if (!d) return esc(iso);
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  }
  function fmtDateTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return esc(iso);
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) +
      " · " + d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  }
  function daysUntil(iso) {
    if (!iso) return null;
    const d = parseDateValue(iso); if (!d) return null;
    return Math.ceil((d - new Date()) / 86400000);
  }

  /* ---------------- access control ----------------
     Every payload that carries the legacy `permissions` booleans also carries the resolved
     `access` object (role_key, role_label, capabilities, data_scope, branch_ids, …). The UI
     asks `can("clients.edit")` rather than reading the three coarse booleans.

     applyAccessPayload only trusts `permissions` when the SAME response also carries
     `access`. That guard matters: thin payloads (the calendar's, a client's Payments tab)
     used to overwrite state.perms wholesale, so opening the Calendar downgraded the rest of
     the session to whatever that one endpoint chose to report. */
  function applyAccessPayload(d) {
    if (!d || typeof d !== "object") return;
    const a = d.access;
    if (!a || typeof a !== "object") return;   // no access block — never touch the session
    state.access = a;
    const caps = a.capabilities;
    // ["*"] (or a missing list) = the owner: hold nothing, allow everything.
    state.caps = (!Array.isArray(caps) || caps.indexOf("*") !== -1) ? null : new Set(caps);
    if (d.permissions && typeof d.permissions === "object") state.perms = d.permissions;
    if (Array.isArray(d.branches)) state.branches = d.branches;
  }

  // Capabilities that a pre-access-control server could only have expressed through
  // can_edit_data / can_manage_users. Used ONLY as a fallback while state.access is
  // still null (an un-upgraded backend), so an old server keeps behaving exactly as it
  // does today instead of the UI unlocking every control.
  const LEGACY_EDIT_CAPS = new Set([
    "clients.create", "clients.edit", "clients.assign", "clients.set_branch", "clients.delete",
    "notes.write", "notes.moderate", "emails.send", "emails.send_bulk",
    "documents.upload", "documents.accept", "documents.delete", "documents.request",
    "universities.manage", "calendar.manage", "interviews.run", "interviews.invite", "copilot.invite",
    "portal.share", "ai.writing", "ai.deepscan", "ai.coursefinder", "ai.shortlist", "credits.spend",
  ]);
  const LEGACY_MANAGE_CAPS = new Set([
    "team.manage", "roles.manage", "branches.manage", "settings.manage", "audit.view",
    "billing.manage", "credits.purchase", "org.legal_accept", "org.transfer_ownership",
    "finance.manage", "finance.refund", "finance.payout_account", "finance.books",
    "finance.books_manage", "finance.export", "support.manage",
  ]);

  function can(cap) {
    if (state.caps) return state.caps.has(cap);
    if (state.access) return true;             // owner — capabilities came back as ["*"]
    const p = state.perms || {};
    if (LEGACY_MANAGE_CAPS.has(cap)) return !!p.can_manage_users;
    if (LEGACY_EDIT_CAPS.has(cap)) return !!p.can_edit_data;
    return p.can_view_data !== false;
  }
  function canAll() {
    for (let i = 0; i < arguments.length; i++) if (!can(arguments[i])) return false;
    return true;
  }
  function canAny() {
    for (let i = 0; i < arguments.length; i++) if (can(arguments[i])) return true;
    return arguments.length === 0;
  }
  // The one sentence shown wherever a whole panel is withheld. Never a blank page.
  function deniedCard(sentence) {
    return `<div class="card"><div class="card-body" style="color:var(--text-2);font-size:14px;line-height:1.7">
      ${esc(sentence)}</div></div>`;
  }
  // Company books cover the whole workspace, so they need workspace-wide data scope on
  // top of the capability — a branch/assigned-scoped member is refused server-side.
  function isOrgScope() {
    const s = state.access && state.access.data_scope;
    return !s || s === "all";
  }

  /* Structured error details. Some conflicts (archiving an office that still has clients,
     deactivating a member who still owns records) answer 409 with a DICT detail —
     {message, code, …counts} — which the UI needs in order to offer a reassignment
     picker. api() flattens the human sentence onto ex.message; the raw body stays on
     ex.data, so read the dict from there. */
  function errDetail(ex) {
    const d = ex && ex.data && ex.data.detail;
    return (d && typeof d === "object" && !Array.isArray(d)) ? d : null;
  }
  function errCode(ex) {
    const d = errDetail(ex);
    return (d && d.code) || "";
  }
  function errMessage(ex) {
    const d = errDetail(ex);
    return (d && d.message) || (ex && ex.message) || "Something went wrong.";
  }

  /* ---------------- phone country dial codes ---------------- */
  const PHONE_COUNTRIES = [
    { f: "🇮🇳", d: "+91", n: "India" },
    { f: "🇺🇸", d: "+1", n: "United States" },
    { f: "🇨🇦", d: "+1", n: "Canada" },
    { f: "🇬🇧", d: "+44", n: "United Kingdom" },
    { f: "🇦🇺", d: "+61", n: "Australia" },
    { f: "🇳🇿", d: "+64", n: "New Zealand" },
    { f: "🇮🇪", d: "+353", n: "Ireland" },
    { f: "🇩🇪", d: "+49", n: "Germany" },
    { f: "🇫🇷", d: "+33", n: "France" },
    { f: "🇮🇹", d: "+39", n: "Italy" },
    { f: "🇪🇸", d: "+34", n: "Spain" },
    { f: "🇵🇹", d: "+351", n: "Portugal" },
    { f: "🇳🇱", d: "+31", n: "Netherlands" },
    { f: "🇧🇪", d: "+32", n: "Belgium" },
    { f: "🇨🇭", d: "+41", n: "Switzerland" },
    { f: "🇦🇹", d: "+43", n: "Austria" },
    { f: "🇸🇪", d: "+46", n: "Sweden" },
    { f: "🇳🇴", d: "+47", n: "Norway" },
    { f: "🇩🇰", d: "+45", n: "Denmark" },
    { f: "🇫🇮", d: "+358", n: "Finland" },
    { f: "🇵🇱", d: "+48", n: "Poland" },
    { f: "🇨🇿", d: "+420", n: "Czechia" },
    { f: "🇬🇷", d: "+30", n: "Greece" },
    { f: "🇷🇺", d: "+7", n: "Russia" },
    { f: "🇺🇦", d: "+380", n: "Ukraine" },
    { f: "🇹🇷", d: "+90", n: "Turkey" },
    { f: "🇦🇪", d: "+971", n: "United Arab Emirates" },
    { f: "🇸🇦", d: "+966", n: "Saudi Arabia" },
    { f: "🇶🇦", d: "+974", n: "Qatar" },
    { f: "🇰🇼", d: "+965", n: "Kuwait" },
    { f: "🇧🇭", d: "+973", n: "Bahrain" },
    { f: "🇴🇲", d: "+968", n: "Oman" },
    { f: "🇮🇱", d: "+972", n: "Israel" },
    { f: "🇪🇬", d: "+20", n: "Egypt" },
    { f: "🇿🇦", d: "+27", n: "South Africa" },
    { f: "🇳🇬", d: "+234", n: "Nigeria" },
    { f: "🇰🇪", d: "+254", n: "Kenya" },
    { f: "🇬🇭", d: "+233", n: "Ghana" },
    { f: "🇪🇹", d: "+251", n: "Ethiopia" },
    { f: "🇹🇿", d: "+255", n: "Tanzania" },
    { f: "🇺🇬", d: "+256", n: "Uganda" },
    { f: "🇵🇰", d: "+92", n: "Pakistan" },
    { f: "🇧🇩", d: "+880", n: "Bangladesh" },
    { f: "🇱🇰", d: "+94", n: "Sri Lanka" },
    { f: "🇳🇵", d: "+977", n: "Nepal" },
    { f: "🇧🇹", d: "+975", n: "Bhutan" },
    { f: "🇲🇻", d: "+960", n: "Maldives" },
    { f: "🇨🇳", d: "+86", n: "China" },
    { f: "🇭🇰", d: "+852", n: "Hong Kong" },
    { f: "🇹🇼", d: "+886", n: "Taiwan" },
    { f: "🇯🇵", d: "+81", n: "Japan" },
    { f: "🇰🇷", d: "+82", n: "South Korea" },
    { f: "🇸🇬", d: "+65", n: "Singapore" },
    { f: "🇲🇾", d: "+60", n: "Malaysia" },
    { f: "🇮🇩", d: "+62", n: "Indonesia" },
    { f: "🇹🇭", d: "+66", n: "Thailand" },
    { f: "🇵🇭", d: "+63", n: "Philippines" },
    { f: "🇻🇳", d: "+84", n: "Vietnam" },
    { f: "🇲🇲", d: "+95", n: "Myanmar" },
    { f: "🇰🇭", d: "+855", n: "Cambodia" },
    { f: "🇧🇷", d: "+55", n: "Brazil" },
    { f: "🇲🇽", d: "+52", n: "Mexico" },
    { f: "🇦🇷", d: "+54", n: "Argentina" },
    { f: "🇨🇴", d: "+57", n: "Colombia" },
    { f: "🇨🇱", d: "+56", n: "Chile" },
    { f: "🇵🇪", d: "+51", n: "Peru" },
  ];
  const DEFAULT_DIAL = "+91";
  function phoneCcOptions(selectedDial) {
    let picked = false;
    return PHONE_COUNTRIES.map((p) => {
      const sel = !picked && p.d === selectedDial;
      if (sel) picked = true;
      return `<option value="${p.d}" title="${esc(p.n)}" ${sel ? "selected" : ""}>${p.f} ${p.d}</option>`;
    }).join("");
  }
  function splitPhone(full) {
    const s = String(full == null ? "" : full).trim();
    if (!s || s[0] !== "+") return { dial: DEFAULT_DIAL, local: s };
    const compact = s.replace(/[\s()-]/g, "");
    const dials = PHONE_COUNTRIES.map((p) => p.d).sort((a, b) => b.length - a.length);
    for (const d of dials) {
      if (compact.startsWith(d)) return { dial: d, local: compact.slice(d.length) };
    }
    return { dial: DEFAULT_DIAL, local: s };
  }

  function rootDomain() {
    const h = location.hostname;
    if (h === "localhost" || /^\d+\.\d+\.\d+\.\d+$/.test(h)) return "rilono.com";
    if (h.endsWith("lvh.me")) return "lvh.me";
    const parts = h.split(".");
    if (parts.length <= 2) return h;
    return parts.slice(-2).join(".");
  }
  /* ---- Money.  Mirrors app/money.py — read that first if you touch this. ----

     Every amount the API hands us is an INTEGER IN THE MINOR UNIT OF ITS OWN CURRENCY.
     Since we started charging in USD/GBP/EUR/… the legacy field name `amount_paise` is
     cents on a USD row, so the currency is no longer implied by the field name and has
     to travel with the number. Hence two functions and no default second argument:

       fmtMoney(minor, currency)   render in the currency it is denominated in. No FX.
       fmtDisplay(minor, currency) INR-denominated figures shown in the org's display
                                   currency (Settings → company country).

     The old fmtPaise() multiplied EVERY amount by display_currency.rate_from_inr. That
     was right only while all money was INR: a $49.99 top-up stored as 4999 came out as
     "$0.59" — no error, no NaN, just a wrong number that looks plausible. Never
     reintroduce a formatter that infers the currency. */
  const CUR_SYMBOLS = {
    INR: "₹", USD: "$", GBP: "£", EUR: "€", CAD: "CA$", AUD: "A$", AED: "AED ",
    SGD: "S$", JPY: "¥", NZD: "NZ$", CHF: "CHF ", HKD: "HK$",
  };
  // Only the currencies whose minor unit is NOT 1/100 — everything else defaults to 2.
  // Mirrors MINOR_UNIT_EXPONENT in app/money.py. JPY is display-only (never charged),
  // but ¥999 is stored as 999, so a blanket /100 would render it as ¥9.99.
  const CUR_EXPONENTS = {
    JPY: 0, KRW: 0, VND: 0, ISK: 0, CLP: 0, XAF: 0, XOF: 0, XPF: 0,
    KWD: 3, BHD: 3, OMR: 3, JOD: 3, TND: 3,
  };
  // Mirrors _MIN_CHARGE_MINOR in app/money.py: the smallest amount the server will create
  // a Razorpay order for, per currency. It is NOT a flat 100 — 100 minor units is ₹1 but
  // $1.00, twice the $0.50 floor the server actually applies, and AED's floor is 200 fils.
  // Anything comparing a discounted total against "can this be charged at all?" MUST use
  // this, or the modal promises a free top-up for an order the server then charges for.
  const MIN_CHARGE_MINOR = {
    INR: 100, USD: 50, GBP: 50, EUR: 50, CAD: 50, AUD: 50, AED: 200, SGD: 50,
  };
  function curCode(currency) { return String(currency || "INR").trim().toUpperCase() || "INR"; }
  function minChargeMinor(currency) {
    const m = MIN_CHARGE_MINOR[curCode(currency)];
    return m === undefined ? 100 : m;   // same fallback as money.min_charge_minor()
  }
  function curSymbol(currency) { const c = curCode(currency); return CUR_SYMBOLS[c] || c + " "; }
  function curExponent(currency) {
    const e = CUR_EXPONENTS[curCode(currency)];
    return e === undefined ? 2 : e;
  }
  function minorToMajor(minor, currency) {
    return Number(minor || 0) / Math.pow(10, curExponent(currency));
  }
  // Render an amount in the currency it is actually denominated in. Use this for
  // anything that came off a payment/order row or a server price — those carry their
  // own currency and must never be run through an exchange rate.
  function fmtMoney(minor, currency) {
    const code = curCode(currency);
    const exp = curExponent(code);
    const v = minorToMajor(minor, code);
    // Mirrors money.format_money(): whole amounts drop the decimals (₹999, not ₹999.00),
    // anything fractional shows the currency's full precision ($19.50, not $19.5). Client
    // and server must render the same amount identically — several screens fall back from
    // one to the other, and a mismatch there reads as two different prices.
    const digits = (exp === 0 || Number.isInteger(v)) ? 0 : exp;
    return curSymbol(code) + v.toLocaleString(code === "INR" ? "en-IN" : "en-US",
      { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }
  // The org's display currency, from Settings → company country. Presentation only.
  function orgCur() {
    const c = state.me && state.me.organization && state.me.organization.display_currency;
    return (c && c.code && c.code !== "INR" && Number(c.rate_from_inr) > 0) ? c : null;
  }
  // Show an amount in the org's display currency where that is actually expressible.
  // `rate_from_inr` is the only rate we hold, so INR → display is the ONLY conversion
  // available: a row already denominated in another currency is rendered as-is rather
  // than multiplied by a rate that does not apply to it.
  function fmtDisplay(minor, currency) {
    const code = curCode(currency);
    const cur = orgCur();
    if (!cur || code !== "INR") return fmtMoney(minor, code);
    const v = minorToMajor(minor, "INR") * Number(cur.rate_from_inr);
    return cur.symbol + v.toLocaleString("en-US", { maximumFractionDigits: v >= 1000 ? 0 : 2 });
  }
  // A handful of API fields are INR *major* units (plain rupees: credit_value_inr,
  // value_inr, min_fee_rupees). Explicitly INR by definition of the field, not a guess.
  function fmtInr(amountInr) {
    return fmtDisplay(Math.round(Number(amountInr || 0) * 100), "INR");
  }
  // Same fields, but where the figure must stay INR because the thing it describes is
  // INR-only (the Razorpay Route fee on student collections). No display conversion.
  function fmtInrExact(amountInr) {
    return fmtMoney(Math.round(Number(amountInr || 0) * 100), "INR");
  }
  // Razorpay Checkout prefill, straight from the server — name/email/contact of the real
  // signed-in buyer. Razorpay: "Your international payment will fail if you send us a
  // dummy email id and phone number of the customer", so blanks are DROPPED (the buyer
  // types them into Checkout) and never replaced with a placeholder.
  // https://razorpay.com/docs/payments/international-payments/?preferred-country=IN
  function checkoutPrefill(prefill) {
    const out = {};
    Object.keys(prefill || {}).forEach((k) => {
      const v = String(prefill[k] == null ? "" : prefill[k]).trim();
      if (v) out[k] = v;
    });
    return out;
  }
  // Shown under every checkout button. Replaces inrBilledNote(), which said "Billed in
  // INR" — a misrepresentation now that we really do create the order in the buyer's
  // currency. The only conversion left is the one we don't control: the buyer's own
  // card network / bank, which is what the second sentence is about.
  function chargeNote(minor, currency) {
    const code = curCode(currency);
    const cur = orgCur();
    const display = cur ? cur.code : "INR";
    // An Indian org paying in INR has nothing to disclose: domestic charge, same currency
    // the whole portal is already showing. Everyone else gets both facts that could
    // surprise them on a statement — which currency we charge, and that Rilono is an
    // Indian merchant, so their bank may treat it as a cross-border transaction.
    if (display === "INR" && code === "INR") return "";
    return `<div style="font-size:11.5px;color:var(--muted);margin-top:2px">You'll be charged
      <b>${esc(fmtMoney(minor, code))}</b> in ${esc(code)}.${display !== code
        ? ` Amounts elsewhere in this portal display in ${esc(display)}.` : ""}
      Your bank may add a foreign-transaction fee and, if it converts, uses its own rate.</div>`;
  }
  // Shared discount-code bar used on the credits top-up and billing pages.
  // `coupon` is null (show input) or { code, percent, percent_display } (show applied state).
  function couponRow(coupon, applyFn, removeFn, inputId, label) {
    if (coupon) {
      return `<div class="coupon-bar applied">
        <div class="coupon-bar-info">
          <span class="coupon-tag">🎟 ${esc(coupon.code)}</span>
          <span class="coupon-msg">${esc(coupon.percent_display)} off all ${esc(label)}</span>
        </div>
        <button class="btn btn-ghost btn-sm" onclick="__ent.${removeFn}()">Remove</button>
      </div>`;
    }
    // The Apply button carries an id so BOTH entry points — the click and the Enter key on
    // the input — resolve the same node; withBusy's already-busy early return then guards
    // the pair with one lock. Validity is synced from an inline oninput rather than
    // bindValidity because renderCredits()/renderBilling() rebuild this row wholesale on
    // every repaint, which would drop any listener attached from outside the markup.
    return `<div class="coupon-bar">
      <input id="${inputId}" class="coupon-input" placeholder="Have a discount code?" maxlength="40"
        oninput="__ent.syncCouponApply('${inputId}')"
        onkeydown="if(event.key==='Enter'){event.preventDefault();__ent.${applyFn}();}" />
      <button class="btn btn-primary btn-sm" id="${inputId}Apply" onclick="__ent.${applyFn}()" disabled title="Enter a discount code first">Apply</button>
    </div>`;
  }

  function syncCouponApply(inputId) {
    const input = $("#" + inputId), btn = $("#" + inputId + "Apply");
    if (!input || !btn || btn.dataset.busy === "1") return;
    btn.disabled = input.value.trim() === "";
    btn.title = btn.disabled ? "Enter a discount code first" : "";
  }

  function defaultApiErrorMessage(status, fallback) {
    if (fallback) return fallback;
    if (status === 401) return "Your session has expired. Please sign in again.";
    if (status === 403) return "You do not have permission to perform this action.";
    if (status === 404) return "The requested item could not be found.";
    if (status === 408 || status === 504) return "The request timed out. Please try again.";
    if (status === 429) return "Too many requests. Please wait a moment and try again.";
    if (status >= 500) return "Sorry, we encountered an error. The issue has been logged. Please try again shortly.";
    return "We couldn't complete that request. Please check the information and try again.";
  }

  function publicApiErrorMessage(status, detail, fallback) {
    const message = typeof detail === "string" ? detail.trim().replace(/\s+/g, " ") : "";
    const internalDetail = /(?:gemini|generative\s*ai|vertex\s*ai|openai|anthropic|claude|model(?:s)?\/|\bmodel\b.*(?:not\s+found|unavailable|deprecated|retired|no\s+longer\s+available)|failed\s+to\s+generate|api[_ -]?key|traceback|stack\s*trace|sqlalchemy|psycopg|postgres(?:ql)?|database\s+(?:error|exception)|internal\s+server\s+error|exception\b|\/app\/|\.py\b.*line\s+\d+)/i;
    if (!message || message.length > 300 || status >= 500 || internalDetail.test(message)) {
      return defaultApiErrorMessage(status, fallback);
    }
    return message;
  }

  function makePublicApiError(response, data, fallback) {
    const detail = data && (data.detail || data.message);
    const err = new Error(publicApiErrorMessage(response.status, detail, fallback));
    err.status = response.status;
    err.data = data;
    err.publicSafe = true;
    return err;
  }

  function publicClientError(message) {
    const err = new Error(message);
    err.publicSafe = true;
    return err;
  }

  // Default request timeout. Regular CRM calls are quick; long AI actions (Deep Scan,
  // AI assistant, mock interview) pass a longer `opts.timeout`. Without this a stalled
  // request (slow network / backend hiccup) would spin forever with no recovery.
  const DEFAULT_API_TIMEOUT_MS = 30000;
  const AI_API_TIMEOUT_MS = 90000;
  // Deep Scan reads the whole dossier (sequential per-document AI calls + a large
  // reconcile pass) — much slower than other AI actions. Aborting at 90s would hide a
  // scan the server still finishes (and bills), so it gets a far longer leash.
  const DEEP_SCAN_API_TIMEOUT_MS = 300000;
  // The Writing Studio is one long-form generation per call — slower than a chat turn,
  // far faster than a whole-dossier scan. Aborting early would hide a draft the server
  // finished (and billed), so it still gets a generous leash.
  const WRITING_API_TIMEOUT_MS = 180000;

  async function api(path, opts) {
    opts = opts || {};
    const controller = new AbortController();
    const timeoutMs = opts.timeout || DEFAULT_API_TIMEOUT_MS;
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let res;
    // A FormData body (file uploads) must go out untouched — the browser sets the multipart
    // Content-Type with its own boundary, and JSON.stringify would flatten it to "{}".
    const isForm = typeof FormData !== "undefined" && opts.body instanceof FormData;
    try {
      res = await fetch(API + path, {
        method: opts.method || "GET",
        credentials: "include",
        headers: opts.body && !isForm ? { "Content-Type": "application/json" } : {},
        body: opts.body ? (isForm ? opts.body : JSON.stringify(opts.body)) : undefined,
        signal: controller.signal,
      });
    } catch (_error) {
      if (_error && _error.name === "AbortError") {
        throw publicClientError("This is taking longer than usual. Please check your connection and try again.");
      }
      throw publicClientError("We couldn't reach Rilono. Check your connection and try again.");
    } finally {
      clearTimeout(timer);
    }
    let data = null;
    try { data = await res.json(); } catch (e) { /* no body */ }
    if (!res.ok) {
      throw makePublicApiError(res, data);
    }
    return data;
  }

  /* Download a file the API generates on the fly (the Writing Studio's .docx export).
     api() is JSON-only, so this is the binary sibling: it keeps the session cookie, turns
     a JSON error body into the same publicClientError the callers already handle, and
     honours the filename the server sent in Content-Disposition. */
  async function downloadFile(path, timeoutMs = 60000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let res;
    try {
      res = await fetch(path, { credentials: "include", signal: controller.signal });
    } catch (error) {
      if (error && error.name === "AbortError") {
        throw publicClientError("That download is taking too long. Please try again.");
      }
      throw publicClientError("We couldn't reach Rilono. Check your connection and try again.");
    } finally {
      clearTimeout(timer);
    }
    if (!res.ok) {
      let data = null;
      try { data = await res.json(); } catch (e) { /* not a JSON error body */ }
      throw makePublicApiError(res, data);
    }
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
    let name = "document";
    try { name = match ? decodeURIComponent(match[1]) : name; } catch (e) { name = match ? match[1] : name; }
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(href); a.remove(); }, 0);
  }

  async function waitForTurnstile(timeoutMs = 9000) {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      if (window.turnstile && typeof window.turnstile.render === "function") return true;
      await new Promise((resolve) => setTimeout(resolve, 120));
    }
    return false;
  }

  async function initializeEnterpriseTurnstile() {
    if (enterpriseTurnstile.loadingPromise) return enterpriseTurnstile.loadingPromise;
    enterpriseTurnstile.loadingPromise = (async () => {
      try {
        const res = await fetch("/api/auth/turnstile-site-key", { credentials: "same-origin" });
        if (!res.ok) throw new Error("Could not load security configuration.");
        const data = await res.json().catch(() => ({}));
        enterpriseTurnstile.siteKey = String(data.site_key || "").trim();

        if (!enterpriseTurnstile.siteKey) {
          Object.keys(turnstileRefs).forEach((key) => {
            const wrap = $(turnstileRefs[key].wrap);
            if (wrap) wrap.classList.add("hidden");
          });
          return false;
        }

        const available = await waitForTurnstile();
        if (!available) throw new Error("Security widget failed to load.");
        return true;
      } catch (error) {
        enterpriseTurnstile.loadFailed = true;
        console.error("Failed to initialize enterprise Turnstile:", error);
        return false;
      }
    })();
    return enterpriseTurnstile.loadingPromise;
  }

  async function renderEnterpriseTurnstile(key) {
    await initializeEnterpriseTurnstile();
    const refs = turnstileRefs[key];
    if (!refs || !enterpriseTurnstile.siteKey) return;

    const wrap = $(refs.wrap);
    const widget = $(refs.widget);
    const hint = $(refs.hint);
    if (!wrap || !widget) return;
    wrap.classList.remove("hidden");

    if (enterpriseTurnstile.loadFailed || !window.turnstile) {
      if (hint) hint.textContent = "Security widget failed to load. Refresh and try again.";
      return;
    }
    if (enterpriseTurnstile.widgets[key] !== null) return;

    try {
      enterpriseTurnstile.widgets[key] = window.turnstile.render(widget, {
        sitekey: enterpriseTurnstile.siteKey,
        theme: "light",
      });
    } catch (error) {
      enterpriseTurnstile.loadFailed = true;
      if (hint) hint.textContent = "Security widget failed to load. Refresh and try again.";
      console.error("Failed to render enterprise Turnstile:", error);
    }
  }

  async function getEnterpriseTurnstileToken(key) {
    await initializeEnterpriseTurnstile();
    if (enterpriseTurnstile.loadFailed) {
      throw publicClientError("Security check could not load. Refresh the page and try again.");
    }
    if (!enterpriseTurnstile.siteKey) return "";
    await renderEnterpriseTurnstile(key);

    const widgetId = enterpriseTurnstile.widgets[key];
    if (enterpriseTurnstile.loadFailed || !window.turnstile || widgetId === null) {
      throw publicClientError("Security check could not load. Refresh the page and try again.");
    }

    let token = "";
    try {
      token = window.turnstile.getResponse(widgetId) || "";
    } catch (error) {
      token = "";
    }
    if (!token) throw publicClientError("Please complete the security check.");
    return token;
  }

  function resetEnterpriseTurnstile(key) {
    const widgetId = enterpriseTurnstile.widgets[key];
    if (!enterpriseTurnstile.siteKey || !window.turnstile || widgetId === null) return;
    try {
      window.turnstile.reset(widgetId);
    } catch (error) {
      // no-op; the next render or page refresh will recover the widget
    }
  }

  /* ---------------- toast ---------------- */
  function toast(msg, type) {
    const el = document.createElement("div");
    el.className = "toast " + (type || "");
    el.innerHTML = (type === "success" ? "✓ " : type === "error" ? "⚠ " : "") + esc(msg);
    $("#toastWrap").appendChild(el);
    setTimeout(() => { el.style.opacity = "0"; el.style.transform = "translateY(8px)"; setTimeout(() => el.remove(), 250); }, 3400);
  }

  /* ---------------- submit guards ----------------
     Two rules for every button that writes something, in one place.

     (1) IN FLIGHT — from the click until the request settles, the button is unclickable.
         That is not decoration. A second click on "Record payment" is a second row in the
         org's books; on "✉ Send link" a second email and a second credit debited; on
         "Add client" a duplicate student. `withBusy` is the re-entrancy guard itself: it
         no-ops when the button is already busy, so a second path into the same handler
         (Enter on a field, a stray programmatic call) cannot produce a duplicate write.
         It restores on EVERY exit — success, error, early return, throw — which is the
         part hand-rolled try/finally blocks keep getting wrong.

     (2) NOT FILLED IN — a button whose required inputs are empty or invalid is disabled,
         rather than clickable-and-then-scolding. `bindValidity` keeps that in sync as the
         user edits. A dead button with no explanation is worse than the toast it replaces,
         so the reason rides along as a tooltip; pass one.

     The two compose. withBusy restores *through* the validity check rather than blindly
     setting disabled=false, so a save that fails re-enables the button only as far as the
     form currently deserves — and bindValidity stands down while a request is in flight so
     the two never fight over the same property. */

  /**
   * Disable `btn` whenever `isValid()` is false and keep it in sync as the user edits.
   *
   * `watch` is either a container (form / modal body — events are delegated, so inputs
   * that appear later, from a cascade or an async prefill, are covered) or an explicit
   * array of elements. `hint` is the tooltip shown while the button is dead.
   *
   * Returns the sync function, also parked on `btn._syncValid`. Call it after changing an
   * input from code — assigning `.value` fires no event, so nothing else will notice.
   */
  function bindValidity(btn, watch, isValid, hint) {
    if (!btn) return () => {};
    const sync = () => {
      // Never fight withBusy: while the request is in flight the button stays disabled and
      // keeps its busy label, whatever the inputs say now.
      if (btn.dataset.busy === "1") return;
      const ok = !!isValid();
      btn.disabled = !ok;
      if (hint) btn.title = ok ? "" : hint;
    };
    if (Array.isArray(watch)) {
      watch.filter(Boolean).forEach((el) => { el.addEventListener("input", sync); el.addEventListener("change", sync); });
    } else if (watch) {
      // Delegated: `input` and `change` both bubble, so one pair of listeners on the
      // container covers every field it will ever hold.
      watch.addEventListener("input", sync);
      watch.addEventListener("change", sync);
    }
    btn._syncValid = sync;
    sync();
    return sync;
  }

  /**
   * Run `fn()` with `btn` locked and showing `busyLabel`, restoring it however `fn` ends.
   *
   * Returns `fn`'s result, or undefined when the button was already busy — that early
   * return IS the duplicate-submit guard, so handlers can simply `await withBusy(...)`
   * without their own flag. Pass "" for a spinner with no words.
   *
   * If `fn` navigates away or closes the modal, the button has left the DOM by the time we
   * restore, and we leave it alone.
   */
  async function withBusy(btn, busyLabel, fn) {
    if (!btn) return fn();
    if (btn.dataset.busy === "1" || btn.disabled) return undefined;
    const html = btn.innerHTML;
    const minWidth = btn.style.minWidth;
    const title = btn.title;
    // Pin the current width so swapping in "⟳ Saving…" doesn't make the button (and the
    // footer row it sits in) jump around mid-request.
    const w = btn.getBoundingClientRect().width;
    if (w) btn.style.minWidth = Math.ceil(w) + "px";
    // The white spinner only reads on a solid gradient; on the soft/ghost/danger fills it
    // would be invisible, so those get the dark one.
    const spin = btn.classList.contains("btn-primary") || btn.dataset.spin === "light" ? "spinner" : "spinner dark";
    btn.dataset.busy = "1";
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    btn.title = "";
    btn.innerHTML = `<span class="${spin}"></span>${busyLabel ? " " + esc(busyLabel) : ""}`;
    try {
      return await fn();
    } finally {
      delete btn.dataset.busy;
      btn.removeAttribute("aria-busy");
      if (btn.isConnected) {
        btn.innerHTML = html;
        btn.style.minWidth = minWidth;
        btn.title = title;
        // Back through the validity gate, not straight to enabled: if the form is still
        // half-filled the button has no business being clickable again.
        if (btn._syncValid) btn._syncValid(); else btn.disabled = false;
      }
    }
  }

  /** True when every one of `els` has a non-blank value. The usual `isValid` for a form. */
  function allFilled(els) {
    return els.filter(Boolean).every((el) => String(el.value || "").trim() !== "");
  }

  /* ---------------- overlay / modal / drawer ---------------- */
  // #modal is a single reused node and closeModal() only strips .show — so the class list
  // is rebuilt on every open. A size modifier can never leak into the next modal.
  function openModal(html, opts) {
    const m = $("#modal");
    m.className = "modal" + (opts && opts.wide ? " modal-wide" : "");
    m.innerHTML = html;
    $("#overlay").classList.add("show"); m.classList.add("show");
  }
  function closeModal() {
    $("#modal").classList.remove("show");
    if (!$("#drawer").classList.contains("show")) $("#overlay").classList.remove("show");
  }
  function openDrawer(html) {
    const d = $("#drawer"); d.innerHTML = html;
    $("#overlay").classList.add("show"); d.classList.add("show");
  }
  function closeDrawer() {
    $("#drawer").classList.remove("show");
    if (!$("#modal").classList.contains("show")) $("#overlay").classList.remove("show");
    state.activeClient = null;
  }
  $("#overlay").addEventListener("click", () => { closeModal(); closeDrawer(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeModal(); closeDrawer(); } });

  /* ---------------- in-app confirm / prompt (replace native window.confirm/prompt) ----------------
     Promise-based styled dialogs so we never show the ugly "acme.lvh.me says" browser popup.
     confirmModal(msg, opts) -> Promise<boolean>;  promptModal(msg, opts) -> Promise<string|null>. */
  function confirmModal(message, opts) {
    opts = opts || {};
    var title = opts.title || "Please confirm";
    var okText = opts.okText || "Confirm";
    var cancelText = opts.cancelText || "Cancel";
    var danger = opts.danger !== false; // default to destructive styling (most uses are deletes)
    return new Promise(function (resolve) {
      var settled = false;
      function finish(val) {
        if (settled) return; settled = true;
        document.removeEventListener("keydown", onKey, true);
        $("#overlay").removeEventListener("click", onOverlay);
        closeModal();
        resolve(val);
      }
      function onKey(e) { if (e.key === "Escape") { e.stopPropagation(); finish(false); } }
      function onOverlay(e) { if (e.target === $("#overlay")) finish(false); }
      openModal(
        '<div class="modal-head"><h3>' + esc(title) + '</h3><button class="x" id="cfmClose" aria-label="Close">×</button></div>' +
        '<div class="modal-body"><p style="margin:0;color:var(--text-2);font-size:14px;line-height:1.65">' + esc(message).replace(/\n/g, "<br>") + '</p></div>' +
        '<div class="modal-foot"><button type="button" class="btn btn-ghost" id="cfmCancel">' + esc(cancelText) + '</button>' +
        '<button type="button" class="btn ' + (danger ? "btn-danger" : "btn-primary") + '" id="cfmOk">' + esc(okText) + '</button></div>'
      );
      $("#cfmClose").onclick = function () { finish(false); };
      $("#cfmCancel").onclick = function () { finish(false); };
      $("#cfmOk").onclick = function () { finish(true); };
      document.addEventListener("keydown", onKey, true);
      $("#overlay").addEventListener("click", onOverlay);
      var ok = $("#cfmOk"); if (ok) ok.focus();
    });
  }
  function promptModal(message, opts) {
    opts = opts || {};
    var title = opts.title || "Enter a value";
    var okText = opts.okText || "OK";
    var placeholder = opts.placeholder || "";
    var value = opts.value || "";
    var inputType = opts.type || "text";
    return new Promise(function (resolve) {
      var settled = false;
      function finish(val) {
        if (settled) return; settled = true;
        document.removeEventListener("keydown", onKey, true);
        $("#overlay").removeEventListener("click", onOverlay);
        closeModal();
        resolve(val);
      }
      function onKey(e) { if (e.key === "Escape") { e.stopPropagation(); finish(null); } }
      function onOverlay(e) { if (e.target === $("#overlay")) finish(null); }
      openModal(
        '<div class="modal-head"><h3>' + esc(title) + '</h3><button class="x" id="pmClose" aria-label="Close">×</button></div>' +
        '<form id="pmForm"><div class="modal-body">' +
        '<p style="margin:0 0 12px;color:var(--text-2);font-size:14px;line-height:1.6">' + esc(message) + '</p>' +
        '<input id="pmInput" type="' + esc(inputType) + '" class="select-mini" style="width:100%" placeholder="' + esc(placeholder) + '" value="' + esc(value) + '"></div>' +
        '<div class="modal-foot"><button type="button" class="btn btn-ghost" id="pmCancel">Cancel</button>' +
        '<button type="submit" class="btn btn-primary" id="pmOk">' + esc(okText) + '</button></div></form>'
      );
      $("#pmClose").onclick = function () { finish(null); };
      $("#pmCancel").onclick = function () { finish(null); };
      $("#pmForm").onsubmit = function (e) { e.preventDefault(); finish($("#pmInput").value); };
      document.addEventListener("keydown", onKey, true);
      $("#overlay").addEventListener("click", onOverlay);
      var inp = $("#pmInput"); if (inp) inp.focus();
    });
  }

  /* ---------------- info tip (ⓘ) ----------------
     Explanatory copy that would otherwise crowd a card lives behind a small ⓘ: hover or
     keyboard-focus reveals it, click/tap pins it open, Esc or an outside click closes it.
     The bubble renders into ONE body-level layer rather than beside the icon because some
     hosts clip their own overflow (.deep-scan-card) and would cut an in-flow popover off.
     `html` is trusted markup (interpolate user values through esc() before passing). */
  function infoTip(html, label) {
    return `<button type="button" class="info-tip" aria-expanded="false" aria-label="${
      esc(label || "More information")}" data-tip="${esc(html)}">i</button>`;
  }
  const tipState = { el: null, owner: null, pinned: false, wired: false };
  function infoTipLayer() {
    if (!tipState.el) {
      const el = document.createElement("div");
      el.className = "info-tip-pop";
      el.id = "infoTipPop";
      el.setAttribute("role", "tooltip");
      document.body.appendChild(el);
      tipState.el = el;
    }
    return tipState.el;
  }
  function hideInfoTip() {
    if (tipState.owner) tipState.owner.setAttribute("aria-expanded", "false");
    tipState.owner = null;
    tipState.pinned = false;
    if (tipState.el) tipState.el.classList.remove("show");
  }
  function showInfoTip(btn, pinned) {
    const el = infoTipLayer();
    if (tipState.owner !== btn) {
      if (tipState.owner) tipState.owner.setAttribute("aria-expanded", "false");
      el.innerHTML = btn.dataset.tip || "";
      tipState.owner = btn;
      tipState.pinned = false;
      btn.setAttribute("aria-expanded", "true");
    }
    if (pinned) tipState.pinned = true;
    el.classList.add("show");
    positionInfoTip();
  }
  // The layer is position:fixed and only ever hidden with opacity/visibility, so it always
  // has real measurements here. Clamp it inside the viewport, flip above the icon when
  // there's no room below, and re-aim the arrow at the icon after any clamping.
  function positionInfoTip() {
    const btn = tipState.owner, el = tipState.el;
    if (!btn || !el) return;
    const r = btn.getBoundingClientRect();
    const gap = 10, edge = 10;
    const w = el.offsetWidth, h = el.offsetHeight;
    const roomBelow = window.innerHeight - r.bottom;
    const flip = roomBelow < h + gap + edge && r.top > roomBelow;
    const top = flip ? r.top - gap - h : r.bottom + gap;
    const left = Math.max(edge, Math.min(r.left + r.width / 2 - w / 2, window.innerWidth - w - edge));
    el.classList.toggle("flip", flip);
    el.style.left = Math.round(left) + "px";
    el.style.top = Math.round(top) + "px";
    // Keep the arrow off the bubble's rounded corners when the icon sits at a screen edge.
    const arrow = Math.min(Math.max(r.left + r.width / 2 - left, 15), w - 15);
    el.style.setProperty("--tip-arrow", Math.round(arrow) + "px");
  }
  function wireInfoTips() {
    if (tipState.wired) return;
    tipState.wired = true;
    const tipBtn = (e) => (e.target instanceof Element ? e.target.closest(".info-tip") : null);
    const inTip = (e) => (e.target instanceof Element ? e.target.closest("#infoTipPop") : null);
    document.addEventListener("pointerover", (e) => {
      // A re-render (scan finished, status changed) can replace the icon underneath an
      // open tip — drop the orphan rather than leave a bubble pointing at nothing.
      if (tipState.owner && !tipState.owner.isConnected) hideInfoTip();
      const btn = tipBtn(e);
      if (btn) { if (!tipState.pinned || tipState.owner === btn) showInfoTip(btn, false); return; }
      if (tipState.owner && !tipState.pinned && !inTip(e)) hideInfoTip();
    });
    document.addEventListener("pointerleave", () => { if (!tipState.pinned) hideInfoTip(); });
    document.addEventListener("focusin", (e) => { const btn = tipBtn(e); if (btn) showInfoTip(btn, false); });
    document.addEventListener("focusout", (e) => {
      if (tipBtn(e) && tipBtn(e) === tipState.owner && !tipState.pinned) hideInfoTip();
    });
    // Capture phase: the icon can sit inside a clickable row (a history row, a card), and
    // opening its explanation must not also trigger that row's action.
    document.addEventListener("click", (e) => {
      const btn = tipBtn(e);
      if (btn) {
        e.preventDefault();
        e.stopPropagation();
        if (tipState.owner === btn && tipState.pinned) hideInfoTip();
        else showInfoTip(btn, true);
        return;
      }
      if (inTip(e)) return;
      if (tipState.owner) hideInfoTip();
    }, true);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && tipState.owner) hideInfoTip(); });
    window.addEventListener("scroll", () => { if (tipState.owner) hideInfoTip(); }, true);
    window.addEventListener("resize", () => { if (tipState.owner) hideInfoTip(); });
  }

  /* ---------------- landmark photo ---------------- */
  // Real bundled landmark photo per country. The parent .country-art carries a
  // gradient background, so if an image is ever missing it degrades gracefully.
  const DESTINATION_PHOTO_CODES = new Set(["ae", "au", "ca", "de", "es", "fr", "ie", "it", "nl", "nz", "pl", "se", "sg", "uk", "us"]);
  function landmarkArt(country) {
    const code = String(country.code || "").toLowerCase();
    const base = DESTINATION_PHOTO_CODES.has(code) ? "/static/destinations" : "/static/assets/enterprise/client-banners";
    return `<img class="lk-img" src="${base}/${esc(code)}.jpg" alt="${esc(country.landmark || country.name || "")}" loading="lazy" onerror="this.style.display='none'">`;
  }

  /* ---------------- catalog lookups ---------------- */
  function countryByCode(code) {
    if (!state.catalog) return null;
    return state.catalog.countries.find((c) => c.code === code) || null;
  }
  function stageByKey(key) {
    if (!state.catalog) return { key, label: key, color: "#94a3b8" };
    return state.catalog.stages.find((s) => s.key === key) || { key, label: key, color: "#94a3b8" };
  }
  // Stage keys/colors are org-wide (kanban columns, filter chips, analytics all share them),
  // but what a stage is CALLED — and, for a few destinations, where it sits in the order —
  // depends on the destination: a UAE case's "submitted" is "Entry Permit Filed", not
  // "Application Submitted", and the Netherlands decides before biometrics. Anything scoped
  // to ONE client uses this; anything spanning the whole pipeline keeps state.catalog.stages.
  function stagesForClient(client) {
    const all = (state.catalog && state.catalog.stages) || [];
    let code = String((client && (client.destination_country_code || (client.country && client.country.code))) || "").trim().toUpperCase();
    if (code === "GB") code = "UK";
    const byCountry = (state.catalog && state.catalog.stages_by_country) || {};
    return (code && byCountry[code]) || all;
  }
  function priorityColor(key) {
    const map = { low: "#94a3b8", normal: "#6366f1", high: "#f97316", urgent: "#ef4444" };
    return map[key] || "#6366f1";
  }

  function statusPill(stage) {
    const c = stage.color || "#94a3b8";
    return `<span class="status-pill" style="background:${c}1f;color:${c}"><span class="sd" style="background:${c}"></span>${esc(stage.label)}</span>`;
  }

  /* ============================================================
     AUTH
     ============================================================ */
  function setupAuth() {
    const suffix = "." + rootDomain();
    $("#signupDomainSuffix").textContent = suffix;
    $("#onboardDomainSuffix").textContent = suffix;
    initializeEnterpriseTurnstile();
    // Login is the default card, so its security widget is the one to pre-render.
    renderEnterpriseTurnstile("login");

    $("#toLogin").onclick = () => showLoginCard();
    $("#toSignup").onclick = () => showSignupCard();

    const forgot = $("#entForgot");
    if (forgot) forgot.onclick = (e) => { e.preventDefault(); showForgotCard(); };
    const back = $("#backToLogin");
    if (back) back.onclick = () => showLoginCard();

    $("#forgotForm").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target; const btn = $("#forgotBtn");
      const err = $("#forgotError"); const ok = $("#forgotSuccess");
      err.classList.add("hidden"); ok.classList.add("hidden");
      const email = (f.email.value || "").trim();
      try {
        // Locked BEFORE the Turnstile await, not after: that await can span a fetch of the
        // site key on a cold page, and every click landing in that window was its own
        // password-reset email.
        btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Sending…';
        const turnstileToken = await getEnterpriseTurnstileToken("forgot");
        const payload = { email };
        if (turnstileToken) payload.cf_turnstile_token = turnstileToken;
        const res = await fetch("/api/auth/forgot-password", {
          method: "POST", credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => null);
        if (!res.ok) throw makePublicApiError(res, data, "We couldn't process the password reset request. Please try again.");
        ok.innerHTML = "If an account exists for <b>" + esc(email) + "</b> and email can be delivered, a password reset link should arrive shortly. Check your inbox and spam folder.";
        ok.classList.remove("hidden");
        f.reset();
        resetEnterpriseTurnstile("forgot");
      } catch (ex) {
        err.textContent = ex && ex.publicSafe
          ? ex.message
          : "Sorry, we encountered an error. Please try again shortly.";
        err.classList.remove("hidden");
        resetEnterpriseTurnstile("forgot");
      } finally { btn.disabled = false; btn.textContent = "Send reset link"; }
    };

    // Two-step signup: (1) validate the form + email a 6-digit code, (2) verify the
    // code and only then create the workspace. Form data is held here in between.
    let pendingSignup = null;

    async function requestSignupCode(email, errEl, btn, busyLabel, idleLabel) {
      // Shared by "Create my workspace" and "Resend code". The guard matters most for Resend:
      // it sits on a card the user is already staring at waiting for a slow email, so
      // double-tapping is the natural human response — and /signup/send-code allows only 6
      // per hour, so a few stray taps lock a prospect out of signing up entirely.
      if (btn.disabled) return false;
      errEl.classList.add("hidden");
      try {
        const body = { email };
        // Locked before the Turnstile await, which can span a site-key fetch on a cold page.
        btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> ' + busyLabel;
        const turnstileToken = await getEnterpriseTurnstileToken("signup");
        if (turnstileToken) body.cf_turnstile_token = turnstileToken;
        const data = await api("/signup/send-code", { method: "POST", body });
        showSignupVerifyCard(email);
        if (data && data.dev_code) $("#signupVerifyForm").code.value = data.dev_code; // local sandbox only
        return true;
      } catch (ex) {
        errEl.textContent = ex.message; errEl.classList.remove("hidden");
        resetEnterpriseTurnstile("signup");
        return false;
      } finally { btn.disabled = false; btn.textContent = idleLabel; }
    }

    $("#signupForm").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target; const btn = $("#signupBtn");
      const err = $("#signupError"); err.classList.add("hidden");
      if (!f.accept_terms.checked) {
        err.textContent = "Please accept the Terms & Conditions and Privacy Policy to continue.";
        err.classList.remove("hidden");
        return;
      }
      if (!f.accept_dpa.checked) {
        err.textContent = "Please accept the Data Processing Agreement to manage your clients' data.";
        err.classList.remove("hidden");
        return;
      }
      pendingSignup = {
        company_name: f.company_name.value.trim(),
        subdomain_slug: f.subdomain_slug.value.trim().toLowerCase(),
        full_name: f.full_name.value.trim(),
        email: f.email.value.trim(),
        password: f.password.value,
        accepted_terms_privacy: f.accept_terms.checked,
        accepted_dpa: f.accept_dpa.checked,
        marketing_emails_consent: f.marketing_consent.checked,
      };
      // `required` blocks an EMPTY field but accepts "   ". Catch that before spending one
      // of the six-per-hour code sends on a request the server will refuse anyway.
      if (!pendingSignup.company_name || !pendingSignup.full_name || !pendingSignup.subdomain_slug) {
        err.textContent = "Please fill in your company name, your name and a portal URL.";
        err.classList.remove("hidden");
        return;
      }
      await requestSignupCode(pendingSignup.email, err, btn, "Sending code…", "Create my workspace");
    };

    $("#signupVerifyForm").onsubmit = async (e) => {
      e.preventDefault();
      const btn = $("#signupVerifyBtn");
      const err = $("#signupVerifyError"); err.classList.add("hidden");
      if (!pendingSignup) { showSignupCard(); return; }
      const body = Object.assign({}, pendingSignup, { email_otp: e.target.code.value.trim() });
      try {
        btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Creating…';
        const data = await api("/signup", { method: "POST", body });
        pendingSignup = null;
        if (redirectToPortalIfNeeded(data)) return;
        await boot({ fromAuthAction: true });
      } catch (ex) {
        err.textContent = ex.message; err.classList.remove("hidden");
      } finally { btn.disabled = false; btn.textContent = "Verify & create workspace"; }
    };

    $("#signupResendBtn").onclick = async () => {
      if (!pendingSignup) { showSignupCard(); return; }
      const ok = await requestSignupCode(
        pendingSignup.email, $("#signupVerifyError"), $("#signupResendBtn"), "Sending…", "Resend code",
      );
      if (ok) {
        const err = $("#signupVerifyError");
        err.textContent = "A fresh code is on its way — check your inbox.";
        err.classList.remove("hidden");
      }
    };

    $("#signupVerifyBack").onclick = () => { showSignupCard(); };

    $("#loginForm").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target; const btn = $("#loginBtn");
      const err = $("#loginError"); err.classList.add("hidden");
      // A portal redirect leaves this page entirely, so re-enabling the button on the way
      // out just flashes a live "Sign in" over a page that is already navigating away.
      let navigating = false;
      try {
        const body = { email: f.email.value.trim(), password: f.password.value };
        // Locked before the Turnstile await — see #forgotForm above. Duplicate logins burn
        // the enterprise.login rate-limit bucket and can lock the user out of their own
        // workspace for the window.
        btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Signing in…';
        const turnstileToken = await getEnterpriseTurnstileToken("login");
        if (turnstileToken) body.cf_turnstile_token = turnstileToken;
        const data = await api("/login", { method: "POST", body });
        if (data.onboarding_required) { showOnboard(); return; }
        if (redirectToPortalIfNeeded(data)) { navigating = true; return; }
        await boot({ fromAuthAction: true });
        // Confirm only once boot actually landed in the workspace — it can bounce back to the
        // auth screen (cookie/permission problems), which surfaces its own error instead.
        if ($("#appView").classList.contains("active")) toast("Login successful — welcome back!", "success");
      } catch (ex) {
        showLoginError(ex.message);
        resetEnterpriseTurnstile("login");
      } finally { if (!navigating) { btn.disabled = false; btn.textContent = "Sign in"; } }
    };

    $("#onboardForm").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target; const btn = $("#onboardBtn");
      const err = $("#onboardError"); err.classList.add("hidden");
      const company = f.company_name.value.trim();
      const slug = f.subdomain_slug.value.trim().toLowerCase();
      // `required` stops an EMPTY field but happily accepts "   ", which the server then
      // rejects — answer that here rather than spending a round trip on it.
      if (!company || !slug) {
        err.textContent = "Enter your company name and a portal URL.";
        err.classList.remove("hidden");
        (company ? f.subdomain_slug : f.company_name).focus();
        return;
      }
      btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Finishing…';
      try {
        await api("/onboarding", { method: "POST", body: { company_name: company, subdomain_slug: slug } });
        await boot({ fromAuthAction: true });
      } catch (ex) {
        err.textContent = ex.message; err.classList.remove("hidden");
      } finally { btn.disabled = false; btn.textContent = "Finish setup"; }
    };
  }
  function showSignupCard() {
    $("#loginCard").classList.add("hidden");
    $("#forgotCard").classList.add("hidden");
    $("#signupVerifyCard").classList.add("hidden");
    $("#signupCard").classList.remove("hidden");
    renderEnterpriseTurnstile("signup");
  }
  function showLoginCard() {
    $("#signupCard").classList.add("hidden");
    $("#forgotCard").classList.add("hidden");
    $("#signupVerifyCard").classList.add("hidden");
    $("#loginCard").classList.remove("hidden");
    renderEnterpriseTurnstile("login");
  }
  function showSignupVerifyCard(email) {
    $("#signupCard").classList.add("hidden");
    $("#loginCard").classList.add("hidden");
    $("#forgotCard").classList.add("hidden");
    $("#signupVerifyError").classList.add("hidden");
    $("#signupVerifyEmail").textContent = email;
    $("#signupVerifyForm").code.value = "";
    $("#signupVerifyCard").classList.remove("hidden");
    try { $("#signupVerifyForm").code.focus(); } catch (e) { /* noop */ }
  }
  function showForgotCard() {
    const em = ($("#loginForm").email.value || "").trim();
    if (em) $("#forgotForm").email.value = em;
    $("#loginCard").classList.add("hidden");
    $("#signupCard").classList.add("hidden");
    $("#signupVerifyCard").classList.add("hidden");
    $("#forgotError").classList.add("hidden");
    $("#forgotSuccess").classList.add("hidden");
    $("#forgotCard").classList.remove("hidden");
    renderEnterpriseTurnstile("forgot");
  }
  function showLoginError(message) {
    showLoginCard();
    const err = $("#loginError");
    err.textContent = message || "Unable to sign in. Please try again.";
    err.classList.remove("hidden");
  }
  function portalUrlFrom(data) {
    return String((data && data.portal_url) || (data && data.organization && data.organization.portal_url) || "").trim();
  }
  function redirectToPortalIfNeeded(data) {
    const portalUrl = portalUrlFrom(data);
    if (!portalUrl) return false;
    let target;
    try { target = new URL(portalUrl, location.href); } catch (e) { return false; }
    if (target.origin === location.origin) return false;
    // Signing in on the marketing origin hops to the org's own portal subdomain, which would
    // discard an in-page toast. Carry the confirmation across (consumed by consumeSignedInFlag).
    target.searchParams.set("signed_in", "1");
    window.location.assign(target.toString());
    return true;
  }

  // Reads the post-redirect "you just signed in" flag exactly once, stripping it from the URL
  // so a refresh never replays the confirmation.
  function consumeSignedInFlag() {
    try {
      const params = new URLSearchParams(location.search);
      if (!params.get("signed_in")) return false;
      params.delete("signed_in");
      const qs = params.toString();
      history.replaceState({}, "", location.pathname + (qs ? `?${qs}` : "") + (location.hash || ""));
      return true;
    } catch (e) { return false; }
  }
  function showAuth() { $("#authView").classList.remove("hidden"); $("#onboardView").classList.add("hidden"); $("#appView").classList.remove("active"); }
  function showOnboard() { $("#authView").classList.add("hidden"); $("#onboardView").classList.remove("hidden"); $("#appView").classList.remove("active"); }
  function showApp() { $("#authView").classList.add("hidden"); $("#onboardView").classList.add("hidden"); $("#appView").classList.add("active"); }

  /* ---------------- sign out ---------------- */
  $("#signoutBtn").onclick = async () => {
    const ok = await confirmModal("Do you want to sign out of your Rilono Enterprise workspace?", {
      title: "Sign out",
      okText: "Sign out",
      cancelText: "Stay signed in",
      danger: false,
    });
    if (!ok) return;
    try { await fetch("/api/auth/logout", { method: "POST", credentials: "include" }); } catch (e) {}
    location.reload();
  };

  /* ============================================================
     BOOT
     ============================================================ */
  // "How did you hear about us?" — one-time post-signup prompt (B2B), shown once for
  // an enterprise user who hasn't answered. Self-contained (injects markup + styles).
  let _hauShown = false;
  async function maybeShowEntHeardAbout(me) {
    if (_hauShown || !me || !me.user || me.user.heard_about_answered) return;
    try {
      const d = await api("/heard-about");
      if (!d || d.answered) return;
      _hauShown = true;
      renderEntHeardAbout(d.options || []);
    } catch (e) { /* best-effort */ }
  }
  function renderEntHeardAbout(options) {
    if (document.getElementById("hauOverlay")) return;
    if (!document.getElementById("hauStyle")) {
      const st = document.createElement("style");
      st.id = "hauStyle";
      st.textContent = `
      #hauOverlay{position:fixed;inset:0;z-index:100000;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(15,23,42,.5);backdrop-filter:blur(4px)}
      .hau-card{width:100%;max-width:440px;background:#fff;border-radius:20px;padding:28px 26px;box-shadow:0 30px 80px rgba(15,23,42,.28);animation:hauPop .28s cubic-bezier(.2,1.4,.4,1)}
      @keyframes hauPop{from{opacity:0;transform:translateY(14px) scale(.98)}to{opacity:1;transform:none}}
      .hau-card .em{font-size:34px}
      .hau-card h3{margin:10px 0 6px;font-size:1.35rem;font-weight:800;color:#0f172a;letter-spacing:-.02em}
      .hau-card p{margin:0 0 18px;color:#64748b;font-size:.95rem;line-height:1.5}
      .hau-card select,.hau-card input{width:100%;padding:12px 14px;border:1.5px solid #d6d9ea;border-radius:12px;font-size:15px;color:#0f172a;background:#f8fafc;outline:none}
      .hau-card select:focus,.hau-card input:focus{border-color:#6366f1;background:#fff;box-shadow:0 0 0 4px rgba(99,102,241,.14)}
      .hau-card input{margin-top:10px}
      .hau-actions{display:flex;align-items:center;gap:12px;margin-top:20px}
      .hau-submit{flex:1;border:0;cursor:pointer;padding:13px 18px;border-radius:12px;font-size:15px;font-weight:800;color:#fff;background:linear-gradient(135deg,#6366f1,#a855f7,#ec4899);box-shadow:0 10px 24px rgba(99,102,241,.34)}
      .hau-submit:hover{filter:brightness(1.05)} .hau-submit:disabled{opacity:.6;cursor:not-allowed}
      .hau-skip{background:none;border:0;color:#94a3b8;font-weight:700;font-size:.9rem;cursor:pointer;padding:6px}`;
      document.head.appendChild(st);
    }
    const opts = ['<option value="" disabled selected>Select an option…</option>']
      .concat(options.map((o) => `<option value="${esc(o.id)}">${esc(o.label)}</option>`)).join("");
    const wrap = document.createElement("div");
    wrap.id = "hauOverlay";
    wrap.innerHTML = `
      <div class="hau-card" role="dialog" aria-modal="true">
        <div class="em">📣</div>
        <h3>How did you hear about us?</h3>
        <p>Quick one — it helps us support more consultancies like yours. (Optional)</p>
        <select id="hauSelect">${opts}</select>
        <input id="hauOther" type="text" maxlength="200" placeholder="Tell us a bit more…" style="display:none">
        <div class="hau-actions">
          <button id="hauSubmit" class="hau-submit" disabled>Submit</button>
          <button id="hauSkip" class="hau-skip" type="button">Skip for now</button>
        </div>
      </div>`;
    document.body.appendChild(wrap);
    const sel = wrap.querySelector("#hauSelect");
    const other = wrap.querySelector("#hauOther");
    const submit = wrap.querySelector("#hauSubmit");
    const send = (source, detail) => { api("/heard-about", { method: "POST", body: { source: source, detail: detail || null } }).catch(() => {}); };
    const close = () => wrap.remove();
    sel.addEventListener("change", () => { submit.disabled = !sel.value; other.style.display = sel.value === "other" ? "block" : "none"; });
    submit.addEventListener("click", () => { if (!sel.value) return; send(sel.value, sel.value === "other" ? (other.value || "").trim() : null); close(); toast("Thanks for letting us know! 🙌", "success"); });
    wrap.querySelector("#hauSkip").addEventListener("click", () => { send("skip"); close(); });
  }

  async function boot(opts) {
    opts = opts || {};
    showApp();
    $("#content").innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
    let me;
    try { me = await api("/me"); }
    catch (ex) {
      if (ex.status === 401) {
        showAuth();
        if (opts.fromAuthAction) {
          showLoginError("Sign-in succeeded, but your browser did not keep the session cookie. Check the enterprise domain/HTTPS cookie settings and try again.");
        }
        return;
      }
      if (ex.status === 403) {
        showAuth();
        if (opts.fromAuthAction) showLoginError(ex.message || "Access restricted");
        else toast(ex.message || "Access restricted", "error");
        return;
      }
      $("#content").innerHTML = `<div class="empty"><div class="emoji">⚠️</div><h3>Something went wrong</h3><p>${esc(ex.message)}</p></div>`;
      return;
    }
    if (me.onboarding_required) { showOnboard(); return; }
    // A different member signed in without a page reload (logout → login) — their AI
    // assistant threads are private, so the previous member's transcript, thread id and
    // cached history list must not survive into this session.
    if (state.me && state.me.user && me.user && state.me.user.id !== me.user.id) {
      state.aiHistory = []; state.aiConvId = null; state.aiConvs = null; state.aiMeter = null;
    }
    state.me = me;
    state.perms = me.permissions || state.perms;
    applyAccessPayload(me);
    state.subscription = me.subscription || null;
    state.credits = me.credits || null;

    // brand + user chip
    const org = me.organization || {};
    $("#brandName").textContent = org.company_name || "Your Consultancy";
    if (org.logo_url) { const l = $("#brandLogo"); l.src = org.logo_url; l.style.display = ""; }
    const u = me.user || {};
    $("#userName").textContent = u.full_name || u.email || "User";
    // The resolved role label ("Branch manager", a custom role's name) — not the coarse
    // legacy role mirror, which reads "Editor" for everyone who can touch a client.
    $("#userRole").textContent = (state.access && state.access.role_label) ||
      ((me.membership && me.membership.role) || "member").replace(/^\w/, (c) => c.toUpperCase());
    const [c1] = avatarColor(u.email);
    $("#userAvatar").textContent = (initials(u.full_name || u.email) || "U").toUpperCase();
    $("#userAvatar").style.background = `linear-gradient(135deg, ${c1}, ${avatarColor(u.email)[1]})`;
    updatePlanChip();
    renderDpaBanner();
    maybeShowEntHeardAbout(me);

    if (!can("clients.create")) $("#topAddClient").classList.add("hidden");
    applyNavCapabilities();

    try { state.catalog = await api("/catalog"); } catch (e) { state.catalog = { countries: [], categories: [], stages: [], priorities: [] }; }

    // Restore the view from the URL (deep-link / refresh / bookmark), replacing the
    // history entry so we don't add a spurious one on first load.
    applyRoute(location.pathname, { replace: true });
    refreshCalendarBadge();  // keep the overdue-reminder badge correct without needing to open Calendar
    wireNotifications();
    refreshNotifications();  // bell badge correct from first paint
    initAiDock();            // bottom-right assistant bubble — mounts on its own, don't block boot
  }

  function updatePlanChip() {
    const s = state.subscription;
    const cr = state.credits;
    // The chip leads with the TIER (that is the subscription the org is on) and adds the
    // live credit balance when we have it, so one glance answers both "what am I paying
    // for" and "can I run another AI action".
    if (s && s.plan_label) {
      const bal = cr && cr.balance_credits != null ? ` · ${cr.balance_credits} cr` : "";
      $("#brandPlan").textContent = s.plan_label + bal;
    } else if (cr && cr.balance_credits != null) {
      $("#brandPlan").textContent = cr.balance_credits + " credits";
    } else {
      $("#brandPlan").textContent = "Rilono Credits";
    }
    if (s && s.clients_used != null) $("#clientsBadge").textContent = s.clients_used;
    const cb = $("#creditsBadge");
    if (cb && cr && cr.balance_credits != null) cb.textContent = cr.balance_credits;
  }

  // Sidebar "Calendar" badge = count of overdue + upcoming reminders. Set here so it's correct
  // on first dashboard load (previously it was only updated inside renderCalendar, so a fresh
  // load showed a stale "0" until you opened the Calendar tab — hiding overdue follow-ups).
  function setCalendarBadge(n) {
    const cb = $("#calendarBadge");
    if (!cb) return;
    n = Number(n) || 0;
    cb.textContent = n;
    cb.style.display = n > 0 ? "" : "none";   // hide at 0 instead of showing a misleading "0"
  }
  async function refreshCalendarBadge() {
    try {
      const up = await api("/calendar/upcoming?days=21");
      setCalendarBadge((up.overdue || []).length + (up.upcoming || []).length);
    } catch (e) { /* best-effort; leave the badge unchanged on error */ }
  }

  /* ============================================================
     NOTIFICATIONS (topbar bell)
     ============================================================ */
  const notifState = { items: [], unread: 0, open: false, timer: null, wired: false };
  const NOTIF_ICONS = {
    client_added: "👤", status_changed: "🔀", interview_completed: "🎤",
    docs_submitted: "📁", member_added: "👥", member_removed: "👥", credits_low: "💳",
    client_email_reply: "✉️",
    // Access-control events. Only types with a committed emitter are listed — an icon for
    // a notification nothing ever sends is dead weight that reads as a missing feature.
    member_role_changed: "🔀", member_access_changed: "🔐",
    branch_created: "🏢", ownership_transferred: "👑",
    lead_received: "🎯",
  };

  function notifAgo(iso) {
    if (!iso) return "";
    const then = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").getTime();
    const s = Math.max(0, Math.floor((Date.now() - then) / 1000));
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + "m ago";
    if (s < 86400) return Math.floor(s / 3600) + "h ago";
    if (s < 7 * 86400) return Math.floor(s / 86400) + "d ago";
    return new Date(then).toLocaleDateString();
  }

  function setNotifBadge(n) {
    const b = $("#notifBadge");
    if (!b) return;
    notifState.unread = Number(n) || 0;
    b.textContent = notifState.unread > 99 ? "99+" : notifState.unread;
    b.style.display = notifState.unread > 0 ? "flex" : "none";
  }

  async function refreshNotifications() {
    try {
      const data = await api("/notifications?limit=30");
      notifState.items = data.notifications || [];
      setNotifBadge(data.unread_count || 0);
      if (notifState.open) renderNotifList();
    } catch (e) { /* best-effort */ }
  }

  function renderNotifList() {
    const list = $("#notifList");
    if (!list) return;
    if (!notifState.items.length) {
      list.innerHTML = '<div class="notif-empty">Nothing yet — team activity, completed mock interviews and document submissions will show up here.</div>';
      return;
    }
    list.innerHTML = notifState.items.map((n) => `
      <div class="notif-item ${n.is_read ? "" : "unread"}" data-nid="${n.id}" data-rt="${esc(n.reference_type || "")}" data-rid="${n.reference_id || ""}">
        <div class="notif-ic">${NOTIF_ICONS[n.type] || "🔔"}</div>
        <div style="flex:1;min-width:0">
          <div class="notif-title">${esc(n.title)}</div>
          ${n.body ? `<div class="notif-body">${esc(n.body)}</div>` : ""}
          <div class="notif-time">${esc(notifAgo(n.created_at))}</div>
        </div>
        ${n.is_read ? "" : '<span class="notif-dot"></span>'}
      </div>`).join("");
    $$(".notif-item", list).forEach((el) => {
      el.onclick = () => {
        const rt = el.dataset.rt, rid = parseInt(el.dataset.rid || "0", 10);
        closeNotifPanel();
        if (rt === "client" && rid) openClient(rid);
        else if (rt === "lead") navigate("leads");
        else if (rt === "credits") navigate("credits");
        else if (rt === "branch") teamGoTab("branches");
        else if (rt === "team") navigate("team");
      };
    });
  }

  function closeNotifPanel() {
    notifState.open = false;
    const p = $("#notifPanel"); if (p) p.classList.add("hidden");
    const btn = $("#notifBtn"); if (btn) btn.setAttribute("aria-expanded", "false");
  }

  async function toggleNotifPanel() {
    const p = $("#notifPanel");
    if (!p) return;
    notifState.open = !notifState.open;
    p.classList.toggle("hidden", !notifState.open);
    const btn = $("#notifBtn"); if (btn) btn.setAttribute("aria-expanded", String(notifState.open));
    if (notifState.open) {
      renderNotifList();
      refreshNotifications();
      // Opening the panel counts as seeing them (like GitHub/Slack) — clear the badge.
      if (notifState.unread > 0) {
        try { await api("/notifications/read", { method: "POST", body: { all: true } }); } catch (e) {}
        setNotifBadge(0);
      }
    }
  }

  function wireNotifications() {
    if (notifState.wired) return;
    notifState.wired = true;
    const btn = $("#notifBtn");
    if (btn) btn.onclick = (e) => { e.stopPropagation(); toggleNotifPanel(); };
    const markAll = $("#notifMarkAll");
    if (markAll) markAll.onclick = async (e) => {
      e.stopPropagation();
      try { await api("/notifications/read", { method: "POST", body: { all: true } }); } catch (ex) {}
      notifState.items.forEach((n) => n.is_read = true);
      setNotifBadge(0);
      renderNotifList();
    };
    document.addEventListener("click", (e) => {
      if (notifState.open && !e.target.closest(".notif-wrap")) closeNotifPanel();
    });
    // Poll every 60s — enough to feel live without hammering the API.
    if (!notifState.timer) notifState.timer = setInterval(refreshNotifications, 60000);
  }

  /* ============================================================
     NAV
     ============================================================ */
  // ---- URL routing: keep the address bar in sync with the active view so refresh,
  // deep-links, bookmarks and browser back/forward all work inside the app. ----
  // "billing" is live again (2026-08-02): the tiered plans — Self-serve sandbox / Starter /
  // Growth / Scale — are the model, and the Plans page is where an org sees its seat and
  // client caps, its monthly AI credit allowance, and upgrades.
  const ROUTE_VIEWS = ["dashboard", "clients", "leads", "calendar", "coursefinder", "ai", "team", "credits", "billing", "finance", "support", "settings"];
  // The capability a whole view needs. A deep link, a bookmark or a Back press into a view
  // the member can't hold must paint one plain sentence — not the renderer's "Couldn't load"
  // after the API 403s.
  const VIEW_CAPABILITY = {
    dashboard: "dashboard.view", clients: "clients.view", team: "team.view",
    credits: "credits.view", finance: "finance.view", settings: "settings.manage",
    billing: "billing.manage", coursefinder: "coursefinder.view", ai: "ai.assistant",
    calendar: "calendar.view", leads: "clients.view",
  };
  const VIEW_DENIED_COPY = {
    dashboard: "You don't have permission to view the dashboard. Ask a workspace admin for access.",
    clients: "You don't have permission to view clients. Ask a workspace admin for access.",
    team: "You don't have permission to view the team. Ask a workspace admin for access.",
    credits: "You don't have permission to view the credit balance. Ask a workspace admin for access.",
    finance: "You don't have permission to view payments. Ask a workspace admin for access.",
    settings: "You don't have permission to change workspace settings. Ask a workspace admin for access.",
    billing: "You don't have permission to manage plans and the subscription. Ask a workspace admin for access.",
    coursefinder: "You don't have permission to browse the course catalog. Ask a workspace admin for access.",
    ai: "You don't have permission to use the Rilono AI Assistant. Ask a workspace admin for access.",
    calendar: "You don't have permission to view the calendar. Ask a workspace admin for access.",
    leads: "You don't have permission to view leads. Ask a workspace admin for access.",
  };
  // Nav items for views the member can't reach are removed outright (house rule: omit the
  // markup rather than show a control that only ever refuses).
  const NAV_CAPABILITY = { credits: "credits.view", billing: "billing.manage", finance: "finance.view", team: "team.view" };
  function applyNavCapabilities() {
    $$(".nav-item").forEach((b) => {
      const cap = NAV_CAPABILITY[b.dataset.view];
      if (cap) b.classList.toggle("hidden", !can(cap));
      // Leads is workspace-scope only (see canSeeLeads) — omit the button rather than
      // offer a section that can only refuse.
      if (b.dataset.view === "leads") b.classList.toggle("hidden", !canSeeLeads());
    });
  }
  function viewToPath(view) {
    return (view && view !== "dashboard" && ROUTE_VIEWS.includes(view)) ? ("/enterprise/" + view) : "/enterprise";
  }
  function parseRoute(pathname) {
    const s = String(pathname || "");
    const cm = /^\/enterprise\/clients\/(\d+)/i.exec(s);
    if (cm) return { view: "clientPage", clientId: Number(cm[1]) };
    const m = /^\/enterprise\/([a-z]+)/i.exec(s);
    const seg = (m && m[1] || "").toLowerCase();
    return { view: ROUTE_VIEWS.includes(seg) ? seg : "dashboard" };
  }
  function syncUrl(path, opts) {
    opts = opts || {};
    if (opts.fromPop) return; // navigation came FROM back/forward — don't push again
    try {
      if (opts.replace) history.replaceState({ ent: true }, "", path);
      else if (location.pathname !== path) history.pushState({ ent: true }, "", path);
    } catch (e) { /* history API unavailable — non-fatal */ }
  }
  // Route a URL into the app (used on first load and on browser back/forward).
  function applyRoute(pathname, opts) {
    const r = parseRoute(pathname);
    if (r.view === "clientPage") openClient(r.clientId, opts);
    else navigate(r.view, opts);
  }

  function navigate(view, opts) {
    state.view = view;
    $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
    $("#sidebar").classList.remove("open");
    const titles = { dashboard: "Dashboard", clients: "Clients", leads: "Leads", calendar: "Calendar", coursefinder: "Course Finder", ai: "Rilono AI Assistant", team: "Team", credits: "Credits & Billing", finance: "Finance", support: "Help & Support", billing: "Plans & Billing", settings: "Settings" };
    $("#viewTitle").textContent = titles[view] || "";
    $("#globalSearchBox").style.display = view === "clients" || view === "dashboard" ? "" : "none";
    // Team's sub-tab travels in ?tab= — read it BEFORE syncUrl rewrites the address bar.
    if (view === "team") teamConsumeTab();
    syncUrl(viewToPath(view), opts);
    syncAiDockVisibility();
    const needCap = VIEW_CAPABILITY[view];
    if (needCap && !can(needCap)) {
      $("#content").innerHTML = deniedCard(VIEW_DENIED_COPY[view] ||
        "You don't have permission to open this section. Ask a workspace admin for access.");
      return;
    }
    if (view === "dashboard") renderDashboard();
    else if (view === "clients") renderClients();
    else if (view === "leads") renderLeads();
    else if (view === "calendar") renderCalendar();
    else if (view === "coursefinder") renderCourseFinder();
    else if (view === "ai") renderAIAssistant();
    else if (view === "team") renderTeam();
    else if (view === "credits") renderCredits();
    else if (view === "finance") renderFinance();
    else if (view === "support") renderSupport();
    else if (view === "billing") renderBilling();
    else if (view === "settings") renderSettings();
  }
  $$(".nav-item").forEach((b) => b.onclick = () => navigate(b.dataset.view));
  // Browser back/forward: re-route to the URL's view without pushing a new entry.
  // Guarded by state.me so it's inert on the auth/onboarding screens.
  window.addEventListener("popstate", () => { if (state.me) applyRoute(location.pathname, { fromPop: true }); });
  $("#menuBtn").onclick = () => $("#sidebar").classList.toggle("open");
  $("#topAddClient").onclick = () => openClientForm(null);
  // Activate role="button" dashboard cards with keyboard (Enter / Space)
  $("#content").addEventListener("keydown", (e) => {
    const t = e.target;
    if ((e.key === "Enter" || e.key === " ") && t && t.getAttribute && t.getAttribute("role") === "button") {
      e.preventDefault(); t.click();
    }
  });
  /* ---------------- full screen ----------------
     Puts the whole console into the browser's full-screen mode so the pipeline, calendar
     and tables get the entire display. The button hides itself where the browser can't do
     it — e.g. iOS Safari, which only allows full screen on <video>. Deliberately no
     single-letter hotkey: a bare "f" would fire on every non-input surface in the console
     (pipeline rows are role="button", confirm dialogs focus a <button>) and single-character
     shortcuts need an off/remap switch to satisfy WCAG 2.1.4. The browser's own F11 covers it. */
  const fullscreenBtn = $("#fullscreenBtn");

  function fsElement() { return document.fullscreenElement || document.webkitFullscreenElement || null; }

  function fsSupported() {
    const el = document.documentElement;
    return !!(document.fullscreenEnabled || document.webkitFullscreenEnabled) &&
           !!(el.requestFullscreen || el.webkitRequestFullscreen);
  }

  function syncFullscreenUi() {
    const on = !!fsElement();
    document.body.classList.toggle("is-fullscreen", on);
    if (!fullscreenBtn) return;
    // One state channel only: the accessible name always names the action the click performs.
    // (aria-pressed alongside a swapping label makes screen readers announce a contradiction.)
    fullscreenBtn.setAttribute("aria-label", on ? "Exit full screen" : "Enter full screen");
    fullscreenBtn.title = on ? "Exit full screen (Esc)" : "Full screen";
    const iconIn = $(".fs-in", fullscreenBtn), iconOut = $(".fs-out", fullscreenBtn);
    if (iconIn) iconIn.classList.toggle("hidden", on);
    if (iconOut) iconOut.classList.toggle("hidden", !on);
  }

  function toggleFullscreen() {
    if (!fsSupported()) { toast("Your browser doesn't support full screen here", "error"); return; }
    const blocked = () => toast("Your browser blocked full screen", "error");
    try {
      if (fsElement()) {
        const exit = document.exitFullscreen || document.webkitExitFullscreen;
        const r = exit && exit.call(document);
        if (r && r.catch) r.catch(() => {});
      } else {
        const el = document.documentElement;
        const enter = el.requestFullscreen || el.webkitRequestFullscreen;
        const r = enter && enter.call(el);
        if (r && r.catch) r.catch(blocked);
      }
    } catch (_) { blocked(); }
  }

  if (fullscreenBtn) {
    if (fsSupported()) fullscreenBtn.onclick = toggleFullscreen;
    else fullscreenBtn.classList.add("hidden");
  }
  document.addEventListener("fullscreenchange", syncFullscreenUi);
  document.addEventListener("webkitfullscreenchange", syncFullscreenUi);
  syncFullscreenUi();

  let searchTimer;
  const globalSearch = $("#globalSearch");
  const globalSearchClear = $("#globalSearchClear");

  function syncGlobalSearchUi() {
    if (!globalSearch || !globalSearchClear) return;
    globalSearchClear.classList.toggle("hidden", !globalSearch.value.trim());
  }

  function clearClientSearch() {
    clearTimeout(searchTimer);
    state.filters.q = "";
    state.dashScope = null;
    state.dashScopeLabel = "";
    if (globalSearch) globalSearch.value = "";
    syncGlobalSearchUi();
    if (state.view === "clients") {
      loadAndRenderClientList();
      renderClientToolbar();
    }
  }

  function runClientSearch(raw) {
    clearTimeout(searchTimer);
    const term = String(raw || "").trim();
    if (!term) {
      clearClientSearch();
      return;
    }

    state.filters.q = term;
    state.dashScope = null;
    state.dashScopeLabel = "";
    if (globalSearch) globalSearch.value = term;
    syncGlobalSearchUi();

    if (state.view !== "clients") {
      state.filters.status = "";
      state.filters.category = "";
      state.filters.country = "";
      navigate("clients");
    } else {
      loadAndRenderClientList();
      renderClientToolbar();
    }
  }

  globalSearch.oninput = (e) => {
    clearTimeout(searchTimer);
    const v = e.target.value;
    syncGlobalSearchUi();
    searchTimer = setTimeout(() => {
      runClientSearch(v);
    }, 280);
  };
  globalSearch.onkeydown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      runClientSearch(e.target.value);
    } else if (e.key === "Escape") {
      e.preventDefault();
      clearClientSearch();
    }
  };
  globalSearchClear.onclick = clearClientSearch;

  // Painted at the top of Dashboard, Clients and Course Finder — the three views an org
  // actually lives in. Without it the only warning that the sandbox is running out lives on
  // Plans & Billing, a page a busy team never opens, so the first signal would be a 402 on
  // the day it lapses. Stays silent for a healthy paid plan.
  function trialBanner() {
    const s = state.subscription;
    if (!s || s.is_free_platform) return "";

    // A LAPSED PAID PLAN outranks everything else here. The backend has already dropped this
    // org to sandbox caps, so without this branch a consultancy that paid last month sees a
    // "sandbox trial ending today" banner and is never told their plan expired or that
    // renewing restores their seats, clients and monthly credits.
    if (s.plan_lapsed) {
      return `<div class="trial-banner trial-banner-warn">
        <span><b>Your ${esc(s.lapsed_plan_label || "paid")} plan expired${s.lapsed_at ? " on " + esc(fmtDate(s.lapsed_at)) : ""}.</b>
        You're on sandbox limits (${Number(s.max_seats)} seats, ${Number(s.max_clients)} clients) and monthly AI credits have stopped.
        Everything already in your workspace is safe — renew to restore your plan.</span>
        <button type="button" class="btn btn-sm btn-primary" onclick="__ent.go('billing')">Renew plan</button>
      </div>`;
    }

    // A pre-cutover org inside the migration ramp: caps are not enforced yet, but the date
    // they start being enforced must be visible well before it arrives.
    if (s.grandfathered) {
      return `<div class="trial-banner trial-banner-warn">
        <span><b>Choose a plan by ${s.grace_ends_at ? esc(fmtDate(s.grace_ends_at)) : "the deadline"}.</b>
        Your workspace predates Rilono plans, so nothing is limited yet${s.over_cap ? " — including what you already have above the new caps, which you keep" : ""}.</span>
        <button type="button" class="btn btn-sm btn-primary" onclick="__ent.go('billing')">See plans</button>
      </div>`;
    }
    if (!s.is_sandbox) {
      // Paid plan: only speak up when a cap is actually reached, since that is the moment
      // adding a client or a teammate is about to fail.
      if (s.can_add_client && s.can_add_seat) return "";
      const what = !s.can_add_client ? "active clients" : "team seats";
      return `<div class="trial-banner trial-banner-warn">
        <span>You've reached your ${esc(s.plan_label)} plan's limit for <b>${what}</b>.</span>
        <button type="button" class="btn btn-sm btn-primary" onclick="__ent.go('billing')">Upgrade</button>
      </div>`;
    }
    if (s.trial_expired) {
      return `<div class="trial-banner trial-banner-danger">
        <span><b>Your 14-day sandbox has ended.</b> Everything here is intact and readable — choose a plan to start adding clients and teammates again.</span>
        <button type="button" class="btn btn-sm btn-primary" onclick="__ent.go('billing')">Choose a plan</button>
      </div>`;
    }
    const left = Number(s.trial_days_left);
    // Only the last stretch, so the banner still reads as information rather than nagging.
    if (!Number.isFinite(left) || left > 7) return "";
    return `<div class="trial-banner trial-banner-warn">
      <span><b>${left === 0 ? "Your sandbox ends today." : `${left} day${left === 1 ? "" : "s"} left in your sandbox.`}</b>
      Plans start at ₹2,999/month + GST and include 1,000 AI credits a month.</span>
      <button type="button" class="btn btn-sm btn-primary" onclick="__ent.go('billing')">See plans</button>
    </div>`;
  }

  /* ---------------- Data Processing Agreement re-consent ---------------- */
  // The org's stored dpa_accepted_version is compared server-side against the current
  // LEGAL_DPA_VERSION. When they differ the portal shows a banner that only an org admin
  // can clear, so nobody keeps working under superseded processor terms unnoticed.
  function renderDpaBanner() {
    const wrap = $("#dpaBannerWrap");
    if (!wrap) return;
    const dpa = (state.me && state.me.dpa) || null;
    if (!dpa || !dpa.reconsent_required) {
      wrap.innerHTML = "";
      wrap.style.display = "none";
      return;
    }
    const updatedOn = fmtDate(dpa.current_version);
    const canAccept = can("org.legal_accept");
    wrap.innerHTML = `
      <div class="plan-banner warn" role="status">
        <div class="pb-icon">📄</div>
        <div class="pb-text"><b>Our Data Processing Agreement was updated on ${esc(updatedOn)}.</b>
          <span>${canAccept
            ? `Please review and accept the updated terms to continue using Rilono Enterprise.`
            : `An administrator must review and accept the updated terms to continue using Rilono Enterprise. Ask an admin in your organization to sign in and accept them.`}</span></div>
        <a class="btn btn-soft btn-sm" href="/dpa" target="_blank" rel="noopener noreferrer">Review DPA</a>
        ${canAccept ? `<button class="btn btn-primary btn-sm" id="dpaAcceptBtn" type="button">Accept updated terms</button>` : ""}
      </div>`;
    wrap.style.display = "";
    const btn = $("#dpaAcceptBtn");
    if (btn) btn.onclick = () => acceptDpa(btn);
  }

  async function acceptDpa(btn) {
    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = "Accepting…";
    let res;
    try {
      res = await api("/dpa/accept", { method: "POST", body: {} });
    } catch (ex) {
      btn.disabled = false;
      btn.textContent = label;
      toast(ex.message || "Could not record your acceptance. Please try again.", "error");
      return;
    }
    if (state.me) state.me.dpa = res.dpa || state.me.dpa;
    renderDpaBanner();
    toast("Updated Data Processing Agreement accepted.", "success");
  }

  /* ============================================================
     DASHBOARD
     ============================================================ */
  async function renderDashboard() {
    const c = $("#content");
    c.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
    let d;
    const dashQs = state.filters.branch_id ? "?branch_id=" + encodeURIComponent(state.filters.branch_id) : "";
    try { d = await api("/dashboard" + dashQs); } catch (ex) { c.innerHTML = errBox(ex); return; }
    applyAccessPayload(d);
    state.subscription = d.subscription || state.subscription;
    updatePlanChip();

    const k = d.kpis;
    const kpiCard = (icGrad, ic, label, val, sub, onclick) =>
      `<div class="kpi${onclick ? " clickable" : ""}"${onclick ? ` role="button" tabindex="0" onclick="${onclick}"` : ""}>
        <div class="kpi-top"><div class="kpi-ic" style="background:${icGrad}">${ic}</div>${onclick ? '<span class="kpi-arrow">→</span>' : ""}</div>
        <div class="kpi-label">${label}</div><div class="kpi-value">${val}</div><div class="kpi-sub">${sub || ""}</div></div>`;

    const maxPipe = Math.max(1, ...d.pipeline.map((p) => p.count));
    const pipeRows = d.pipeline.map((p) =>
      `<div class="pipe-row clickable" role="button" tabindex="0" onclick="__ent.viewClients({status:'${p.key}'})"><div class="pl"><span class="dot" style="background:${p.color}"></span>${esc(p.label)}</div>
       <div class="pipe-track"><div class="pipe-fill" style="width:${(p.count / maxPipe) * 100}%;background:${p.color}"></div></div>
       <div class="pv">${p.count}</div></div>`).join("");

    const vtCounts = d.visa_type_counts || [];
    state.dashVisaTypes = vtCounts.map((v) => v.visa_type);
    const vtCells = vtCounts.length ? vtCounts.map((vt, i) =>
      `<div class="cat-cell clickable" role="button" tabindex="0" onclick="__ent.viewVisaType(${i})"><div class="ci" style="background:linear-gradient(135deg,#6366f1,#8b5cf6)">🎓</div>
        <div><div class="cv">${vt.count}</div><div class="cl">${esc(vt.visa_type)}</div></div></div>`).join("")
      : `<div class="empty" style="padding:22px"><p>Add clients to see visa-type insights.</p></div>`;

    // These cards are *our clients* grouped by where they're applying — not a menu of
    // countries Rilono supports. Every label says "clients" so nobody reads it as a
    // destination catalogue. The landmark name moves to hover; the photo already shows it.
    const ctList = d.top_countries || [];
    const ctShown = ctList.reduce((n, ct) => n + (ct.count || 0), 0);
    const ctPlural = (n) => n + " client" + (n === 1 ? "" : "s");
    const ctHint = !ctList.length ? ""
      : ctShown < (k.total_clients || 0)
        ? `Top ${ctList.length} · ${ctShown} of your ${k.total_clients} clients`
        : `All ${ctPlural(ctShown)}, by where they're applying`;
    const countryCards = ctList.map((ct) =>
      `<div class="country-card clickable" role="button" tabindex="0" title="${esc(ctPlural(ct.count) + " applying to " + ct.name + (ct.landmark ? " · " + ct.landmark : ""))}" onclick="__ent.viewClients({country:'${ct.code}'})">
        <div class="country-art" style="background:linear-gradient(135deg,${ct.gradient_from || "#6366f1"},${ct.gradient_to || "#8b5cf6"})">${landmarkArt(ct)}
        <span class="flag">${ct.flag_emoji || "🌐"}</span><span class="cnt">${ct.count}</span></div>
        <div class="country-meta"><b>${esc(ct.name)}</b><span>${esc(ctPlural(ct.count))}</span></div></div>`).join("");

    const deadlines = (d.upcoming_deadlines || []).length ? d.upcoming_deadlines.map((cl) => {
      const du = daysUntil(cl.target_date);
      const tag = du != null ? (du <= 7 ? `<span class="prio" style="background:#fee2e2;color:#b91c1c">${du}d</span>` : `<span class="prio" style="background:#eef0f8;color:#475569">${du}d</span>`) : "";
      return `<div class="member-row" style="cursor:pointer;padding:11px 0" onclick="__ent.openClient(${cl.id})">
        <div class="cl-avatar" style="background:linear-gradient(135deg,${cl.country.gradient_from},${cl.country.gradient_to})">${esc(cl.country.flag_emoji || "🌐")}</div>
        <div class="m-meta"><b>${esc(cl.full_name)}</b><span>${esc(cl.visa_type)} · ${fmtDate(cl.target_date)}</span></div>${tag}</div>`;
    }).join("") : `<div class="empty" style="padding:24px"><p>No upcoming deadlines 🎉</p></div>`;

    const recent = d.recent_clients.length ? d.recent_clients.map((cl) =>
      `<div class="member-row" style="cursor:pointer;padding:11px 0" onclick="__ent.openClient(${cl.id})">
        <div class="cl-avatar" style="background:linear-gradient(135deg,${avatarColor(cl.full_name).join(',')})">${esc(initials(cl.full_name).toUpperCase())}</div>
        <div class="m-meta"><b>${esc(cl.full_name)}</b><span>${esc(cl.country.flag_emoji)} ${esc(cl.destination_country_name)} · ${esc(cl.visa_type)}</span></div>
        ${statusPill(cl.stage)}</div>`).join("") : `<div class="empty" style="padding:24px"><p>No clients yet.</p></div>`;

    // "What's next" — overdue + the next few days of reminders, tasks, key dates and passport
    // expiries: the same feed the Calendar shows, on the screen people actually land on. The
    // server omits it for a role without calendar.view, which keeps the client-deadline card.
    const wn = d.whats_next;
    // Keep the shared zone label in step here too — dashEvent opens the same detail modal as
    // the Calendar page, and it must not print a time with the previous page's zone.
    if (wn) { calTzLabel = wn.timezone_label || ""; calTodayYmd = wn.today || ""; }
    const wnItem = (e) => `
      <div class="cal-up-item ${e.overdue ? "overdue" : ""}" role="button" tabindex="0" onclick="__ent.dashEvent('${e.id}')">
        <span class="cal-dot" style="background:${e.color}"></span>
        <div class="cal-up-meta">
          <b>${esc(e.title)}</b>
          <span>${esc(e.type_label)}${e.client_name && e.source !== "client" ? " · " + esc(e.client_name) : ""}${e.attachment_count ? " · 📎 " + e.attachment_count : ""}</span>
        </div>
        <div class="cal-up-when ${e.overdue ? "overdue" : ""}">${esc(calRel(e.date, wn.today))}${e.time ? " · " + esc(calClock(e.time)) : ""}</div>
      </div>`;
    // The card carries a few rows, never the whole feed — say so rather than quietly truncating.
    const wnMore = (shown, total) => total > shown
      ? `<div class="dash-wn-more" role="button" tabindex="0" onclick="__ent.go('calendar')">+${total - shown} more in Calendar →</div>` : "";
    let whatsNextBody = "", overdueStrip = "";
    if (wn) {
      // Feed __ent.dashEvent's lookup, the same map the Calendar page fills.
      (wn.overdue || []).concat(wn.upcoming || []).forEach((e) => { calEventsById[e.id] = e; });
      const od = wn.overdue || [], upNext = wn.upcoming || [];
      const todayItems = upNext.filter((e) => e.date === wn.today);
      const laterItems = upNext.filter((e) => e.date !== wn.today);
      let html = "";
      if (od.length) html += `<div class="cal-up-label overdue">⚠ Overdue (${wn.overdue_total})</div>${od.map(wnItem).join("")}${wnMore(od.length, wn.overdue_total)}`;
      if (todayItems.length) html += `<div class="cal-up-label">Today</div>${todayItems.map(wnItem).join("")}`;
      if (laterItems.length) html += `<div class="cal-up-label">Next ${wn.horizon_days} days</div>${laterItems.map(wnItem).join("")}`;
      if (upNext.length) html += wnMore(upNext.length, wn.upcoming_total);
      whatsNextBody = html || `<div class="cal-up-empty">Nothing due in the next ${wn.horizon_days} days. You're all caught up. 🎉</div>`;

      // A follow-up that aged out is the expensive miss, so it gets its own line at the top of
      // the dashboard instead of waiting to be scrolled to.
      if (wn.overdue_total) {
        const oldest = od[0];
        overdueStrip = `<div class="dash-due" role="button" tabindex="0" onclick="__ent.go('calendar')">
          <span class="dash-due-ic">⚠</span>
          <div class="dash-due-txt"><b>${wn.overdue_total} overdue ${wn.overdue_total === 1 ? "item needs" : "items need"} attention</b>
            ${oldest ? `<span>Oldest: ${esc(oldest.title)} · ${esc(calRel(oldest.date, wn.today))}</span>` : ""}</div>
          <span class="dash-due-go">Open calendar →</span>
        </div>`;
      }
    }

    // Money — invoiced but not collected. Grouped by currency and never summed across them
    // (fmtMoney renders each in its own denomination; there is no FX anywhere in this app).
    const fin = d.finance_snapshot;
    const finFigure = (rows) => (rows || []).length
      ? rows.map((r) => fmtMoney(r.amount_minor, r.currency)).join(" + ")
      : "—";
    const financeCard = fin ? `
      <div class="card dash-money" role="button" tabindex="0" onclick="__ent.go('finance')">
        <div class="card-head"><h3>Payments</h3><button class="link">Finance →</button></div>
        <div class="card-body">
          <div class="dash-money-grid">
            <div class="dash-money-cell">
              <span class="dash-money-lbl">Awaiting payment</span>
              <b class="dash-money-val">${esc(finFigure(fin.outstanding))}</b>
              <span class="dash-money-sub">${(fin.outstanding || []).reduce((n, r) => n + r.count, 0)} open request${(fin.outstanding || []).reduce((n, r) => n + r.count, 0) === 1 ? "" : "s"}</span>
            </div>
            <div class="dash-money-cell">
              <span class="dash-money-lbl">Past due</span>
              <b class="dash-money-val ${fin.overdue_count ? "is-bad" : ""}">${fin.overdue_count}</b>
              <span class="dash-money-sub">${fin.overdue_count ? "chase these first" : "nothing overdue"}</span>
            </div>
            <div class="dash-money-cell">
              <span class="dash-money-lbl">Collected this month</span>
              <b class="dash-money-val is-good">${esc(finFigure(fin.collected_this_month))}</b>
              <span class="dash-money-sub">${(fin.collected_this_month || []).reduce((n, r) => n + r.count, 0)} payment${(fin.collected_this_month || []).reduce((n, r) => n + r.count, 0) === 1 ? "" : "s"}</span>
            </div>
          </div>
        </div>
      </div>` : "";

    // Needs attention — open cases nobody has touched in a fortnight. The one panel that
    // answers "what is quietly rotting", which no count card can.
    const st = d.stalled;
    const staleRows = st && st.clients.length ? st.clients.map((cl) => `
      <div class="member-row" style="cursor:pointer;padding:11px 0" onclick="__ent.openClient(${cl.id})">
        <div class="cl-avatar" style="background:linear-gradient(135deg,${cl.country.gradient_from},${cl.country.gradient_to})">${esc(cl.country.flag_emoji || "🌐")}</div>
        <div class="m-meta"><b>${esc(cl.full_name)}</b><span>${esc(cl.destination_country_name)} · ${esc(cl.visa_type)}</span></div>
        <span class="prio dash-stale-age">${cl.days_stale}d quiet</span>
      </div>`).join("") : "";
    const staleCard = st ? `
      <div class="card"><div class="card-head"><h3>Needs attention</h3>
        <span class="dash-stale-hint">No activity in ${st.days}+ days</span></div>
        <div class="card-body"><div class="dash-feed">${staleRows
          ? staleRows + (st.total > st.clients.length
              ? `<div class="dash-wn-more" role="button" tabindex="0" onclick="__ent.viewClients({scope:'active',label:'Active cases'})">${st.truncated ? "+" : ""}${st.total - st.clients.length} more going quiet · see active cases →</div>`
              : "")
          : `<div class="cal-up-empty">Every open case has moved in the last ${st.days} days. 👏</div>`}</div></div></div>` : "";

    const attentionRow = (financeCard || staleCard)
      ? `<div class="dash-row${financeCard && staleCard ? " even" : ""}">${financeCard}${staleCard}</div>`
      : "";

    const dashBranchBar = branchFilterHtml("dashBranch")
      ? `<div class="toolbar" style="margin-bottom:16px"><div class="spacer"></div>${branchFilterHtml("dashBranch")}</div>` : "";

    c.innerHTML = `
      ${trialBanner()}
      ${dashBranchBar}
      <div class="kpi-grid">
        ${kpiCard("linear-gradient(135deg,#6366f1,#8b5cf6)", "👥", "Total clients", k.total_clients, "View all clients", "__ent.viewClients({})")}
        ${kpiCard("linear-gradient(135deg,#0ea5e9,#22d3ee)", "📂", "Active cases", k.active_clients, "in progress", "__ent.viewClients({scope:'active',label:'Active cases'})")}
        ${kpiCard("linear-gradient(135deg,#10b981,#34d399)", "✅", "Approved", k.approved, k.approval_rate != null ? k.approval_rate + "% approval rate" : "View approved", "__ent.viewClients({status:'approved'})")}
        ${kpiCard("linear-gradient(135deg,#f59e0b,#f97316)", "🆕", "New this month", k.new_this_month, "this month", "__ent.viewClients({scope:'month',label:'New this month'})")}
      </div>
      ${overdueStrip}
      <div class="dash-row even">
        <div class="card"><div class="card-head"><h3>${wn ? "What's next" : "Upcoming deadlines"}</h3>${wn ? `<button class="link" onclick="__ent.go('calendar')">Calendar →</button>` : ""}</div>
          <div class="card-body">${wn ? `<div class="cal-upcoming dash-wn">${whatsNextBody}</div>` : `<div class="dash-feed">${deadlines}</div>`}</div></div>
        <div class="card"><div class="card-head"><h3>Recent clients</h3><button class="link" onclick="__ent.go('clients')">All →</button></div>
          <div class="card-body"><div class="dash-feed">${recent}</div></div></div>
      </div>
      ${attentionRow}
      <div class="dash-row">
        <div class="card"><div class="card-head"><h3>Client pipeline</h3><button class="link" onclick="__ent.go('clients')">View all →</button></div>
          <div class="card-body"><div class="pipe-grid" style="--pipe-rows:${Math.ceil(d.pipeline.length / 2)}">${pipeRows}</div></div></div>
      </div>
      <div class="dash-row even">
        <div class="card"><div class="card-head"><h3>By visa type</h3></div>
          <div class="card-body"><div class="cat-grid">${vtCells}</div></div></div>
        <div class="card"><div class="card-head"><h3>Client destinations</h3>
          ${ctHint ? `<span class="dash-head-hint">${esc(ctHint)}</span>` : ""}</div>
          <div class="card-body">${countryCards ? `<div class="country-grid">${countryCards}</div>` : `<div class="empty" style="padding:24px"><p>Add clients to see where they're applying.</p></div>`}</div></div>
      </div>`;

    const dbf = $("#dashBranch");
    if (dbf) dbf.onchange = () => { state.filters.branch_id = dbf.value; renderDashboard(); };
  }

  function errBox(ex) {
    return `<div class="empty"><div class="emoji">⚠️</div><h3>Couldn't load</h3><p>${esc(ex.message || "Error")}</p></div>`;
  }

  // Open the Clients view pre-filtered from a dashboard click.
  function openClientsFiltered(opts) {
    opts = opts || {};
    state.filters.status = opts.status || "";
    state.filters.country = opts.country || "";
    state.filters.q = "";
    const gs = $("#globalSearch"); if (gs) gs.value = "";
    syncGlobalSearchUi();
    state.dashScope = opts.scope || null;          // 'active' | 'month' | { visaType }
    state.dashScopeLabel = opts.label || "";
    navigate("clients");
  }
  function viewVisaType(i) {
    const vt = (state.dashVisaTypes || [])[i];
    if (!vt) { openClientsFiltered({}); return; }
    openClientsFiltered({ scope: { visaType: vt }, label: "Visa type · " + vt });
  }
  // Dashboard/anywhere entry point: pick a student, then email them a mock-interview
  // link (the primary way the feature is used). Reuses the same invite endpoint.
  async function openSendInterviewPicker(preselectId) {
    if (!can("interviews.invite")) { toast("You don't have permission to send interview invites. Ask a workspace admin for access.", "error"); return; }
    let clients = [];
    try { const d = await api("/clients?limit=500"); clients = (d.clients || []).filter((c) => c.email); }
    catch (ex) { toast(ex.message, "error"); return; }
    if (!clients.length) { toast("Add a client with an email address first, then you can send them a mock interview.", "error"); return; }

    const cr = state.credits || {};
    const mockCost = ((cr.actions || []).find((a) => a.key === "mock_interview") || {}).credits || 20;
    const perInr = cr.credit_value_inr || 10;
    const isInr = (cr.currency || "INR") === "INR";
    const balance = (typeof cr.balance_credits === "number") ? cr.balance_credits : null;
    const money = (credits) => isInr ? ` (≈ ${fmtInr(Math.round(credits * perInr))})` : "";

    openModal(`<div class="modal-head"><h3>🎤 Send a mock interview</h3><button class="x" onclick="__ent.closeModal()">×</button></div>
      <form id="sendIvForm"><div class="modal-body">
        <p style="margin:0 0 16px;color:var(--text-2);font-size:14px;line-height:1.6">We'll email a secure link to the student. They verify with a one-time code, take the interview(s) on their own time, and every result appears in their profile here.</p>
        <div class="field"><label>Student</label>
          <div class="docsel" id="sendIvSel" style="max-width:none;min-width:0">
            <input type="text" id="sendIvSearch" class="docsel-input" autocomplete="off" placeholder="Search students by name or email…" role="combobox" aria-expanded="false" aria-autocomplete="list" />
            <input type="hidden" id="sendIvClient" value="" />
            <div class="docsel-menu hidden" id="sendIvMenu" role="listbox"></div>
          </div></div>
        <div class="field"><label>How many interviews can they take?</label>
          <input type="number" id="sendIvCount" min="1" max="20" value="3" /></div>
        <div id="sendIvCost" style="background:rgba(99,102,241,.07);border:1px solid var(--border);border-radius:10px;padding:10px 12px;font-size:13px;color:var(--text-2);line-height:1.5;margin:-2px 0 4px"></div>
        <div id="sendIvErr" class="auth-error hidden"></div>
      </div>
      <div class="modal-foot"><button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
      <button type="submit" class="btn btn-primary" id="sendIvSave">✉ Send link</button></div></form>`);

    // ---- Searchable student picker (typeahead + suggestions) ----
    const ivSearch = $("#sendIvSearch"), ivMenu = $("#sendIvMenu"), ivHidden = $("#sendIvClient");
    let ivActive = -1, ivFiltered = clients.slice();
    const ivLabel = (c) => `${c.full_name} — ${c.email}`;
    const ivPick = (c) => {
      if (!c) return;
      ivHidden.value = c.id;
      ivSearch.value = ivLabel(c);
      ivMenu.classList.add("hidden");
      ivSearch.setAttribute("aria-expanded", "false");
      ivActive = -1;
    };
    function ivPaint(q) {
      const term = (q || "").trim().toLowerCase();
      ivFiltered = term
        ? clients.filter((c) => (c.full_name + " " + c.email + " " + (c.destination_country_name || "") + " " + (c.visa_type || "")).toLowerCase().includes(term))
        : clients.slice();
      if (ivActive >= ivFiltered.length) ivActive = ivFiltered.length - 1;
      ivMenu.innerHTML = ivFiltered.length
        ? ivFiltered.map((c, i) => {
            const flag = (c.country && c.country.flag_emoji) ? c.country.flag_emoji + " " : "";
            return `<div class="docsel-item${i === ivActive ? " active" : ""}" data-idx="${i}" role="option">
              <div class="docsel-line"><span class="docsel-label">${esc(c.full_name)}</span></div>
              <div class="docsel-hint">${flag}${esc(c.email)}${c.visa_type ? " · " + esc(c.visa_type) : ""}</div>
            </div>`;
          }).join("")
        : `<div class="docsel-empty">No student matches “${esc(q || "")}”. Add them under Clients first.</div>`;
      ivMenu.querySelectorAll(".docsel-item").forEach((el) => {
        el.onmousedown = (e) => { e.preventDefault(); ivPick(ivFiltered[parseInt(el.dataset.idx, 10)]); };
      });
      ivMenu.classList.remove("hidden");
      ivSearch.setAttribute("aria-expanded", "true");
    }
    const ivScroll = () => { const el = ivMenu.querySelector(".docsel-item.active"); if (el) el.scrollIntoView({ block: "nearest" }); };
    ivSearch.addEventListener("focus", () => { ivActive = -1; ivPaint(""); });
    ivSearch.addEventListener("input", () => { ivHidden.value = ""; ivActive = -1; ivPaint(ivSearch.value); });
    ivSearch.addEventListener("blur", () => setTimeout(() => { ivMenu.classList.add("hidden"); ivSearch.setAttribute("aria-expanded", "false"); }, 150));
    ivSearch.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (ivMenu.classList.contains("hidden")) { ivActive = 0; ivPaint(ivSearch.value); ivScroll(); return; }
        ivActive = Math.min(ivFiltered.length - 1, ivActive + 1); ivPaint(ivSearch.value); ivScroll();
      } else if (e.key === "ArrowUp") {
        e.preventDefault(); ivActive = Math.max(0, ivActive - 1); ivPaint(ivSearch.value); ivScroll();
      } else if (e.key === "Enter") {
        if (!ivMenu.classList.contains("hidden") && ivActive >= 0 && ivFiltered[ivActive]) { e.preventDefault(); ivPick(ivFiltered[ivActive]); }
      } else if (e.key === "Escape") {
        ivMenu.classList.add("hidden"); ivSearch.setAttribute("aria-expanded", "false");
      }
    });
    // Preselect the caller's client, or default to the first so there's always a valid target.
    ivPick(clients.find((c) => c.id === preselectId) || clients[0]);

    function updateCost() {
      const el = $("#sendIvCost"); if (!el) return;
      const n = Math.max(1, Math.min(20, parseInt($("#sendIvCount").value, 10) || 1));
      const total = n * mockCost;
      const blocked = !!cr.enforced && balance !== null && balance < total;
      let balanceLine = "";
      if (balance !== null) {
        balanceLine = blocked
          ? `<div style="margin-top:6px;color:var(--warning,#f59e0b);font-weight:600">⚠ Wallet balance: ${balance} credits — not enough for ${n} interview${n === 1 ? "" : "s"}. <button type="button" class="btn btn-soft btn-sm" style="margin-left:6px" onclick="__ent.closeModal();__ent.go('credits')">Top up</button></div>`
          : `<div style="margin-top:5px;color:var(--muted)">Wallet balance: ${balance} credits</div>`;
      }
      el.innerHTML = `<div>Costs up to <b>${total} credits</b>${money(total)} for ${n} interview${n === 1 ? "" : "s"} — <b>${mockCost}</b> credits each, charged only when an interview is actually taken.</div>` + balanceLine;
      // This runs on every keystroke in #sendIvCount — including while the invite is in
      // flight, where it would happily un-disable the button mid-request and let a second
      // invite (and a second credit hold) go out. withBusy owns the button while busy.
      const sb = $("#sendIvSave");
      if (sb && sb.dataset.busy !== "1") { sb.disabled = blocked; sb.title = blocked ? "Top up your wallet to send this link" : ""; }
    }
    const ic = $("#sendIvCount"); if (ic) ic.addEventListener("input", updateCost);
    // Registering it as the button's validity sync means withBusy's finally restores the
    // wallet-blocked state instead of blanket-enabling a button the balance can't afford.
    const ivSaveBtn = $("#sendIvSave"); if (ivSaveBtn) ivSaveBtn._syncValid = updateCost;
    updateCost();
    $("#sendIvForm").onsubmit = async (e) => {
      e.preventDefault();
      const id = parseInt($("#sendIvClient").value, 10);
      if (!id || Number.isNaN(id)) {
        const er = $("#sendIvErr"); er.textContent = "Pick a student from the list first."; er.classList.remove("hidden");
        $("#sendIvSearch").focus();
        return;
      }
      const n = Math.max(1, Math.min(20, parseInt($("#sendIvCount").value, 10) || 3));
      await withBusy($("#sendIvSave"), "Sending…", async () => {
        try {
          const r = await api(`/clients/${id}/interview/invite`, { method: "POST", body: { allowed_count: n } });
          closeModal();
          toast(r.message || "Mock interview link sent", r.email_sent ? "success" : "error");
          if (state.activeClient === id) openClient(id);  // refresh the open profile
        } catch (ex) {
          const er = $("#sendIvErr"); er.textContent = ex.message; er.classList.remove("hidden");
        }
      });
    };
  }

  /* ============================================================
     CLIENTS
     ============================================================ */
  function renderClients() {
    const c = $("#content");
    c.innerHTML = `
      ${trialBanner()}
      <div class="toolbar" id="clientToolbar"></div>
      <div id="clientListWrap"><div class="center-load"><div class="spinner dark"></div></div></div>`;
    renderClientToolbar();
    loadAndRenderClientList();
  }

  function renderClientToolbar() {
    const tb = $("#clientToolbar"); if (!tb) return;
    const stages = state.catalog ? state.catalog.stages : [];
    const sc = state.statusCounts || {};
    const allActive = !state.filters.status;
    const chips = [`<button class="chip ${allActive ? "active" : ""}" data-st="">All</button>`]
      .concat(stages.map((s) => `<button class="chip ${state.filters.status === s.key ? "active" : ""}" data-st="${s.key}">
        <span class="dot" style="width:8px;height:8px;border-radius:50%;background:${s.color}"></span>${esc(s.label)}
        <span class="c-count">${sc[s.key] || 0}</span></button>`)).join("");

    const searchChip = state.filters.q ? `<button class="chip search-chip active" id="searchChip">Search: ${esc(state.filters.q)} ✕</button>` : "";
    const scopeChip = state.dashScope ? `<button class="chip scope-chip active" id="scopeChip">${esc(state.dashScopeLabel || "Filtered")} ✕</button>` : "";

    const countries = state.catalog ? state.catalog.countries : [];
    const countryOpts = `<option value="">All countries</option>` + countries.map((c) => `<option value="${c.code}" ${state.filters.country === c.code ? "selected" : ""}>${esc(c.flag_emoji)} ${esc(c.name)}</option>`).join("");

    tb.innerHTML = `<div class="chips">${searchChip}${scopeChip}${chips}</div><div class="spacer"></div>
      ${branchFilterHtml("filterBranch")}
      <select class="select-mini" id="filterCountry">${countryOpts}</select>
      ${can("clients.create") ? `<button class="btn btn-primary btn-sm" id="addClientBtn">+ Add Client</button>` : ""}`;

    function clearScope() { state.dashScope = null; state.dashScopeLabel = ""; }
    $$(".chip[data-st]", tb).forEach((ch) => ch.onclick = () => { state.filters.status = ch.dataset.st; clearScope(); loadAndRenderClientList(); renderClientToolbar(); });
    const searchEl = $("#searchChip", tb); if (searchEl) searchEl.onclick = () => clearClientSearch();
    const scEl = $("#scopeChip", tb); if (scEl) scEl.onclick = () => { clearScope(); loadAndRenderClientList(); renderClientToolbar(); };
    $("#filterCountry").onchange = (e) => { state.filters.country = e.target.value; clearScope(); loadAndRenderClientList(); };
    const bf = $("#filterBranch", tb);
    if (bf) bf.onchange = () => { state.filters.branch_id = bf.value; clearScope(); loadAndRenderClientList(); };
    const ab = $("#addClientBtn"); if (ab) ab.onclick = () => openClientForm(null);
  }

  /* An office filter, but only once there is a choice to make: a workspace with one office
     (or none) would just get a select with a single option. `state.branches` is whatever
     /me said this member may file a client under, so a branch-scoped counsellor sees only
     their own offices here. */
  function branchFilterHtml(id) {
    const list = (state.branches || []).filter((b) => b.is_active !== false);
    if (list.length < 2) return "";
    const sel = String(state.filters.branch_id || "");
    return `<select class="select-mini" id="${esc(id)}" aria-label="Filter by office">
      <option value="">All offices</option>
      ${list.map((b) => `<option value="${b.id}" ${sel === String(b.id) ? "selected" : ""}>${esc(b.name)}</option>`).join("")}
    </select>`;
  }

  let clientLoadSeq = 0; // guards against out-of-order client-list responses (see below)
  async function loadAndRenderClientList() {
    const wrap = $("#clientListWrap"); if (!wrap) return;
    // Capture the query THIS request is for, so the empty-state text always matches the
    // results shown — never a newer/older global state.filters.q.
    const q = state.filters.q ? String(state.filters.q).trim() : "";
    const p = new URLSearchParams();
    if (state.filters.status) p.set("status_filter", state.filters.status);
    if (state.filters.category) p.set("category", state.filters.category);
    if (state.filters.country) p.set("country", state.filters.country);
    if (state.filters.branch_id) p.set("branch_id", state.filters.branch_id);
    if (q) p.set("q", q);
    // Monotonic token: a slow fetch for a previous query must NOT repaint the list once a
    // newer search/filter has been issued (the "shows the previous query" race).
    const seq = ++clientLoadSeq;
    let data;
    try { data = await api("/clients?" + p.toString()); }
    catch (ex) { if (seq === clientLoadSeq) wrap.innerHTML = errBox(ex); return; }
    if (seq !== clientLoadSeq) return; // superseded by a newer request — drop this response
    let clients = data.clients;
    const scope = state.dashScope;
    if (scope === "active") clients = clients.filter((c) => c.stage && c.stage.is_open);
    else if (scope === "month") { const ms = new Date(); ms.setDate(1); ms.setHours(0, 0, 0, 0); clients = clients.filter((c) => c.created_at && new Date(c.created_at) >= ms); }
    else if (scope && scope.visaType) clients = clients.filter((c) => (c.visa_type || "") === scope.visaType);
    state.clients = clients;
    state.statusCounts = data.status_counts || {};
    $("#clientsBadge").textContent = data.total_clients;
    renderClientToolbar();

    const hasFilter = q || state.filters.status || state.filters.country || state.filters.branch_id || state.dashScope;
    if (!clients.length) {
      const emptyTitle = q ? `No clients found for “${esc(q)}”` : (hasFilter ? "No matching clients" : "No clients yet");
      const emptyHelp = q ? "Try another name, email, phone, city, course, branch, visa type, country, intake, lead source, or counselor." : (hasFilter ? "Try clearing your filters." : "Add your first client to get started.");
      wrap.innerHTML = `<div class="empty"><div class="emoji">🗂️</div><h3>${emptyTitle}</h3>
        <p>${emptyHelp}</p>
        ${q ? `<button class="btn btn-ghost" onclick="__ent.clearSearch()">Clear search</button>` : ""}
        ${!hasFilter && can("clients.create") ? `<button class="btn btn-primary" onclick="__ent.openClientForm()">+ Add your first client</button>` : ""}</div>`;
      return;
    }

    const rows = clients.map((cl) => {
      const [a, b] = avatarColor(cl.full_name);
      const du = daysUntil(cl.target_date);
      const deadline = cl.target_date ? `<small>${fmtDate(cl.target_date)}${du != null && du <= 14 && du >= 0 ? ` · ${du}d` : ""}</small>` : "";
      return `<tr onclick="__ent.openClient(${cl.id})">
        <td><div class="cl-name"><div class="cl-avatar" style="background:linear-gradient(135deg,${a},${b})">${esc(initials(cl.full_name).toUpperCase())}</div>
          <div><b>${esc(cl.full_name)}</b><span>${esc(cl.email || cl.phone || "—")}</span></div></div></td>
        <td class="hide-sm"><div class="cl-dest"><span class="fl">${esc(cl.country.flag_emoji)}</span><div>${esc(cl.destination_country_name)}<small>${esc(cl.intake || "")}</small></div></div></td>
        <td class="hide-sm">${esc(cl.visa_type)}${cl.intake ? `<br><small style="color:var(--muted)">${esc(cl.intake)}</small>` : ""}</td>
        <td>${statusPill(cl.stage)}</td>
        <td class="hide-sm">${cl.assigned_to_name ? esc(cl.assigned_to_name) : '<span style="color:var(--muted)">Unassigned</span>'}${deadline}</td>
      </tr>`;
    }).join("");

    wrap.innerHTML = `<table class="client-table"><thead><tr>
        <th>Client</th><th class="hide-sm">Destination</th><th class="hide-sm">Visa type</th><th>Status</th><th class="hide-sm">Assigned · Deadline</th>
      </tr></thead><tbody>${rows}</tbody></table>`;
  }

  /* ---------------- the client intake record ----------------
     What a consultancy has to have on file for a lead: who they are and how to reach
     them, what they want to study and how far along it already is, the profile that
     decides whether it is sellable (marks, tests, budget, prior refusals), where the
     lead came from, and the consents.

     ONE markup builder + ONE wiring/collect pair, shared by the Add-client modal and the
     "Edit details" pane on the client page, so the two can never drift apart. Every
     dropdown's options come from the server catalog (client_profile_options), which is the
     same list the API validates against — a select and its validation can't disagree. */

  function profileOptions(field) {
    const map = (state.catalog && state.catalog.client_profile_options) || {};
    return map[field] || [];
  }
  function profileSelect(name, value, placeholder) {
    const opts = [`<option value="">${esc(placeholder || "Select…")}</option>`].concat(
      profileOptions(name).map((o) => `<option value="${esc(o.key)}" ${o.key === value ? "selected" : ""}>${esc(o.label)}</option>`));
    return `<select name="${name}">${opts.join("")}</select>`;
  }
  function suggestList(id, items) {
    return `<datalist id="${id}">${(items || []).map((s) => `<option value="${esc(s)}"></option>`).join("")}</datalist>`;
  }

  /* Which office a client belongs to. This used to be a free-text box, which is how one
     workspace ended up with "Banjara Hills", "banjara hills" and "BH" as three offices.
     It is now a picker over the real offices (`state.branches`, already narrowed by /me to
     the ones this member may file under) and the server writes branch_name from the chosen
     office. A workspace whose server predates offices gets the old text box back so the
     field never silently stops working. */
  function clientBranchFieldHtml(c) {
    const all = (state.branches || []);
    if (!all.length) {
      return `<input name="branch_name" value="${esc((c && c.branch_name) || "")}" placeholder="e.g. Banjara Hills"/>`;
    }
    const isNew = !(c && c.id);
    const access = state.access || {};
    const current = (c && c.branch_id) || null;
    let list = all.filter((b) => b.is_active !== false);
    // Keep the client's current office selectable even when it is archived or sits outside
    // this member's scope — otherwise merely opening and saving the form would move them.
    if (current && !list.some((b) => b.id === current)) {
      const known = all.find((b) => b.id === current);
      list = [{ id: current, name: (known && known.name) || (c && c.branch_name) || "Current office" }].concat(list);
    }
    const fallbackDefault = (list.find((b) => b.is_default) || {}).id;
    const selected = current || (isNew ? (access.primary_branch_id || fallbackDefault || "") : "");
    // Moving an existing client between offices is its own capability. A new client can
    // always be filed somewhere, and the server clamps the choice to the member's scope.
    const locked = !isNew && !!current && !can("clients.set_branch");
    return `<select name="branch_id"${locked ? " disabled" : ""}${current ? ' data-had-branch="1"' : ""}>
      <option value="">— No office —</option>
      ${list.map((b) => `<option value="${b.id}" ${String(selected) === String(b.id) ? "selected" : ""}>${esc(b.name)}${
        b.city ? " · " + esc(b.city) : ""}</option>`).join("")}
    </select>${locked ? `<div class="mw-hint" style="margin-top:4px">Only members who can move clients between offices may change this.</div>` : ""}`;
  }

  /* The assigned counsellor. An assignee who has since been deactivated is NOT in the
     active member list, and a plain rebuild of this <select> would therefore render with
     "Unassigned" selected — so opening the edit form and pressing Save silently dropped
     the assignment. Keep them as a selected (disabled) option instead. */
  function clientAssigneeSelectHtml(c, members) {
    const current = (c && c.assigned_to_user_id) || null;
    const list = members || [];
    const known = current != null && list.some((m) => m.user_id === current);
    const opts = [`<option value=""${current == null ? " selected" : ""}>Unassigned</option>`];
    if (current != null && !known) {
      opts.push(`<option value="${current}" selected disabled>${esc((c && c.assigned_to_name) || "Former member")} (removed)</option>`);
    }
    list.forEach((m) => {
      opts.push(`<option value="${m.user_id}" ${current === m.user_id ? "selected" : ""}>${esc(m.full_name || m.email)}</option>`);
    });
    const locked = !can("clients.assign");
    return `<select name="assigned_to_user_id"${locked ? " disabled" : ""}>${opts.join("")}</select>`;
  }
  // What the "Source detail" box means changes with the source picked next to it.
  const LEAD_SOURCE_DETAIL_LABEL = {
    referral: "Referred by", repeat_client: "Referred by",
    partner_agent: "Partner / agent name", institution_referral: "Institution",
    social: "Campaign", google_ads: "Campaign", education_fair: "Event",
    website: "Landing page / form", whatsapp: "Campaign",
  };

  const CLIENT_FORM_FIELD_KEYS = [
    "full_name", "email", "nationality", "date_of_birth", "passport_number", "passport_expiry",
    "application_reference", "destination_country_code", "visa_type", "intake", "target_date",
    "priority", "status",
    "whatsapp_number", "current_city", "gender", "guardian_name", "guardian_relation", "guardian_phone",
    // `admission_stage` is staff-editable: it records the UNIVERSITY phase, which the visa
    // pipeline cannot express on its own (a walk-in already holding an admit may sit at
    // `new_lead`), and `deferred` is only ever reachable from here. The server re-derives it
    // on a real stage transition, so a save that does not move the case leaves it alone.
    "study_level", "field_of_study", "admission_stage", "prior_refusal_history", "prior_refusal_notes",
    "highest_qualification", "qualification_score", "qualification_scale", "year_of_passing",
    "backlogs_count", "work_experience_band", "english_test_status", "english_test_type",
    "english_test_score", "english_test_date", "aptitude_test_type", "aptitude_test_score",
    // NB: `branch_name` is NOT here. The office is picked by id now (branch_id) and the
    // server writes branch_name from the chosen office. collectClientFormBody still
    // handles the legacy free-text input as a fallback for a workspace with no offices.
    "budget_band", "funding_source", "lead_source", "lead_source_detail",
    "next_followup_date",
  ];
  // Never sent empty — the server treats these as mandatory for a valid visa case.
  const CLIENT_FORM_REQUIRED_KEYS = ["full_name", "destination_country_code", "visa_type", "priority", "status"];

  function clientFormFieldsHtml(c, opts) {
    const p = opts.prefix;
    const members = opts.members || [];
    const dval = (v) => esc(String(v || "").slice(0, 10));
    const nval = (v) => (v === 0 || v ? esc(String(v)) : "");
    const cat = state.catalog || {};
    const channels = cat.marketing_consent_channels || [];
    const picked = c.marketing_consent_channels || [];
    const refusalOpen = c.prior_refusal_history && c.prior_refusal_history !== "none";
    const detailLabel = LEAD_SOURCE_DETAIL_LABEL[c.lead_source] || "Source detail";

    return `
      <div class="cp-sub-label">Client</div>
      <div class="mw-grid mw-sec">
        <div class="field span2"><label>Full name *</label><input name="full_name" required value="${esc(c.full_name || "")}" placeholder="As printed on the passport"/></div>
        <div class="field"><label>Phone</label><div class="phone-input-group"><select name="phone_cc" id="${p}PhoneCc" aria-label="Phone country code"></select><input name="phone" id="${p}Phone" inputmode="tel" placeholder="98765 43210"/></div></div>
        <div class="field"><label>Email</label><input type="email" name="email" value="${esc(c.email || "")}" placeholder="client@email.com"/></div>
        <div class="field"><label>WhatsApp number</label><input name="whatsapp_number" inputmode="tel" value="${esc(c.whatsapp_number || "")}" placeholder="Only if different"/></div>
        <div class="field"><label>Current city</label><input name="current_city" list="${p}CityList" value="${esc(c.current_city || "")}" placeholder="e.g. Hyderabad"/>${suggestList(p + "CityList", cat.city_suggestions)}</div>
      </div>

      <div class="cp-sub-label">Case &amp; risk</div>
      <div class="mw-grid mw-sec">
        <div class="field"><label>Destination country *</label><select name="destination_country_code" id="${p}Country" required></select></div>
        <div class="field"><label>Visa type *</label><select name="visa_type" id="${p}Visa" required></select></div>
        <div class="field" id="${p}IntakeWrap"><label>Target intake</label><select name="intake" id="${p}Intake"><option value="">—</option></select></div>
        <div class="field"><label>Level of study</label>${profileSelect("study_level", c.study_level)}</div>
        <div class="field span2"><label>Intended course / field</label><input name="field_of_study" list="${p}FieldList" value="${esc(c.field_of_study || "")}" placeholder="e.g. Data Science &amp; AI"/>${suggestList(p + "FieldList", cat.field_of_study_suggestions)}</div>
        <div class="field"><label>Admission stage</label>${profileSelect("admission_stage", c.admission_stage)}</div>
        <div class="field span2"><label>Prior visa / refusal history</label>${profileSelect("prior_refusal_history", c.prior_refusal_history)}</div>
        <div class="field span3" id="${p}RefusalWrap" style="${refusalOpen ? "" : "display:none"}"><label>Refusal details</label><textarea name="prior_refusal_notes" style="min-height:70px" placeholder="Country, visa type, month/year and the ground quoted — e.g. US F-1, Mar 2025, 214(b)">${esc(c.prior_refusal_notes || "")}</textarea></div>
      </div>

      <div class="cp-sub-label">Lead source &amp; ownership</div>
      <div class="mw-grid mw-sec">
        <div class="field"><label>How did they hear about us?</label>${profileSelect("lead_source", c.lead_source)}</div>
        <div class="field"><label id="${p}DetailLabel">${esc(detailLabel)}</label><input name="lead_source_detail" value="${esc(c.lead_source_detail || "")}" placeholder="Name or campaign"/></div>
        <div class="field"><label>Branch / office</label>${clientBranchFieldHtml(c)}</div>
        <div class="field"><label>Assigned counselor</label>${clientAssigneeSelectHtml(c, members)}</div>
        <div class="field"><label>Next follow-up</label><input type="date" name="next_followup_date" value="${dval(c.next_followup_date)}"/></div>
        <div class="field"><label>Key date (interview / travel)</label><input type="date" name="target_date" value="${dval(c.target_date)}"/></div>
        ${opts.withStatus ? `<div class="field"><label>Pipeline stage</label><select name="status" id="${p}Status"></select></div>` : ""}
        <div class="field"><label>Priority</label><select name="priority" id="${p}Priority"></select></div>
      </div>

      <details class="mw-fold"><summary>Academic profile, tests &amp; funding</summary>
        <div class="mw-grid">
          <div class="field"><label>Highest qualification</label>${profileSelect("highest_qualification", c.highest_qualification)}</div>
          <div class="field"><label>Marks / GPA</label><input name="qualification_score" value="${esc(c.qualification_score || "")}" placeholder="e.g. 7.2"/></div>
          <div class="field"><label>Scale</label>${profileSelect("qualification_scale", c.qualification_scale, "Scale…")}</div>
          <div class="field"><label>Year of passing</label><input type="number" name="year_of_passing" min="1950" max="2100" step="1" value="${nval(c.year_of_passing)}" placeholder="2023"/></div>
          <div class="field"><label>Backlogs / arrears</label><input type="number" name="backlogs_count" min="0" max="99" step="1" value="${nval(c.backlogs_count)}" placeholder="0"/></div>
          <div class="field"><label>Work experience</label>${profileSelect("work_experience_band", c.work_experience_band)}</div>
          <div class="field"><label>English test status</label>${profileSelect("english_test_status", c.english_test_status)}</div>
          <div class="field"><label>Test taken</label>${profileSelect("english_test_type", c.english_test_type)}</div>
          <div class="field"><label>Overall score</label><input name="english_test_score" value="${esc(c.english_test_score || "")}" placeholder="7.5 / 110 / 65"/></div>
          <div class="field"><label>Test date</label><input type="date" name="english_test_date" value="${dval(c.english_test_date)}"/></div>
          <div class="field"><label>Aptitude test</label>${profileSelect("aptitude_test_type", c.aptitude_test_type)}</div>
          <div class="field"><label>Aptitude score</label><input name="aptitude_test_score" value="${esc(c.aptitude_test_score || "")}" placeholder="e.g. 318"/></div>
          <div class="field"><label>Budget (per year)</label>${profileSelect("budget_band", c.budget_band)}</div>
          <div class="field span2"><label>How will it be funded?</label>${profileSelect("funding_source", c.funding_source)}</div>
        </div>
      </details>

      <details class="mw-fold"><summary>Identity, family &amp; documents</summary>
        <div class="mw-grid">
          <div class="field"><label>Nationality</label><input name="nationality" value="${esc(c.nationality || "")}"/></div>
          <div class="field"><label>Gender</label>${profileSelect("gender", c.gender)}</div>
          <div class="field"><label>Date of birth</label><input type="date" name="date_of_birth" max="${isoToday()}" value="${dval(c.date_of_birth)}"/></div>
          <div class="field"><label>Passport number</label><input name="passport_number" value="${esc(c.passport_number || "")}"/></div>
          <div class="field"><label>Passport expiry</label><input type="date" name="passport_expiry" value="${dval(c.passport_expiry)}"/></div>
          <div class="field"><label>Application reference</label><input name="application_reference" value="${esc(c.application_reference || "")}"/></div>
          <div class="field"><label>Parent / guardian name</label><input name="guardian_name" value="${esc(c.guardian_name || "")}"/></div>
          <div class="field"><label>Relationship</label>${profileSelect("guardian_relation", c.guardian_relation)}</div>
          <div class="field"><label>Parent / guardian phone</label><input name="guardian_phone" inputmode="tel" value="${esc(c.guardian_phone || "")}" placeholder="+91 98765 43210"/></div>
        </div>
      </details>

      <div class="cp-sub-label">${opts.withNote ? "Notes &amp; consent" : "Consent"}</div>
      ${opts.withNote ? `<div class="field"><label>First note (optional)</label><textarea name="initial_note" style="min-height:70px" placeholder="e.g. Walk-in enquiry, father wants Canada, sister already in Toronto…"></textarea></div>` : ""}
      ${opts.withDpaConsent ? `<div class="consent-field"><input type="checkbox" id="${p}Consent" name="client_consent_confirmed" required/><label for="${p}Consent">This client has consented to their personal data being collected and processed through Rilono (see <a href="/dpa" target="_blank" rel="noopener">Data Processing Agreement</a>).</label></div>` : ""}
      <div class="field" style="margin-bottom:8px"><label>Consent to receive updates on</label></div>
      <div class="mw-checks">
        ${channels.map((ch) => `<label><input type="checkbox" name="marketing_consent_channels" value="${esc(ch.key)}" ${picked.indexOf(ch.key) !== -1 ? "checked" : ""}/>${esc(ch.label)}</label>`).join("")}
      </div>
      <div class="mw-checks">
        <label><input type="checkbox" name="institution_share_consent" ${c.institution_share_consent ? "checked" : ""}/>Consent to share this profile with universities / partner institutions abroad</label>
      </div>
      <p class="mw-hint">Promotional contact and sharing the profile abroad are separate permissions — leave them unticked unless the client agreed to them.</p>`;
  }

  /* Wires the cascades, phone parts and conditional fields for markup built above.
     Every lookup is scoped to the form itself — the app has other views carrying ids in the
     same namespace, and a document-wide $() would bind the modal's cascade to whatever is
     rendered behind it. */
  function wireClientFormFields(c, opts) {
    const p = opts.prefix;
    const CAT = "student";
    const form = $("#" + opts.formId);
    if (!form) return;
    const pick = (suffix) => $("#" + p + suffix, form);
    const countrySel = pick("Country"), visaSel = pick("Visa"),
      intakeSel = pick("Intake"), intakeWrap = pick("IntakeWrap");

    const statusSel = pick("Status");
    const prioSel = pick("Priority");
    if (prioSel) prioSel.innerHTML = state.catalog.priorities.map((pr) => `<option value="${pr.key}" ${(c.priority || "normal") === pr.key ? "selected" : ""}>${esc(pr.label)}</option>`).join("");

    // A client's stored visa type / intake can fall out of the catalog (intakes are
    // materialized forward, so a past one disappears). Keep the stored value as an option
    // or editing an unrelated field would silently drop it.
    function withStored(options, stored) {
      const list = (options || []).slice();
      if (stored && list.indexOf(stored) === -1) list.unshift(stored);
      return list;
    }
    function fillVisas() {
      const ct = countryByCode(countrySel.value);
      const sameCountry = ct && ct.code === c.destination_country_code;
      const visas = withStored(ct ? ct.visa_types[CAT] : [], sameCountry ? c.visa_type : "");
      visaSel.innerHTML = visas.map((v) => `<option value="${esc(v)}" ${c.visa_type === v ? "selected" : ""}>${esc(v)}</option>`).join("");
      if (ct) {
        intakeWrap.style.display = "";
        intakeSel.innerHTML = `<option value="">—</option>` + withStored(ct.student_intakes, sameCountry ? c.intake : "")
          .map((i) => `<option value="${esc(i)}" ${c.intake === i ? "selected" : ""}>${esc(i)}</option>`).join("");
      } else { intakeWrap.style.display = "none"; intakeSel.innerHTML = `<option value="">—</option>`; }
      // Stage wording is destination-specific, so the picker has to be rebuilt whenever the
      // destination changes — otherwise it keeps the previous destination's labels. The key
      // already chosen stays chosen; the keys themselves are the same everywhere.
      if (statusSel) {
        const stages = stagesForClient({ destination_country_code: countrySel.value });
        const picked = statusSel.value || c.status || "new_lead";
        const known = stages.some((s) => s.key === picked);
        const keep = known ? picked : "";
        // A stored stage the catalog no longer carries has no <option> to select, and the
        // browser silently falls back to the first one — so opening this form to fix a phone
        // number would rewind the case to New Lead and drag the admissions milestone down
        // with it. Show the stored key as a disabled option instead: the counsellor can see
        // the case sits on an unknown stage, and its empty value means `status` is dropped
        // by collectClientFormBody (a required key is never sent empty), so saving without
        // choosing a stage leaves the case exactly where it is.
        const unknown = known ? ""
          : `<option value="" selected disabled>${esc(String(picked).replace(/_/g, " "))} — unknown stage, leave as is</option>`;
        statusSel.innerHTML = unknown + stages.map((s) => `<option value="${s.key}" ${keep === s.key ? "selected" : ""}>${esc(s.label)}</option>`).join("");
      }
    }
    const list = state.catalog.countries.filter((ct) => (ct.visa_types[CAT] || []).length);
    countrySel.innerHTML = list.map((ct) => `<option value="${ct.code}" ${c.destination_country_code === ct.code ? "selected" : ""}>${ct.flag_emoji} ${esc(ct.name)}</option>`).join("");
    countrySel.onchange = fillVisas;
    fillVisas();

    const phoneParts = splitPhone(c.phone || "");
    pick("PhoneCc").innerHTML = phoneCcOptions(phoneParts.dial);
    pick("Phone").value = phoneParts.local;

    // "Refused once" isn't actionable — ask for the detail the moment there is one to give.
    const refusalSel = form.prior_refusal_history;
    const refusalWrap = pick("RefusalWrap");
    if (refusalSel && refusalWrap) {
      refusalSel.onchange = () => {
        const on = refusalSel.value && refusalSel.value !== "none";
        refusalWrap.style.display = on ? "" : "none";
        // Clearing it too, so a corrected answer can't leave contradictory notes behind
        // on a client whose history now reads "No prior application".
        if (!on && form.prior_refusal_notes) form.prior_refusal_notes.value = "";
      };
    }
    const sourceSel = form.lead_source;
    const detailLabel = pick("DetailLabel");
    if (sourceSel && detailLabel) {
      sourceSel.onchange = () => { detailLabel.textContent = LEAD_SOURCE_DETAIL_LABEL[sourceSel.value] || "Source detail"; };
    }
  }

  /* Reads the whole intake record off a form. Empty values ARE sent (so a field can be
     cleared on edit) except for the handful the server requires. */
  function collectClientFormBody(f) {
    const body = {};
    CLIENT_FORM_FIELD_KEYS.forEach((k) => {
      const el = f[k]; if (!el) return;
      const v = (el.value || "").trim();
      if (v === "" && CLIENT_FORM_REQUIRED_KEYS.indexOf(k) !== -1) return;
      // Email is validated as an email address server-side, so "cleared" must be null.
      body[k] = (k === "email" && v === "") ? null : v;
    });
    const phoneLocal = (f.phone.value || "").trim();
    const dial = (f.phone_cc && f.phone_cc.value) || DEFAULT_DIAL;
    body.phone = phoneLocal ? (phoneLocal[0] === "+" ? phoneLocal : dial + " " + phoneLocal) : "";
    const assign = f.assigned_to_user_id ? f.assigned_to_user_id.value : "";
    body.assigned_to_user_id = assign ? parseInt(assign, 10) : null;
    // Office. Sent as an int, like assigned_to_user_id. An empty pick is only forwarded as
    // an explicit null when the client HAD an office (a deliberate clear) — on a brand-new
    // client we leave the key out entirely so the server can apply its own default rather
    // than us pinning the record to "no office".
    if (f.branch_id) {
      const bid = (f.branch_id.value || "").trim();
      if (bid) body.branch_id = parseInt(bid, 10);
      else if (f.branch_id.dataset.hadBranch === "1") body.branch_id = null;
    } else if (f.branch_name) {
      body.branch_name = (f.branch_name.value || "").trim();   // pre-offices server
    }
    body.marketing_consent_channels = $$('input[name="marketing_consent_channels"]:checked', f).map((el) => el.value);
    body.institution_share_consent = !!(f.institution_share_consent && f.institution_share_consent.checked);
    return body;
  }

  /* ---------------- possible-duplicate warning ----------------
     The server soft-blocks a client that looks like one the workspace already holds
     (POST/PATCH /clients -> 409 duplicate_client). This renders that answer INSIDE the
     open client form rather than in a confirm dialog: the form is long and the typed
     intake would be lost if a modal replaced it, and the warning belongs where the eye
     already is — directly above the button that was just pressed. */
  function duplicateMatchHtml(match) {
    const meta = [
      match.stage && match.stage.label,
      match.destination_country_name,
      match.branch_name,
      match.assigned_to_name ? "with " + match.assigned_to_name : null,
      match.created_at ? "added " + fmtDate(match.created_at) : null,
    ].filter(Boolean);
    const contact = [match.email, match.phone].filter(Boolean);
    return `<div class="dupw-row">
      <div class="dupw-row-main">
        <div class="dupw-name">${esc(match.full_name || "Unnamed client")}</div>
        ${contact.length ? `<div class="dupw-contact">${esc(contact.join(" · "))}</div>` : ""}
        ${meta.length ? `<div class="dupw-meta">${esc(meta.join(" · "))}</div>` : ""}
        <div class="dupw-chips">${(match.reason_labels || []).map((r) => `<span class="dupw-chip">${esc(r)}</span>`).join("")}</div>
      </div>
      ${match.in_scope && match.id
        ? `<button type="button" class="btn btn-ghost btn-sm dupw-open" data-dup-open="${match.id}">Open file</button>`
        /* No link out of here for a record this member's access scope doesn't cover —
           the file would refuse to open anyway. Say who to ask instead. */
        : `<span class="dupw-locked">Another team’s file</span>`}
    </div>`;
  }

  function renderDuplicateWarning(box, detail, isEdit) {
    const list = (detail && detail.duplicates) || [];
    box.innerHTML = `
      <div class="dupw-head">
        <span class="dupw-icon">⚠️</span>
        <div>
          <div class="dupw-title">${list.length === 1 ? "This may already be one of your clients" : "This may already be in your workspace"}</div>
          <div class="dupw-sub">${esc(detail.message || "")} ${isEdit ? "Save again to keep these details anyway." : "Press Add anyway to open a second file regardless."}</div>
        </div>
      </div>
      <div class="dupw-list">${list.map(duplicateMatchHtml).join("")}</div>`;
    box.classList.remove("hidden");
    $$("[data-dup-open]", box).forEach((btn) => {
      btn.onclick = () => {
        const id = parseInt(btn.getAttribute("data-dup-open"), 10);
        closeModal();
        openClient(id);
      };
    });
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  /* ---------------- add / edit client form ---------------- */
  // opts2 (all optional): { forceCreate, heading, onCreated } — the Leads convert flow
  // reuses this whole form as a prefilled "Add client" (forceCreate keeps a truthy
  // client object from flipping it into edit mode; onCreated(client) runs after a
  // successful POST and may return true to take over post-save navigation).
  function openClientForm(client, opts2) {
    opts2 = opts2 || {};
    const isEdit = !!client && !opts2.forceCreate;
    const members = teamMembersCache || [];
    const c = client || {};
    // "cform", not "cf" — the Course Finder view renders its own #cfCountry filter and both
    // can be in the DOM at once (the modal opens over whatever view you were on).
    const opts = { prefix: "cform", members: members, formId: "clientForm", withStatus: true, withNote: !isEdit, withDpaConsent: !isEdit };

    openModal(`
      <div class="modal-head"><h3>${isEdit ? "Edit client" : esc(opts2.heading || "Add new client")}</h3><button class="x" onclick="__ent.closeModal()">×</button></div>
      <form id="clientForm">
      <div class="modal-body">
        ${clientFormFieldsHtml(c, opts)}
        <div id="clientDupWarn" class="dupw hidden"></div>
        <div id="clientFormError" class="auth-error hidden"></div>
      </div>
      <div class="modal-foot">
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary" id="clientSaveBtn">${isEdit ? "Save changes" : "Add client"}</button>
      </div></form>`, { wide: true });

    wireClientFormFields(c, opts);

    // Flipped by a duplicate 409 and never unset: the second press of the same button is
    // the acknowledgement the server is waiting for. Re-running the check after they have
    // read it would only stop them saying yes.
    let dupAcknowledged = false;
    const saveLabel = () => (isEdit
      ? (dupAcknowledged ? "Save anyway" : "Save changes")
      : (dupAcknowledged ? "Add anyway" : "Add client"));

    $("#clientForm").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target; const btn = $("#clientSaveBtn"); const err = $("#clientFormError");
      err.classList.add("hidden");
      const body = collectClientFormBody(f);
      if (dupAcknowledged) body.allow_duplicate = true;
      if (!isEdit) body.visa_category = "student";
      if (!isEdit && f.initial_note && f.initial_note.value.trim()) body.initial_note = f.initial_note.value.trim();

      if (!isEdit) {
        if (!f.client_consent_confirmed || !f.client_consent_confirmed.checked) {
          err.textContent = "Please confirm the client has consented to their data being processed.";
          err.classList.remove("hidden");
          return;
        }
        body.client_consent_confirmed = true;
      }

      btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
      try {
        if (isEdit) {
          await api("/clients/" + client.id, { method: "PATCH", body });
          toast("Client updated", "success");
        } else {
          const r = await api("/clients", { method: "POST", body });
          state.subscription = r.subscription || state.subscription; updatePlanChip();
          toast("Client added", "success");
          if (opts2.onCreated && r.client) {
            closeModal();
            let handled = false;
            try { handled = await opts2.onCreated(r.client); } catch (e2) { /* link-back is best-effort */ }
            if (handled) return;
          }
        }
        closeModal();
        if (isEdit && state.view === "clientPage" && state.activeClient === client.id) { openClient(client.id); }
        else if (state.view === "clients") loadAndRenderClientList();
        else navigate("clients");
      } catch (ex) {
        if (ex.status === 402) { closeModal(); toast(ex.message, "error"); navigate("credits"); return; }
        const detail = ex.status === 409 && ex.data ? ex.data.detail : null;
        if (detail && detail.code === "duplicate_client") {
          dupAcknowledged = true;
          renderDuplicateWarning($("#clientDupWarn"), detail, isEdit);
          return;
        }
        err.textContent = ex.message; err.classList.remove("hidden");
      } finally { btn.disabled = false; btn.innerHTML = saveLabel(); }
    };
  }

  /* ---------------- full-page client profile ---------------- */
  function fmtSize(bytes) {
    const b = Number(bytes || 0);
    if (!b) return "—";
    if (b < 1024) return b + " B";
    if (b < 1048576) return (b / 1024).toFixed(0) + " KB";
    return (b / 1048576).toFixed(1) + " MB";
  }
  function docIcon(filename) {
    const ext = String(filename || "").split(".").pop().toLowerCase();
    if (ext === "pdf") return "📕";
    if (["jpg", "jpeg", "png", "webp", "gif", "heic"].includes(ext)) return "🖼️";
    if (["doc", "docx"].includes(ext)) return "📘";
    if (["xls", "xlsx", "csv"].includes(ext)) return "📊";
    return "📄";
  }

  /* ---------------- rich text (email composer) ----------------
     The composer is a contenteditable, so three places need HTML that is safe to
     put in the DOM: what a user pastes in, what we render back from the server,
     and what we POST. sanitizeRichHtml() is the one gate for all three — it mirrors
     app/utils/html_sanitizer.py (which sanitizes again server-side, authoritatively).
     Everything is rebuilt node by node: nothing from the input string is ever
     re-inserted as markup. */
  const RT_ALLOWED_TAGS = {
    P: 1, BR: 1, DIV: 1, SPAN: 1, B: 1, STRONG: 1, I: 1, EM: 1, U: 1, S: 1, STRIKE: 1,
    A: 1, UL: 1, OL: 1, LI: 1, BLOCKQUOTE: 1, H2: 1, H3: 1, H4: 1, HR: 1, PRE: 1, CODE: 1,
    // Kept so a fee table pasted from Excel/Word survives as a table instead of
    // collapsing into one run-on line. Matches app/utils/html_sanitizer.py.
    TABLE: 1, THEAD: 1, TBODY: 1, TFOOT: 1, TR: 1, TD: 1, TH: 1, CAPTION: 1,
  };
  // Tags whose *contents* go too (rather than being unwrapped into plain text).
  const RT_DROP_SUBTREE = {
    SCRIPT: 1, STYLE: 1, IFRAME: 1, OBJECT: 1, EMBED: 1, SVG: 1, MATH: 1, TEMPLATE: 1,
    NOSCRIPT: 1, TEXTAREA: 1, TITLE: 1, LINK: 1, META: 1, BASE: 1, FORM: 1, INPUT: 1,
    BUTTON: 1, SELECT: 1, IMG: 1, VIDEO: 1, AUDIO: 1, CANVAS: 1,
  };
  const RT_INVISIBLE = /[\x00-\x20\u00a0\u180e\u200b-\u200f\u2028-\u202f\u2060-\u206f\ufeff]/g;

  function safeLinkUrl(raw) {
    const value = String(raw == null ? "" : raw).trim();
    if (!value) return null;
    const probe = value.replace(RT_INVISIBLE, "").toLowerCase();
    if (!/^(https?:\/\/|mailto:|tel:)/.test(probe)) return null;
    if (/[\r\n\t]/.test(value)) return null;
    return value.slice(0, 2000);
  }

  function sanitizeRichHtml(html) {
    const parsed = new DOMParser().parseFromString("<body>" + String(html == null ? "" : html) + "</body>", "text/html");
    const out = document.createElement("div");
    (function walk(source, target, depth) {
      if (depth > 40) return;
      Array.prototype.forEach.call(source.childNodes, (node) => {
        if (node.nodeType === 3) {
          target.appendChild(document.createTextNode(node.nodeValue.replace(/[\u202a-\u202e\u2066-\u2069]/g, "")));
          return;
        }
        if (node.nodeType !== 1) return;               // comments, CDATA, PIs
        const tag = node.tagName;
        if (RT_DROP_SUBTREE[tag]) return;
        if (!RT_ALLOWED_TAGS[tag]) { walk(node, target, depth + 1); return; }  // unwrap, keep text
        const el = document.createElement(tag === "STRIKE" ? "S" : tag);
        if (tag === "A") {
          const href = safeLinkUrl(node.getAttribute("href"));
          if (!href) { walk(node, target, depth + 1); return; }
          el.setAttribute("href", href);
          el.setAttribute("target", "_blank");
          el.setAttribute("rel", "noopener noreferrer nofollow");
        }
        target.appendChild(el);
        walk(node, el, depth + 1);
      });
    })(parsed.body, out, 0);
    return out.innerHTML;
  }

  // Plain-text bodies (inbound replies, legacy sends) rendered with clickable links.
  function plainTextToHtml(text) {
    return esc(text)
      .replace(/(https?:\/\/[^\s<]+[^\s<.,;:!?)\]])/g,
        (m) => `<a href="${m}" target="_blank" rel="noopener noreferrer nofollow">${m}</a>`)
      .replace(/\r?\n/g, "<br>");
  }

  /* Starter templates for the composer. Merge fields are resolved at insert time,
     so a half-substituted "{{first_name}}" can never reach a student. */
  const EMAIL_TEMPLATES = [
    {
      key: "documents", icon: "📄", label: "Request documents",
      hint: "Ask for the files you're missing",
      subject: "Documents needed for your {{destination}} application",
      body: "<p>Hi {{first_name}},</p><p>Your {{visa_type}} application is moving along nicely. To take the next step I need a few documents from you:</p><ul><li>Passport — photo page</li><li>Latest 6 months of bank statements</li><li>Academic transcripts and certificates</li></ul><p>You can reply to this email with the files attached, and I'll confirm as soon as they're in.</p>",
    },
    {
      key: "interview", icon: "🎤", label: "Interview preparation",
      hint: "Prep notes before the visa interview",
      subject: "Preparing for your {{destination}} visa interview",
      body: "<p>Hi {{first_name}},</p><p>Your interview is the last big step, so let's get you ready for it.</p><ul><li>Be clear on why you chose this course and this university</li><li>Know who is funding your studies and be ready to show the proof</li><li>Have a straight answer for what you'll do after you graduate</li></ul><p>Answer calmly and honestly — short, confident answers work best. I'll send a practice session across shortly.</p>",
    },
    {
      key: "offer", icon: "🎓", label: "Offer received — next steps",
      hint: "Congratulate and lay out what's next",
      subject: "Congratulations! Next steps for your {{destination}} offer",
      body: "<p>Hi {{first_name}},</p><p>Congratulations — this is a great result, and everything from here is process.</p><p>Here's what happens next:</p><ol><li>Accept the offer and pay the deposit before the deadline</li><li>Arrange your funds and keep the statements ready</li><li>We prepare and submit your visa application</li></ol><p>I'll guide you through each step.</p>",
    },
    {
      key: "payment", icon: "💳", label: "Payment reminder",
      hint: "Gentle nudge about a pending fee",
      subject: "Reminder: pending payment for your {{destination}} application",
      body: "<p>Hi {{first_name}},</p><p>Just a gentle reminder that a payment on your file is still pending. Clearing it lets us keep your application on schedule.</p><p>If you've already paid, ignore this note — and if anything is unclear, reply here and I'll sort it out.</p>",
    },
    {
      key: "appointment", icon: "📅", label: "Appointment confirmed",
      hint: "Confirm a booked date and what to bring",
      subject: "Your {{destination}} visa appointment is confirmed",
      body: "<p>Hi {{first_name}},</p><p>Your appointment is confirmed. Please arrive at least 30 minutes early and carry:</p><ul><li>Your passport</li><li>The appointment confirmation</li><li>Your full document folder</li></ul><p>Tell me if anything changes and I'll rearrange it.</p>",
    },
    {
      key: "checkin", icon: "👋", label: "Friendly check-in",
      hint: "Warm nudge when a file goes quiet",
      subject: "Quick check-in on your {{destination}} application",
      body: "<p>Hi {{first_name}},</p><p>I wanted to check in on your application. Nothing is urgent right now — I just want to make sure you're not stuck on anything.</p><p>If you have questions about the timeline, funds or the next steps, reply here and I'll walk you through it.</p>",
    },
  ];

  // Composer dropdowns close on any outside click. Registered once (not per render)
  // so re-rendering the Emails tab can't stack duplicate document listeners.
  function emCloseMenus() {
    ["#emTplMenu", "#emFieldMenu"].forEach((sel) => {
      const menu = $(sel);
      if (menu) menu.classList.add("hidden");
    });
    ["#emTplBtn", "#emFieldBtn"].forEach((sel) => {
      const btn = $(sel);
      if (btn) btn.setAttribute("aria-expanded", "false");
    });
  }
  document.addEventListener("click", emCloseMenus);

  const EMAIL_MERGE_FIELDS = [
    { key: "first_name", label: "First name" },
    { key: "full_name", label: "Full name" },
    { key: "destination", label: "Destination country" },
    { key: "visa_type", label: "Visa type" },
    { key: "intake", label: "Intake" },
    { key: "target_date", label: "Key date" },
    { key: "counselor", label: "Your name" },
    { key: "company", label: "Company name" },
  ];

  async function openClient(id, opts) {
    state.activeClient = id;
    if (state.view !== "clientPage") state.clientReturnView = state.view || "clients";
    state.view = "clientPage";
    syncUrl("/enterprise/clients/" + id, opts);
    $("#globalSearchBox").style.display = "none";
    $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === "clients"));
    const c = $("#content");
    if (!can("clients.view")) { c.innerHTML = deniedCard(VIEW_DENIED_COPY.clients); return; }
    c.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
    await ensureTeam();
    let data;
    try { data = await api("/clients/" + id); } catch (ex) { c.innerHTML = errBox(ex); return; }
    renderClientPage(data);
  }

  function renderClientPage(data) {
    const cl = data.client;
    // One coarse "can they edit anything here" used to gate every control on this page.
    // Each area now asks for the capability it actually needs, so a role can hand out
    // note-writing without handing out document deletion.
    const canEdit = can("clients.edit");
    const canShare = can("portal.share");
    const canWriteNotes = can("notes.write");
    const canModerateNotes = can("notes.moderate");
    const canSendEmail = can("emails.send");
    const canUploadDocs = can("documents.upload");
    const canAcceptDocs = can("documents.accept");
    const canDeleteDocs = can("documents.delete");
    const canRequestDocs = can("documents.request");
    const canDownloadDocs = can("documents.download");
    const canInviteInterview = can("interviews.invite");
    const canInviteCopilot = can("copilot.invite");
    const canRunInterview = can("interviews.run");
    const canManageUnis = can("universities.manage");
    const canShortlistAi = can("ai.shortlist");
    const canWritingAi = can("ai.writing");
    const canDeepScan = can("ai.deepscan");
    const canSeeSensitive = can("clients.view_sensitive");
    const members = teamMembersCache || [];
    const grad = `linear-gradient(135deg,${cl.country.gradient_from},${cl.country.gradient_to})`;
    const hero = clientHeroTheme(cl);
    const docs = data.documents || [];
    const pendingDocIds = new Set();  // docs uploaded this session, awaiting AI validation (for the "scanning…" badge)
    // Price + affordability of ONE document scan, refreshed from every documents payload
    // so the button never quotes a stale price after a top-up or a wallet drain.
    let scanPricing = data.scan_pricing || null;
    const canSpendCredits = can("credits.spend");
    const iv = { started: false, history: [], finished: false, feedback: null, busy: false, voiceOn: false, sessions: null, spoken: 0 };
    // Client-facing copilot invite state. invite: undefined = not fetched yet,
    // null = none exists. cp.link holds the raw link from the latest POST response
    // only — it is never returned by a GET, so "Copy link" shows just in that window.
    const cp = { invite: undefined, link: null, busy: false };
    const dr = { request: undefined };  // secure document-request state (lazy-loaded)
    // Email composer state. Kept on the client page (not inside renderEmails) so a
    // half-written message survives switching tabs and re-rendering the thread.
    const em = {
      subject: "", html: "", attachments: [], busy: false,
      draftsLoaded: false, filter: "all", query: "", expanded: {}, seq: 0,
    };
    const uni = { data: null, suggestions: [] };  // university shortlist state (lazy-loaded)
    // Deep Scan tab state (lazy-loaded): stored scan history + the currently open report.
    const ds = { scans: null, active: null, pricing: null, aiAvailable: true, loading: false, error: null, busy: false };
    // Writing Studio tab state (lazy-loaded). `form` is the composer's live values, held
    // here rather than read off the DOM so a half-filled brief survives a tab switch.
    const ws = {
      drafts: null, active: null, catalog: null, defaults: null, pricing: null,
      aiAvailable: true, loading: false, error: null, busy: false,
      docType: "sop", composerOpen: true, refineOpen: false, refineText: "",
      versions: null, versionsRoot: null,
      form: {
        university: "", program: "", study_level: "", intake: "", brief: "",
        recommender_type: "professor", recommender_name: "", recommender_title: "",
        recommender_org: "", recommender_email: "", relationship_context: "",
      },
    };
    let overviewEditing = false;  // inline "Edit details" mode on the Overview tab
    let openStageKey = null;      // stage whose case-record panel is expanded under the tracker
    $("#viewTitle").textContent = cl.full_name;

    const detail = (label, val) => `<div class="detail-item"><label>${label}</label><div>${val || "—"}</div></div>`;

    $("#content").innerHTML = `
      <div class="client-page">
        <div class="cp-actionbar">
          <button class="cp-back" id="cpBack"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M19 12H5M11 6l-6 6 6 6" stroke-linecap="round" stroke-linejoin="round"/></svg> Back</button>
          <div style="flex:1"></div>
          ${canShare ? `<button class="btn btn-soft btn-sm" id="cpShare">🔗 Share with client</button>` : ""}
          ${canEdit ? `<button class="btn btn-soft btn-sm" id="cpEdit">Edit details</button>` : ""}
        </div>
        <div class="cp-hero cp-hero--${hero.key}" style="--cp-hero-fallback:${grad}"
          aria-label="${esc(cl.destination_country_name)} case for ${esc(cl.full_name)}">
          <div class="cp-destination-seal" aria-hidden="true">
            <span>Destination</span>
            <div class="cp-seal-code"><strong>${esc(hero.code)}</strong><small>${esc(cl.country.flag_emoji || "🌐")}</small></div>
          </div>
          <div class="cp-hmeta">
            <div class="cp-kicker">Student dossier</div>
            <h1>${esc(cl.full_name)}</h1>
            <div class="cp-hsub">${esc(cl.destination_country_name)} · ${esc(cl.visa_type)}${cl.intake ? " · " + esc(cl.intake) : ""}</div>
          </div>
          <div class="cp-hstatus">${statusPill(cl.stage)}</div>
        </div>
        <div class="cp-tabs" id="cpTabs">
          <button class="cp-tab active" data-tab="overview">Overview</button>
          <button class="cp-tab" data-tab="documents">Documents${docs.length ? ` (${docs.length})` : ""}</button>
          <button class="cp-tab" data-tab="notes">Notes${data.notes.length ? ` (${data.notes.length})` : ""}</button>
          <button class="cp-tab" data-tab="emails">Emails${data.emails.length ? ` (${data.emails.length})` : ""}</button>
          <button class="cp-tab" data-tab="payments">💳 Payments</button>
          <button class="cp-tab" data-tab="universities">🎓 Universities</button>
          <button class="cp-tab" data-tab="interview">🎤 Interview</button>
          <button class="cp-tab" data-tab="copilot">✨ Copilot</button>
          <button class="cp-tab" data-tab="writing">✍️ SOP &amp; LOR</button>
          <button class="cp-tab" data-tab="deepscan">🛡️ Deep Scan</button>
        </div>
        <div class="cp-body" id="cpBody"></div>
      </div>`;

    $("#cpBack").onclick = () => navigate(state.clientReturnView || "clients");
    if (canEdit) {
      // Edit inline within the Overview pane (no popup) instead of opening a modal.
      // Deleting is deliberately NOT here — it lives in a type-to-confirm "Danger zone"
      // at the bottom of Edit details, so a client can't be removed with a stray click.
      $("#cpEdit").onclick = () => { overviewEditing = true; showTab("overview"); };
    }
    if (canShare) $("#cpShare").onclick = openPortalShareModal;
    const body = $("#cpBody");

    /* ---- Share portal with client (read-only tracking link) ----
       Mirrors the interview-invite flow: secure emailed link + one-time code.
       The raw link is only known right after a send, so "Copy link" appears
       only in that window; a resend rotates the token (old link dies). */
    const ps = { share: undefined, link: null, busy: false };
    function psStatusHtml() {
      const first = (cl.full_name || "the student").split(" ")[0];
      const s = ps.share;
      if (!cl.email) {
        return `<p class="muted" style="margin:0 0 14px">Add an email address to ${esc(first)}'s profile first — the secure portal link is emailed to them.</p>
          <button class="btn btn-primary btn-block" id="psAddEmail">Add an email</button>`;
      }
      if (s && s.live) {
        const opens = s.open_count || 0;
        const opened = opens > 0
          ? `Opened ${opens} time${opens === 1 ? "" : "s"}${s.last_opened_at ? " · last " + fmtDate(s.last_opened_at) : ""}`
          : "Not opened yet";
        const meta = `Shared${s.created_at ? " " + fmtDate(s.created_at) : ""}${s.created_by_name ? " by " + esc(s.created_by_name) : ""}${s.expires_at ? " · valid until " + fmtDate(s.expires_at) : ""}`;
        return `<p class="ps-lead">A secure portal link is with <b>${esc(s.email)}</b>. ${esc(first)} confirms a one-time code sent to that address, then sees a <b>view-only</b> copy of this case — stages, recorded details, documents, universities and payments. Internal notes are never shown.</p>
          <div class="ps-status${opens > 0 ? " is-open" : ""}">
            <span class="ps-status-ic">${opens > 0 ? "✓" : "✉"}</span>
            <div class="ps-status-txt">
              <b>${esc(opened)}</b>
              <span class="ps-meta">${meta}</span>
            </div>
          </div>
          <div class="ps-actions">
            <button class="btn btn-soft btn-sm" id="psResend">Resend new link</button>
            ${ps.link ? `<button class="btn btn-ghost btn-sm" id="psCopy">Copy link</button>` : ""}
            <button class="btn btn-danger btn-sm ps-revoke" id="psRevoke">Revoke access</button>
          </div>`;
      }
      return `<p style="margin:0 0 10px">Email <b>${esc(cl.email)}</b> a secure link so ${esc(first)} can follow their own application — journey stage, recorded case details, profile info, documents on file, university shortlist and payment history.</p>
        <p style="margin:0 0 10px">Everything is <b>strictly view-only</b> — ${esc(first)} can't change anything, and your internal notes are never shown.</p>
        <p class="muted" style="font-size:12.5px;margin:0 0 16px">🔒 They confirm a one-time code sent to their email before viewing. You can revoke access anytime.</p>
        <button class="btn btn-primary btn-block" id="psSend">✉ Share portal with ${esc(first)}</button>`;
    }
    function psDraw() {
      const b = $("#psBody");
      if (!b) return;
      b.innerHTML = ps.share === undefined
        ? '<div style="text-align:center;padding:18px 0"><span class="spinner"></span></div>'
        : psStatusHtml();
      const send = $("#psSend"); if (send) send.onclick = () => psSend();
      const rs = $("#psResend"); if (rs) rs.onclick = () => psSend();
      const rv = $("#psRevoke"); if (rv) rv.onclick = psRevoke;
      const ae = $("#psAddEmail"); if (ae) ae.onclick = () => { closeModal(); overviewEditing = true; showTab("overview"); };
      const cp = $("#psCopy"); if (cp) cp.onclick = async () => {
        try { await navigator.clipboard.writeText(ps.link); toast("Link copied", "success"); }
        catch (e) { toast("Couldn't copy — the emailed link still works", "error"); }
      };
    }
    async function psSend() {
      if (ps.busy) return;
      ps.busy = true;
      const btn = $("#psSend") || $("#psResend");
      if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Sending…'; }
      try {
        const r = await api(`/clients/${cl.id}/portal-share`, { method: "POST" });
        ps.share = r.share || null;
        ps.link = r.link || null;
        toast(r.message || "Portal link sent", r.email_sent ? "success" : "error");
      } catch (ex) { toast(ex.message, "error"); }
      ps.busy = false;
      if (state.activeClient !== cl.id) return;  // user moved on mid-request
      psDraw();
    }
    async function psRevoke() {
      const first = (cl.full_name || "The student").split(" ")[0];
      const ok = await confirmModal(`${first} will lose access to their portal until you share it again.`, { title: "Revoke portal access?", okText: "Revoke" });
      if (ok) {
        try {
          await api(`/clients/${cl.id}/portal-share/revoke`, { method: "POST" });
          ps.share = null; ps.link = null;
          toast("Portal access revoked", "success");
        } catch (ex) { toast(ex.message, "error"); }
      }
      if (state.activeClient !== cl.id) return;  // user moved on mid-request
      openPortalShareModal();  // confirmModal replaced + closed the share modal — restore it
    }
    function openPortalShareModal() {
      openModal(`<div class="modal-head"><h3>Share with ${esc((cl.full_name || "client").split(" ")[0])}</h3><button class="x" onclick="__ent.closeModal()">×</button></div>
        <div class="modal-body" id="psBody"></div>`);
      psDraw();
      if (ps.share === undefined) {
        api(`/clients/${cl.id}/portal-share`)
          .then((r) => { if (state.activeClient !== cl.id) return;  // stale response for a client we've left
            ps.share = r.share || null; psDraw(); })
          .catch(() => {
            if (state.activeClient !== cl.id) return;
            // Leave ps.share undefined: a transient failure must NOT be cached as
            // "no share exists" — Send would then quietly rotate a live token.
            const b = $("#psBody");
            if (b) {
              b.innerHTML = `<p class="muted" style="margin:0 0 14px">Couldn't load the share status. Check your connection and try again.</p>
                <button class="btn btn-soft btn-sm" id="psRetry">Retry</button>`;
              const rt = $("#psRetry"); if (rt) rt.onclick = openPortalShareModal;
            }
          });
      }
    }

    function tabCount(tab, n) {
      const labels = { documents: "Documents", notes: "Notes", emails: "Emails" };
      const el = $(`.cp-tab[data-tab="${tab}"]`);
      if (el) el.textContent = labels[tab] + (n ? ` (${n})` : "");
    }

    // Stage buttons. In view mode they are read-only (a progress indicator); they only
    // become clickable inside the inline edit form, so a stray click can't auto-save.
    function stageStepsHtml(interactive, current) {
      const stages = stagesForClient(cl).filter((s) => s.key !== "on_hold");
      const onHold = stagesForClient(cl).find((s) => s.key === "on_hold");
      const cur = current != null ? current : cl.status;
      const btn = (s) => {
        const active = cur === s.key;
        const style = active ? ` style="background:${s.color}"` : "";
        const attrs = interactive ? ` data-key="${s.key}"` : " disabled";
        return `<button type="button" class="stage-step ${active ? "done" : ""}"${style}${attrs}>${esc(s.label)}</button>`;
      };
      return stages.map(btn).join("") + (onHold ? btn(onHold) : "");
    }

    // "Everything before the current stage is done" is an assumption the tracker used to draw
    // as a fact. `stages_skipped` is the server's answer to it — the stages this case went past
    // without working, worked out once against the record of where the case has actually stood
    // (see _skipped_stage_keys). It is empty whenever that record cannot prove a skip, so a
    // case older than the record, or one whose past cannot be placed, still reads as it always
    // did. Everything on this page branches on this one list rather than re-deriving it.
    function stageWasSkipped(stageKey) {
      return (cl.stages_skipped || []).indexOf(stageKey) >= 0;
    }

    // Visual journey tracker (mirrors the B2C stage stepper): the linear client pipeline as
    // connected nodes with done / skipped / current / upcoming states, off-path Rejected &
    // On-Hold pills, and a document-readiness line built from the client's uploaded documents.
    function journeyTrackHtml(interactive, current, docs) {
      const stages = stagesForClient(cl);
      if (!stages.length) return "";
      // Resolved order (a destination may re-sequence it) only ever SORTS. Every stage is
      // picked out by KEY and every comparison is a position within this resolved list, so
      // inserting a stage into the catalog can never re-point a check at the wrong one.
      const ordered = stages.slice().sort((a, b) => (a.order || 0) - (b.order || 0));
      const rejected = ordered.find((s) => s.key === "rejected");
      const onHold = ordered.find((s) => s.key === "on_hold");
      const linear = ordered.filter((s) => s.key !== "rejected" && s.key !== "on_hold");
      const idxOf = (k) => linear.findIndex((s) => s.key === k);
      const curIdx = idxOf(current);
      const isRejected = rejected && current === rejected.key;
      const isOnHold = onHold && current === onHold.key;
      // On Hold keeps the client's real position (held_from_status, remembered by the
      // backend) so the tracker shows WHERE the case is paused — and Resume restores it.
      const heldStage = isOnHold && cl.held_from_status
        ? linear.find((s) => s.key === cl.held_from_status) : null;
      const heldIdx = heldStage ? idxOf(heldStage.key) : -1;
      // Gaps only show on stages the case has already REACHED. Off the linear path — closed
      // as rejected, or a legacy hold with no remembered position — all of it counts.
      const reachedIdx = curIdx >= 0 ? curIdx
        : heldIdx >= 0 ? heldIdx
        : (isRejected || isOnHold) ? linear.length - 1 : -1;
      // Behind the case, a stage is either WORKED THROUGH or JUMPED OVER — a tick on both is
      // the tracker asserting work nobody did. See stageWasSkipped.
      const visitedAt = (cl.stage_visits && typeof cl.stage_visits === "object") ? cl.stage_visits : {};
      const behindCls = (key) => (stageWasSkipped(key) ? "skipped" : "done");
      let skippedCount = 0;

      const nodes = linear.map((s, i) => {
        // The success node is the one keyed `approved` — not "whichever stage is terminal".
        // `linear` is built by EXCLUDING rejected/on_hold, so a future terminal stage would
        // land in it and inherit the green tick without being a win.
        const isSuccess = s.key === "approved";
        let cls;
        if (isRejected) cls = isSuccess ? "upcoming" : behindCls(s.key);  // walked the path, then refused
        else if (isOnHold) {
          if (heldIdx >= 0) {
            cls = i < heldIdx ? behindCls(s.key) : (i === heldIdx ? "current paused" : "upcoming");
          } else cls = "upcoming";                              // legacy hold — position unknown
        }
        else if (i < curIdx) cls = behindCls(s.key);
        else if (i === curIdx) cls = "current";
        else cls = "upcoming";
        const isSkipped = cls === "skipped";
        if (isSkipped) skippedCount += 1;
        // The green tick is a WIN. A pipeline re-sequenced so the approval sits behind the
        // case must not hand that tick to a stage the case never actually reached.
        if (isSuccess && cls !== "upcoming" && !isSkipped && !isOnHold) cls += " approved";
        const inner = isSkipped ? "–"
          : cls.indexOf("paused") >= 0 ? "⏸"
          : cls.indexOf("done") >= 0 ? "✓"
          : (cls.indexOf("current") >= 0 && isSuccess ? "✓" : String(i + 1));
        const jk = interactive ? ` data-jkey="${s.key}"` : "";
        // Amber dot on a reached stage whose required case-record fields are still empty. A
        // skipped stage is exempt: the case deliberately never did that work, and nagging for
        // records nobody was ever going to enter is how a gap indicator gets ignored.
        const gaps = (interactive && i <= reachedIdx && !isSkipped) ? stageMissingRequired(s.key).length : 0;
        const openCls = (openStageKey === s.key) ? " panel-open" : "";
        const reachedOn = (!isSkipped && cls.indexOf("done") >= 0) ? fmtDate(visitedAt[s.key]) : null;
        const tip = gaps ? `${s.label} — ${gaps} required field${gaps === 1 ? "" : "s"} still empty`
          : isSkipped ? `${s.label} — skipped: this case never went through this stage`
          : (reachedOn && reachedOn !== "—") ? `${s.label} — reached ${reachedOn}`
          : s.label;
        return `<div class="jtrack-step ${cls}${openCls}"${jk} title="${esc(tip)}">
            <div class="jtrack-node">${inner}${gaps ? '<span class="jtrack-gap" aria-hidden="true"></span>' : ""}</div>
            <div class="jtrack-label">${esc(s.label)}</div>
          </div>`;
      }).join("");

      const altPill = (s, active) => {
        if (!s) return "";
        const jk = interactive ? ` data-jkey="${s.key}"` : "";
        const tone = s.key === "rejected" ? "jtrack-alt-rej" : "jtrack-alt-hold";
        return `<button type="button" class="jtrack-alt-pill ${tone}${active ? " active" : ""}"${jk}${interactive ? "" : " disabled"}>${esc(s.label)}</button>`;
      };
      // One-click way OUT of On Hold: resume to the remembered stage (or restart at the
      // first stage if the hold predates position tracking).
      const resumeKey = isOnHold ? (heldStage ? heldStage.key : (linear[0] && linear[0].key)) : null;
      const resumeBtn = (interactive && resumeKey)
        ? `<button type="button" class="jtrack-resume" data-jkey="${resumeKey}">▶ Resume${heldStage ? " · " + esc(heldStage.label) : ""}</button>`
        : "";

      // State-aware helper text, directly under the tracker.
      let hint = "";
      if (interactive) {
        const first = esc((cl.full_name || "the client").split(" ")[0]);
        if (isOnHold) hint = heldStage
          ? `${first} is on hold at “${esc(heldStage.label)}”. Click Resume to continue, or click any stage.`
          : `${first} is on hold. Click a stage to resume the case.`;
        else if (isRejected) hint = `This case is closed as rejected. Click any stage to reopen it.`;
        else hint = `Click a stage to open its case record — the details to capture are tailored to ${esc(cl.destination_country_name || "this destination")}. Moving ${first} is a separate button inside.`;
      }

      const dArr = docs || [];
      const dTypes = [];
      dArr.forEach((d) => { const t = d && d.document_type; if (t && dTypes.indexOf(t) < 0) dTypes.push(t); });
      const shown = dTypes.slice(0, 6);
      const docHtml = `<div class="jtrack-docs">
          <span class="jtrack-docs-count">📄 ${dArr.length} document${dArr.length === 1 ? "" : "s"} on file</span>
          ${shown.map((t) => `<span class="jtrack-docchip">${esc(t)}</span>`).join("")}
          ${dTypes.length > 6 ? `<span class="jtrack-docchip more">+${dTypes.length - 6}</span>` : ""}
        </div>`;

      // A tick explains itself; a dashed node does not, and a gap in an otherwise solid chain
      // reads as a bug until it is named. Only shown when there is something to name.
      const skipNote = skippedCount
        ? `<div class="jtrack-skipnote"><span class="jtrack-skipmark">–</span> ${skippedCount} stage${skippedCount === 1 ? "" : "s"} skipped — the case moved straight past ${skippedCount === 1 ? "it" : "them"}.${interactive ? " Recording a skipped stage's case details marks it done." : ""}</div>`
        : "";

      return `<div class="jtrack${isOnHold ? " jtrack-held" : ""}">${nodes}</div>
        <div class="jtrack-alt">${altPill(rejected, isRejected)}${altPill(onHold, isOnHold)}${resumeBtn}</div>
        ${skipNote}
        ${hint ? `<div class="cpe-hint jtrack-hint">${hint}</div>` : ""}
        ${docHtml}`;
    }

    /* ---- Per-stage case record (destination-aware fields under the journey tracker) ---- */
    // Field definitions come from /catalog (stage_fields_by_country), resolved for THIS
    // client's destination, so a US case records SEVIS/DS-160 and a UK case records CAS/IHS.
    function stageFieldsFor(stageKey) {
      const byCountry = (state.catalog && state.catalog.stage_fields_by_country) || {};
      const cc = String(cl.destination_country_code || "").toUpperCase();
      return ((byCountry[cc] || {})[stageKey]) || [];
    }
    function stageValuesFor(stageKey) {
      return ((cl.stage_data || {})[stageKey]) || {};
    }
    function stageMissingRequired(stageKey) {
      const vals = stageValuesFor(stageKey);
      return stageFieldsFor(stageKey).filter((f) => f.required && !String(vals[f.key] || "").trim());
    }
    function stagePanelHtml() {
      if (!openStageKey) return "";
      const stages = stagesForClient(cl);
      const s = stages.find((x) => x.key === openStageKey);
      if (!s) return "";
      const fields = stageFieldsFor(openStageKey);
      const vals = stageValuesFor(openStageKey);
      const isCurrent = cl.status === openStageKey;
      // Same list the tracker used when it drew this stage as a dash.
      const isSkipped = !isCurrent && stageWasSkipped(openStageKey);

      const body = fields.length ? `<div class="stage-fields">${fields.map((f) => {
        const raw = vals[f.key] == null ? "" : String(vals[f.key]);
        const id = "sf_" + f.key;
        let control;
        if (f.type === "select") {
          const opts = ['<option value="">—</option>'].concat((f.options || []).map((o) =>
            `<option value="${esc(o)}"${raw === o ? " selected" : ""}>${esc(o)}</option>`)).join("");
          control = `<select id="${id}" data-fkey="${esc(f.key)}"${canEdit ? "" : " disabled"}>${opts}</select>`;
        } else if (f.type === "textarea") {
          control = `<textarea id="${id}" data-fkey="${esc(f.key)}" rows="2"${canEdit ? "" : " disabled"}>${esc(raw)}</textarea>`;
        } else {
          const t = f.type === "date" ? "date" : (f.type === "number" ? "number" : "text");
          control = `<input id="${id}" data-fkey="${esc(f.key)}" type="${t}" value="${esc(raw)}"${canEdit ? "" : " disabled"}>`;
        }
        return `<div class="field stage-field">
            <label for="${id}">${esc(f.label)}${f.required ? ' <span class="sf-req" title="Required for this stage">*</span>' : ""}</label>
            ${control}
            ${f.hint ? `<div class="sf-hint">${esc(f.hint)}</div>` : ""}
          </div>`;
      }).join("")}</div>`
        : `<p class="muted" style="margin:0;font-size:13px">No case-record fields for this stage yet.</p>`;

      const actions = canEdit ? `<div class="stage-panel-actions">
          ${fields.length ? `<button type="button" class="btn btn-primary btn-sm" id="stageSave">Save record</button>` : ""}
          ${isCurrent ? `<span class="stage-current-pill">Current stage</span>`
                      : `<button type="button" class="btn btn-soft btn-sm" id="stageMove">Move ${esc((cl.full_name || "client").split(" ")[0])} here</button>`}
          <button type="button" class="btn btn-ghost btn-sm" id="stageClose">Close</button>
        </div>` : `<div class="stage-panel-actions"><button type="button" class="btn btn-ghost btn-sm" id="stageClose">Close</button></div>`;

      return `<div class="stage-panel" id="stagePanel">
          <div class="stage-panel-head">
            <div><h4>${esc(s.label)}</h4><p>${esc(s.description || "")}</p></div>
            ${isCurrent ? "" : isSkipped
              ? `<span class="stage-panel-tag stage-panel-tag-skip" title="The case moved past this stage without going through it">Skipped</span>`
              : `<span class="stage-panel-tag">Not the current stage</span>`}
          </div>
          ${body}
          ${actions}
        </div>`;
    }

    function renderOverview() {
      if (overviewEditing && canEdit) { renderOverviewEdit(); return; }

      const assignField = `<div class="detail-item"><label>Assigned counselor</label><div>${cl.assigned_to_name ? esc(cl.assigned_to_name) : "—"}</div></div>`;
      const ovFirst = (cl.full_name || "the student").split(" ")[0];
      const isUKClient = String(cl.destination_country_code || "").toUpperCase() === "UK";
      // Only pin the mock-interview CTA to the top of Overview for destinations that actually
      // run an interview (US, FR). For the rest the feature stays reachable in the Mock
      // Interview tab, just not pushed here — see interviewRelevance().
      const pushInterview = interviewRelevance(cl) === "standard";
      body.innerHTML = `
        ${canInviteInterview && pushInterview ? `<button class="btn btn-primary btn-block cp-iv-cta" id="ovSendIv">🎤 Send ${esc(ovFirst)} a mock interview</button>` : ""}
        <div class="cp-card">
          <div class="cp-card-head"><h3>Client journey</h3>${statusPill(cl.stage)}</div>
          <div id="ovStageFlow">${journeyTrackHtml(canEdit, cl.status, docs)}</div>
          <div id="ovStagePanel">${stagePanelHtml()}</div>
        </div>
        ${isUKClient ? `
        <div class="cp-card">
          <div class="cp-card-head"><h3>💷 Maintenance funds</h3></div>
          <p style="margin:0 0 12px;font-size:13px;color:var(--text-2);line-height:1.5">The trickiest part of a UK application. Work out ${esc(ovFirst)}'s exact figure &amp; 28-day window here, or send them the calculator to plan themselves.</p>
          <div style="display:flex;flex-wrap:wrap;gap:10px">
            <button type="button" class="btn btn-primary btn-sm" id="ukCalcOpen" style="width:auto">🧮 Open calculator</button>
            <button type="button" class="btn btn-soft btn-sm" id="ukCalcCopy" style="width:auto">🔗 Copy student link</button>
          </div>
        </div>` : ""}
        <div class="cp-card">
          <div class="cp-card-head"><h3>Client details</h3>${canEdit ? `<button class="btn btn-soft btn-sm" id="cpEditInline">Edit details</button>` : ""}</div>
          <div class="detail-grid">
            ${detail("Email", cl.email ? esc(cl.email) : "")}
            ${detail("Phone", cl.phone ? esc(cl.phone) : "")}
            ${detail("WhatsApp", cl.whatsapp_number ? esc(cl.whatsapp_number) : "")}
            ${detail("Current city", cl.current_city ? esc(cl.current_city) : "")}
            ${detail("Priority", `<span class="prio" style="background:${priorityColor(cl.priority)}1f;color:${priorityColor(cl.priority)}">${esc(cl.priority)}</span>`)}
            ${detail("Key date", cl.target_date ? fmtDate(cl.target_date) : "")}
            ${detail("Next follow-up", cl.next_followup_date ? fmtDate(cl.next_followup_date) : "")}
            ${detail("Intake", cl.intake ? esc(cl.intake) : "")}
            ${assignField}
            ${detail("Branch / office", cl.branch_name ? esc(cl.branch_name) : "")}
            ${detail("Lead source", esc(cl.lead_source_label || ""))}
            ${detail(esc(LEAD_SOURCE_DETAIL_LABEL[cl.lead_source] || "Source detail"), cl.lead_source_detail ? esc(cl.lead_source_detail) : "")}
            ${detail("Added", fmtDate(cl.created_at))}
          </div>
        </div>
        <div class="cp-card">
          <div class="cp-card-head"><h3>Study plan &amp; profile</h3></div>
          <div class="detail-grid">
            ${detail("Level of study", esc(cl.study_level_label || ""))}
            ${detail("Intended course / field", cl.field_of_study ? esc(cl.field_of_study) : "")}
            ${detail("Admission stage", esc(cl.admission_stage_label || ""))}
            ${detail("Highest qualification", esc(cl.highest_qualification_label || ""))}
            ${detail("Marks / GPA", cl.qualification_score ? esc(cl.qualification_score) + (cl.qualification_scale_label ? ` <small style="color:var(--muted)">${esc(cl.qualification_scale_label)}</small>` : "") : "")}
            ${detail("Year of passing", cl.year_of_passing ? esc(String(cl.year_of_passing)) : "")}
            ${detail("Backlogs / arrears", cl.backlogs_count != null ? esc(String(cl.backlogs_count)) : "")}
            ${detail("Work experience", esc(cl.work_experience_band_label || ""))}
            ${detail("English test", [cl.english_test_type_label, cl.english_test_status_label, cl.english_test_date ? fmtDate(cl.english_test_date) : ""].filter(Boolean).map(esc).join(" · "))}
            ${detail("Overall score", cl.english_test_score ? esc(cl.english_test_score) : "")}
            ${detail("Aptitude test", [cl.aptitude_test_type_label, cl.aptitude_test_score].filter(Boolean).map(esc).join(" · "))}
            ${detail("Budget (per year)", esc(cl.budget_band_label || ""))}
            ${detail("Funding", esc(cl.funding_source_label || ""))}
            ${detail("Prior visa / refusal", esc(cl.prior_refusal_history_label || ""))}
            ${cl.prior_refusal_notes ? `<div class="detail-item" style="grid-column:1/-1"><label>Refusal details</label><div>${esc(cl.prior_refusal_notes)}</div></div>` : ""}
          </div>
        </div>
        <div class="cp-card">
          <div class="cp-card-head"><h3>Identity, family &amp; consent</h3></div>
          <div class="detail-grid">
            ${detail("Nationality", cl.nationality ? esc(cl.nationality) : "")}
            ${detail("Gender", esc(cl.gender_label || ""))}
            ${detail("Date of birth", cl.date_of_birth ? fmtDate(cl.date_of_birth) : "")}
            ${canSeeSensitive ? detail("Passport no.", cl.passport_number ? esc(cl.passport_number) : "") : ""}
            ${detail("Passport expiry", cl.passport_expiry ? fmtDate(cl.passport_expiry) : "")}
            ${detail("Application ref.", cl.application_reference ? esc(cl.application_reference) : "")}
            ${detail("Parent / guardian", [cl.guardian_name, cl.guardian_relation_label].filter(Boolean).map(esc).join(" · "))}
            ${detail("Guardian phone", cl.guardian_phone ? esc(cl.guardian_phone) : "")}
            ${detail("Promotional contact", (cl.marketing_consent_channel_labels || []).map(esc).join(", "))}
            ${detail("Share with institutions", cl.institution_share_consent ? "Consented " + (cl.institution_share_consent_at ? "· " + fmtDate(cl.institution_share_consent_at) : "") : "Not given")}
          </div>
        </div>`;
      const ovIv = $("#ovSendIv");
      if (ovIv) ovIv.onclick = () => { if (cl.email) openSendModal(); else { toast("Add an email to this client first.", "error"); editClient(cl.id); } };
      const editInline = $("#cpEditInline");
      if (editInline) editInline.onclick = () => { overviewEditing = true; renderOverview(); };
      // UK maintenance-funds tools (shared calculator engine, reused from the B2C app + public page).
      const ukOpen = $("#ukCalcOpen");
      if (ukOpen) ukOpen.onclick = () => {
        if (window.RilonoUkMaintenanceCalc) window.RilonoUkMaintenanceCalc.openModal({ eyebrow: "UK Student visa · " + (cl.full_name || "Client") });
        else toast("Calculator failed to load — refresh and try again.", "error");
      };
      const ukCopy = $("#ukCalcCopy");
      if (ukCopy) ukCopy.onclick = async () => {
        const path = (window.RilonoUkMaintenanceCalc && window.RilonoUkMaintenanceCalc.FIGURES.publicPath) || "/tools/uk-maintenance-calculator";
        const url = location.origin + path;
        try { await navigator.clipboard.writeText(url); toast("Calculator link copied — paste it to your student.", "success"); }
        catch (e) { toast(url, "info"); }
      };
      if (canEdit) {
        wireJourneyTrack();
        wireStagePanel();
      }
      focusCurrentStage();
    }

    // Clicking a stage OPENS that stage's case-record panel underneath the tracker.
    // Moving the case is a deliberate button inside the panel, so a stray click on the
    // journey can never silently change the client's status.
    function wireJourneyTrack() {
      $$("#ovStageFlow [data-jkey]").forEach((b) => {
        b.onclick = () => {
          const key = b.dataset.jkey;
          if (!key) return;
          openStageKey = (openStageKey === key) ? null : key;   // click again to collapse
          renderOverview();
          const panel = $("#stagePanel");
          if (panel && panel.scrollIntoView) panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
        };
      });
    }

    // The track is the one strip that scrolls sideways, and nothing ever scrolled it — on a
    // laptop pane a late-stage case sat past the right edge with no hint it was there. Bring
    // the node the case is actually on into view, horizontally only and without animation:
    // the vertical position of the page belongs to the counsellor, not to a re-render.
    // `inline: nearest` (not center) is what makes .jtrack-step's scroll-margin-inline count,
    // so the node lands a step short of the edge instead of under the edge gradient.
    function focusCurrentStage() {
      const track = $("#ovStageFlow .jtrack");
      if (!track || track.scrollWidth <= track.clientWidth + 1) return;
      // Skipped counts as walked past here: the fallback wants the furthest node the case
      // has GONE BY, and stopping at the last tick would scroll short of it.
      const reached = $$(".jtrack-step.done, .jtrack-step.skipped", track);
      // `current paused` covers On Hold; a closed-as-rejected case has no current node, so
      // fall back to the furthest stage it walked.
      const node = $(".jtrack-step.current", track) || reached[reached.length - 1];
      if (!node || !node.scrollIntoView) return;
      node.scrollIntoView({ block: "nearest", inline: "nearest" });
    }

    // Redraws the parts of the journey that are on screen right now, for a stage change that
    // must NOT rebuild the client page (the counsellor may be working in another tab).
    function refreshStageUi() {
      const pill = $(".cp-hstatus");
      if (pill) pill.innerHTML = statusPill(cl.stage);
      const flow = $("#ovStageFlow");
      if (!flow) return;
      flow.innerHTML = journeyTrackHtml(canEdit, cl.status, docs);
      if (canEdit) wireJourneyTrack();
      focusCurrentStage();
    }

    function wireStagePanel() {
      const closeBtn = $("#stageClose");
      if (closeBtn) closeBtn.onclick = () => { openStageKey = null; renderOverview(); };

      const saveBtn = $("#stageSave");
      if (saveBtn) saveBtn.onclick = async () => {
        const stageKey = openStageKey;
        const values = {};
        $$("#stagePanel [data-fkey]").forEach((el) => { values[el.dataset.fkey] = el.value; });
        saveBtn.disabled = true; saveBtn.innerHTML = '<span class="spinner"></span> Saving…';
        try {
          const r = await api(`/clients/${cl.id}/stage-data`, { method: "PATCH", body: { stage_key: stageKey, values } });
          if (r && r.client) Object.assign(cl, r.client);
          toast("Case record saved", "success");
          renderOverview();
        } catch (ex) {
          toast(ex.message, "error");
          saveBtn.disabled = false; saveBtn.textContent = "Save record";
        }
      };

      const moveBtn = $("#stageMove");
      if (moveBtn) moveBtn.onclick = async () => {
        const key = openStageKey;
        if (!key || key === cl.status) return;
        const stages = stagesForClient(cl);
        const stageOf = (k) => stages.find((x) => x.key === k) || {};
        const labelOf = (k) => stageOf(k).label || (k || "").replace(/_/g, " ");
        const orderOf = (k) => (stageOf(k).order != null ? stageOf(k).order : 0);
        const first = (cl.full_name || "the client").split(" ")[0];
        const toLabel = labelOf(key), fromLabel = labelOf(cl.status);
        // Exact keys, never a substring match: this decides whether the move CLOSES the
        // case, and a future key such as "offer_rejected" must not trip it.
        const isReject = key === "rejected", isHold = key === "on_hold";

        // Warn — but never block — when advancing while the stage being LEFT is still
        // missing required record fields.
        let warn = "";
        if (!isReject && !isHold && orderOf(key) > orderOf(cl.status)) {
          const missing = stageMissingRequired(cl.status);
          if (missing.length) {
            warn = `\n\n⚠ “${fromLabel}” is still missing: ${missing.map((f) => f.label).join(", ")}.\nYou can continue and fill this in later.`;
          }
        }
        const title = isReject ? "Mark case as rejected?" : isHold ? "Put case on hold?" : `Move to “${toLabel}”?`;
        const message = (isReject
          ? `${first}'s case will be closed as “${toLabel}”. You can reopen it later by clicking any stage.`
          : isHold
            ? `${first}'s case will be paused at “${fromLabel}”. You can resume it anytime.`
            : `${first} will move from “${fromLabel}” to “${toLabel}”.`) + warn;
        const ok = await confirmModal(message, {
          title,
          okText: isReject ? "Mark rejected" : isHold ? "Put on hold" : "Move stage",
          danger: isReject,
        });
        if (ok) { openStageKey = null; setStatus(cl.id, key); }
      };
    }

    // Inline edit of the client details, in-pane (no popup). Save writes via PATCH and
    // re-renders the client page so the hero + details reflect the change immediately.
    function renderOverviewEdit() {
      const formOpts = { prefix: "cpe", members: members, formId: "cpEditForm", withStatus: false, withNote: false, withDpaConsent: false };
      let pending = cl.status;  // selected-but-unsaved visa status — only applied on Save
      body.innerHTML = `
        <div class="cp-card">
          <div class="cp-card-head"><h3>Pipeline stage</h3><span class="cpe-hint">Pick a stage — saved with the form</span></div>
          <div class="stage-flow" id="cpeStageFlow">${stageStepsHtml(true, pending)}</div>
        </div>
        <div class="cp-card">
          <div class="cp-card-head"><h3>Edit client details</h3></div>
          <form id="cpEditForm" class="cp-edit-form">
            ${clientFormFieldsHtml(cl, formOpts)}
            <div id="cpEditError" class="auth-error hidden" style="margin-top:2px"></div>
            <div class="cp-edit-actions">
              <button type="button" class="btn btn-ghost btn-sm" id="cpEditCancel">Cancel</button>
              <button type="submit" class="btn btn-primary btn-sm" id="cpEditSave">Save changes</button>
            </div>
          </form>
        </div>
        <div class="cp-card" style="border-color:#f3c9c9;background:linear-gradient(0deg,#fff8f8,#fff)">
          <div class="cp-card-head"><h3 style="color:#b42318">Danger zone</h3></div>
          <p style="margin:0 0 14px;color:var(--text-2);font-size:13.5px;line-height:1.6">Deleting removes <b>${esc(cl.full_name)}</b> along with all their notes, emails and case records. This is permanent and <b>cannot be undone</b>.</p>
          <div class="field cpe-full">
            <label>To confirm, type the client's full name — <b>${esc(cl.full_name)}</b></label>
            <input id="cpDelConfirm" autocomplete="off" spellcheck="false" placeholder="${esc(cl.full_name)}">
          </div>
          <div style="margin-top:14px"><button type="button" class="btn btn-danger btn-sm" id="cpDelBtn" disabled>Delete client</button></div>
          <div id="cpDelError" class="auth-error hidden" style="margin-top:10px"></div>
        </div>`;

      // Visa-status stage selector — clicking only marks a pending choice (re-highlights
      // in place, preserving the form inputs); it's written on Save changes, never on a stray click.
      const stageFlowEl = $("#cpeStageFlow");
      function wireStages() {
        stageFlowEl.querySelectorAll(".stage-step[data-key]").forEach((b) => {
          b.onclick = () => { pending = b.dataset.key; stageFlowEl.innerHTML = stageStepsHtml(true, pending); wireStages(); };
        });
      }
      wireStages();

      // Same builder/cascade as the Add-client modal — one source of truth for the fields.
      wireClientFormFields(cl, formOpts);

      $("#cpEditCancel").onclick = () => { overviewEditing = false; renderOverview(); };
      $("#cpEditForm").onsubmit = async (e) => {
        e.preventDefault();
        const f = e.target, btn = $("#cpEditSave"), err = $("#cpEditError");
        err.classList.add("hidden");
        const patch = collectClientFormBody(f);
        // Visa status + counselor save with the form (no live auto-save on click).
        patch.status = pending;
        btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
        try {
          await api("/clients/" + cl.id, { method: "PATCH", body: patch });
          toast("Client updated", "success");
          overviewEditing = false;
          openClient(cl.id);  // in-pane refresh — updates hero + details, exits edit mode
        } catch (ex) {
          if (ex.status === 402) { toast(ex.message, "error"); navigate("credits"); return; }
          err.textContent = ex.message; err.classList.remove("hidden");
          btn.disabled = false; btn.innerHTML = "Save changes";
        }
      };

      // Danger zone — delete stays disabled until the exact client name is typed.
      const delInput = $("#cpDelConfirm"), delBtn = $("#cpDelBtn"), delErr = $("#cpDelError");
      if (delInput && delBtn) {
        const target = (cl.full_name || "").trim();
        const matches = () => (delInput.value || "").trim() === target && target !== "";
        const sync = () => { delBtn.disabled = !matches(); };
        delInput.addEventListener("input", sync);
        delInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); if (matches()) delBtn.click(); } });
        sync();
        delBtn.onclick = async () => {
          if (!matches()) return;
          delErr.classList.add("hidden");
          delBtn.disabled = true; delBtn.innerHTML = '<span class="spinner"></span> Deleting…';
          try {
            await deleteClient(cl.id);  // navigates away on success
          } catch (ex) {
            delErr.textContent = ex.message; delErr.classList.remove("hidden");
            delBtn.innerHTML = "Delete client"; sync();
          }
        };
      }
    }

    // Destination-personalized document list for THIS client (each of the ten destinations
    // get their own detailed catalog; unknown destinations fall back to the generic list).
    function clientDocTypes() {
      const map = state.catalog.document_types_by_country || {};
      const list = map[cl.destination_country_code];
      if (list && list.length) return list;
      return (state.catalog.document_types || []).map((t) => ({ key: t, label: t, required: false, hint: "" }));
    }

    // After an upload, Rilono AI validates the document in the background. Poll for the verdict,
    // update the badge in place, and — when a validated passport auto-filled empty profile
    // fields — refresh the client so the Overview reflects the new details.
    async function pollDocValidation(docId) {
      // Only repaint when the user is actually LOOKING at the Documents tab of THIS
      // client page — #cpBody is shared by every tab, so a blind renderDocs() here
      // would clobber a half-typed note or a selected file on another tab.
      const onDocsTab = () => {
        const t = $(".cp-tab.active");
        return !!(t && t.dataset.tab === "documents");
      };
      for (let i = 0; i < 8; i++) {
        await new Promise((r) => setTimeout(r, i === 0 ? 2500 : 3500));
        if (state.activeClient !== cl.id || !body.isConnected) return;   // navigated away / page rebuilt
        let fresh;
        try { fresh = await api("/clients/" + cl.id + "/documents"); } catch (e) { return; }
        const arr = fresh.documents || [];
        docs.splice(0, docs.length, ...arr);
        if (fresh.scan_pricing) scanPricing = fresh.scan_pricing;
        // The scan's debit happens in the background worker, so this poll is the first
        // moment the new balance exists — push it to the sidebar badge as it lands.
        if (fresh.wallet) { state.credits = fresh.wallet; updatePlanChip(); }
        const found = arr.find((x) => x.id === docId);
        const done = found && found.validation_status;
        if (done) pendingDocIds.delete(docId);
        // Repaint only when the verdict just landed (nothing changes between ticks).
        if (done && onDocsTab()) renderDocs();
        if (done) {
          const af = (found.extracted && found.extracted.autofill) || {};
          const filled = af.filled || [];
          if (filled.length) {
            try { const c = await api("/clients/" + cl.id); Object.assign(cl, c.client); } catch (e) {}
            toast("✅ " + found.document_type + " validated — auto-filled " + filled.map((f) => f.field).join(", ") + ". Open Overview to review.", "success");
          } else if (found.validation_status === "valid") {
            toast("✅ " + found.document_type + " validated by Rilono AI", "success");
          } else if (found.validation_status === "invalid") {
            toast("⚠ Rilono AI flagged the " + found.document_type + " — see the document card", "error");
          } else if (found.validation_status === "error") {
            // A scan that returned no verdict is never charged, so say so — otherwise it
            // reads as a credit spent on nothing.
            toast("Rilono AI couldn't read the " + found.document_type + " — you haven't been charged.", "error");
          }
          return;
        }
      }
      pendingDocIds.delete(docId);                     // stop showing "validating…" after the timeout
      if (state.activeClient === cl.id && body.isConnected && onDocsTab()) renderDocs();
    }

    function renderDocs() {
      // Scanning is the billed half of an upload, so the choice is made here, with the
      // price visible, before a credit is spent. Storing the file is always free.
      const scanCost = scanPricing ? scanPricing.cost_credits : null;
      const scanUnaffordable = !!(scanPricing && !scanPricing.can_afford);
      const scanUnavailable = !!(scanPricing && !scanPricing.ai_available);
      const scanOfferable = canUploadDocs && canSpendCredits && !scanUnavailable;
      const scanToggle = scanOfferable ? `
        <label class="doc-scan-opt${scanUnaffordable ? " disabled" : ""}" for="docScanChk">
          <input type="checkbox" id="docScanChk" ${scanUnaffordable ? "disabled" : "checked"} />
          <span class="doc-scan-opt-txt">
            <b>Scan &amp; validate with Rilono AI</b>
            <span class="doc-scan-opt-sub">${scanUnaffordable
              ? "Not enough credits — the document will still be stored. Top up in Credits to scan it."
              : `Checks the document is genuine, current and the right type, then cross-checks it against ${esc(cl.full_name)}’s profile and their already-validated documents.`}</span>
          </span>
          ${scanCost != null ? `<span class="doc-scan-price">${scanCost} credit${scanCost === 1 ? "" : "s"}</span>` : ""}
        </label>` : "";
      const uploader = canUploadDocs ? `
        <div class="cp-card doc-upload">
          <div class="cp-sub-label">Upload a document</div>
          <div class="doc-up-row">
            <div class="docsel" id="docSel">
              <input type="text" id="docTypeInput" class="docsel-input" autocomplete="off"
                placeholder="Search ${esc(cl.destination_country_name || "")} document types…" />
              <div class="docsel-menu hidden" id="docTypeMenu"></div>
            </div>
            <input type="file" id="docFile" class="doc-file" />
            <button class="btn btn-primary btn-sm" id="docUploadBtn" disabled>Upload document</button>
            <div id="docOtherWrap" class="docsel-other-wrap" style="display:none">
              <input type="text" id="docOtherDetail" class="docsel-input" maxlength="70" autocomplete="off"
                placeholder="What is this document? e.g. Police clearance certificate, Name-change affidavit…" />
            </div>
          </div>
          ${scanToggle}
          <div class="doc-hint">🔒 Encrypted at rest · PDF, images, Word/Excel, CSV or text · up to 25 MB${
            scanOfferable ? " · uploading is free" : ""}</div>
        </div>` : "";
      const docValInfo = (d) => {
        const s = d.validation_status;
        // A staff override is stored as "valid" — but a human cleared it, not the AI.
        // Label it as such so nobody mistakes an overridden document for an AI-verified one.
        if (d.manually_accepted) {
          const bits = [];
          if (d.manually_accepted_by) bits.push("by " + d.manually_accepted_by);
          if (d.manually_accepted_at) bits.push(fmtDate(d.manually_accepted_at));
          return { cls: "manual", txt: "✓ Manually approved", msg: bits.join(" · ") };
        }
        if (s === "valid") return { cls: "ok", txt: "✓ Validated by Rilono AI", msg: "" };
        if (s === "invalid") return { cls: "warn", txt: "⚠ Needs review", msg: d.validation_message || "" };
        if (s === "error") return { cls: "muted", txt: "Scan failed", msg: d.validation_message || "" };
        // A scan this tab kicked off is genuinely in flight. A NULL status WITHOUT a live
        // poll is a document whose worker died mid-scan (or a legacy row) — call that "not
        // scanned" and let staff re-run it, rather than spinning "scanning…" forever.
        if (pendingDocIds.has(d.id)) return { cls: "pending", txt: "◌ Rilono AI is scanning…", msg: "" };
        // Stored but never scanned — the scan wasn't asked for (or it came in via the
        // client's secure link, which never auto-scans). Not a failure, so it reads neutral.
        if (s === "not_scanned" || !s) return { cls: "muted", txt: "Not scanned", msg: "" };
        return null;
      };
      const list = docs.length ? `<div class="doc-list">${docs.map((d) => {
        const v = docValInfo(d);
        const af = (d.extracted && d.extracted.autofill) || {};
        const filled = af.filled || [];
        const conflicts = af.conflicts || [];
        const valRow = v ? `<div class="doc-val ${v.cls}"><span class="doc-val-badge">${v.txt}</span>${v.msg ? `<span class="doc-val-msg">${esc(v.msg)}</span>` : ""}</div>` : "";
        const afRow = filled.length ? `<div class="doc-af">✓ Auto-filled profile: <b>${filled.map((f) => esc(f.field)).join(", ")}</b></div>` : "";
        const cfRow = conflicts.length ? `<div class="doc-cf"><b>⚠ Review — document differs from the saved profile:</b>${conflicts.map((c) => `<div class="doc-cf-item">${esc(c.field)}: profile “${esc(c.existing)}” vs document “${esc(c.document)}”</div>`).join("")}</div>` : "";
        // The AI's own structured red flags. Known shape is
        // {field, status: match|conflict|unknown, current_document_value, reference_value, note}
        // — pretty-print those (skipping "match" rows: they're confirmations, not flags) and
        // fall back to generic rendering for anything else the AI returns.
        const cvfItem = (it) => {
          if (it && typeof it === "object" && (it.field || it.status || it.note)) {
            if (String(it.status || "").toLowerCase() === "match") return "";  // not a red flag
            const label = String(it.field || "check").replace(/_/g, " ");
            const vals = (it.current_document_value || it.reference_value)
              ? ` (document: ${esc(String(it.current_document_value ?? "—"))} · on file: ${esc(String(it.reference_value ?? "—"))})` : "";
            return `<div class="doc-cf-item"><b>${esc(label)}</b>: ${esc(String(it.note || it.status || ""))}${vals}</div>`;
          }
          return `<div class="doc-cf-item">${esc(typeof it === "string" ? it : JSON.stringify(it))}</div>`;
        };
        const cvfItems = (x) => {
          if (Array.isArray(x)) return x.map(cvfItem).join("");
          if (x && typeof x === "object") return cvfItem(x) || Object.entries(x).map(([k, it]) => `<div class="doc-cf-item">${esc(k)}: ${esc(typeof it === "string" ? it : JSON.stringify(it))}</div>`).join("");
          return `<div class="doc-cf-item">${esc(String(x))}</div>`;
        };
        // Show the AI's red flags while the document is flagged — and keep showing them
        // (as overridden history) after staff accept it, so the override stays auditable.
        const cvf = (d.validation_status === "invalid" || d.manually_accepted)
          ? ((d.extracted && d.extracted.cross_validation_flags) || null) : null;
        const cvfBody = cvf ? cvfItems(cvf) : "";
        const cvfHead = d.manually_accepted
          ? `⚠ Rilono AI had flagged this — overridden${d.manually_accepted_by ? " by " + esc(d.manually_accepted_by) : ""}:`
          : "⚠ Rilono AI flagged:";
        const cvfNote = (d.manually_accepted && d.ai_flag_before_accept && !cvfBody)
          ? `<div class="doc-cf overridden"><b>${cvfHead}</b><div class="doc-cf-item">${esc(d.ai_flag_before_accept)}</div></div>` : "";
        const cvfRow = cvfBody
          ? `<div class="doc-cf${d.manually_accepted ? " overridden" : ""}"><b>${cvfHead}</b>${cvfBody}</div>`
          : cvfNote;
        const acceptRow = (canAcceptDocs && (d.validation_status === "invalid" || d.validation_status === "error"))
          ? `<div class="doc-accept-row"><button class="btn btn-soft btn-sm doc-accept" data-id="${d.id}">✓ Checked it myself — accept anyway</button></div>` : "";
        // Scan on demand: for a document stored without one, and re-scan for one already
        // checked — a re-scan is worth offering because the cross-validation reference set
        // grows as the client's other documents pass. Both cost the same, so both say so.
        const scanned = !!d.validated_at && d.validation_status !== "not_scanned";
        const scanRow = (scanOfferable && !pendingDocIds.has(d.id))
          ? `<div class="doc-scan-row">
              <button class="btn ${scanned ? "btn-soft" : "btn-primary"} btn-sm doc-scan" data-id="${d.id}"
                ${scanUnaffordable ? "disabled" : ""}>
                ${scanned ? "↻ Re-scan with Rilono AI" : "✦ Scan &amp; validate with Rilono AI"}${
                  scanCost != null ? ` · ${scanCost} credit${scanCost === 1 ? "" : "s"}` : ""}
              </button>
              ${scanUnaffordable ? `<span class="doc-scan-note">Not enough credits</span>` : ""}
            </div>` : "";
        // Downloading raw files (passports, bank letters) is its own capability — without
        // it the filename stays visible but never becomes a link to the file.
        const nameCell = canDownloadDocs
          ? `<a href="${d.download_url}" target="_blank" rel="noopener" class="doc-name">${esc(d.original_filename)}</a>`
          : `<span class="doc-name">${esc(d.original_filename)}</span>`;
        return `
        <div class="doc-card">
          <div class="doc-ic">${docIcon(d.original_filename)}</div>
          <div class="doc-meta">
            ${nameCell}
            <div class="doc-sub">${esc(d.document_type)} · ${fmtSize(d.file_size)} · ${esc(d.uploaded_by_name || "")} · ${fmtDate(d.created_at)}</div>
            ${valRow}${afRow}${cfRow}${cvfRow}${acceptRow}${scanRow}
          </div>
          ${canDownloadDocs ? `<a class="doc-act" href="${d.download_url}" target="_blank" rel="noopener" title="View / download">⬇</a>` : ""}
          ${canDeleteDocs ? `<button class="doc-act doc-del" data-id="${d.id}" title="Delete">✕</button>` : ""}
        </div>`;
      }).join("")}</div>`
        : `<div class="empty" style="padding:34px"><div class="emoji">📁</div><h3>No documents yet</h3><p>${canUploadDocs ? "Upload this student's passport, offer letter, financials, test scores and more — securely." : "No documents have been uploaded for this client."}</p></div>`;
      // The full audit lives in its own Deep Scan tab now — this card is a pointer.
      const deepScanBar = docs.length ? `
        <div class="cp-card deep-scan-card" id="deepScanCard">
          <div class="deep-scan-head">
            <div class="deep-scan-copy">
              <div class="deep-scan-title"><span class="deep-scan-title-icon" aria-hidden="true">🛡️</span> Deep Scan client audit${
                infoTip("Rilono AI strictly audits the <b>entire dossier</b> — these documents' contents plus profile, case records, notes, emails and payments — and flags anything irregular.", "What Deep Scan checks")}</div>
            </div>
            <button class="btn btn-primary btn-sm deep-scan-btn" id="deepScanOpenBtn">Open Deep Scan</button>
          </div>
        </div>` : "";
      const docReqHolder = canRequestDocs ? `<div id="docReqCard" class="cp-card doc-req-card" style="margin-bottom:14px"></div>` : "";
      body.innerHTML = uploader + docReqHolder + deepScanBar + list;
      const dsb = $("#deepScanOpenBtn");
      if (dsb) dsb.onclick = () => showTab("deepscan");
      if (canRequestDocs) { drawDocReq(); if (dr.request === undefined) loadDocReq(); }

      if (canUploadDocs) {
        // Searchable, destination-scoped document-type picker.
        const dtInput = $("#docTypeInput");
        const dtMenu = $("#docTypeMenu");
        const dtItems = clientDocTypes();
        const paintMenu = (q) => {
          const term = (q || "").trim().toLowerCase();
          const matches = term
            ? dtItems.filter((t) => (t.label + " " + (t.hint || "")).toLowerCase().includes(term))
            : dtItems;
          dtMenu.innerHTML = matches.length ? matches.map((t) => `
            <div class="docsel-item" data-label="${esc(t.label)}">
              <div class="docsel-line"><span class="docsel-label">${esc(t.label)}</span>${t.required ? '<span class="docsel-req">Required</span>' : ""}</div>
              ${t.hint ? `<div class="docsel-hint">${esc(t.hint)}</div>` : ""}
            </div>`).join("")
            : `<div class="docsel-empty">No match — press Upload to use "${esc(q)}" as a custom type.</div>`;
          $$(".docsel-item", dtMenu).forEach((el) => {
            el.onmousedown = (e) => {
              e.preventDefault();
              dtInput.value = el.dataset.label;
              dtMenu.classList.add("hidden");
              syncOtherDetail(true);
            };
          });
        };
        // "Other" gets a describe-it field so the stored type is meaningful
        // (e.g. "Other — Police clearance certificate") instead of a bare "Other".
        const syncOtherDetail = (focusWhenShown) => {
          const wrap = $("#docOtherWrap");
          if (!wrap || !dtInput) return;
          const isOther = /^other$/i.test(dtInput.value.trim());
          wrap.style.display = isOther ? "block" : "none";
          if (isOther && focusWhenShown) setTimeout(() => $("#docOtherDetail")?.focus(), 30);
        };
        if (dtInput) {
          dtInput.onfocus = () => { paintMenu(dtInput.value); dtMenu.classList.remove("hidden"); };
          dtInput.oninput = () => { paintMenu(dtInput.value); dtMenu.classList.remove("hidden"); syncOtherDetail(false); };
          dtInput.onblur = () => setTimeout(() => dtMenu.classList.add("hidden"), 140);
          dtInput.onkeydown = (e) => { if (e.key === "Escape") dtMenu.classList.add("hidden"); };
        }

        // The document type is free to stay on its "Other" default, so the file is the only
        // thing that makes this button meaningful — watch it and nothing else.
        bindValidity($("#docUploadBtn"), [$("#docFile")],
          () => { const f = $("#docFile"); return !!(f && f.files && f.files[0]); }, "Choose a file to upload");

        $("#docUploadBtn").onclick = async () => {
          const fileEl = $("#docFile");
          if (!fileEl.files || !fileEl.files[0]) { toast("Choose a file first", "error"); return; }
          let chosenType = (dtInput && dtInput.value.trim()) || "Other";
          if (/^other$/i.test(chosenType)) {
            const detail = ($("#docOtherDetail")?.value || "").trim();
            if (detail) chosenType = "Other — " + detail;   // stored & shown everywhere
          }
          const chk = $("#docScanChk");
          const wantScan = !!(chk && chk.checked && !chk.disabled);
          const fd = new FormData();
          fd.append("file", fileEl.files[0]);
          fd.append("document_type", chosenType);
          fd.append("scan", wantScan ? "true" : "false");
          // withBusy restores through bindValidity, so a failed upload re-enables the button
          // only while a file is still selected.
          await withBusy($("#docUploadBtn"), "Uploading…", async () => {
            try {
              const res = await fetch(API + "/clients/" + cl.id + "/documents", { method: "POST", credentials: "include", body: fd });
              const out = await res.json().catch(() => null);
              if (!res.ok) throw makePublicApiError(res, out, "We couldn't upload this document. Please try again.");
              docs.unshift(out.document);
              // Only poll when a scan is actually running — otherwise the badge would sit on
              // "scanning…" for a document nobody asked to scan.
              if (out.scan_requested && out.document && out.document.id) pendingDocIds.add(out.document.id);
              if (out.scan_pricing) scanPricing = out.scan_pricing;
              tabCount("documents", docs.length);
              toast(out.scan_requested
                ? "Document uploaded — Rilono AI is scanning…"
                : "Document uploaded. You can scan it any time from its card.", "success");
              renderDocs();
              if (out.scan_requested && out.document && out.document.id) pollDocValidation(out.document.id);
            } catch (ex) { toast(ex.message, "error"); }
          });
        };
      }

      // Scan / re-scan one document. Confirmed first because it always spends a credit —
      // unlike upload, where the price was agreed on the card before the file went up.
      $$(".doc-scan", body).forEach((b) => b.onclick = async () => {
        const id = parseInt(b.dataset.id, 10);
        const d = docs.find((x) => x.id === id);
        const already = d && !!d.validated_at && d.validation_status !== "not_scanned";
        const price = scanCost != null ? `${scanCost} credit${scanCost === 1 ? "" : "s"}` : "credits";
        const ok = await confirmModal(
          (already
            ? "Rilono AI will scan this document again and replace the current verdict."
            : "Rilono AI will read this document and cross-check it against the client's profile and their already-validated documents.")
          + ` This costs ${price}.`,
          { title: already ? "Re-scan document?" : "Scan document?", okText: already ? "Re-scan" : "Scan" });
        if (!ok) return;
        b.disabled = true; b.innerHTML = '<span class="spinner"></span> Starting…';
        try {
          const r = await api("/clients/" + cl.id + "/documents/" + id + "/scan", { method: "POST" });
          if (r.scan_pricing) scanPricing = r.scan_pricing;
          if (r.document) { const i = docs.findIndex((x) => x.id === id); if (i >= 0) docs.splice(i, 1, r.document); }
          pendingDocIds.add(id);
          renderDocs();
          pollDocValidation(id);
        } catch (ex) {
          toast(ex.message, "error");
          renderDocs();   // restore the button (and any refreshed price) after a 402/409
        }
      });

      // Delete and "accept anyway" are separate capabilities from uploading, so their
      // wiring lives outside the uploader block — the buttons simply don't exist
      // when the member can't hold them, and these loops then find nothing.
      $$(".doc-del", body).forEach((b) => b.onclick = async () => {
          const id = parseInt(b.dataset.id, 10);
          // confirmModal closes the dialog before it resolves, and this ✕ lives in the page
          // body rather than the modal — so without a lock it is clickable again the instant
          // the user confirms, and stays that way for the whole DELETE.
          if (b.disabled) return;
          if (!(await confirmModal("This document will be permanently deleted. This cannot be undone.", { title: "Delete document?", okText: "Delete" }))) return;
          b.disabled = true;
          try {
            await api("/clients/" + cl.id + "/documents/" + id, { method: "DELETE" });
            const i = docs.findIndex((x) => x.id === id); if (i >= 0) docs.splice(i, 1);
            tabCount("documents", docs.length); toast("Document deleted", "success"); renderDocs();
          } catch (ex) { toast(ex.message, "error"); if (b.isConnected) b.disabled = false; }
        });
        // Human override for AI red flags: staff checked the document themselves.
        $$(".doc-accept", body).forEach((b) => b.onclick = async () => {
          const id = parseInt(b.dataset.id, 10);
          const ok = await confirmModal(
            "Rilono AI flagged this document. Accept it only if you've reviewed it yourself — it will show as “Manually approved” in your name (never as AI-validated), the flag stays on record, and empty profile fields will be auto-filled from it.",
            { title: "Accept this document?", okText: "Accept & apply", danger: false }
          );
          if (!ok) return;
          b.disabled = true;
          try {
            const r = await api("/clients/" + cl.id + "/documents/" + id + "/accept", { method: "POST" });
            const i = docs.findIndex((x) => x.id === id);
            if (i >= 0 && r.document) docs.splice(i, 1, r.document);
            try { const c = await api("/clients/" + cl.id); Object.assign(cl, c.client); } catch (e) {}
            toast("Marked as manually approved — profile updated where empty", "success");
            renderDocs();
          } catch (ex) { b.disabled = false; toast(ex.message, "error"); }
      });
    }

    /* ---- Secure document requests (email a client an upload link) ---- */
    function drawDocReq() {
      const host = $("#docReqCard"); if (!host) return;
      const r = dr.request;
      if (r === undefined) {
        host.innerHTML = `<div class="cp-sub-label">📩 Request documents from client</div><div class="muted" style="padding:6px 0"><span class="spinner dark" style="width:14px;height:14px"></span></div>`;
        return;
      }
      const first = (cl.full_name || "the student").split(" ")[0];
      let inner;
      if (!cl.email) {
        inner = `<p class="muted" style="margin:0;font-size:13.5px">Add an email to this client (Edit details) to request documents by email.</p>`;
      } else if (r && r.live) {
        const ticks = (r.items || []).map((it) =>
          `<div class="docreq-item ${it.received ? "done" : ""}"><span>${it.received ? "✅" : "⏳"} ${esc(it.document_type)}</span><span class="muted">${it.received ? "Received" : "Pending"}</span></div>`).join("");
        inner = `<p class="muted" style="margin:0 0 10px;font-size:13.5px">Secure link sent to <b>${esc(r.email)}</b> · <b>${r.received}/${r.total}</b> received${r.created_at ? " · " + fmtDate(r.created_at) : ""}${r.created_by_name ? " by " + esc(r.created_by_name) : ""}</p>
          <div class="docreq-list">${ticks}</div>
          <div class="row" style="margin-top:12px"><button class="btn btn-soft btn-sm" id="docReqResend">Resend / change</button><button class="btn btn-danger btn-sm" id="docReqRevoke">Revoke link</button></div>`;
      } else {
        inner = `<p class="muted" style="margin:0 0 12px;font-size:13.5px">Email <b>${esc(cl.email)}</b> a secure link so ${esc(first)} can upload the exact documents you need — they verify with a one-time code, and the encrypted files appear here.</p>
          <button class="btn btn-primary btn-sm" id="docReqSend">✉ Request documents</button>`;
      }
      host.innerHTML = `<div class="cp-sub-label">📩 Request documents from client</div>${inner}`;
      const sb = $("#docReqSend"); if (sb) sb.onclick = openDocReqModal;
      const rs = $("#docReqResend"); if (rs) rs.onclick = openDocReqModal;
      const rv = $("#docReqRevoke"); if (rv) rv.onclick = () => revokeDocReq(rv);
    }
    async function loadDocReq() {
      try { const r = await api(`/clients/${cl.id}/document-requests`); dr.request = r.request || null; }
      catch (e) { dr.request = null; }
      drawDocReq();
    }
    function openDocReqModal() {
      const first = (cl.full_name || "the student").split(" ")[0];
      const types = clientDocTypes();
      const checks = `<input type="search" id="docReqFilter" class="docreq-filter" placeholder="Filter ${esc(cl.destination_country_name || "")} document types…" autocomplete="off" />` +
        types.map((t) =>
          `<label class="docreq-check" data-search="${esc((t.label + " " + (t.hint || "")).toLowerCase())}" ${t.hint ? `title="${esc(t.hint)}"` : ""}>
             <input type="checkbox" value="${esc(t.label)}"> <span>${esc(t.label)}${t.required ? ' <b class="docreq-req">Required</b>' : ""}</span>
           </label>`).join("");
      openModal(`<div class="modal-head"><h3>Request documents from ${esc(first)}</h3><button class="x" onclick="__ent.closeModal()">×</button></div>
        <form id="docReqForm"><div class="modal-body">
          <p style="margin:0 0 14px;color:var(--text-2);font-size:14px;line-height:1.6">We'll email a secure link to <b>${esc(cl.email)}</b>. ${esc(first)} verifies with a one-time code, then uploads exactly what you select — files appear here, encrypted.</p>
          <div class="cp-sub-label">Which documents do you need?</div>
          <div class="docreq-checks">${checks}</div>
          <div class="field" style="margin-top:14px"><label>Add a note (optional)</label>
            <textarea id="docReqMsg" rows="3" maxlength="2000" placeholder="e.g. Please make sure your bank statement covers the last 6 months."></textarea></div>
          <div id="docReqErr" class="auth-error hidden"></div>
        </div>
        <div class="modal-foot"><button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary" id="docReqSave" disabled>✉ Send request</button></div></form>`);
      // Watch the form, not #docReqMsg — the note is explicitly optional. Delegated, so the
      // ticks inside .docreq-checks are covered however the filter shows and hides them.
      bindValidity($("#docReqSave"), $("#docReqForm"),
        () => $$("#docReqForm input[type=checkbox]:checked").length > 0, "Select at least one document to request");
      const reqFilter = $("#docReqFilter");
      if (reqFilter) {
        reqFilter.oninput = () => {
          const term = reqFilter.value.trim().toLowerCase();
          $$("#docReqForm .docreq-check").forEach((row) => {
            row.style.display = (!term || (row.dataset.search || "").includes(term)) ? "" : "none";
          });
        };
      }
      $("#docReqForm").onsubmit = async (e) => {
        e.preventDefault();
        const picked = $$("#docReqForm input[type=checkbox]:checked").map((c) => c.value);
        const er = $("#docReqErr");
        if (!picked.length) { er.textContent = "Select at least one document to request."; er.classList.remove("hidden"); return; }
        await withBusy($("#docReqSave"), "Sending…", async () => {
          try {
            const r = await api(`/clients/${cl.id}/document-requests`, { method: "POST", body: { document_types: picked, message: ($("#docReqMsg").value || "").trim() || null } });
            dr.request = r.request; closeModal(); toast(r.message || "Document request sent", r.email_sent ? "success" : "error"); drawDocReq();
          } catch (ex) { er.textContent = ex.message; er.classList.remove("hidden"); }
        });
      };
    }
    // Takes the button so the request can hold it: the card lives in the page body, not in
    // the confirm dialog, so it survives confirmModal closing and would otherwise stay live
    // for the whole POST — a second revoke on an already-revoked link 404s at the student.
    async function revokeDocReq(btn) {
      if (!(await confirmModal("The student's upload link will stop working.", { title: "Revoke document request?", okText: "Revoke" }))) return;
      await withBusy(btn, "Revoking…", async () => {
        try { await api(`/clients/${cl.id}/document-requests/revoke`, { method: "POST" }); dr.request = null; toast("Request revoked", "success"); drawDocReq(); }
        catch (ex) { toast(ex.message, "error"); }
      });
    }

    function renderNotes() {
      const add = canWriteNotes ? `<div class="cp-card note-add">
        <div class="cp-sub-label">Add a note</div>
        <textarea id="noteInput" placeholder="Log a call, a follow-up or a decision about ${esc(cl.full_name)}…"></textarea>
        <button class="btn btn-primary btn-sm" id="noteSaveBtn" disabled>Add note</button></div>` : "";
      // notes.moderate deletes anyone's note (incl. AI-generated); notes.write only their own.
      const myId = state.me && state.me.user ? state.me.user.id : null;
      const canDeleteNote = (n) => canModerateNotes || (canWriteNotes && myId != null && n.author_user_id === myId);
      const list = data.notes.length ? `<div class="timeline">${data.notes.map((n) =>
        `<div class="tl-item"><div class="tl-meta">${esc(n.author_name || "Team")} · ${fmtDateTime(n.created_at)}${canDeleteNote(n) ? `<button class="tl-del" data-note-id="${n.id}" title="Delete note" aria-label="Delete note">✕</button>` : ""}</div><div class="tl-body">${esc(n.body)}</div></div>`).join("")}</div>`
        : `<div class="empty" style="padding:30px"><div class="emoji">📝</div><h3>No notes yet</h3><p>Keep a running record of calls, follow-ups and decisions.</p></div>`;
      body.innerHTML = add + list;
      if (canWriteNotes) {
        // This used to be a silent `if (!v) return` — the button looked live, ate the click
        // and said nothing. Disabled-until-typed says the same thing without the dead click.
        bindValidity($("#noteSaveBtn"), [$("#noteInput")],
          () => $("#noteInput").value.trim() !== "", "Write a note first");
        $("#noteSaveBtn").onclick = async () => {
          const v = $("#noteInput").value.trim(); if (!v) return;
          await withBusy($("#noteSaveBtn"), "", async () => {
            try { const r = await api(`/clients/${cl.id}/notes`, { method: "POST", body: { body: v } }); data.notes.unshift(r.note); tabCount("notes", data.notes.length); renderNotes(); toast("Note added", "success"); }
            catch (ex) { toast(ex.message, "error"); }
          });
        };
      }
      $$(".tl-del", body).forEach((b) => b.onclick = async () => {
        const id = parseInt(b.dataset.noteId, 10);
        if (!(await confirmModal("This note will be permanently deleted.", { title: "Delete note?", okText: "Delete" }))) return;
        b.disabled = true;
        try {
          await api(`/clients/${cl.id}/notes/${id}`, { method: "DELETE" });
          const i = data.notes.findIndex((x) => x.id === id); if (i >= 0) data.notes.splice(i, 1);
          tabCount("notes", data.notes.length); renderNotes(); toast("Note deleted", "success");
        } catch (ex) { toast(ex.message, "error"); b.disabled = false; }
      });
    }

    /* ---- Emails tab: rich-text composer + conversation thread ---- */

    const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
    const EM_SEND_HINT = IS_MAC ? "⌘ + Enter" : "Ctrl + Enter";
    // Mirrors ENTERPRISE_EMAIL_ATTACH_MAX_FILES / _MAX_TOTAL_BYTES on the server.
    const EM_MAX_FILES = 10;
    const EM_MAX_TOTAL_BYTES = 15 * 1024 * 1024;

    // Merge-field values for this client. Every field has a readable fallback so a
    // template never emails a student a blank or a leftover {{placeholder}}.
    function emMergeValues() {
      const meUser = (state.me && state.me.user) || {};
      const org = (state.me && state.me.organization) || {};
      return {
        first_name: (cl.full_name || "").trim().split(/\s+/)[0] || "there",
        full_name: cl.full_name || "there",
        destination: cl.destination_country_name || "your destination",
        visa_type: cl.visa_type || "visa",
        intake: cl.intake || "your intake",
        target_date: cl.target_date ? fmtDate(cl.target_date) : "the scheduled date",
        counselor: meUser.full_name || meUser.email || "your counselor",
        company: (org.company_name || "our team"),
      };
    }
    function emMerge(text, asHtml) {
      const values = emMergeValues();
      return String(text || "").replace(/\{\{\s*(\w+)\s*\}\}/g, (whole, key) => {
        const value = values[key];
        if (value == null) return whole;
        return asHtml ? esc(value) : value;
      });
    }

    /* -- attachments -- */
    function emAttsHtml() {
      if (!em.attachments.length) return "";
      return em.attachments.map((a) => {
        const cls = a.status === "error" ? " is-error" : a.status === "uploading" ? " is-uploading" : "";
        const meta = a.status === "uploading" ? (a.pct || 0) + "%"
          : a.status === "error" ? "Couldn't upload" : fmtSize(a.size);
        return `<div class="emc-chip${cls}">
            <span class="emc-chip-ic">${a.status === "error" ? "⚠️" : docIcon(a.name)}</span>
            <span class="emc-chip-name" title="${esc(a.name)}">${esc(a.name)}</span>
            <span class="emc-chip-meta">${esc(meta)}</span>
            ${a.documentId ? '<span class="emc-chip-tag">on file</span>' : ""}
            <button type="button" class="emc-chip-x" data-uid="${esc(a.uid)}" aria-label="Remove ${esc(a.name)}">✕</button>
            ${a.status === "uploading" ? `<span class="emc-chip-bar" style="width:${a.pct || 0}%"></span>` : ""}
          </div>`;
      }).join("");
    }
    function emDrawAtts() {
      const host = $("#emAtts");
      if (!host) return;
      host.innerHTML = emAttsHtml();
      host.classList.toggle("hidden", !em.attachments.length);
      $$(".emc-chip-x", host).forEach((b) => b.onclick = () => emRemoveAttachment(b.dataset.uid));
      const total = em.attachments.reduce((sum, a) => sum + (a.size || 0), 0);
      const note = $("#emAttNote");
      if (note) {
        note.textContent = em.attachments.length
          ? `${em.attachments.length} file${em.attachments.length === 1 ? "" : "s"} · ${fmtSize(total)}` : "";
      }
      emSyncSend();
    }
    /* Send is held only for attachment state — a file still uploading, or one that failed.
       Subject and body keep their toasts: the body is a contenteditable whose emptiness is
       not reliably observable (a stray <br> or an empty <div> from the browser both read as
       content), so gating on it would strand a composed email behind a dead button. This
       runs from emDrawAtts, which already fires on every upload start, tick, finish, failure
       and removal — so the button tracks the uploads rather than waiting for a click. */
    function emSyncSend() {
      const btn = $("#emSendBtn");
      if (!btn || em.busy) return;
      const uploading = em.attachments.some((a) => a.status === "uploading");
      const failed = em.attachments.some((a) => a.status === "error");
      btn.disabled = uploading || failed;
      btn.title = uploading ? "Waiting for attachments to finish uploading"
        : failed ? "Remove the attachment that failed to upload, then send" : "";
    }
    async function emRemoveAttachment(uid) {
      const index = em.attachments.findIndex((a) => a.uid === uid);
      if (index < 0) return;
      const entry = em.attachments[index];
      if (entry.xhr && entry.status === "uploading") { try { entry.xhr.abort(); } catch (e) {} }
      em.attachments.splice(index, 1);
      emDrawAtts();
      if (entry.id) {
        // Best-effort: the draft is swept server-side anyway if this ever fails.
        try { await api(`/clients/${cl.id}/email/attachments/${entry.id}`, { method: "DELETE" }); } catch (e) {}
      }
    }
    function emUploadFile(file) {
      const entry = {
        uid: "u" + (++em.seq), name: file.name || "file", size: file.size || 0,
        status: "uploading", pct: 0, id: null, xhr: null,
      };
      em.attachments.push(entry);
      emDrawAtts();

      const form = new FormData();
      form.append("file", file);
      const xhr = new XMLHttpRequest();
      entry.xhr = xhr;
      xhr.open("POST", API + "/clients/" + cl.id + "/email/attachments");
      xhr.withCredentials = true;
      xhr.upload.onprogress = (e) => {
        if (!e.lengthComputable) return;
        entry.pct = Math.min(99, Math.round((e.loaded / e.total) * 100));
        emDrawAtts();
      };
      xhr.onload = () => {
        let out = null;
        try { out = JSON.parse(xhr.responseText); } catch (e) {}
        if (xhr.status >= 200 && xhr.status < 300 && out && out.attachment) {
          entry.status = "done";
          entry.pct = 100;
          entry.id = out.attachment.id;
          entry.size = out.attachment.file_size || entry.size;
        } else {
          entry.status = "error";
          const detail = out && typeof out.detail === "string" && out.detail.length < 300 ? out.detail : "";
          toast(detail || `Couldn't attach ${entry.name}`, "error");
        }
        entry.xhr = null;
        emDrawAtts();
      };
      xhr.onerror = () => {
        entry.status = "error"; entry.xhr = null; emDrawAtts();
        toast("Upload failed — check your connection and try again", "error");
      };
      // Without this a stalled connection leaves the chip spinning forever and the
      // send button permanently blocked on an upload that will never finish.
      xhr.timeout = 180000;
      xhr.ontimeout = () => {
        entry.status = "error"; entry.xhr = null; emDrawAtts();
        toast(`${entry.name} took too long to upload — remove it and try again`, "error");
      };
      xhr.send(form);
    }
    function emAddFiles(fileList) {
      const files = Array.prototype.slice.call(fileList || []);
      if (!files.length) return;
      const room = EM_MAX_FILES - em.attachments.length;
      if (room <= 0) { toast(`You can attach up to ${EM_MAX_FILES} files to one email`, "error"); return; }
      const used = em.attachments.reduce((sum, a) => sum + (a.size || 0), 0);
      const accepted = [];
      let running = used;
      files.slice(0, room).forEach((f) => {
        if (running + (f.size || 0) > EM_MAX_TOTAL_BYTES) return;   // don't upload what the server will refuse
        running += f.size || 0;
        accepted.push(f);
      });
      accepted.forEach(emUploadFile);
      const skipped = files.length - accepted.length;
      if (skipped > 0) {
        toast(
          accepted.length
            ? `${skipped} file${skipped === 1 ? "" : "s"} skipped — an email can carry ${EM_MAX_FILES} files totalling ${fmtSize(EM_MAX_TOTAL_BYTES)}`
            : `That's over the ${fmtSize(EM_MAX_TOTAL_BYTES)} limit for one email. Share the file as a link instead.`,
          "error");
      }
    }

    /* -- selection helpers: toolbar clicks must not steal the caret -- */
    let emSavedRange = null;
    function emSaveRange() {
      const editor = $("#emEditor");
      const sel = window.getSelection();
      if (!editor || !sel || !sel.rangeCount) return;
      const range = sel.getRangeAt(0);
      if (editor.contains(range.commonAncestorContainer)) emSavedRange = range.cloneRange();
    }
    function emRestoreRange() {
      const editor = $("#emEditor");
      if (!editor) return;
      editor.focus();
      if (!emSavedRange) return;
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(emSavedRange);
    }
    function emInsertHtml(html) {
      emRestoreRange();
      document.execCommand("insertHTML", false, html);
      emSyncEditor();
    }
    function emExec(command, value) {
      emRestoreRange();
      try { document.execCommand("styleWithCSS", false, false); } catch (e) {}
      try { document.execCommand(command, false, value || null); } catch (e) {}
      emSaveRange();
      emSyncEditor();
      emSyncToolbar();
    }
    // Keep the composer's cached copy current so switching tabs never loses a draft.
    function emSyncEditor() {
      const editor = $("#emEditor");
      if (!editor) return;
      em.html = editor.innerHTML;
      editor.classList.toggle("is-empty", !(editor.textContent || "").trim() && !editor.querySelector("li, hr"));
    }
    function emSyncToolbar() {
      const bar = $("#emToolbar");
      if (!bar) return;
      $$(".emc-tb[data-cmd]", bar).forEach((b) => {
        const cmd = b.dataset.cmd;
        let on = false;
        try { on = document.queryCommandState(cmd); } catch (e) {}
        b.classList.toggle("active", !!on);
      });
    }

    /* -- link dialog (never window.prompt) -- */
    function emOpenLinkDialog() {
      emSaveRange();
      const selected = emSavedRange ? String(emSavedRange).trim() : "";
      const presetUrl = /^(https?:\/\/|mailto:|www\.)/i.test(selected) ? selected : "";
      openModal(`
        <div class="modal-head"><h3>Insert link</h3><button class="x" id="lkClose" aria-label="Close">×</button></div>
        <div class="modal-body">
          <div class="field"><label>Link to</label>
            <input type="text" id="lkUrl" placeholder="https://example.com or name@email.com" value="${esc(presetUrl)}" autocomplete="off"></div>
          <div class="field"><label>Text to show</label>
            <input type="text" id="lkText" placeholder="e.g. Book your slot" value="${esc(presetUrl ? "" : selected)}" autocomplete="off"></div>
          <p class="muted" style="margin:2px 0 0;font-size:12.5px">Links open in a new tab for the student.</p>
        </div>
        <div class="modal-foot">
          <button type="button" class="btn btn-ghost" id="lkCancel">Cancel</button>
          <button type="button" class="btn btn-primary" id="lkOk">Insert link</button>
        </div>`);
      const urlEl = $("#lkUrl");
      setTimeout(() => urlEl && urlEl.focus(), 40);
      const close = () => closeModal();
      $("#lkClose").onclick = close;
      $("#lkCancel").onclick = close;
      const submit = () => {
        let raw = (urlEl.value || "").trim();
        if (!raw) { toast("Add a link address", "error"); return; }
        // Typing "rilono.com" or an email address should just work.
        if (/^www\./i.test(raw) || /^[\w.-]+\.[a-z]{2,}(\/|$)/i.test(raw)) raw = "https://" + raw;
        else if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(raw)) raw = "mailto:" + raw;
        const href = safeLinkUrl(raw);
        if (!href) { toast("That link isn't valid. Use a https:// address or an email.", "error"); return; }
        const label = ($("#lkText").value || "").trim() || selected || href.replace(/^mailto:/, "");
        closeModal();
        emInsertHtml(`<a href="${esc(href)}" target="_blank" rel="noopener noreferrer nofollow">${esc(label)}</a>&nbsp;`);
      };
      $("#lkOk").onclick = submit;
      [urlEl, $("#lkText")].forEach((el) => el.onkeydown = (e) => {
        if (e.key === "Enter") { e.preventDefault(); submit(); }
      });
    }

    /* -- attach a document already on file -- */
    function emOpenDocsDialog() {
      if (!docs.length) {
        toast("No documents on file for this client yet", "error");
        return;
      }
      const already = new Set(em.attachments.filter((a) => a.documentId).map((a) => a.documentId));
      openModal(`
        <div class="modal-head"><h3>Attach from documents on file</h3><button class="x" id="adClose" aria-label="Close">×</button></div>
        <div class="modal-body">
          <p class="muted" style="margin:0 0 12px;font-size:13.5px">These are ${esc(cl.full_name.split(" ")[0])}'s stored documents. A copy is sent with the email, so deleting the original later won't change what was sent.</p>
          <div class="docreq-checks">
            ${docs.map((d) => `
              <label class="docreq-check">
                <input type="checkbox" value="${d.id}" ${already.has(d.id) ? "checked disabled" : ""}>
                <span style="flex:1;min-width:0">
                  <span style="display:block;font-weight:600">${docIcon(d.original_filename)} ${esc(d.original_filename)}</span>
                  <span class="muted" style="font-size:12px">${esc(d.document_type)} · ${fmtSize(d.file_size)}${already.has(d.id) ? " · already attached" : ""}</span>
                </span>
              </label>`).join("")}
          </div>
        </div>
        <div class="modal-foot">
          <button type="button" class="btn btn-ghost" id="adCancel">Cancel</button>
          <button type="button" class="btn btn-primary" id="adOk">Attach selected</button>
        </div>`);
      $("#adClose").onclick = closeModal;
      $("#adCancel").onclick = closeModal;
      $("#adOk").onclick = () => {
        const picked = $$(".docreq-checks input:checked:not(:disabled)").map((i) => parseInt(i.value, 10));
        if (!picked.length) { toast("Pick at least one document", "error"); return; }
        if (em.attachments.length + picked.length > EM_MAX_FILES) {
          toast(`You can attach up to ${EM_MAX_FILES} files to one email`, "error"); return;
        }
        // Mirror the server ceiling here so an oversized pick is refused before the
        // server copies anything (the copy is what costs storage).
        const projected = em.attachments.reduce((sum, a) => sum + (a.size || 0), 0)
          + picked.reduce((sum, id) => sum + ((docs.find((d) => d.id === id) || {}).file_size || 0), 0);
        if (projected > EM_MAX_TOTAL_BYTES) {
          toast(`Attachments would total ${fmtSize(projected)} — the limit is ${fmtSize(EM_MAX_TOTAL_BYTES)} per email. Send a secure link instead.`, "error");
          return;
        }
        picked.forEach((id) => {
          const doc = docs.find((d) => d.id === id);
          if (!doc) return;
          em.attachments.push({
            uid: "d" + (++em.seq), name: doc.original_filename, size: doc.file_size || 0,
            status: "done", pct: 100, id: null, documentId: doc.id,
          });
        });
        closeModal();
        emDrawAtts();
      };
    }

    /* -- templates & merge fields -- */
    function emApplyTemplate(key) {
      const tpl = EMAIL_TEMPLATES.find((t) => t.key === key);
      if (!tpl) return;
      const subjectEl = $("#emSubject");
      const editor = $("#emEditor");
      if (!subjectEl || !editor) return;
      const write = () => {
        subjectEl.value = emMerge(tpl.subject, false);
        editor.innerHTML = sanitizeRichHtml(emMerge(tpl.body, true));
        em.subject = subjectEl.value;
        emSyncEditor();
        editor.focus();
      };
      const hasContent = (editor.textContent || "").trim() || (subjectEl.value || "").trim();
      if (!hasContent) { write(); return; }
      confirmModal("Applying this template replaces what you've written so far.", {
        title: "Replace your draft?", okText: "Use template", danger: false,
      }).then((ok) => { if (ok) write(); });
    }

    /* -- send -- */
    async function emSend() {
      if (em.busy) return;
      const subjectEl = $("#emSubject");
      const editor = $("#emEditor");
      if (!subjectEl || !editor) return;
      const subject = (subjectEl.value || "").trim();
      const text = (editor.innerText || "").replace(/\u00a0/g, " ").trim();
      if (!subject) { toast("Add a subject so the student knows what this is about", "error"); subjectEl.focus(); return; }
      if (!text) { toast("Write a message before sending", "error"); editor.focus(); return; }
      if (em.attachments.some((a) => a.status === "uploading")) { toast("Hold on — attachments are still uploading", "error"); return; }
      if (em.attachments.some((a) => a.status === "error")) { toast("Remove the attachment that failed to upload, then send", "error"); return; }

      const payload = {
        subject: subject,
        body: text,
        body_html: sanitizeRichHtml(editor.innerHTML),
        attachment_ids: em.attachments.filter((a) => a.id).map((a) => a.id),
        document_ids: em.attachments.filter((a) => a.documentId).map((a) => a.documentId),
      };
      const btn = $("#emSendBtn");
      em.busy = true;
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> Sending…';
      try {
        // Attachments are relayed to the mail provider inline, so this can outlast a
        // normal CRM call — give it room rather than aborting a send that succeeds.
        const r = await api(`/clients/${cl.id}/email`, { method: "POST", body: payload, timeout: 90000 });
        data.emails.unshift(r.email);
        tabCount("emails", data.emails.length);
        em.subject = ""; em.html = ""; em.attachments = []; em.busy = false;
        renderEmails();
        toast(`Email sent to ${cl.full_name.split(" ")[0] || "the client"}`, "success");
      } catch (ex) {
        em.busy = false;
        toast(ex.message, "error");
        btn.innerHTML = `${EM_ICONS.send} Send email`;
        emSyncSend();   // not a blanket re-enable — a failed attachment still holds the send
      }
    }

    /* -- composer markup -- */
    const EM_ICONS = {
      ul: '<svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="3.4" cy="5" r="1.2" fill="currentColor" stroke="none"/><circle cx="3.4" cy="10" r="1.2" fill="currentColor" stroke="none"/><circle cx="3.4" cy="15" r="1.2" fill="currentColor" stroke="none"/><path d="M7.5 5h9M7.5 10h9M7.5 15h9"/></svg>',
      ol: '<svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M7.5 5h9M7.5 10h9M7.5 15h9"/><text x="1" y="7" font-size="6" fill="currentColor" stroke="none" font-family="system-ui">1</text><text x="1" y="12.4" font-size="6" fill="currentColor" stroke="none" font-family="system-ui">2</text><text x="1" y="17.6" font-size="6" fill="currentColor" stroke="none" font-family="system-ui">3</text></svg>',
      link: '<svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M8.5 11.5a3.4 3.4 0 0 0 5 .3l2.2-2.2a3.4 3.4 0 0 0-4.8-4.8l-1.3 1.2"/><path d="M11.5 8.5a3.4 3.4 0 0 0-5-.3L4.3 10.4a3.4 3.4 0 0 0 4.8 4.8l1.2-1.2"/></svg>',
      unlink: '<svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M8.5 11.5a3.4 3.4 0 0 0 5 .3l1.2-1.2"/><path d="M11.5 8.5a3.4 3.4 0 0 0-5-.3l-1.2 1.2a3.4 3.4 0 0 0 2.4 5.8"/><path d="M3 3l14 14"/></svg>',
      quote: '<svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor"><path d="M7.6 5.2c-2.3 1-3.8 3.1-3.8 5.7 0 2.3 1.3 3.9 3.1 3.9 1.5 0 2.7-1.1 2.7-2.6s-1-2.5-2.4-2.5c-.2 0-.5 0-.7.1.3-1.2 1.2-2.2 2.4-2.8l-1.3-1.8Zm7.3 0c-2.3 1-3.8 3.1-3.8 5.7 0 2.3 1.3 3.9 3.1 3.9 1.5 0 2.7-1.1 2.7-2.6s-1-2.5-2.4-2.5c-.2 0-.5 0-.7.1.3-1.2 1.2-2.2 2.4-2.8l-1.3-1.8Z"/></svg>',
      clear: '<svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6.5 4.5h9M9 4.5 7.5 15.5M12.5 9.5l4 4M16.5 9.5l-4 4"/></svg>',
      attach: '<svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M14.5 9.2 9.3 14.4a3.3 3.3 0 0 1-4.7-4.7l5.6-5.6a2.2 2.2 0 0 1 3.1 3.1l-5.5 5.6a1.1 1.1 0 0 1-1.6-1.6l5-5"/></svg>',
      send: '<svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 2.5 9 11M17.5 2.5l-5.6 15-3-6.5-6.4-3 15-5.5Z"/></svg>',
    };

    function emComposerHtml() {
      if (!canSendEmail) return "";
      if (!cl.email) {
        return `<div class="plan-banner warn" style="margin-bottom:18px">
          <div class="pb-icon">✉</div>
          <div class="pb-text"><b>No email address on file.</b>
            <span>Add one under “Edit details” to message ${esc(cl.full_name.split(" ")[0] || "this client")}.</span></div>
          <button class="btn btn-soft btn-sm" id="emAddEmail">Add an email</button></div>`;
      }
      const meUser = (state.me && state.me.user) || {};
      const [c1, c2] = avatarColor(cl.email || cl.full_name);
      const tb = (cmd, label, title, extra) =>
        `<button type="button" class="emc-tb${extra || ""}" data-cmd="${cmd}" title="${esc(title)}" aria-label="${esc(title)}">${label}</button>`;
      return `
      <div class="emc" id="emCompose">
        <div class="emc-dropzone" id="emDrop" aria-hidden="true"><div>${EM_ICONS.attach} Drop files to attach</div></div>
        <div class="emc-head">
          <span class="emc-to-label">To</span>
          <span class="emc-recipient">
            <span class="emc-av" style="background:linear-gradient(135deg,${c1},${c2})">${esc(initials(cl.full_name) || "C")}</span>
            <b>${esc(cl.full_name)}</b><span class="emc-email">${esc(cl.email)}</span>
          </span>
          <div style="flex:1"></div>
          <div class="emc-menu-wrap">
            <button type="button" class="emc-tool" id="emTplBtn" aria-haspopup="true" aria-expanded="false">⚡ Templates</button>
            <div class="emc-menu emc-menu-right hidden" id="emTplMenu" role="menu">
              <div class="emc-menu-label">Start from a template</div>
              ${EMAIL_TEMPLATES.map((t) => `<button type="button" class="emc-menu-item" role="menuitem" data-tpl="${t.key}">
                  <span class="emc-menu-ic">${t.icon}</span>
                  <span><b>${esc(t.label)}</b><small>${esc(t.hint)}</small></span>
                </button>`).join("")}
            </div>
          </div>
        </div>

        <input id="emSubject" class="emc-subject" type="text" maxlength="200" autocomplete="off"
          placeholder="Subject" value="${esc(em.subject)}" aria-label="Subject">

        <div class="emc-toolbar" id="emToolbar">
          ${tb("bold", "<b>B</b>", "Bold (" + (IS_MAC ? "⌘B" : "Ctrl+B") + ")")}
          ${tb("italic", "<i>I</i>", "Italic (" + (IS_MAC ? "⌘I" : "Ctrl+I") + ")")}
          ${tb("underline", "<u>U</u>", "Underline (" + (IS_MAC ? "⌘U" : "Ctrl+U") + ")")}
          <span class="emc-tb-sep"></span>
          ${tb("insertUnorderedList", EM_ICONS.ul, "Bulleted list")}
          ${tb("insertOrderedList", EM_ICONS.ol, "Numbered list")}
          ${tb("formatBlock:h3", "H", "Heading")}
          ${tb("formatBlock:blockquote", EM_ICONS.quote, "Quote")}
          <span class="emc-tb-sep"></span>
          <button type="button" class="emc-tb" id="emLinkBtn" title="Insert link (${IS_MAC ? "⌘K" : "Ctrl+K"})" aria-label="Insert link">${EM_ICONS.link}</button>
          ${tb("unlink", EM_ICONS.unlink, "Remove link")}
          ${tb("removeFormat", EM_ICONS.clear, "Clear formatting")}
          <div style="flex:1"></div>
          <div class="emc-menu-wrap">
            <button type="button" class="emc-tool emc-tool-sm" id="emFieldBtn" aria-haspopup="true" aria-expanded="false">Insert detail</button>
            <div class="emc-menu emc-menu-right hidden" id="emFieldMenu" role="menu">
              <div class="emc-menu-label">Insert from this client's file</div>
              ${EMAIL_MERGE_FIELDS.map((f) => `<button type="button" class="emc-menu-item is-compact" role="menuitem" data-field="${f.key}">
                  <span><b>${esc(f.label)}</b><small>${esc(emMergeValues()[f.key] || "—")}</small></span>
                </button>`).join("")}
            </div>
          </div>
        </div>

        <div id="emEditor" class="emc-editor is-empty" contenteditable="true" role="textbox" aria-multiline="true"
          aria-label="Message" data-placeholder="Write your message…"></div>

        <div class="emc-atts hidden" id="emAtts"></div>

        <div class="emc-foot">
          <button class="btn btn-primary btn-sm emc-send" id="emSendBtn">${EM_ICONS.send} Send email</button>
          <button type="button" class="emc-tool" id="emAttachBtn">${EM_ICONS.attach} Attach files</button>
          <button type="button" class="emc-tool" id="emDocsBtn">🗂 From documents${docs.length ? ` (${docs.length})` : ""}</button>
          <input type="file" id="emFile" class="hidden" multiple
            accept=".pdf,.jpg,.jpeg,.png,.webp,.gif,.heic,.doc,.docx,.xls,.xlsx,.csv,.txt">
          <span class="emc-att-note" id="emAttNote"></span>
          <div class="emc-foot-spacer"></div>
          <button type="button" class="emc-tool emc-tool-ghost" id="emDiscard">Discard</button>
        </div>
        <div class="emc-hint">
          <span>↩ Replies go to <b>${esc(meUser.email || "your inbox")}</b></span>
          <span class="emc-hint-sep">·</span><span>${esc(EM_SEND_HINT)} to send</span>
          <span class="emc-hint-sep">·</span><span>🔒 Attachments encrypted · up to 10 files, 15 MB</span>
        </div>
      </div>`;
    }

    /* -- conversation thread -- */
    function emThreadHtml() {
      const all = data.emails || [];
      if (!all.length) {
        return `<div class="empty" style="padding:38px 30px"><div class="emoji">✉️</div>
          <h3>No emails yet</h3>
          <p>${canSendEmail && cl.email
            ? "Everything you send from here is kept on the client's file, so your whole team sees the same history."
            : "Messages sent to this client will appear here."}</p></div>`;
      }
      const query = (em.query || "").trim().toLowerCase();
      const rows = all.filter((m) => {
        if (em.filter === "sent" && m.direction === "inbound") return false;
        if (em.filter === "replies" && m.direction !== "inbound") return false;
        if (!query) return true;
        return ((m.subject || "") + " " + (m.body || "")).toLowerCase().includes(query);
      });
      const replies = all.filter((m) => m.direction === "inbound").length;
      const showTools = all.length >= 3;
      const chip = (key, label) =>
        `<button type="button" class="emt-chip${em.filter === key ? " active" : ""}" data-filter="${key}">${esc(label)}</button>`;
      const head = `
        <div class="emt-head">
          <div class="emt-title">Conversation<span class="emt-count">${all.length}</span></div>
          ${showTools ? `<div class="emt-filters">
              ${chip("all", "All")}${chip("sent", "Sent")}${replies ? chip("replies", `Replies (${replies})`) : ""}
            </div>
            <input type="search" class="emt-search" id="emSearch" placeholder="Search this conversation…"
              value="${esc(em.query)}" aria-label="Search this conversation">` : ""}
        </div>`;

      if (!rows.length) {
        return head + `<div class="empty" style="padding:30px"><div class="emoji">🔍</div><h3>Nothing matches</h3>
          <p>Try a different search or clear the filter.</p></div>`;
      }

      const messages = rows.map((m) => {
        const inbound = m.direction === "inbound";
        const failed = m.status === "failed";
        const who = inbound ? (m.from_email || cl.full_name) : (m.sent_by_name || "Your team");
        const [a1, a2] = avatarColor(inbound ? (m.from_email || cl.email || cl.full_name) : who);
        const mismatch = inbound && m.from_email && cl.email &&
          m.from_email.toLowerCase() !== cl.email.trim().toLowerCase();
        // Rich HTML is only ever rendered for messages this org composed. Inbound mail
        // is plain text by design and stays escaped.
        const bodyHtml = (!inbound && m.body_html)
          ? sanitizeRichHtml(m.body_html)
          : plainTextToHtml(m.body || "");
        const long = (m.body || "").length > 620;
        const open = !!em.expanded[m.id];
        const atts = (m.attachments || []).length ? `<div class="em-msg-atts">${m.attachments.map((a) => `
            <a class="em-att" href="${esc(a.download_url || "#")}" target="_blank" rel="noopener">
              <span>${docIcon(a.filename)}</span><b>${esc(a.filename)}</b><span class="em-att-size">${fmtSize(a.file_size)}</span>
            </a>`).join("")}</div>` : "";
        return `
        <article class="em-msg${inbound ? " is-inbound" : ""}${failed ? " is-failed" : ""}">
          <div class="em-av" style="background:linear-gradient(135deg,${a1},${a2})">${esc(initials(who) || (inbound ? "S" : "T"))}</div>
          <div class="em-msg-main">
            <div class="em-msg-top">
              <div class="em-msg-who">
                <b>${esc(who)}</b>
                <span>${inbound ? "replied" : `to ${esc(cl.full_name.split(" ")[0] || "client")}`}</span>
                ${mismatch ? '<span class="ei-unverified">· not the address on file</span>' : ""}
                ${failed ? '<span class="em-tag is-fail">Not delivered</span>' : ""}
              </div>
              <time class="em-msg-when" title="${esc(fmtDateTime(m.created_at))}">${esc(fmtDateTime(m.created_at))}</time>
            </div>
            <h4 class="em-msg-subject">${esc(m.subject)}</h4>
            <div class="em-msg-body${long && !open ? " is-clamped" : ""}">${bodyHtml}</div>
            ${long ? `<button type="button" class="em-more" data-id="${m.id}">${open ? "Show less" : "Show more"}</button>` : ""}
            ${atts}
            ${failed ? `<div class="ei-fail">⚠ Delivery failed${m.error_message ? ": " + esc(m.error_message) : ""}</div>` : ""}
          </div>
        </article>`;
      }).join("");
      return head + `<div class="em-thread">${messages}</div>`;
    }

    function emDrawThread() {
      const host = $("#emThread");
      if (!host) return;
      host.innerHTML = emThreadHtml();
      $$(".emt-chip", host).forEach((b) => b.onclick = () => { em.filter = b.dataset.filter; emDrawThread(); });
      $$(".em-more", host).forEach((b) => b.onclick = () => {
        em.expanded[b.dataset.id] = !em.expanded[b.dataset.id];
        emDrawThread();
      });
      const search = $("#emSearch", host);
      if (search) {
        search.oninput = () => {
          em.query = search.value;
          const at = search.selectionStart;
          emDrawThread();
          const again = $("#emSearch");
          if (again) { again.focus(); try { again.setSelectionRange(at, at); } catch (e) {} }
        };
      }
    }

    function renderEmails() {
      body.innerHTML = emComposerHtml() + `<div id="emThread"></div>`;
      emDrawThread();

      const addEmail = $("#emAddEmail");
      if (addEmail) addEmail.onclick = () => { overviewEditing = true; showTab("overview"); };

      const editor = $("#emEditor");
      if (!editor) return;   // read-only member, or no email on file

      const subjectEl = $("#emSubject");
      editor.innerHTML = em.html || "";
      emSyncEditor();
      emDrawAtts();
      if (!em.draftsLoaded) { em.draftsLoaded = true; emLoadDraftAttachments(); }

      subjectEl.oninput = () => { em.subject = subjectEl.value; };
      subjectEl.onkeydown = (e) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        // ⌘/Ctrl+Enter sends from anywhere; a plain Enter just moves on to the body.
        if (e.metaKey || e.ctrlKey) emSend();
        else editor.focus();
      };

      // Toolbar: mousedown-preventDefault keeps the caret in the editor.
      $$(".emc-tb", $("#emToolbar")).forEach((btn) => {
        btn.onmousedown = (e) => { e.preventDefault(); emSaveRange(); };
        btn.onclick = () => {
          const cmd = btn.dataset.cmd;
          if (!cmd) return;
          if (cmd.indexOf("formatBlock:") === 0) {
            const tag = cmd.split(":")[1];
            // Toggle back to a paragraph when the block is already applied.
            let current = "";
            try { current = (document.queryCommandValue("formatBlock") || "").toLowerCase(); } catch (e) {}
            emExec("formatBlock", "<" + (current === tag ? "p" : tag) + ">");
            return;
          }
          emExec(cmd);
        };
      });
      const linkBtn = $("#emLinkBtn");
      linkBtn.onmousedown = (e) => { e.preventDefault(); emSaveRange(); };
      linkBtn.onclick = emOpenLinkDialog;

      editor.oninput = () => { emSyncEditor(); emSaveRange(); };
      editor.onkeyup = () => { emSaveRange(); emSyncToolbar(); };
      editor.onmouseup = () => { emSaveRange(); emSyncToolbar(); };
      editor.onblur = emSaveRange;
      editor.onkeydown = (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); emSend(); return; }
        if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) { e.preventDefault(); emOpenLinkDialog(); }
      };
      // Pasted markup is rebuilt through the allow-list before it touches the DOM.
      editor.onpaste = (e) => {
        if (!e.clipboardData) return;
        const html = e.clipboardData.getData("text/html");
        const text = e.clipboardData.getData("text/plain");
        if (!html && !text) return;
        e.preventDefault();
        document.execCommand("insertHTML", false, html ? sanitizeRichHtml(html) : plainTextToHtml(text));
        emSyncEditor();
      };

      const tplBtn = $("#emTplBtn"), tplMenu = $("#emTplMenu");
      tplBtn.onclick = (e) => {
        e.stopPropagation();
        const open = tplMenu.classList.contains("hidden");
        emCloseMenus();
        tplMenu.classList.toggle("hidden", !open);
        tplBtn.setAttribute("aria-expanded", String(open));
      };
      $$(".emc-menu-item[data-tpl]", tplMenu).forEach((b) => b.onclick = () => {
        emCloseMenus(); emApplyTemplate(b.dataset.tpl);
      });

      const fieldBtn = $("#emFieldBtn"), fieldMenu = $("#emFieldMenu");
      fieldBtn.onmousedown = (e) => { e.preventDefault(); emSaveRange(); };
      fieldBtn.onclick = (e) => {
        e.stopPropagation();
        const open = fieldMenu.classList.contains("hidden");
        emCloseMenus();
        fieldMenu.classList.toggle("hidden", !open);
        fieldBtn.setAttribute("aria-expanded", String(open));
      };
      $$(".emc-menu-item[data-field]", fieldMenu).forEach((b) => b.onmousedown = (e) => {
        e.preventDefault();
        emCloseMenus();
        emInsertHtml(esc(emMergeValues()[b.dataset.field] || ""));
      });

      $("#emSendBtn").onclick = emSend;
      const fileInput = $("#emFile");
      $("#emAttachBtn").onclick = () => fileInput.click();
      fileInput.onchange = () => { emAddFiles(fileInput.files); fileInput.value = ""; };
      $("#emDocsBtn").onclick = emOpenDocsDialog;
      $("#emDiscard").onclick = async () => {
        if (!(em.subject || "").trim() && !(editor.textContent || "").trim() && !em.attachments.length) return;
        const ok = await confirmModal("This clears the subject, the message and any attachments you added.", {
          title: "Discard this draft?", okText: "Discard",
        });
        if (!ok) return;
        em.attachments.slice().forEach((a) => emRemoveAttachment(a.uid));
        em.subject = ""; em.html = "";
        renderEmails();
      };

      // Drag & drop anywhere over the composer.
      const card = $("#emCompose");
      let dragDepth = 0;
      const hasFiles = (e) => {
        const types = (e.dataTransfer && e.dataTransfer.types) || [];
        return Array.prototype.indexOf.call(types, "Files") >= 0;
      };
      card.addEventListener("dragenter", (e) => {
        if (!hasFiles(e)) return;
        e.preventDefault(); dragDepth++; card.classList.add("is-dragging");
      });
      card.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
      card.addEventListener("dragleave", () => {
        dragDepth = Math.max(0, dragDepth - 1);
        if (!dragDepth) card.classList.remove("is-dragging");
      });
      card.addEventListener("drop", (e) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        dragDepth = 0;
        card.classList.remove("is-dragging");
        emAddFiles(e.dataTransfer.files);
      });
    }

    // Files uploaded for a message that was never sent (tab closed, page refreshed)
    // are still on the server — put them back on the composer instead of orphaning them.
    async function emLoadDraftAttachments() {
      try {
        const r = await api(`/clients/${cl.id}/email/attachments`);
        (r.attachments || []).forEach((a) => {
          if (em.attachments.some((x) => x.id === a.id)) return;
          em.attachments.push({
            uid: "u" + (++em.seq), name: a.filename, size: a.file_size || 0,
            status: "done", pct: 100, id: a.id,
          });
        });
        emDrawAtts();
      } catch (e) { /* drafts are a convenience — never block the composer */ }
    }

    /* ---- Mock interview tab ---- */
    const micSupported = !!(window.SpeechRecognition || window.webkitSpeechRecognition);
    let ivRecog = null;
    function ivSpeak(text) {
      if (!iv.voiceOn || !("speechSynthesis" in window)) return;
      try {
        window.speechSynthesis.cancel();
        const u = new SpeechSynthesisUtterance(String(text || "").replace(/[*_#`>]/g, ""));
        u.rate = 1.0; u.pitch = 1.0;
        window.speechSynthesis.speak(u);
      } catch (e) {}
    }
    function ivStopSpeak() { try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch (e) {} }

    function renderInterview() {
      body.innerHTML = `<div id="ivWrap"></div>`;
      if (iv.sessions === null) { iv.sessions = []; loadIvSessions(); }
      if (iv.invite === undefined) { iv.invite = null; loadIvInvite(); }
      drawIv();
    }
    async function loadIvSessions() {
      try { const r = await api(`/clients/${cl.id}/interview/sessions`); iv.sessions = r.sessions || []; if ($("#ivWrap") && !iv.started) drawIv(); }
      catch (e) { iv.sessions = []; }
    }
    async function loadIvInvite() {
      try { const r = await api(`/clients/${cl.id}/interview/invite`); iv.invite = r.invite || null; if ($("#ivWrap") && !iv.started) drawIv(); }
      catch (e) { iv.invite = null; }
    }
    function openSendModal() {
      const first = (cl.full_name || "the student").split(" ")[0];
      const cr = state.credits || {};
      const mockCost = ((cr.actions || []).find((a) => a.key === "mock_interview") || {}).credits || 20;
      const perInr = cr.credit_value_inr || 10;
      const isInr = (cr.currency || "INR") === "INR";
      const balance = (typeof cr.balance_credits === "number") ? cr.balance_credits : null;
      const money = (credits) => isInr ? ` (≈ ${fmtInr(Math.round(credits * perInr))})` : "";
      openModal(`<div class="modal-head"><h3>Send mock interview to ${esc(first)}</h3><button class="x" onclick="__ent.closeModal()">×</button></div>
        <form id="ivSendForm"><div class="modal-body">
          <p style="margin:0 0 16px;color:var(--text-2);font-size:14px;line-height:1.6">We'll email a secure link to <b>${esc(cl.email)}</b>. ${esc(first)} verifies with a one-time code, then can take the interview(s) on their own — and you'll see the results here.</p>
          <div class="field"><label>How many interviews can they take?</label>
            <input type="number" id="ivCount" min="1" max="20" value="3" /></div>
          <div id="ivCostNote" style="background:rgba(99,102,241,.07);border:1px solid var(--border);border-radius:10px;padding:10px 12px;font-size:13px;color:var(--text-2);line-height:1.5;margin:-2px 0 4px"></div>
          <div id="ivSendErr" class="auth-error hidden"></div>
        </div>
        <div class="modal-foot"><button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary" id="ivSendSave">✉ Send link</button></div></form>`);
      function updateIvCost() {
        const el = $("#ivCostNote"); if (!el) return;
        const n = Math.max(1, Math.min(20, parseInt($("#ivCount").value, 10) || 1));
        const total = n * mockCost;
        const enforced = !!cr.enforced;
        const short = balance !== null && balance < total;
        // Block sending when credits are enforced and the wallet can't fund every
        // interview — so the client never receives a link they can't use.
        const blocked = enforced && short;
        let balanceLine = "";
        if (balance !== null) {
          if (blocked) {
            balanceLine = `<div style="margin-top:6px;color:var(--warning,#f59e0b);font-weight:600">⚠ Wallet balance: ${balance} credits — not enough to send ${n} interview${n === 1 ? "" : "s"}.
              <button type="button" class="btn btn-soft btn-sm" style="margin-left:6px" onclick="__ent.closeModal();__ent.go('credits')">Top up wallet</button></div>`;
          } else {
            balanceLine = `<div style="margin-top:5px;color:var(--muted)">Wallet balance: ${balance} credits${short ? ` — only ${Math.floor(balance / mockCost)} funded right now` : ""}</div>`;
          }
        }
        el.innerHTML =
          `<div>Costs up to <b>${total} credits</b>${money(total)} for ${n} interview${n === 1 ? "" : "s"} — <b>${mockCost}</b> credits each, charged only when an interview is actually taken.</div>` +
          balanceLine;
        // Runs on every keystroke in #ivCount, so it must stand down while the invite is in
        // flight — otherwise typing in the count field un-disables the button mid-request.
        const sb = $("#ivSendSave");
        if (sb && sb.dataset.busy !== "1") {
          sb.disabled = blocked;
          sb.title = blocked ? "Top up your wallet to send this link" : "";
        }
      }
      const ic = $("#ivCount");
      if (ic) ic.addEventListener("input", updateIvCost);
      // withBusy restores through this, so a failed send returns to the wallet-blocked
      // state rather than being blanket-enabled.
      const ivSendBtn = $("#ivSendSave"); if (ivSendBtn) ivSendBtn._syncValid = updateIvCost;
      updateIvCost();
      $("#ivSendForm").onsubmit = async (e) => {
        e.preventDefault();
        // One parse shared with updateIvCost's quote above, so the price the user was shown
        // and the count actually sent can never disagree.
        const n = Math.max(1, Math.min(20, parseInt($("#ivCount").value, 10) || 3));
        await withBusy($("#ivSendSave"), "Sending…", async () => {
          try {
            const r = await api(`/clients/${cl.id}/interview/invite`, { method: "POST", body: { allowed_count: n } });
            iv.invite = r.invite; closeModal(); toast(r.message || "Interview link sent", r.email_sent ? "success" : "error"); drawIv();
          } catch (ex) { const er = $("#ivSendErr"); er.textContent = ex.message; er.classList.remove("hidden"); }
        });
      };
    }
    async function revokeInvite() {
      if (!(await confirmModal("The student won't be able to use it anymore.", { title: "Revoke interview link?", okText: "Revoke" }))) return;
      try { await api(`/clients/${cl.id}/interview/invite/revoke`, { method: "POST" }); iv.invite = null; toast("Link revoked", "success"); drawIv(); }
      catch (ex) { toast(ex.message, "error"); }
    }
    function ivSessionRow(s) {
      const v = s.verdict || "Completed";
      const cls = /approved/i.test(v) ? "ok" : /needs/i.test(v) ? "bad" : "mid";
      return `<div class="iv-srow" onclick="__ent.viewInterview(${cl.id},${s.id})">
        <div class="iv-sv ${cls}">${esc(v)}</div>
        <div class="iv-smeta"><b>${fmtDate(s.created_at)}</b><span>${esc(s.conducted_by_name || "")}${s.mode === "voice" ? " · 🎙 voice" : ""}</span></div>
        <span class="iv-sarrow">→</span></div>`;
    }
    function drawIv() {
      const w = $("#ivWrap"); if (!w) return;
      if (iv.started) return drawIvChat(w);
      const sessions = iv.sessions || [];
      w.innerHTML = `
        ${canInviteInterview ? sendHeroCard() : `<div class="cp-card iv-intro"><div class="iv-orb">🎤</div><h3>AI mock visa interview</h3><p class="muted">You don't have permission to send or run mock interviews. Ask a workspace admin for access.</p></div>`}
        ${canRunInterview ? staffPreviewCard() : ""}
        <div class="cp-card">
          <div class="cp-sub-label">Past mock interviews</div>
          <div class="iv-slist">${sessions.length ? sessions.map(ivSessionRow).join("") : `<div class="iv-empty">No mock interviews yet — sessions ${esc((cl.full_name || "the student").split(" ")[0])} completes will show up here.</div>`}</div>
        </div>`;
      const sb = $("#ivSendBtn"); if (sb) sb.onclick = openSendModal;
      const rs = $("#ivResend"); if (rs) rs.onclick = openSendModal;
      const rv = $("#ivRevoke"); if (rv) rv.onclick = revokeInvite;
      const seg = w.querySelectorAll(".iv-seg");
      seg.forEach((s) => (s.onclick = () => { seg.forEach((x) => x.classList.remove("active")); s.classList.add("active"); }));
      const pb = $("#ivStartBtn"); if (pb) pb.onclick = () => { const a = w.querySelector(".iv-seg.active"); startIv(!!a && a.dataset.mode === "voice"); };
    }
    // PRIMARY action: send the mock interview to the student (the real product).
    function sendHeroCard() {
      const first = (cl.full_name || "the student").split(" ")[0];
      const inv = iv.invite;
      let inner;
      if (!cl.email) {
        inner = `<p class="iv-hero-sub">Add an email to ${esc(first)} (Edit details) to send them a mock interview link.</p>
          <button class="btn btn-primary btn-block" onclick="__ent.editClient(${cl.id})">Add an email</button>`;
      } else if (inv && inv.live) {
        const started = inv.started_count != null ? inv.started_count : (inv.used_count || 0);
        const completed = inv.completed_count || 0;
        let statusBadge;
        if (completed > 0) statusBadge = `<span class="iv-sv ok">✓ Completed${inv.last_completed_at ? " · " + fmtDate(inv.last_completed_at) : ""}</span>`;
        else if (started > 0) statusBadge = `<span class="iv-sv mid">⏳ Started — not completed</span>`;
        else statusBadge = `<span class="iv-sv" style="background:#eef2f7;color:#64748b">Not started yet</span>`;
        inner = `<p class="iv-hero-sub">A secure link is with <b>${esc(inv.email)}</b> so ${esc(first)} can practise on their own (verified by a one-time code).</p>
          <div class="iv-invite-status">
            <div>${statusBadge}<br><span class="muted" style="display:inline-block;margin-top:7px">${started} started · ${completed} completed · ${inv.remaining} remaining<br>Sent${inv.created_at ? " " + fmtDate(inv.created_at) : ""}${inv.created_by_name ? " by " + esc(inv.created_by_name) : ""}</span></div>
            <div class="row"><button class="btn btn-soft btn-sm" id="ivResend">Resend / change</button><button class="btn btn-danger btn-sm" id="ivRevoke">Revoke</button></div>
          </div>`;
      } else {
        inner = `<p class="iv-hero-sub">Email <b>${esc(cl.email)}</b> a secure link so ${esc(first)} can take the mock interview on their own time — they verify with a one-time code, and every result appears right here.</p>
          <button class="btn btn-primary btn-block" id="ivSendBtn">✉ Send mock interview to ${esc(first)}</button>`;
      }
      // Badge/emphasis follows the destination's real interview reality (interviewRelevance).
      // The feature is always usable here; we only change how we frame it.
      const relevance = interviewRelevance(cl);
      const country = esc(cl.destination_country_name || "This destination");
      let badge = "", note = "";
      if (relevance === "standard") {
        badge = `<div class="iv-hero-badge">Recommended</div>`;
      } else if (relevance === "rare") {
        badge = `<div class="iv-hero-badge iv-hero-badge--opt">Optional</div>`;
        note = `<p class="iv-hero-note">${country} rarely interviews student-visa applicants, so this is optional — use it if a credibility interview or provider screening is expected.</p>`;
      }
      return `<div class="cp-card iv-hero">
        <div class="iv-hero-head"><div class="iv-orb">🎤</div>
          <div>${badge}<h3>Send a mock visa interview</h3></div></div>
        ${note}
        ${inner}
        <div class="iv-tag">Officer adapts to <b>${esc(cl.destination_country_name)}</b> · ${esc(cl.visa_type)} — using ${esc(first)}'s profile</div>
      </div>`;
    }
    // SECONDARY action: run it yourself, to test the software or interview a student
    // sitting with you. A few free previews per org, then normal price.
    function staffPreviewCard() {
      const prevInfo = (state.credits && state.credits.staff_interview_previews) || {};
      const prevLeft = typeof prevInfo.remaining === "number" ? prevInfo.remaining : null;
      const mockCost = ((state.credits && state.credits.actions || []).find((a) => a.key === "mock_interview") || {}).credits || 20;
      const costNote = prevLeft && prevLeft > 0
        ? `<span class="iv-prev-free">${prevLeft} free preview${prevLeft === 1 ? "" : "s"} left</span>`
        : `<span class="muted">${mockCost} credits each</span>`;
      return `<div class="cp-card iv-preview">
        <div class="iv-preview-row">
          <div><div class="cp-sub-label" style="margin:0">Try it yourself</div>
            <p class="muted" style="margin:4px 0 0;font-size:13px">Run a quick preview in your browser to test it or interview a student sitting with you.</p></div>
          <div class="iv-preview-actions">
            <div class="iv-mode-seg" role="group" aria-label="Interview mode">
              <button type="button" class="iv-seg active" data-mode="chat">💬 Chat</button>
              <button type="button" class="iv-seg" data-mode="voice">🎙 Voice${micSupported ? "" : " (read aloud)"}</button>
            </div>
            <button class="btn btn-soft btn-sm" id="ivStartBtn">▶ Start preview</button>
            <div class="iv-prev-note">${costNote}</div>
          </div>
        </div>
      </div>`;
    }
    function ivBubble(m) {
      if (m.role === "user") return `<div class="ai-msg user"><div class="ai-bubble">${esc(m.content).replace(/\n/g, "<br>")}</div></div>`;
      return `<div class="ai-msg bot"><div class="ai-av">🧑‍✈️</div><div class="ai-bubble">${aiFormat(m.content)}</div></div>`;
    }
    /* Send is live only while the officer isn't mid-reply AND there is an answer to send —
       an empty Send used to land on a silent `if (!v) return`. The dictated path matters as
       much as the typed one: SpeechRecognition assigns .value directly, which fires no input
       event, so ivRecog.onresult calls this by hand. */
    function ivSyncSend() {
      const b = $("#ivSend"); if (!b) return;
      const ta = $("#ivInput");
      b.disabled = iv.busy || !((ta && ta.value) || "").trim();
    }
    function drawIvChat(w) {
      const typing = iv.busy ? `<div class="ai-msg bot"><div class="ai-av">🧑‍✈️</div><div class="ai-bubble"><span class="ai-typing"><i></i><i></i><i></i></span></div></div>` : "";
      const fb = iv.feedback ? `<div class="cp-card iv-feedback"><div class="cp-sub-label">📋 Interview feedback</div>${feedbackFormat(iv.feedback)}</div>` : "";
      w.innerHTML = `
        <div class="cp-card iv-chat">
          <div class="iv-chead">
            <div class="iv-ctitle">🧑‍✈️ ${esc(cl.destination_country_name)} visa officer · <span class="muted">mock interview</span></div>
            <div class="iv-cactions">
              <button class="btn btn-soft btn-sm" id="ivVoiceBtn">${iv.voiceOn ? "🔊 Voice on" : "🔈 Voice off"}</button>
              ${iv.finished ? `<button class="btn btn-soft btn-sm" id="ivRestart">↻ New interview</button>` : `<button class="btn btn-ghost btn-sm" id="ivEnd" ${iv.busy || !iv.history.some((m) => m.role === "user") ? "disabled" : ""} title="Answer at least one question first">End &amp; get feedback</button>`}
            </div>
          </div>
          <div class="iv-thread" id="ivThread">${iv.history.map(ivBubble).join("")}${typing}</div>
          ${iv.finished ? `<div class="iv-done">Interview ended. ${iv.feedback ? "See feedback below." : ""}</div>` : `
          <div class="iv-inrow">
            <textarea id="ivInput" placeholder="Type ${esc((cl.full_name || "the student").split(" ")[0])}'s answer…" rows="1" ${iv.busy ? "disabled" : ""}></textarea>
            ${micSupported ? `<button class="iv-mic" id="ivMic" title="Speak the answer" ${iv.busy ? "disabled" : ""}>🎙</button>` : ""}
            <button class="btn btn-primary" id="ivSend" disabled>Send</button>
          </div>`}
        </div>${fb}`;
      const thread = $("#ivThread"); if (thread) thread.scrollTop = thread.scrollHeight;
      // speak the latest officer message once
      const last = iv.history[iv.history.length - 1];
      if (iv.voiceOn && last && last.role === "officer" && iv.spoken < iv.history.length) { iv.spoken = iv.history.length; ivSpeak(last.content); }

      const inp = $("#ivInput");
      if (inp) { inp.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendIv(); } });
        inp.addEventListener("input", () => { inp.style.height = "auto"; inp.style.height = Math.min(inp.scrollHeight, 140) + "px"; ivSyncSend(); }); if (!iv.busy) inp.focus(); }
      const sendBtn = $("#ivSend"); if (sendBtn) sendBtn.onclick = sendIv;
      ivSyncSend();
      const endBtn = $("#ivEnd"); if (endBtn) endBtn.onclick = endIv;
      const rb = $("#ivRestart"); if (rb) rb.onclick = () => { ivStopSpeak(); iv.started = false; iv.history = []; iv.finished = false; iv.feedback = null; iv.spoken = 0; drawIv(); };
      const vb = $("#ivVoiceBtn"); if (vb) vb.onclick = () => { iv.voiceOn = !iv.voiceOn; if (!iv.voiceOn) ivStopSpeak(); else { const l = iv.history[iv.history.length - 1]; if (l && l.role === "officer") ivSpeak(l.content); } drawIvChat(w); };
      const mic = $("#ivMic"); if (mic) mic.onclick = () => ivMic(mic);
    }
    async function startIv(voice) {
      iv.started = true; iv.voiceOn = !!voice; iv.history = []; iv.finished = false; iv.feedback = null; iv.busy = true; iv.spoken = 0;
      renderInterview();
      try {
        const r = await api(`/clients/${cl.id}/interview/chat`, { method: "POST", body: { start: true }, timeout: AI_API_TIMEOUT_MS });
        iv.history.push({ role: "officer", content: r.reply });
        if (r.wallet) { state.credits = r.wallet; updatePlanChip(); }
        if (r.was_preview) toast(`Preview started · free${typeof r.previews_remaining === "number" ? ` · ${r.previews_remaining} preview${r.previews_remaining === 1 ? "" : "s"} left` : ""}`, "success");
        else if (r.credits_charged) toast(`Interview started · ${r.credits_charged} credits used`, "success");
      } catch (ex) {
        iv.started = false;
        if (ex.status === 402) { toast(ex.message, "error"); iv.busy = false; if (state.activeClient === cl.id) drawIv(); navigate("credits"); return; }
        toast(ex.message, "error");
      }
      iv.busy = false; if (state.activeClient === cl.id) drawIv();
    }
    async function sendIv() {
      const ta = $("#ivInput"); if (!ta) return;
      const v = (ta.value || "").trim(); if (!v || iv.busy) return;
      const prior = iv.history.slice();
      iv.history.push({ role: "user", content: v }); iv.busy = true; drawIv();
      let ended = false;
      try {
        const r = await api(`/clients/${cl.id}/interview/chat`, { method: "POST", body: { message: v, history: prior }, timeout: AI_API_TIMEOUT_MS });
        iv.history.push({ role: "officer", content: r.reply });
        ended = !!r.finished;  // backend signals when the AI officer has wrapped up
      } catch (ex) { toast(ex.message, "error"); }
      // If the officer ended the interview, generate feedback automatically so staff
      // don't have to notice and click "End & get feedback" themselves.
      if (ended && iv.history.some((m) => m.role === "user")) {
        toast("The officer wrapped up the interview — preparing feedback…", "success");
        await generateIvFeedback();
        return;
      }
      iv.busy = false; drawIv();
    }
    async function generateIvFeedback() {
      iv.busy = true; ivStopSpeak(); drawIv();
      try {
        const r = await api(`/clients/${cl.id}/interview/feedback`, { method: "POST", body: { history: iv.history, mode: iv.voiceOn ? "voice" : "chat" } });
        iv.finished = true; iv.feedback = r.feedback;
        if (iv.sessions) iv.sessions.unshift(r.session);
        toast("Feedback ready", "success");
      } catch (ex) { toast(ex.message, "error"); }
      iv.busy = false; drawIv();
    }
    async function endIv() {
      if (iv.busy || iv.history.filter((m) => m.role === "user").length === 0) { toast("Answer at least one question first.", "error"); return; }
      await generateIvFeedback();
    }
    function ivMic(btn) {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition; if (!SR) return;
      if (ivRecog) { try { ivRecog.stop(); } catch (e) {} ivRecog = null; btn.classList.remove("rec"); return; }
      ivRecog = new SR(); ivRecog.lang = "en-US"; ivRecog.interimResults = true; ivRecog.continuous = false;
      btn.classList.add("rec");
      let finalText = "";
      ivRecog.onresult = (e) => {
        let interim = "";
        for (let i = e.resultIndex; i < e.results.length; i++) { const t = e.results[i][0].transcript; if (e.results[i].isFinal) finalText += t; else interim += t; }
        const inp = $("#ivInput"); if (inp) { inp.value = (finalText + interim).trim(); inp.style.height = "auto"; inp.style.height = Math.min(inp.scrollHeight, 140) + "px"; }
        ivSyncSend();   // assigning .value fires no input event — Send would stay dead
      };
      ivRecog.onerror = () => { btn.classList.remove("rec"); ivRecog = null; };
      ivRecog.onend = () => { btn.classList.remove("rec"); ivRecog = null; };
      try { ivRecog.start(); } catch (e) { ivRecog = null; btn.classList.remove("rec"); }
    }

    /* ---- Copilot access tab ----
       Client-facing AI copilot invite. Mirrors the interview-invite flow: secure
       emailed link + one-time code. The raw link exists only in the POST response,
       so "Copy link" appears only right after a send; a resend rotates the token
       (the old link dies). */
    function renderCopilot() {
      body.innerHTML = `<div id="cpilWrap"></div>`;
      if (cp.invite === undefined && canInviteCopilot) loadCopilotInvite();
      drawCopilot();
    }
    async function loadCopilotInvite() {
      // No state.activeClient guard here: the global ESC/backdrop dismiss nulls
      // activeClient even while this page is still mounted, and bailing before
      // cp.invite is assigned would leave the tab an eternal spinner. Storing
      // the result is always safe; the DOM check gates the redraw (same shape
      // as loadIvInvite on the interview tab).
      try {
        const r = await api(`/clients/${cl.id}/copilot/invite`);
        cp.invite = r.invite || null;
        if (r.config) cp.config = r.config;
        if ($("#cpilWrap")) drawCopilot();
      } catch (e) {
        // Leave cp.invite undefined: a transient failure must NOT be cached as
        // "no invite exists" — Send would then quietly rotate a live token.
        const w = $("#cpilWrap");
        if (w) {
          w.innerHTML = `<div class="cp-card iv-hero">
            <div class="iv-hero-head"><div class="iv-orb">✨</div><div><h3>Client copilot access</h3></div></div>
            <p class="muted" style="margin:0 0 14px">Couldn't load the copilot status. Check your connection and try again.</p>
            <button class="btn btn-soft btn-sm" id="cpilRetry">Retry</button></div>`;
          const rt = $("#cpilRetry"); if (rt) rt.onclick = renderCopilot;
        }
      }
    }
    // The flat activation cost: the org's credit price list wins, then the server's
    // copilot config from the GET, then a safe default.
    function copilotCost() {
      const cr = state.credits || {};
      return ((cr.actions || []).find((a) => a.key === "copilot_client") || {}).credits || (cp.config && cp.config.cost_credits) || 20;
    }
    function drawCopilot() {
      const w = $("#cpilWrap"); if (!w) return;
      if (!canInviteCopilot) {
        w.innerHTML = `<div class="cp-card iv-intro"><div class="iv-orb">✨</div><h3>Client copilot access</h3><p class="muted">You don't have permission to share copilot access. Ask a workspace admin.</p></div>`;
        return;
      }
      w.innerHTML = cp.invite === undefined
        ? '<div style="text-align:center;padding:18px 0"><span class="spinner"></span></div>'
        : copilotHeroCard();
      const sb = $("#cpSendBtn"); if (sb) sb.onclick = openCopilotSendModal;
      const rs = $("#cpResend"); if (rs) rs.onclick = openCopilotSendModal;
      const rv = $("#cpRevoke"); if (rv) rv.onclick = revokeCopilotInvite;
      const cpy = $("#cpCopyLink"); if (cpy) cpy.onclick = async () => {
        try { await navigator.clipboard.writeText(cp.link); toast("Link copied", "success"); }
        catch (e) { toast("Couldn't copy — the emailed link still works", "error"); }
      };
    }
    function copilotHeroCard() {
      const first = (cl.full_name || "the student").split(" ")[0];
      const inv = cp.invite;
      const cfg = cp.config || {};
      const msgs = cfg.allowed_messages != null ? cfg.allowed_messages : 100;
      const expDays = cfg.expires_days != null ? cfg.expires_days : 30;
      const cost = copilotCost();
      let inner;
      if (!cl.email) {
        inner = `<p class="iv-hero-sub">Add an email to ${esc(first)} (Edit details) to send them their copilot link.</p>
          <button class="btn btn-primary btn-block" onclick="__ent.editClient(${cl.id})">Add an email</button>`;
      } else if (inv && inv.live) {
        const statusBadge = inv.unlocked
          ? `<span class="iv-sv ok">✓ Activated${inv.unlocked_at ? " · " + fmtDate(inv.unlocked_at) : ""}</span>`
          : `<span class="iv-sv" style="background:#eef2f7;color:#64748b">Not opened yet</span>`;
        inner = `<p class="iv-hero-sub">A personal copilot link is with <b>${esc(inv.email)}</b> — ${esc(first)} can ask about their application any time (verified by a one-time code).</p>
          <div class="iv-invite-status">
            <div>${statusBadge}<br><span class="muted" style="display:inline-block;margin-top:7px">${esc(inv.used_messages)} of ${esc(inv.allowed_messages)} messages used · expires ${fmtDate(inv.expires_at)}<br>Sent${inv.created_at ? " " + fmtDate(inv.created_at) : ""}${inv.created_by_name ? " by " + esc(inv.created_by_name) : ""}</span></div>
            <div class="row">${cp.link ? `<button class="btn btn-ghost btn-sm" id="cpCopyLink">Copy link</button>` : ""}<button class="btn btn-soft btn-sm" id="cpResend">Resend / new link</button><button class="btn btn-danger btn-sm" id="cpRevoke">Revoke</button></div>
          </div>`;
      } else {
        inner = `<p class="iv-hero-sub muted">Give ${esc(first)} their own secure copilot chat about their application — a flat <b>${esc(cost)} credits</b> once they activate, valid ${esc(expDays)} days, up to ${esc(msgs)} messages.</p>
          <button class="btn btn-primary btn-block" id="cpSendBtn">✨ Send copilot access to ${esc(first)}</button>`;
      }
      return `<div class="cp-card iv-hero">
        <div class="iv-hero-head"><div class="iv-orb">✨</div>
          <div><h3>Client copilot access</h3></div></div>
        ${inner}
      </div>`;
    }
    function openCopilotSendModal() {
      const first = (cl.full_name || "the student").split(" ")[0];
      const cr = state.credits || {};
      const cfg = cp.config || {};
      const cost = copilotCost();
      const msgs = cfg.allowed_messages != null ? cfg.allowed_messages : 100;
      const expDays = cfg.expires_days != null ? cfg.expires_days : 30;
      const perInr = cr.credit_value_inr || 10;
      const isInr = (cr.currency || "INR") === "INR";
      const balance = (typeof cr.balance_credits === "number") ? cr.balance_credits : null;
      const money = (credits) => isInr ? ` (≈ ${fmtInr(Math.round(credits * perInr))})` : "";
      const enforced = !!cr.enforced;
      const short = balance !== null && balance < cost;
      const live = !!(cp.invite && cp.invite.live);
      // A live, already-activated invite carries its paid unlock over to the new
      // link (server-side) — resending is free, so nothing to block or price.
      const carriesOver = live && !!cp.invite.unlocked;
      // Block sending when credits are enforced and the wallet can't fund the
      // activation — so the client never receives a link they can't use.
      const blocked = enforced && short && !carriesOver;
      openModal(`<div class="modal-head"><h3>Send copilot access to ${esc(first)}</h3><button class="x" onclick="__ent.closeModal()">×</button></div>
        <form id="cpSendForm"><div class="modal-body">
          <p style="margin:0 0 16px;color:var(--text-2);font-size:14px;line-height:1.6">We'll email a secure link to <b>${esc(cl.email)}</b>. ${esc(first)} verifies with a one-time code, then can chat with the copilot about their own application — and only theirs.</p>
          ${live ? `<p style="margin:0 0 12px;color:var(--warning,#f59e0b);font-size:13px;font-weight:600">⚠ This replaces the current link — the old one stops working.</p>` : ""}
          <div id="cpCostNote" style="background:rgba(99,102,241,.07);border:1px solid var(--border);border-radius:10px;padding:10px 12px;font-size:13px;color:var(--text-2);line-height:1.5;margin:-2px 0 4px"></div>
          <div id="cpSendErr" class="auth-error hidden"></div>
        </div>
        <div class="modal-foot"><button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary" id="cpSendSave">✨ Send copilot link</button></div></form>`);
      const el = $("#cpCostNote");
      if (el) {
        let balanceLine = "";
        if (balance !== null) {
          if (blocked) {
            balanceLine = `<div style="margin-top:6px;color:var(--warning,#f59e0b);font-weight:600">⚠ Wallet balance: ${balance} credits — not enough to send copilot access.
              <button type="button" class="btn btn-soft btn-sm" style="margin-left:6px" onclick="__ent.closeModal();__ent.go('credits')">Top up wallet</button></div>`;
          } else {
            balanceLine = `<div style="margin-top:5px;color:var(--muted)">Wallet balance: ${balance} credits</div>`;
          }
        }
        el.innerHTML =
          (carriesOver
            ? `<div>Already activated — resending a new link is <b>free</b>: ${esc(first)} keeps their remaining messages and expiry date.</div>`
            : `<div>Flat <b>${esc(cost)} credits</b>${money(cost)} — charged only when ${esc(first)} first activates the link. Valid ${esc(expDays)} days · up to ${esc(msgs)} messages.</div>`) +
          balanceLine;
      }
      const sv = $("#cpSendSave");
      if (sv) { sv.disabled = blocked; sv.title = blocked ? "Top up your wallet to send this link" : ""; }
      $("#cpSendForm").onsubmit = async (e) => {
        e.preventDefault();
        if (cp.busy) return;
        cp.busy = true;
        const btn = $("#cpSendSave"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Sending…';
        try {
          const r = await api(`/clients/${cl.id}/copilot/invite`, { method: "POST" });
          cp.busy = false;
          // Always record the result and close the modal — no activeClient
          // guard: the invite WAS created, so the UI must reflect it even if a
          // global dismiss nulled activeClient mid-request (interview-tab shape).
          cp.invite = r.invite;
          cp.link = r.link || null;
          closeModal();
          toast(r.message || "Copilot link sent", r.email_sent ? "success" : "error");
          drawCopilot();
        } catch (ex) {
          cp.busy = false;
          if (ex.status === 402) { closeModal(); toast(ex.message, "error"); navigate("credits"); return; }
          const er = $("#cpSendErr"); if (er) { er.textContent = ex.message; er.classList.remove("hidden"); }
          btn.disabled = false; btn.innerHTML = "✨ Send copilot link";
        }
      };
    }
    async function revokeCopilotInvite() {
      const ok = await confirmModal("The client won't be able to use their copilot link anymore.", { title: "Revoke copilot access?", okText: "Revoke" });
      if (!ok) return;
      try {
        await api(`/clients/${cl.id}/copilot/invite/revoke`, { method: "POST" });
        cp.invite = null; cp.link = null;
        toast("Copilot access revoked", "success");
      } catch (ex) { toast(ex.message, "error"); }
      drawCopilot();  // no-ops if the tab's DOM is gone (drawCopilot checks the wrap)
    }

    /* ---- Payments tab: collected-from-this-client ledger + secure pay-link requests.
       Reads are member-visible; money actions (request / cancel / refund) are admin-only,
       enforced server-side and mirrored in the UI.

       EVERY figure on this tab is INR and stays INR. Razorpay Route — the linked-account
       split that lets a consultancy collect straight into its own bank — settles only in
       INR, so there is no currency choice to offer here and no display conversion either:
       an org raising a ₹25,000 invoice has to see ₹25,000, not an FX estimate of it, or
       the refund dialog and the invoice disagree. Hence fmtMoney(x, "INR") throughout
       rather than fmtDisplay. ---- */
    async function renderPayments() {
      const body = $("#cpBody");
      body.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
      let d;
      try { d = await api(`/clients/${cl.id}/payments`); }
      catch (ex) { body.innerHTML = errBox(ex); return; }
      applyAccessPayload(d);
      // Raising / cancelling / recording a payment is finance.manage; moving real money
      // back out to a student is the separate, owner-only finance.refund.
      const canManage = can("finance.manage");
      const canRefund = can("finance.refund");
      const t = d.totals || {};
      const fee = d.fee || { percent: 2, min_fee_rupees: 49 };
      const MANUAL_METHODS = [["cash", "Cash"], ["bank_transfer", "Bank transfer"], ["upi", "UPI"], ["card", "Card / POS"], ["cheque", "Cheque"], ["other", "Other"]];
      const manualMethodLabel = (m) => (MANUAL_METHODS.find((x) => x[0] === m) || [m, m || "Payment"])[1];
      const todayISO = () => { const dt = new Date(); return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`; };
      // Mirrors EARLIEST_PAYMENT_DATE in enterprise_payments.py. The server is the one that
      // enforces both ends — this pair only feeds the picker and the pre-flight check below,
      // so drifting out of sync costs a worse message, never a bad row.
      const MIN_PAY_DATE = "2000-01-01";

      const chipRow = `
        <div class="pay-chips">
          <div class="pay-chip"><div class="k">Collected</div><div class="v ok">${fmtMoney(t.collected_paise || 0, "INR")}</div></div>
          <div class="pay-chip"><div class="k">Pending</div><div class="v">${fmtMoney(t.pending_paise || 0, "INR")}</div></div>
          <div class="pay-chip"><div class="k">Refunded</div><div class="v warn">${fmtMoney(t.refunded_paise || 0, "INR")}</div></div>
        </div>`;

      let gateNote = "";
      if (!d.collect_enabled && !orgIsIndian()) {
        // Route can't onboard this org at all, so pointing them at "connect your bank"
        // would send them to a dead end. See acctCountryBlockedCard in Finance.
        gateNote = `<div class="pay-gate-note">Online collection runs on Razorpay Route, which onboards
          India-registered businesses only — see <a href="#" id="payGoFinance">Finance</a> for the details.${
          canManage ? " You can still <b>record payments you've collected yourself</b> below, and they book into your Income ledger." : " You can still browse this ledger."}</div>`;
      } else if (!d.collect_enabled) {
        gateNote = `<div class="pay-gate-note">Online collection isn't live yet — connect your company bank account in
          <a href="#" id="payGoFinance">Finance</a> to charge clients online.${canManage ? " Meanwhile you can <b>record payments you've taken offline</b> below." : " You can still browse this ledger."}</div>`;
      } else if (!d.client_email) {
        gateNote = `<div class="pay-gate-note">Add an email address to this client to send them a payment request.</div>`;
      }

      const canRequest = canManage && d.collect_enabled && !!d.client_email;
      const reqBtn = canManage
        ? `<button class="btn btn-primary btn-sm" id="payReqToggle" ${canRequest ? "" : "disabled"}>+ Request payment</button>`
        : "";

      const reqForm = `
        <div class="card hidden" id="payReqForm"><div class="card-body">
          <div style="font-weight:800;font-size:14.5px;margin-bottom:12px">Request a payment from ${esc(cl.full_name)}</div>
          <div class="field-row">
            <div class="field"><label>Amount in INR (₹) *</label>
              <input id="payAmt" type="number" min="1" step="1" placeholder="e.g. 25000" autocomplete="off"></div>
            <div class="field"><label>Due date <span style="color:var(--muted);font-weight:500">(optional)</span></label>
              <input id="payDue" type="date" min="${todayISO()}"></div>
          </div>
          <div class="field"><label>What is this payment for? *</label>
            <input id="payDesc" type="text" maxlength="300" placeholder="e.g. University application service fee" autocomplete="off"></div>
          <div class="pay-split-preview" id="paySplit">Rilono fee: ${Number(fee.percent)}% (min ${esc(fmtInrExact(fee.min_fee_rupees))}) — enter an amount to preview your payout.</div>
          <div style="font-size:12px;color:var(--muted);line-height:1.55;margin-top:8px">Invoices are raised in INR
            and settle to your bank in INR. A student overseas can still pay one with an international card —
            their bank converts at its own rate and may add a foreign-transaction fee, so what you receive
            is unaffected.</div>
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:12px">
            <button class="btn btn-primary" id="payCreateBtn">Create &amp; email secure link</button>
            <span style="font-size:12px;color:var(--muted)">Sent to ${esc(d.client_email || "")} · paid via Razorpay · settles to your bank</span>
          </div>
        </div></div>`;

      // Manual / off-platform recording — available to managers even when online collection is off.
      const manualBtn = canManage
        ? `<button class="btn btn-ghost btn-sm" id="payManualToggle">+ Record payment</button>`
        : "";
      const manualForm = canManage ? `
        <div class="card hidden" id="payManualForm"><div class="card-body">
          <div style="font-weight:800;font-size:14.5px;margin-bottom:4px">Record an off-platform payment</div>
          <div style="font-size:12.5px;color:var(--muted);margin-bottom:12px">For money already collected outside Rilono (cash, bank transfer, UPI…). This is a bookkeeping entry — it does not charge the client. Record it in INR; if you were paid in another currency, enter the INR amount that actually landed in your account.</div>
          <div class="field-row">
            <div class="field"><label>Amount received in INR (₹) *</label>
              <input id="mpAmt" type="number" min="1" step="1" placeholder="e.g. 25000" autocomplete="off"></div>
            <div class="field"><label>How was it paid? *</label>
              <select id="mpMethod">${MANUAL_METHODS.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("")}</select></div>
          </div>
          <div class="field-row">
            <div class="field"><label>Date received</label>
              <input id="mpDate" type="date" value="${todayISO()}" min="${MIN_PAY_DATE}" max="${todayISO()}"></div>
            <div class="field"><label>Reference <span style="color:var(--muted);font-weight:500">(optional)</span></label>
              <input id="mpRef" type="text" maxlength="80" placeholder="UTR / cheque no. / txn id" autocomplete="off"></div>
          </div>
          <div class="field"><label>What is this payment for? <span style="color:var(--muted);font-weight:500">(optional)</span></label>
            <input id="mpDesc" type="text" maxlength="300" placeholder="e.g. Initial consultation fee" autocomplete="off"></div>
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:12px">
            <button class="btn btn-primary" id="mpSaveBtn">Record payment</button>
            <span style="font-size:12px;color:var(--muted)">Added to this client's ledger &amp; Collected total</span>
          </div>
        </div></div>` : "";

      const chip = (s) => {
        const map = {
          created: ["Awaiting payment", "pend"], failed: ["Failed", "err"], cancelled: ["Cancelled", "mut"],
          paid: ["Paid", "ok"], transferred: ["Paid · payout on the way", "ok"], settled: ["Paid · settled to bank", "ok"],
          refunded: ["Refunded", "warn"], partially_refunded: ["Partially refunded", "warn"],
        };
        const [label, cls] = map[s] || [s, "mut"];
        return `<span class="pay-status ${cls}">${esc(label)}</span>`;
      };
      const dateStr = (iso) => iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "—";

      const rows = (d.payments || []).map((p) => {
        const acts = [];
        const isManual = !!p.is_manual;
        if (canManage && !isManual && (p.status === "created" || p.status === "failed")) {
          acts.push(`<button class="btn btn-ghost btn-xs" data-act="resend" data-id="${p.id}">Copy / resend link</button>`);
          acts.push(`<button class="btn btn-ghost btn-xs" data-act="cancel" data-id="${p.id}">Cancel</button>`);
        }
        if (canRefund && !isManual && ["paid", "transferred", "settled", "partially_refunded"].includes(p.status)) {
          acts.push(`<button class="btn btn-ghost btn-xs danger" data-act="refund" data-id="${p.id}" data-amt="${fmtMoney(p.amount_paise - (p.refunded_amount_paise || 0), "INR")}">Refund</button>`);
        }
        if (canManage && isManual) {
          acts.push(`<button class="btn btn-ghost btn-xs danger" data-act="delete-manual" data-id="${p.id}">Remove</button>`);
        }
        const when = isManual ? (p.paid_at || p.created_at) : p.created_at;
        const statusCell = isManual ? `<span class="pay-status ok">Recorded manually</span>` : chip(p.status);
        const sub = isManual
          ? `${esc(manualMethodLabel(p.manual_method))}${p.utr ? " · Ref " + esc(p.utr) : ""}`
          : `${esc(p.invoice_number || "")}${p.utr ? " · UTR " + esc(p.utr) : ""}`;
        return `<tr>
          <td>${dateStr(when)}</td>
          <td>${esc(p.description || (isManual ? "Offline payment" : "Payment"))}<div class="pay-sub">${sub}</div></td>
          <td style="font-weight:700;white-space:nowrap">${fmtMoney(p.amount_paise, "INR")}</td>
          <td>${statusCell}</td>
          <td class="pay-acts">${acts.join("")}</td>
        </tr>`;
      }).join("");

      body.innerHTML = `
        ${gateNote}
        <div class="card"><div class="card-body">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:14px">
            <div style="font-weight:800;font-size:15px">Payments from ${esc(cl.full_name)}</div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">${manualBtn}${reqBtn}</div>
          </div>
          ${chipRow}
        </div></div>
        ${reqForm}
        ${manualForm}
        <div class="card"><div class="card-body" style="overflow-x:auto">
          ${rows ? `<table class="client-table pay-table">
              <thead><tr><th>Date</th><th>Description</th><th>Amount</th><th>Status</th><th></th></tr></thead>
              <tbody>${rows}</tbody></table>`
            : `<div style="color:var(--muted);font-size:13.5px;padding:6px 0">No payments yet${canManage ? " — request one online or record an offline payment above." : "."}</div>`}
        </div></div>`;

      const goFin = $("#payGoFinance");
      if (goFin) goFin.onclick = (e) => { e.preventDefault(); navigate("finance"); };
      const tgl = $("#payReqToggle");
      if (tgl) tgl.onclick = () => { $("#payReqForm").classList.toggle("hidden"); const mf = $("#payManualForm"); if (mf) mf.classList.add("hidden"); };
      const mtgl = $("#payManualToggle");
      if (mtgl) mtgl.onclick = () => { $("#payManualForm").classList.toggle("hidden"); const rf = $("#payReqForm"); if (rf) rf.classList.add("hidden"); };

      const previewEl = $("#paySplit");
      const amtEl = $("#payAmt");
      if (amtEl && previewEl) {
        amtEl.oninput = () => {
          const rupees = parseFloat(amtEl.value || "0");
          if (!rupees || rupees <= 0) {
            previewEl.textContent = `Rilono fee: ${Number(fee.percent)}% (min ${fmtInrExact(fee.min_fee_rupees)}) — enter an amount to preview your payout.`;
            return;
          }
          // The client-side `fee` fallback above is {percent: 2, min_fee_rupees: 49} — an
          // INR figure by definition, and Route only ever charges in INR, so it is rendered
          // with fmtInrExact/fmtMoney and never through the display-currency converter.
          const paise = Math.round(rupees * 100);
          const commission = Math.max(Math.round(paise * (Number(fee.percent) / 100)), Math.round(Number(fee.min_fee_rupees) * 100));
          const payout = paise - commission;
          previewEl.innerHTML = payout > 0
            ? `Student pays <b>${fmtMoney(paise, "INR")}</b> · Rilono fee <b>${fmtMoney(commission, "INR")}</b> · You receive <b>${fmtMoney(payout, "INR")}</b> (settled to your bank by Razorpay)`
            : `Amount is too small — after the minimum fee of ${fmtInrExact(fee.min_fee_rupees)} there would be nothing left to pay out.`;
        };
      }

      const createBtn = $("#payCreateBtn");
      // An amount and a description are both genuinely required; the due date is optional.
      // The >= 3-character rule stays a toast rather than part of the predicate — a button
      // that dies again on the second character of a real description reads as broken.
      if (createBtn) bindValidity(createBtn, [$("#payAmt"), $("#payDesc")],
        () => parseFloat($("#payAmt").value || "0") > 0 && $("#payDesc").value.trim() !== "",
        "Enter an amount and what the payment is for");
      if (createBtn) createBtn.onclick = async () => {
        const rupees = parseFloat(($("#payAmt").value || "0"));
        const desc = ($("#payDesc").value || "").trim();
        const due = ($("#payDue").value || "").trim() || null;
        if (!rupees || rupees <= 0) { toast("Enter the amount to collect.", "error"); return; }
        if (desc.length < 3) { toast("Describe what this payment is for.", "error"); return; }
        await withBusy(createBtn, "Creating…", async () => {
          try {
            const res = await api(`/clients/${cl.id}/payments`, {
              method: "POST",
              body: { amount_paise: Math.round(rupees * 100), description: desc, due_date: due },
            });
            try { if (res.pay_url && navigator.clipboard) await navigator.clipboard.writeText(res.pay_url); } catch (e) { /* ignore */ }
            toast(res.message + (res.pay_url ? " Link copied to your clipboard." : ""), "success");
            renderPayments();
          } catch (ex) {
            toast(ex.message || "Could not create the payment request.", "error");
          }
        });
      };

      const mpSave = $("#mpSaveBtn");
      // Amount is the only unconditionally-required field: #mpMethod defaults to "cash" and
      // #mpDate ships pre-filled with today, so neither belongs in the predicate — a bad date
      // keeps its toast below, which can explain WHY, where a dead button cannot.
      if (mpSave) bindValidity(mpSave, [$("#mpAmt")],
        () => parseFloat($("#mpAmt").value || "0") > 0, "Enter the amount received");
      if (mpSave) mpSave.onclick = async () => {
        const rupees = parseFloat(($("#mpAmt").value || "0"));
        const method = $("#mpMethod").value;
        const date = ($("#mpDate").value || "").trim() || null;
        const ref = ($("#mpRef").value || "").trim();
        const desc = ($("#mpDesc").value || "").trim();
        if (!rupees || rupees <= 0) { toast("Enter the amount received.", "error"); return; }
        // `min`/`max` on the input are constraint-validation hints, not clamps — a year typed
        // straight into the field still lands in .value (the field just goes :invalid), and
        // nothing here reads validity, so check it. String compare is safe: a date input's
        // value is either "" or a valid date string, whose year is always four+ digits.
        // The server re-checks against the ORG's calendar and is the actual guard.
        if (date && date > todayISO()) { toast("The date received can't be in the future — check the date.", "error"); return; }
        if (date && date < MIN_PAY_DATE) { toast("Check the date received — that year looks wrong.", "error"); return; }
        await withBusy(mpSave, "Saving…", async () => {
          try {
            const res = await api(`/clients/${cl.id}/payments/manual`, {
              method: "POST",
              body: { amount_paise: Math.round(rupees * 100), method, received_on: date, reference: ref || null, description: desc || null },
            });
            toast(res.message || "Payment recorded.", "success");
            renderPayments();
          } catch (ex) {
            toast(ex.message || "Could not record the payment.", "error");
          }
        });
      };

      // One lock for the whole row-action set, not one per button. confirmModal closes the
      // dialog BEFORE it resolves and these buttons live in #cpBody rather than the modal, so
      // without this the row stays fully live from the moment the user presses "Refund" until
      // the POST returns — long enough to fire a second refund, or to stack a second dialog.
      // The flag is per-render because all four actions repaint #cpBody through
      // renderPayments(); by then these nodes are detached and the release is a no-op.
      let payBusy = false;
      body.querySelectorAll("[data-act]").forEach((btn) => {
        btn.onclick = async () => {
          if (payBusy) return;
          const pid = btn.dataset.id;
          const act = btn.dataset.act;
          // Claimed before the confirm, not after it — a second click must not open a second
          // dialog for the same payment.
          payBusy = true;
          btn.disabled = true;
          try {
            if (act === "resend") {
              const res = await api(`/finance/payments/${pid}/resend-email`, { method: "POST" });
              try { if (res.pay_url && navigator.clipboard) await navigator.clipboard.writeText(res.pay_url); } catch (e) { /* ignore */ }
              toast(res.message + (res.pay_url ? " Link copied to your clipboard." : ""), "success");
              renderPayments();
            } else if (act === "cancel") {
              const ok = await confirmModal("Cancel this payment request? The emailed pay-link will stop working.", { title: "Cancel payment request", okText: "Cancel request" });
              if (!ok) return;
              const res = await api(`/finance/payments/${pid}/cancel`, { method: "POST" });
              toast(res.message, "success");
              renderPayments();
            } else if (act === "refund") {
              const amt = btn.dataset.amt || "";
              const ok = await confirmModal(
                `Refund ${amt} to the student's original payment method? This also reverses the payout from your account and cannot be undone.`,
                { title: "Refund payment", okText: "Refund" }
              );
              if (!ok) return;
              const res = await api(`/finance/payments/${pid}/refund`, { method: "POST", body: { reason: "" } });
              toast(res.message, "success");
              renderPayments();
            } else if (act === "delete-manual") {
              const ok = await confirmModal(
                "Remove this manually-recorded payment? This only deletes the ledger note — it does not move any money.",
                { title: "Remove payment record", okText: "Remove" }
              );
              if (!ok) return;
              const res = await api(`/finance/payments/${pid}/manual`, { method: "DELETE" });
              toast(res.message || "Removed.", "success");
              renderPayments();
            }
          } catch (ex) {
            toast(ex.message || "Action failed.", "error");
          } finally {
            payBusy = false;
            if (btn.isConnected) btn.disabled = false;
          }
        };
      });
    }

    /* ---- Universities tab (per-client shortlist, tailored to their destination) ---- */
    const UNI_STATUSES = [
      { key: "considering", label: "Considering", color: "#64748b" },
      { key: "applied", label: "Applied", color: "#2563eb" },
      { key: "admitted", label: "Admitted", color: "#059669" },
      { key: "rejected", label: "Rejected", color: "#dc2626" },
    ];
    const UNI_DIFFICULTY = {
      reach: { label: "Reach", bg: "rgba(239,68,68,.12)", fg: "#b91c1c" },
      match: { label: "Match", bg: "rgba(37,99,235,.12)", fg: "#1d4ed8" },
      safety: { label: "Safety", bg: "rgba(16,185,129,.14)", fg: "#047857" },
    };

    // Defence in depth: the server already stores only http(s) URLs, but never build an
    // href from model-authored text without re-checking the scheme.
    function safeUrl(u) {
      return typeof u === "string" && /^https?:\/\/[^\s]+$/i.test(u.trim());
    }

    function renderUniversities() {
      body.innerHTML = `<div id="uniWrap"><div class="muted" style="padding:8px 0">Loading shortlist…</div></div>`;
      // Let the module-level row handlers (status change / remove) redraw this tab,
      // since they're invoked from inline onclick and can't see this closure.
      _uniRefresh = loadUniversities;
      _uniStageSync = syncStepperToShortlist;
      // Bring back any paid-for AI matches the user hasn't actioned yet.
      restoreUniSuggestions();
      loadUniversities();
    }

    async function loadUniversities() {
      try {
        uni.data = await api(`/clients/${cl.id}/universities`);
      } catch (ex) {
        uni.data = null;
        const w = $("#uniWrap");
        if (w) w.innerHTML = `<div class="cp-card"><div class="muted">Could not load the shortlist: ${esc(ex.message)}</div></div>`;
        return;
      }
      if ($("#uniWrap")) drawUniversities();
    }

    // Keeps the journey stepper in step with the shortlist, and OFFERS the matching pipeline
    // move — it must never make one. Three separate code paths write shortlist rows, and a
    // counsellor marking research must not silently reposition the client or fire a
    // "moved X to Y" notification, so the move only happens if the user confirms it.
    async function syncStepperToShortlist(clientId, status) {
      if (clientId !== cl.id) return;
      refreshStageUi();
      if (status !== "applied" || !canEdit) return;
      const stages = stagesForClient(cl);
      const target = stages.find((s) => s.key === "applications_sent");
      const from = stages.find((s) => s.key === cl.status);
      if (!target || !from) return;
      const orderOf = (s) => (s.order != null ? s.order : 0);
      if (orderOf(from) >= orderOf(target)) return;
      const first = (cl.full_name || "the client").split(" ")[0];
      // Same wording as the "Move X here" button in the stage panel — it is the same move,
      // and a counsellor should not have to work out whether two differently-phrased prompts
      // do the same thing. The extra line is the only part specific to this trigger.
      const missing = stageMissingRequired(cl.status);
      const warn = missing.length
        ? `\n\n⚠ “${from.label}” is still missing: ${missing.map((f) => f.label).join(", ")}.\nYou can continue and fill this in later.`
        : "";
      const ok = await confirmModal(
        `${first} will move from “${from.label}” to “${target.label}”.\n\nThe shortlist row is saved either way.` + warn,
        { title: "Move to “" + target.label + "”?", okText: "Move stage", cancelText: "Leave the stage as is", danger: false }
      );
      if (!ok) return;
      // Deliberately not setStatus(): that rebuilds the client page and drops the counsellor
      // back on Overview, mid-shortlist. Patch, re-read the client into this closure so every
      // tab renders the new stage, and redraw only the journey.
      try {
        await api(`/clients/${cl.id}/status`, { method: "PATCH", body: { status: target.key } });
        const fresh = await api("/clients/" + cl.id);
        if (fresh && fresh.client) Object.assign(cl, fresh.client);
        toast("Status updated", "success");
        refreshStageUi();
      } catch (ex) {
        toast(ex.message, "error");
      }
    }

    function uniStatusSelect(entry) {
      const opts = UNI_STATUSES.map((s) =>
        `<option value="${s.key}"${entry.status === s.key ? " selected" : ""}>${s.label}</option>`).join("");
      const color = (UNI_STATUSES.find((s) => s.key === entry.status) || UNI_STATUSES[0]).color;
      return `<select class="uni-status" style="color:${color}" onchange="__ent.setUniStatus(${cl.id},${entry.id},this.value,this)">${opts}</select>`;
    }

    function uniRow(e) {
      const d = UNI_DIFFICULTY[(e.admission_difficulty || "").toLowerCase()];
      const meta = [e.program, e.location].filter(Boolean).join(" · ");
      const ranks = [
        e.qs_world_rank ? `QS #${esc(e.qs_world_rank)}` : "",
        e.country_rank ? `National #${esc(e.country_rank)}` : "",
        e.est_tuition ? esc(e.est_tuition) : "",
        e.application_fee ? `App fee ${esc(e.application_fee)}` : "",
      ].filter(Boolean).join(" &nbsp;·&nbsp; ");
      const reqs = (e.key_requirements || []).length
        ? `<div class="uni-reqs">${e.key_requirements.map((r) => `<span>${esc(r)}</span>`).join("")}</div>` : "";
      // Only http(s) URLs are ever stored, but re-check before rendering an href.
      const links = [
        safeUrl(e.website_url) ? `<a class="uni-link" href="${esc(e.website_url)}" target="_blank" rel="noopener noreferrer">🔗 University site</a>` : "",
        safeUrl(e.admissions_url) ? `<a class="uni-link" href="${esc(e.admissions_url)}" target="_blank" rel="noopener noreferrer">📋 Entry requirements</a>` : "",
      ].filter(Boolean).join("");
      const linkRow = links ? `<div class="uni-links">${links}</div>` : "";
      return `<div class="uni-row">
        <div class="uni-main">
          <div class="uni-name">${esc(e.university_name)}
            ${e.source === "ai" ? '<span class="uni-badge-ai">AI</span>' : ""}
            ${d ? `<span class="uni-badge" style="background:${d.bg};color:${d.fg}">${d.label}</span>` : ""}
          </div>
          ${meta ? `<div class="uni-meta">${esc(meta)}</div>` : ""}
          ${ranks ? `<div class="uni-ranks">${ranks}</div>` : ""}
          ${e.rationale ? `<div class="uni-why">${esc(e.rationale)}</div>` : ""}
          ${reqs}
          ${linkRow}
        </div>
        <div class="uni-actions">
          ${canManageUnis ? uniStatusSelect(e) : `<span class="uni-status-ro">${esc((UNI_STATUSES.find((s) => s.key === e.status) || UNI_STATUSES[0]).label)}</span>`}
          ${canManageUnis ? `<button class="uni-del" title="Remove" onclick="__ent.removeUni(${cl.id},${e.id},this)">&times;</button>` : ""}
        </div>
      </div>`;
    }

    function drawUniversities() {
      const w = $("#uniWrap");
      if (!w || !uni.data) return;
      const d = uni.data;
      const entries = d.entries || [];
      const dest = d.destination_country || "their destination";
      const cost = d.recommend_cost || 0;
      const first = (cl.full_name || "this client").split(" ")[0];

      const aiCard = !canShortlistAi ? "" : `
        <div class="cp-card uni-ai-card">
          <div class="uni-ai-head">
            <div>
              <div class="cp-card-head" style="margin:0"><h3>🎓 Find universities in ${esc(dest)}</h3></div>
              <p class="muted" style="margin:4px 0 0;font-size:13px">Rilono AI matches real ${esc(dest)} universities to ${esc(first)}'s profile, budget and grades — with rankings and entry requirements.</p>
            </div>
            <span class="uni-cost">${cost} credits</span>
          </div>
          ${d.recommend_available === false
            ? `<div class="muted" style="margin-top:10px">AI recommendations are not available right now.</div>`
            : `<div class="uni-form">
                 <div class="field"><label>Field of study <span style="color:#dc2626">*</span></label><input id="uniField" placeholder="e.g. Computer Science" maxlength="120"></div>
                 <div class="field"><label>Study level</label>
                   <select id="uniLevel"><option value="">Any</option><option>Bachelors</option><option>Masters</option><option>PhD</option><option>Diploma</option></select></div>
                 <div class="field"><label>Annual budget</label><input id="uniBudget" placeholder="${esc(uniBudgetHint(d.destination_country_code))}" maxlength="60"></div>
                 <div class="field"><label>Grades / GPA</label><input id="uniGpa" placeholder="${esc(uniGpaHint(d.destination_country_code))}" maxlength="60"></div>
                 <div class="field"><label>Test scores</label><input id="uniScores" placeholder="${esc(uniScoreHint(d.destination_country_code))}" maxlength="160"></div>
                 <div class="field"><label>Other preferences</label><input id="uniPrefs" placeholder="e.g. scholarships, near a major city" maxlength="300"></div>
               </div>
               <div class="uni-ai-foot">
                 <button class="btn btn-primary" id="uniRecBtn">✨ Get AI recommendations</button>
                 <span class="muted" id="uniRecMsg"></span>
               </div>`}
        </div>`;

      const addCard = !canManageUnis ? "" : `
        <div class="cp-card">
          <div class="cp-sub-label">Add manually</div>
          <div class="uni-add-row">
            <input id="uniManual" placeholder="Search ${esc(dest)} universities…" autocomplete="off">
            <input id="uniManualProgram" placeholder="Program (optional)" maxlength="200">
            <button class="btn btn-soft" id="uniAddBtn">Add</button>
          </div>
          <div id="uniSuggest" class="uni-suggest" style="display:none"></div>
        </div>`;

      w.innerHTML = `
        ${aiCard}
        ${canManageUnis ? uniSuggestionsPanel() : ""}
        ${addCard}
        <div class="cp-card">
          <div class="cp-card-head"><h3>Shortlist</h3>
            <div class="uni-head-right">
              <span class="muted">${entries.length} ${entries.length === 1 ? "university" : "universities"}</span>
              ${entries.length ? `<button class="btn btn-soft btn-sm" id="uniExportBtn" title="Download as CSV — opens directly in Excel">⬇ Export</button>` : ""}
            </div>
          </div>
          ${entries.length
            ? `<div class="uni-list">${entries.map(uniRow).join("")}</div>`
            : `<div class="uni-empty">No universities shortlisted yet${canManageUnis ? ` — run an AI match for ${esc(dest)} or add one manually.` : "."}</div>`}
        </div>`;

      // Export is available to viewers too — reading the shortlist doesn't require edit rights.
      const exportBtn = $("#uniExportBtn");
      if (exportBtn) exportBtn.onclick = () => exportUniversitiesCsv();

      if (canManageUnis || canShortlistAi) {
        const rec = $("#uniRecBtn");
        // Field of study is the one starred field; everything else on this form is optional.
        if (rec) bindValidity(rec, [$("#uniField")],
          () => ($("#uniField").value || "").trim() !== "", "Enter a field of study first");
        if (rec) rec.onclick = () => recommendUniversities();
        const addBtn = $("#uniAddBtn");
        if (addBtn) bindValidity(addBtn, [$("#uniManual")],
          () => ($("#uniManual").value || "").trim() !== "", "Enter a university name first");
        if (addBtn) addBtn.onclick = () => addManualUniversity();
        const save = $("#uniSavePicks");
        // Delegated on the panel so every .uni-pick tick re-checks, however many there are.
        if (save) bindValidity(save, $("#uniSuggPanel"),
          () => !!document.querySelector(".uni-pick:checked"), "Tick at least one university");
        if (save) save.onclick = () => addSelectedUniSuggestions();
        const dismiss = $("#uniDismissSugg");
        if (dismiss) dismiss.onclick = () => dismissUniSuggestions();
        if (canManageUnis) wireUniAutocomplete();
      }
    }

    // Country-aware placeholders so a UK client never sees "$" / "GRE" hints.
    function uniBudgetHint(code) {
      return ({ US: "e.g. $30,000", UK: "e.g. £22,000", CA: "e.g. C$25,000", AU: "e.g. A$35,000", DE: "e.g. €12,000", IE: "e.g. €18,000", FR: "e.g. €13,000", ES: "e.g. €14,000", NL: "e.g. €22,000", AE: "e.g. AED 80,000" })[code] || "e.g. annual budget";
    }
    function uniGpaHint(code) {
      return ({ US: "e.g. 3.6/4.0", UK: "e.g. 2:1 or AAB", CA: "e.g. 3.6/4.0 or 85%", AU: "e.g. 75% or GPA 5.5/7", DE: "e.g. 1.7 (German scale)", IE: "e.g. 2:1 (Honours)", FR: "e.g. 14/20 (mention bien)", ES: "e.g. 7.5/10 (notable)", NL: "e.g. 7.5/10", AE: "e.g. 3.4/4.0" })[code] || "e.g. GPA or grade average";
    }
    function uniScoreHint(code) {
      return ({ US: "e.g. IELTS 7.5, GRE 320", UK: "e.g. IELTS 7.0", CA: "e.g. IELTS 7.0", AU: "e.g. IELTS 7.0, PTE 65", DE: "e.g. IELTS 6.5, TestDaF 4", IE: "e.g. IELTS 6.5", FR: "e.g. IELTS 6.5, DELF B2", ES: "e.g. IELTS 6.5, DELE B2", NL: "e.g. IELTS 6.5, TOEFL 90", AE: "e.g. IELTS 6.5, TOEFL 79" })[code] || "e.g. IELTS 7.0";
    }

    function wireUniAutocomplete() {
      const input = $("#uniManual");
      const box = $("#uniSuggest");
      if (!input || !box) return;
      let timer = null;
      const hide = () => { box.style.display = "none"; box.innerHTML = ""; };
      input.addEventListener("input", () => {
        const q = input.value.trim();
        if (timer) clearTimeout(timer);
        if (q.length < 2) return hide();
        timer = setTimeout(async () => {
          try {
            const r = await api(`/clients/${cl.id}/universities/search?q=${encodeURIComponent(q)}`);
            const results = r.results || [];
            if (!results.length) return hide();
            box.innerHTML = results.map((u) =>
              `<button type="button" class="uni-sugg" data-name="${esc(u.name)}">${esc(u.name)}${u.location ? `<span>${esc(u.location)}</span>` : ""}</button>`).join("");
            box.style.display = "block";
            box.querySelectorAll(".uni-sugg").forEach((b) => {
              // Assigning .value fires no input event, so nudge the Add button's validity
              // check by hand — otherwise picking a suggestion leaves it dead.
              b.onclick = () => {
                input.value = b.dataset.name; hide();
                const add = $("#uniAddBtn"); if (add && add._syncValid) add._syncValid();
                const p = $("#uniManualProgram"); if (p && !p.value) p.focus();
              };
            });
          } catch (e) { hide(); }
        }, 220);
      });
      input.addEventListener("blur", () => setTimeout(hide, 180));
    }

    async function addManualUniversity() {
      const input = $("#uniManual");
      const prog = $("#uniManualProgram");
      const name = (input && input.value || "").trim();
      if (!name) { toast("Enter a university name first.", "error"); return; }
      const btn = $("#uniAddBtn");
      if (btn) { btn.disabled = true; btn.textContent = "Adding…"; }
      try {
        await api(`/clients/${cl.id}/universities`, {
          method: "POST",
          body: { university_name: name, program: (prog && prog.value || "").trim() || null, source: "manual" },
        });
        if (input) input.value = "";
        if (prog) prog.value = "";
        toast("Added to shortlist", "success");
        await loadUniversities();
      } catch (ex) { toast(ex.message, "error"); }
      // Re-queried because loadUniversities() has replaced the node by now; back through the
      // validity gate rather than straight to enabled, since a successful add cleared the input.
      finally { const b = $("#uniAddBtn"); if (b) { b.textContent = "Add"; if (b._syncValid) b._syncValid(); else b.disabled = false; } }
    }

    async function recommendUniversities() {
      const field = ($("#uniField") && $("#uniField").value || "").trim();
      const msg = $("#uniRecMsg");
      if (!field) { if (msg) msg.textContent = "Enter a field of study first."; return; }
      const btn = $("#uniRecBtn");
      if (btn) { btn.disabled = true; btn.textContent = "Matching universities…"; }
      if (msg) msg.textContent = "Rilono AI is researching current rankings — this can take ~20s.";
      try {
        const r = await api(`/clients/${cl.id}/universities/recommend`, {
          method: "POST",
          timeout: AI_API_TIMEOUT_MS,
          body: {
            field_of_study: field,
            level: ($("#uniLevel") && $("#uniLevel").value) || null,
            budget: ($("#uniBudget") && $("#uniBudget").value || "").trim() || null,
            gpa: ($("#uniGpa") && $("#uniGpa").value || "").trim() || null,
            test_scores: ($("#uniScores") && $("#uniScores").value || "").trim() || null,
            preferences: ($("#uniPrefs") && $("#uniPrefs").value || "").trim() || null,
            max_results: 6,
          },
        });
        if (r.wallet) { state.credits = r.wallet; updatePlanChip(); }
        uni.suggestions = r.universities || [];
        uni.grounded = !!r.grounded;
        // These cost credits — persist immediately so a refresh, tab switch or stray
        // click can never destroy results the consultancy already paid for.
        persistUniSuggestions();
        drawUniversities();
        if (r.credits_charged) toast(`${r.universities.length} matches · ${r.credits_charged} credits used`, "success");
      } catch (ex) {
        if (ex.status === 402) { toast(ex.message, "error"); navigate("credits"); }
        else if (msg) msg.textContent = ex.message || "Could not generate recommendations.";
      } finally {
        const b = $("#uniRecBtn");
        if (b) { b.textContent = "✨ Get AI recommendations"; if (b._syncValid) b._syncValid(); else b.disabled = false; }
      }
    }

    /* AI results cost credits, so they are NEVER shown in a dismissable modal — a stray
       backdrop click would burn the charge with nothing saved. They render inline in the
       tab and are mirrored to sessionStorage, so a refresh or tab switch can't lose them.
       sessionStorage (not localStorage) keeps client data off disk between sessions. */
    const uniSuggestKey = () => `rilono_ent_uni_sugg_${cl.id}`;

    function persistUniSuggestions() {
      try {
        sessionStorage.setItem(uniSuggestKey(), JSON.stringify({
          universities: uni.suggestions || [], grounded: !!uni.grounded,
        }));
      } catch (e) { /* private mode / quota — the in-memory copy still works */ }
    }

    function restoreUniSuggestions() {
      if (uni.suggestions && uni.suggestions.length) return;
      try {
        const raw = sessionStorage.getItem(uniSuggestKey());
        if (!raw) return;
        const saved = JSON.parse(raw);
        uni.suggestions = Array.isArray(saved.universities) ? saved.universities : [];
        uni.grounded = !!saved.grounded;
      } catch (e) { uni.suggestions = []; }
    }

    function clearUniSuggestions() {
      uni.suggestions = [];
      uni.grounded = false;
      try { sessionStorage.removeItem(uniSuggestKey()); } catch (e) { /* noop */ }
    }

    function uniSuggestionsPanel() {
      const list = uni.suggestions || [];
      if (!list.length) return "";
      const dest = (uni.data && uni.data.destination_country) || "";
      const first = (cl.full_name || "").split(" ")[0];
      return `<div class="cp-card uni-sugg-card" id="uniSuggPanel">
        <div class="uni-sugg-head">
          <div>
            <div class="cp-card-head" style="margin:0"><h3>🎓 ${list.length} matches in ${esc(dest)}</h3></div>
            <p class="muted" style="margin:4px 0 0;font-size:13px">Pick the ones worth shortlisting for ${esc(first)}${uni.grounded ? " · rankings checked against live sources" : ""}.</p>
          </div>
          <span class="uni-sugg-saved">✓ Saved — safe to come back to</span>
        </div>
        <div class="uni-sugg-list">
          ${list.map((u, i) => {
            const d = UNI_DIFFICULTY[(u.admission_difficulty || "").toLowerCase()];
            const ranks = [u.qs_world_rank ? `QS #${esc(u.qs_world_rank)}` : "", u.country_rank ? `National #${esc(u.country_rank)}` : "", u.estimated_annual_tuition ? esc(u.estimated_annual_tuition) : "", u.application_fee ? `App fee ${esc(u.application_fee)}` : ""].filter(Boolean).join(" · ");
            const sLinks = [
              safeUrl(u.official_website) ? `<a class="uni-link" href="${esc(u.official_website)}" target="_blank" rel="noopener noreferrer">🔗 University site</a>` : "",
              safeUrl(u.admissions_url) ? `<a class="uni-link" href="${esc(u.admissions_url)}" target="_blank" rel="noopener noreferrer">📋 Entry requirements</a>` : "",
            ].filter(Boolean).join("");
            return `<label class="uni-sugg-item">
              <input type="checkbox" class="uni-pick" data-i="${i}" checked>
              <div>
                <div class="uni-name">${esc(u.name || "")}${d ? `<span class="uni-badge" style="background:${d.bg};color:${d.fg}">${d.label}</span>` : ""}</div>
                ${[u.program, u.location].filter(Boolean).length ? `<div class="uni-meta">${esc([u.program, u.location].filter(Boolean).join(" · "))}</div>` : ""}
                ${ranks ? `<div class="uni-ranks">${ranks}</div>` : ""}
                ${u.why_recommended ? `<div class="uni-why">${esc(u.why_recommended)}</div>` : ""}
                ${(u.key_requirements || []).length ? `<div class="uni-reqs">${u.key_requirements.map((r) => `<span>${esc(r)}</span>`).join("")}</div>` : ""}
                ${sLinks ? `<div class="uni-links">${sLinks}</div>` : ""}
              </div>
            </label>`;
          }).join("")}
        </div>
        <div class="uni-sugg-foot">
          <button class="btn btn-primary" id="uniSavePicks">Add selected to shortlist</button>
          <button class="btn btn-ghost" id="uniDismissSugg">Dismiss</button>
        </div>
      </div>`;
    }

    async function addSelectedUniSuggestions() {
      const list = uni.suggestions || [];
      const picks = [...document.querySelectorAll(".uni-pick")].filter((c) => c.checked).map((c) => list[Number(c.dataset.i)]).filter(Boolean);
      if (!picks.length) { toast("Tick at least one university first.", "error"); return; }
      const btn = $("#uniSavePicks");
      if (btn) { btn.disabled = true; btn.textContent = "Adding…"; }
      let added = 0;
      const failed = [];
      for (const u of picks) {
        try {
          await api(`/clients/${cl.id}/universities`, {
            method: "POST",
            body: {
              university_name: u.name, program: u.program || null, location: u.location || null,
              source: "ai", est_tuition: u.estimated_annual_tuition || null, rationale: u.why_recommended || null,
              qs_world_rank: u.qs_world_rank || null, country_rank: u.country_rank || null,
              admission_difficulty: u.admission_difficulty || null,
              application_fee: u.application_fee || null,
              website_url: u.official_website || null,
              admissions_url: u.admissions_url || null,
              key_requirements: Array.isArray(u.key_requirements) ? u.key_requirements : null,
            },
          });
          added += 1;
        } catch (e) { failed.push(u); }
      }
      // Only drop the paid-for results once everything selected actually saved.
      if (failed.length) {
        uni.suggestions = failed;
        persistUniSuggestions();
        toast(`${added} added · ${failed.length} failed — still here to retry`, "error");
      } else {
        clearUniSuggestions();
        toast(`${added} added to shortlist`, "success");
      }
      await loadUniversities();
    }

    /* Export the shortlist as CSV — Excel opens it natively, so no server round-trip or
       spreadsheet dependency is needed. Two details that matter for real Excel use:
         1. A UTF-8 BOM, or Excel mangles £/€/accented university names.
         2. Formula-injection guarding: a cell starting with = + - @ is executed by Excel,
            and these rows carry AI-generated text and free-text notes. */
    function csvCell(value) {
      let s = value === null || value === undefined ? "" : String(value);
      if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
      return `"${s.replace(/"/g, '""')}"`;
    }

    function exportUniversitiesCsv() {
      const entries = (uni.data && uni.data.entries) || [];
      if (!entries.length) { toast("Nothing to export yet.", "error"); return; }

      const statusLabel = (k) => (UNI_STATUSES.find((s) => s.key === k) || UNI_STATUSES[0]).label;
      const fitLabel = (k) => (UNI_DIFFICULTY[(k || "").toLowerCase()] || {}).label || "";
      const headers = [
        "University", "Program", "Location", "Status", "Fit", "QS World Rank", "National Rank",
        "Est. Annual Tuition", "Application Fee", "Key Requirements", "University Website",
        "Entry Requirements Link", "Why Recommended", "Notes", "Source", "Added By", "Added On",
      ];
      const rows = entries.map((e) => [
        e.university_name, e.program, e.location, statusLabel(e.status), fitLabel(e.admission_difficulty),
        e.qs_world_rank, e.country_rank, e.est_tuition, e.application_fee,
        (e.key_requirements || []).join("; "), e.website_url, e.admissions_url,
        e.rationale, e.notes,
        e.source === "ai" ? "Rilono AI" : "Manual", e.added_by_name,
        e.created_at ? new Date(e.created_at).toLocaleDateString() : "",
      ]);
      const csv = [headers, ...rows].map((r) => r.map(csvCell).join(",")).join("\r\n");

      const safeName = (cl.full_name || "client").replace(/[^\w\- ]+/g, "").trim().replace(/\s+/g, "-") || "client";
      const stamp = new Date().toISOString().slice(0, 10);
      const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${safeName}-universities-${stamp}.csv`;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 0);
      toast(`Exported ${entries.length} ${entries.length === 1 ? "university" : "universities"}`, "success");
    }

    async function dismissUniSuggestions() {
      const ok = await confirmModal(
        "Discard these AI matches? The credits for this search have already been used, so they can't be recovered without running it again.",
        { title: "Discard AI matches", okText: "Discard" }
      );
      if (!ok) return;
      clearUniSuggestions();
      drawUniversities();
    }

    /* ---- Deep Scan tab: full-dossier AI audit with stored history ----
       The scan itself is POST /deep-scan (first one per client free, then billed);
       results persist server-side, so this tab re-opens past audits like the
       interview tab re-opens past sessions. */
    async function loadDeepScans() {
      try {
        const r = await api(`/clients/${cl.id}/deep-scans`);
        ds.scans = r.scans || [];
        ds.pricing = r.pricing || null;
        ds.aiAvailable = r.ai_available !== false;
        ds.error = null;
        if (ds.scans.length && !ds.active) {
          // Re-open the most recent stored audit so the tab remembers where things stand.
          try { ds.active = (await api(`/clients/${cl.id}/deep-scans/${ds.scans[0].id}`)).scan; } catch (e) { /* list still renders */ }
        }
      } catch (ex) { ds.scans = null; ds.error = ex.message; }  // null = retry on next tab entry
      ds.loading = false;
      if (state.activeClient === cl.id && body.isConnected && $("#dsWrap")) drawDeepScan();
    }
    async function openDeepScanResult(scanId) {
      if (ds.active && ds.active.id === scanId) return;
      try { ds.active = (await api(`/clients/${cl.id}/deep-scans/${scanId}`)).scan; }
      catch (ex) { toast(ex.message, "error"); return; }
      if (state.activeClient === cl.id && body.isConnected && $("#dsWrap")) drawDeepScan();
    }
    async function runDeepScanNow() {
      if (ds.busy || deepScanInflight.has(cl.id)) return;
      ds.busy = true;
      deepScanInflight.add(cl.id);
      const btn = $("#deepScanBtn");
      const visualizer = startDeepScanVisualizer(docs.slice());
      // The full audit reads the whole dossier and cross-references it (map-reduce),
      // so it's the slowest AI action — escalate the button so staff know it's working.
      let ticks = 0, progressTimer = null;
      if (btn) {
        btn.disabled = true;
        const paint = () => {
          const s = ticks;
          const label = s < 8 ? "Auditing the dossier…"
            : s < 20 ? `Cross-checking every source… ${s}s`
            : `Almost done — reconciling… ${s}s`;
          const phase = s < 8 ? 0 : s < 20 ? 1 : 2;
          const phaseLabel = phase === 0 ? "Reading profile, records & documents"
            : phase === 1 ? "Cross-checking names, dates, funds & activity"
            : "Preparing audit findings";
          btn.innerHTML = `<span class="spinner"></span> ${label}`;
          visualizer.setPhase(phase, phaseLabel, s);
        };
        paint();
        progressTimer = setInterval(() => { ticks += 1; paint(); }, 1000);
      }
      const stopProgress = () => { if (progressTimer) { clearInterval(progressTimer); progressTimer = null; } };
      let res;
      try { res = await api(`/clients/${cl.id}/deep-scan`, { method: "POST", timeout: DEEP_SCAN_API_TIMEOUT_MS }); }
      catch (ex) {
        stopProgress();
        ds.busy = false;
        deepScanInflight.delete(cl.id);
        visualizer.fail();
        visualizer.destroy(900);
        if (!body.isConnected) { deepScanDirty.add(cl.id); }
        if (ex.status === 402) { toast(ex.message, "error"); ds.scans = null; ds.active = null; navigate("credits"); return; }
        toast(ex.message, "error");
        // A client-side timeout can hide a scan the server still completed (and billed) —
        // never redraw from stale state; refetch history + pricing from the server.
        ds.scans = null; ds.active = null; ds.loading = true;
        if (state.activeClient === cl.id && body.isConnected && $("#dsWrap")) drawDeepScan();
        loadDeepScans();
        return;
      }
      stopProgress();
      ds.busy = false;
      deepScanInflight.delete(cl.id);
      if (!body.isConnected) { deepScanDirty.add(cl.id); }
      if (res.wallet) { state.credits = res.wallet; updatePlanChip(); }
      if (res.pricing) ds.pricing = res.pricing;
      if (res.scan) {
        ds.active = res.scan;
        ds.scans = [{
          id: res.scan.id, risk_level: res.scan.risk_level, summary: res.scan.summary,
          stats: res.scan.stats, credits_charged: res.scan.credits_charged,
          triggered_by_name: res.scan.triggered_by_name, created_at: res.scan.created_at,
        }].concat(ds.scans || []);
      }
      toast(res.was_free ? "Deep Scan complete — this first scan was free"
        : `Deep Scan complete · ${res.credits_charged} credits used`, "success");
      visualizer.complete();
      await new Promise((resolve) => window.setTimeout(resolve, 700));
      visualizer.destroy();
      if (state.activeClient === cl.id && body.isConnected && $("#dsWrap")) drawDeepScan();
    }
    function drawDeepScan() {
      const wrap = $("#dsWrap");
      if (!wrap || !body.isConnected) return;
      // A live scan owns this tree (ticking button + visualizer) — repainting now would
      // orphan its progress UI. runDeepScanNow always redraws when the request settles.
      if (ds.busy) return;
      const first = (cl.full_name || "the student").split(" ")[0];
      const pricing = ds.pricing || {};
      const cost = pricing.cost_credits != null ? pricing.cost_credits
        : (((state.credits && (state.credits.actions || []).find((a) => a.key === "deep_scan")) || {}).credits || 20);
      const isFree = !!pricing.next_scan_free;
      // A scan may be running in an older render of this same client — keep the button
      // locked so it can't be double-run (and double-charged) from this one.
      const scanning = deepScanInflight.has(cl.id);
      // The "what does it read / what does it cost" explanation is reference material, not
      // something to re-read on every visit — it lives behind the ⓘ so the card stays a
      // one-line header + action. An unconfigured server still shows inline: that's a
      // blocking state, not an explanation.
      const scanTip = `Rilono AI strictly audits ${esc(first)}'s <b>entire dossier</b> — profile details, stage case records, the contents of every uploaded document, notes, emails, universities, interview results and payments — and flags anything irregular or inconsistent.<br><br>${
        isFree ? `The first scan for each client is <b>free</b>; after that it's <b>${cost} credits</b> per scan.`
          : `Each scan costs <b>${cost} credits</b>.`}`;
      const heroCard = `
        <div class="cp-card deep-scan-card" id="deepScanCard">
          <div class="deep-scan-head">
            <div class="deep-scan-copy">
              <div class="deep-scan-title"><span class="deep-scan-title-icon" aria-hidden="true">🛡️</span> Deep Scan — full client audit${
                infoTip(scanTip, "What Deep Scan checks")}</div>
              ${!ds.aiAvailable ? `<div class="deep-scan-description"><b>Rilono AI isn't configured on this server yet.</b></div>` : ""}
            </div>
            ${canDeepScan ? `<button class="btn btn-primary btn-sm deep-scan-btn" id="deepScanBtn" ${(!ds.aiAvailable || scanning) ? "disabled" : ""}>${
              scanning ? '<span class="spinner"></span> Scanning…' : isFree ? "Run Deep Scan · Free" : `Run Deep Scan · ${cost} cr`}</button>` : ""}
          </div>
          <div class="deep-scan-visualizer hidden" id="deepScanVisualizer" aria-live="polite"></div>
        </div>`;
      const resultBlock = ds.loading
        ? `<div class="cp-card"><div class="center-load"><div class="spinner dark"></div></div></div>`
        : ds.active
          ? `<div class="cp-card" id="dsResult">${deepScanResultHtml(ds.active)}</div>`
          : `<div class="cp-card"><div class="empty" style="padding:30px"><div class="emoji">🛡️</div><h3>${ds.error ? "Couldn't load Deep Scans" : "No Deep Scan yet"}</h3>
              <p>${ds.error ? esc(ds.error) : canDeepScan ? `Run ${esc(first)}'s first full-dossier audit — it's free.` : "No audits have been run for this client yet."}</p>
              ${ds.error ? `<button class="btn btn-soft btn-sm" id="dsRetryBtn" style="margin-top:10px">Retry</button>` : ""}</div></div>`;
      const historyCard = (ds.scans || []).length ? `
        <div class="cp-card">
          <div class="cp-sub-label">Scan history</div>
          ${ds.scans.map((s) => {
            const st = s.stats || {};
            const issues = (st.critical || 0) + (st.warning || 0) + (st.info || 0);
            const active = ds.active && ds.active.id === s.id;
            return `<div class="ds-hrow${active ? " active" : ""}" data-id="${s.id}">
              <span class="iv-sv ${s.risk_level === "low" ? "ok" : s.risk_level === "high" ? "bad" : "mid"}">${esc((s.risk_level || "medium").toUpperCase())}</span>
              <div class="ds-hmain"><b>${fmtDateTime(s.created_at)}</b><span>${issues} finding${issues === 1 ? "" : "s"}${s.triggered_by_name ? " · by " + esc(s.triggered_by_name) : ""}</span></div>
              <span class="ds-hcredits">${s.credits_charged ? s.credits_charged + " cr" : "Free"}</span>
            </div>`;
          }).join("")}
        </div>` : "";
      wrap.innerHTML = heroCard + resultBlock + historyCard;
      const runBtn = $("#deepScanBtn");
      if (runBtn) runBtn.onclick = runDeepScanNow;
      const retryBtn = $("#dsRetryBtn");
      if (retryBtn) retryBtn.onclick = () => { ds.error = null; ds.loading = true; drawDeepScan(); loadDeepScans(); };
      $$(".ds-hrow", wrap).forEach((r) => { r.onclick = () => openDeepScanResult(Number(r.dataset.id)); });
    }
    function renderDeepScan() {
      body.innerHTML = `<div id="dsWrap"></div>`;
      if (ds.busy) {
        // Tabbed back mid-scan (same closure): show a holding state — runDeepScanNow
        // repaints the full tab when the request settles.
        $("#dsWrap").innerHTML = `<div class="cp-card"><div class="center-load"><div class="spinner dark"></div></div>
          <p class="muted" style="text-align:center;margin:0 0 14px">Deep Scan in progress — this can take a few minutes…</p></div>`;
        return;
      }
      // A scan from a previous render of this client settled after its DOM was replaced —
      // our cached list predates it, so force a refetch.
      if (deepScanDirty.has(cl.id)) { deepScanDirty.delete(cl.id); ds.scans = null; ds.active = null; }
      if (ds.scans === null && !ds.loading) { ds.loading = true; loadDeepScans(); }
      drawDeepScan();
    }

    /* ---- Writing Studio tab: AI-drafted SOPs & LORs, exported as Word ----
       Generation and refinement each cost one credit; re-downloading a stored
       version is free, so the Word button never spends anything. Versions are
       immutable server-side — refining adds v2, v3 … to the same document. */
    async function loadWriting() {
      try {
        const r = await api(`/clients/${cl.id}/writing`);
        ws.drafts = r.drafts || [];
        ws.active = r.active || null;
        ws.catalog = r.catalog || null;
        ws.defaults = r.defaults || null;
        ws.pricing = r.pricing || null;
        ws.aiAvailable = r.ai_available !== false;
        ws.composerOpen = !ws.drafts.length;
        if (ws.active) ws.docType = ws.active.doc_type || "sop";
        if (!ws.form.intake && ws.defaults && ws.defaults.intake) ws.form.intake = ws.defaults.intake;
        ws.error = null;
      } catch (ex) {
        ws.error = ex.message;
        ws.drafts = ws.drafts || [];
      } finally {
        ws.loading = false;
        if (body.isConnected && $("#wsWrap")) drawWriting();
      }
    }

    function wsField(name, value) { ws.form[name] = value; }

    async function openWritingDraft(id, opts) {
      const keepOpen = opts && opts.keepComposer;
      const summary = (ws.drafts || []).find((d) => d.id === id || d.root_id === id);
      // Fetching the chain gives us the full content AND the version list in one call.
      const rootId = summary ? summary.root_id : id;
      ws.loading = true;
      if (!keepOpen) ws.composerOpen = false;
      ws.refineOpen = false;
      drawWriting();
      try {
        const r = await api(`/clients/${cl.id}/writing/${rootId}/versions`);
        ws.versions = r.versions || [];
        ws.versionsRoot = rootId;
        ws.active = ws.versions.length ? ws.versions[ws.versions.length - 1] : null;
        if (ws.active) ws.docType = ws.active.doc_type || ws.docType;
      } catch (ex) {
        toast(ex.message, "error");
      } finally {
        ws.loading = false;
        if (body.isConnected && $("#wsWrap")) drawWriting();
      }
    }

    function wsShowVersion(id) {
      const v = (ws.versions || []).find((x) => x.id === id);
      if (v) { ws.active = v; drawWriting(); }
    }

    async function generateWritingNow() {
      if (ws.busy || writingInflight.has(cl.id)) return;
      const isLor = ws.docType === "lor";
      const f = ws.form;
      if (isLor && !(f.recommender_name || "").trim()) {
        toast("Add the recommender's name — the letter is written in their voice.", "error");
        return;
      }
      if (!isLor && !(f.university || "").trim() && !(f.program || "").trim()) {
        toast("Add the target university or program first.", "error");
        return;
      }
      ws.busy = true;
      writingInflight.add(cl.id);
      drawWriting();
      const stop = wsProgressTicker("wsGenerateBtn", isLor ? "Drafting the letter" : "Drafting the statement");
      try {
        const payload = {
          doc_type: ws.docType,
          university: f.university || null,
          program: f.program || null,
          study_level: f.study_level || null,
          intake: f.intake || null,
          brief: f.brief || null,
        };
        if (isLor) {
          payload.recommender_type = f.recommender_type || "professor";
          payload.recommender_name = f.recommender_name || null;
          payload.recommender_title = f.recommender_title || null;
          payload.recommender_org = f.recommender_org || null;
          payload.recommender_email = f.recommender_email || null;
          payload.relationship_context = f.relationship_context || null;
        }
        const r = await api(`/clients/${cl.id}/writing/generate`, {
          method: "POST", body: payload, timeout: WRITING_API_TIMEOUT_MS,
        });
        if (r.wallet) { state.credits = r.wallet; updatePlanChip(); }
        if (r.pricing) ws.pricing = r.pricing;
        ws.active = r.draft;
        ws.versions = [r.draft];
        ws.versionsRoot = r.draft.root_id;
        ws.drafts = [{ ...r.draft, content_md: undefined, notes_md: undefined }, ...(ws.drafts || [])];
        ws.composerOpen = false;
        ws.form.brief = "";
        toast(`Draft ready · ${r.credits_charged} ${r.credits_charged === 1 ? "credit" : "credits"} used`, "success");
      } catch (ex) {
        toast(ex.message, "error");
      } finally {
        stop();
        ws.busy = false;
        writingInflight.delete(cl.id);
        if (!body.isConnected) { writingDirty.add(cl.id); return; }
        drawWriting();
      }
    }

    async function refineWritingNow() {
      if (ws.busy || writingInflight.has(cl.id)) return;
      const instruction = (ws.refineText || "").trim();
      if (instruction.length < 3) { toast("Describe the revision you want.", "error"); return; }
      if (!ws.active) return;
      ws.busy = true;
      writingInflight.add(cl.id);
      drawWriting();
      const stop = wsProgressTicker("wsRefineBtn", "Revising");
      try {
        const r = await api(`/clients/${cl.id}/writing/${ws.active.root_id}/refine`, {
          method: "POST", body: { instruction }, timeout: WRITING_API_TIMEOUT_MS,
        });
        if (r.wallet) { state.credits = r.wallet; updatePlanChip(); }
        if (r.pricing) ws.pricing = r.pricing;
        ws.active = r.draft;
        ws.versions = [...(ws.versions || []), r.draft];
        ws.drafts = (ws.drafts || []).map((d) =>
          d.root_id === r.draft.root_id ? { ...r.draft, content_md: undefined, notes_md: undefined } : d);
        ws.refineOpen = false;
        ws.refineText = "";
        toast(`Version ${r.draft.version} ready · ${r.credits_charged} ${r.credits_charged === 1 ? "credit" : "credits"} used`, "success");
      } catch (ex) {
        toast(ex.message, "error");
      } finally {
        stop();
        ws.busy = false;
        writingInflight.delete(cl.id);
        if (!body.isConnected) { writingDirty.add(cl.id); return; }
        drawWriting();
      }
    }

    async function downloadWritingDocx(draftId) {
      const btn = $("#wsDownloadBtn");
      const label = btn ? btn.innerHTML : "";
      if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Building…'; }
      try {
        await downloadFile(`${API}/clients/${cl.id}/writing/${draftId}/docx`);
        toast("Word document downloaded", "success");
      } catch (ex) {
        toast(ex.message, "error");
      } finally {
        if (btn && btn.isConnected) { btn.disabled = false; btn.innerHTML = label; }
      }
    }

    async function deleteWritingDraft(rootId) {
      const ok = await confirmModal(
        "Delete this document and every version of it? The credits already spent on it can't be recovered.",
        { title: "Delete document", okText: "Delete" }
      );
      if (!ok) return;
      try {
        await api(`/clients/${cl.id}/writing/${rootId}`, { method: "DELETE" });
        ws.drafts = (ws.drafts || []).filter((d) => d.root_id !== rootId);
        if (ws.active && ws.active.root_id === rootId) { ws.active = null; ws.versions = null; }
        ws.composerOpen = !ws.drafts.length;
        toast("Document deleted", "success");
        drawWriting();
      } catch (ex) { toast(ex.message, "error"); }
    }

    function wsComposerHtml() {
      const isLor = ws.docType === "lor";
      const first = (cl.full_name || "the student").split(" ")[0];
      const cost = (ws.pricing && ws.pricing.cost_credits != null) ? ws.pricing.cost_credits
        : (((state.credits && (state.credits.actions || []).find((a) => a.key === "writing_studio")) || {}).credits || 1);
      const rTypes = (ws.catalog && ws.catalog.recommender_types) || [];
      const shortlist = (ws.defaults && ws.defaults.universities) || [];
      const docName = wsDocName(ws.docType);
      const running = ws.busy || writingInflight.has(cl.id);

      const tip = isLor
        ? `Rilono AI drafts the letter in the <b>recommender's</b> voice, grounded in ${esc(first)}'s dossier — case records, uploaded documents, shortlist and notes — and never invents a fact.<br><br>The export is a <b>draft for the recommender to review, edit and sign</b>, with that stated on its own final page. It is never a finished letter.<br><br>Costs <b>${cost} credit</b> per draft or revision. Re-downloading the Word file is free.`
        : `Rilono AI writes a ${esc(docName)} in ${esc(first)}'s own voice from their real dossier — case records, the contents of every uploaded document, university shortlist and counselor notes. Anything it can't evidence becomes a <b>[PLACEHOLDER]</b> for you to fill, never a guess.<br><br>Conventions follow the destination: a UK personal statement, a Canadian study plan and a German Motivationsschreiben are written differently.<br><br>Costs <b>${cost} credit</b> per draft or revision. Re-downloading the Word file is free.`;

      const shortlistPicker = shortlist.length ? `
        <label class="ws-lbl">Pick from ${esc(first)}'s shortlist
          <select class="ws-in" id="wsPick">
            <option value="">—</option>
            ${shortlist.map((u, i) => `<option value="${i}">${esc(u.university_name)}${
              u.program ? " · " + esc(u.program) : ""}${u.status ? " (" + esc(u.status) + ")" : ""}</option>`).join("")}
          </select>
        </label>` : "";

      const targetFields = `
        ${shortlistPicker}
        <label class="ws-lbl">Target university${isLor ? " (optional)" : ""}
          <input class="ws-in" id="wsUniversity" value="${esc(ws.form.university)}" placeholder="e.g. University of Toronto" maxlength="200">
        </label>
        <label class="ws-lbl">Program${isLor ? " (optional)" : ""}
          <input class="ws-in" id="wsProgram" value="${esc(ws.form.program)}" placeholder="e.g. MSc Computer Science" maxlength="200">
        </label>`;

      const sopFields = `
        <label class="ws-lbl">Study level
          <input class="ws-in" id="wsStudyLevel" value="${esc(ws.form.study_level)}" placeholder="e.g. Master's" maxlength="60">
        </label>
        <label class="ws-lbl">Intake
          <input class="ws-in" id="wsIntake" value="${esc(ws.form.intake)}" placeholder="e.g. Fall 2027" maxlength="60">
        </label>`;

      const lorFields = `
        <label class="ws-lbl"><span class="ws-cap">Recommender's name <span class="ws-req">required</span></span>
          <input class="ws-in" id="wsRecName" value="${esc(ws.form.recommender_name)}" placeholder="e.g. Dr. Anita Sharma" maxlength="160">
        </label>
        <label class="ws-lbl">Who are they to ${esc(first)}?
          <select class="ws-in" id="wsRecType">
            ${rTypes.map((t) => `<option value="${esc(t.key)}"${
              t.key === ws.form.recommender_type ? " selected" : ""}>${esc(t.label)}</option>`).join("")}
          </select>
        </label>
        <label class="ws-lbl">Their title / role
          <input class="ws-in" id="wsRecTitle" value="${esc(ws.form.recommender_title)}" placeholder="e.g. Associate Professor, Dept. of Physics" maxlength="160">
        </label>
        <label class="ws-lbl">Their institution or company
          <input class="ws-in" id="wsRecOrg" value="${esc(ws.form.recommender_org)}" placeholder="e.g. University of Delhi" maxlength="200">
        </label>
        <label class="ws-lbl">Their email (printed on the letterhead)
          <input class="ws-in" id="wsRecEmail" type="email" value="${esc(ws.form.recommender_email)}" placeholder="name@university.edu" maxlength="254">
        </label>
        <label class="ws-lbl ws-lbl-wide">How do they know ${esc(first)}? Capacity, dates, the course or project
          <textarea class="ws-in ws-ta" id="wsRelationship" rows="3" maxlength="2000" placeholder="e.g. Taught her Thermodynamics (PHY-302) in 2025-26 and supervised her final-year project on solar absorber coatings.">${esc(ws.form.relationship_context)}</textarea>
        </label>`;

      const canAfford = !ws.pricing || ws.pricing.can_afford !== false;
      return `
        <div class="cp-card ws-card">
          <div class="ws-head">
            <div class="ws-title"><span class="ws-title-icon" aria-hidden="true">✍️</span> ${
              ws.drafts && ws.drafts.length ? "New document" : "Writing Studio"}${infoTip(tip, "How the Writing Studio works")}</div>
            ${ws.drafts && ws.drafts.length
              ? `<button class="btn btn-ghost btn-sm" id="wsComposerClose">Cancel</button>` : ""}
          </div>
          ${!ws.aiAvailable ? `<div class="ws-blocked"><b>Rilono AI isn't configured on this server yet.</b></div>` : ""}
          <div class="ws-seg" role="tablist">
            <button class="ws-seg-btn${ws.docType === "sop" ? " active" : ""}" data-doctype="sop" role="tab" aria-selected="${ws.docType === "sop"}">Statement of Purpose</button>
            <button class="ws-seg-btn${ws.docType === "lor" ? " active" : ""}" data-doctype="lor" role="tab" aria-selected="${ws.docType === "lor"}">Letter of Recommendation</button>
          </div>
          <div class="ws-doc-note">${esc(cl.destination_country_name)} convention · <b>${esc(docName)}</b></div>
          <div class="ws-grid">
            ${isLor ? lorFields + targetFields : targetFields + sopFields}
            <label class="ws-lbl ws-lbl-wide"><span class="ws-cap">What should this document emphasise? <span class="ws-opt">optional</span></span>
              <textarea class="ws-in ws-ta" id="wsBrief" rows="3" maxlength="4000" placeholder="${
                isLor ? "e.g. Lean on the research project, not grades. Mention she rebuilt the rig after it failed."
                      : "e.g. Lead with the 18 months at Infosys, address the one-year study gap honestly, keep it under 800 words."}">${esc(ws.form.brief)}</textarea>
            </label>
          </div>
          <div class="ws-actions">
            <button class="btn btn-primary" id="wsGenerateBtn" ${(!ws.aiAvailable || running || !canAfford) ? "disabled" : ""}>${
              running ? '<span class="spinner"></span> Drafting…' : `Draft with Rilono AI · ${cost} cr`}</button>
            ${!canAfford ? `<span class="ws-hint ws-hint-warn">Your wallet is empty — top up in Credits.</span>`
              : `<span class="ws-hint">Takes up to a minute. You're charged only if a draft comes back.</span>`}
          </div>
        </div>`;
    }

    function wsDraftListHtml() {
      if (!(ws.drafts || []).length) return "";
      return `
        <div class="cp-card">
          <div class="cp-sub-label">Documents</div>
          ${ws.drafts.map((d) => {
            const active = ws.active && ws.active.root_id === d.root_id;
            const target = [d.university, d.program].filter(Boolean).join(" · ");
            const who = d.doc_type === "lor" && d.recommender_name ? `for ${esc(d.recommender_name)}` : "";
            return `<div class="ws-hrow${active ? " active" : ""}" data-root="${d.root_id}">
              <span class="ws-badge ${d.doc_type === "lor" ? "lor" : "sop"}">${d.doc_type === "lor" ? "LOR" : "SOP"}</span>
              <div class="ws-hmain">
                <b>${esc(target || d.doc_name || "Document")}</b>
                <span>${who ? who + " · " : ""}v${d.version} · ${d.word_count || 0} words${
                  d.created_by_name ? " · " + esc(d.created_by_name) : ""} · ${fmtDate(d.created_at)}</span>
              </div>
              <span class="ws-hcr">${d.credits_charged ? d.credits_charged + " cr" : ""}</span>
            </div>`;
          }).join("")}
        </div>`;
    }

    function wsReaderHtml() {
      const d = ws.active;
      if (!d) return "";
      const isLor = d.doc_type === "lor";
      const target = [d.university, d.program].filter(Boolean).join(" · ");
      const versions = ws.versions || [];
      const running = ws.busy || writingInflight.has(cl.id);
      const chips = isLor
        ? ["Add a stronger cohort comparison", "Be more specific about the project", "Shorten it to one page", "Make the tone more restrained"]
        : ["Make it more technical", "Tighten it to the word limit", "Strengthen why this university", "Make the opening more specific"];

      const notice = isLor ? `
        <div class="ws-notice">
          <span class="ws-notice-ic" aria-hidden="true">✋</span>
          <div><b>This is a draft for ${esc(d.recommender_name || "the recommender")} to review and sign.</b>
          Send it to them to verify, edit into their own words and sign on their letterhead — the Word file says so on its final page. Never submit it as it stands.</div>
        </div>` : "";

      const versionBar = versions.length > 1 ? `
        <div class="ws-versions">
          ${versions.map((v) => `<button class="ws-vbtn${v.id === d.id ? " active" : ""}" data-version="${v.id}" title="${
            v.instruction ? esc(v.instruction) : "Original draft"}">v${v.version}</button>`).join("")}
          ${d.instruction ? `<span class="ws-vnote">“${esc(d.instruction)}”</span>` : `<span class="ws-vnote">Original draft</span>`}
        </div>` : "";

      const refine = ws.refineOpen ? `
        <div class="ws-refine">
          <div class="ws-refine-chips">${chips.map((c) =>
            `<button class="ws-chip" data-chip="${esc(c)}">${esc(c)}</button>`).join("")}</div>
          <textarea class="ws-in ws-ta" id="wsRefineText" rows="2" maxlength="1000"
            placeholder="What should change? e.g. “Cut the second paragraph and expand the internship instead.”">${esc(ws.refineText)}</textarea>
          <div class="ws-actions">
            <button class="btn btn-primary btn-sm" id="wsRefineBtn" ${running ? "disabled" : ""}>${
              running ? '<span class="spinner"></span> Revising…' : `Revise · ${
                (ws.pricing && ws.pricing.cost_credits) || 1} cr`}</button>
            <button class="btn btn-ghost btn-sm" id="wsRefineCancel">Cancel</button>
          </div>
        </div>` : "";

      return `
        <div class="cp-card ws-reader">
          <div class="ws-rhead">
            <div>
              <div class="ws-rtitle">${esc(d.doc_name || (isLor ? "Letter of Recommendation" : "Statement of Purpose"))}</div>
              <div class="ws-rmeta">${esc(cl.full_name)}${target ? " · " + esc(target) : ""} · ${d.word_count || 0} words · v${d.version}</div>
            </div>
            <div class="ws-rbtns">
              <button class="btn btn-primary btn-sm" id="wsDownloadBtn">⬇ Download Word</button>
              ${canWritingAi ? `<button class="btn btn-soft btn-sm" id="wsRefineOpen" ${running ? "disabled" : ""}>Refine</button>` : ""}
              <button class="btn btn-ghost btn-sm" id="wsCopyBtn">Copy text</button>
              ${canWritingAi ? `<button class="btn btn-ghost btn-sm ws-del" id="wsDeleteBtn">Delete</button>` : ""}
            </div>
          </div>
          ${notice}
          ${versionBar}
          ${refine}
          <div class="ws-paper">${wsMarkdownToHtml(d.content_md)}</div>
          ${(d.notes_md || "").trim() ? `
            <div class="ws-notes">
              <div class="ws-notes-head">Rilono notes — finish these before it goes out</div>
              ${wsMarkdownToHtml(d.notes_md)}
            </div>` : ""}
        </div>`;
    }

    function drawWriting() {
      const wrap = $("#wsWrap");
      if (!wrap || !body.isConnected) return;
      // A live generation owns this tree (ticking button) — repainting now would orphan
      // it. generateWritingNow/refineWritingNow always redraw when the request settles.
      const running = ws.busy;
      if (ws.loading && !running) {
        wrap.innerHTML = `<div class="cp-card"><div class="center-load"><div class="spinner dark"></div></div></div>`;
        return;
      }
      const first = (cl.full_name || "the student").split(" ")[0];
      const composer = (ws.composerOpen || running) ? wsComposerHtml() : `
        <div class="cp-card ws-newbar">
          <div class="ws-title"><span class="ws-title-icon" aria-hidden="true">✍️</span> Writing Studio</div>
          ${canWritingAi ? `<button class="btn btn-primary btn-sm" id="wsNewBtn">+ New SOP or LOR</button>` : ""}
        </div>`;
      const empty = (!ws.active && !ws.composerOpen && !running) ? `
        <div class="cp-card"><div class="empty" style="padding:30px"><div class="emoji">✍️</div>
          <h3>${ws.error ? "Couldn't load the Writing Studio" : "No documents yet"}</h3>
          <p>${ws.error ? esc(ws.error)
            : canWritingAi ? `Draft ${esc(first)}'s statement of purpose or a letter of recommendation.`
                      : "No documents have been drafted for this client yet."}</p>
          ${ws.error ? `<button class="btn btn-soft btn-sm" id="wsRetryBtn" style="margin-top:10px">Retry</button>` : ""}</div></div>` : "";

      wrap.innerHTML = composer + empty + wsReaderHtml() + wsDraftListHtml();
      wireWriting();
    }

    function wireWriting() {
      const wrap = $("#wsWrap");
      if (!wrap) return;
      // Composer
      $$(".ws-seg-btn", wrap).forEach((b) => b.onclick = () => {
        ws.docType = b.dataset.doctype; drawWriting();
      });
      const bind = (sel, name) => {
        const el = $(sel, wrap);
        if (el) el.oninput = () => wsField(name, el.value);
      };
      bind("#wsUniversity", "university");
      bind("#wsProgram", "program");
      bind("#wsStudyLevel", "study_level");
      bind("#wsIntake", "intake");
      bind("#wsBrief", "brief");
      bind("#wsRecName", "recommender_name");
      bind("#wsRecTitle", "recommender_title");
      bind("#wsRecOrg", "recommender_org");
      bind("#wsRecEmail", "recommender_email");
      bind("#wsRelationship", "relationship_context");
      const recType = $("#wsRecType", wrap);
      if (recType) recType.onchange = () => {
        wsField("recommender_type", recType.value);
        // Prefill the title from the archetype only while the counselor hasn't typed one.
        const t = ((ws.catalog && ws.catalog.recommender_types) || []).find((x) => x.key === recType.value);
        const titleEl = $("#wsRecTitle", wrap);
        if (t && titleEl && !titleEl.value.trim()) {
          titleEl.value = t.default_title || "";
          wsField("recommender_title", titleEl.value);
        }
      };
      const pick = $("#wsPick", wrap);
      if (pick) pick.onchange = () => {
        const u = ((ws.defaults && ws.defaults.universities) || [])[Number(pick.value)];
        if (!u) return;
        const uEl = $("#wsUniversity", wrap), pEl = $("#wsProgram", wrap);
        if (uEl) { uEl.value = u.university_name || ""; wsField("university", uEl.value); }
        if (pEl) { pEl.value = u.program || ""; wsField("program", pEl.value); }
        if (gen && gen._syncValid) gen._syncValid();   // .value assignments fire no event
      };
      const gen = $("#wsGenerateBtn", wrap);
      // Adds the two checks the handler only made as post-click toasts — an LOR is written
      // in the recommender's voice, so their name is required; an SOP needs a target, and
      // either the university or the programme will do. The AI-availability and wallet terms
      // are re-stated here because bindValidity owns .disabled from now on and would
      // otherwise re-enable a button the markup had deliberately killed.
      if (gen) bindValidity(gen, wrap, () => {
        if (!ws.aiAvailable || ws.busy || writingInflight.has(cl.id)) return false;
        if (ws.pricing && ws.pricing.can_afford === false) return false;
        return ws.docType === "lor"
          ? (ws.form.recommender_name || "").trim() !== ""
          : ((ws.form.university || "").trim() !== "" || (ws.form.program || "").trim() !== "");
      }, ws.docType === "lor" ? "Add the recommender's name first" : "Add the target university or program first");
      if (gen) gen.onclick = generateWritingNow;
      const close = $("#wsComposerClose", wrap);
      if (close) close.onclick = () => { ws.composerOpen = false; drawWriting(); };
      const newBtn = $("#wsNewBtn", wrap);
      if (newBtn) newBtn.onclick = () => { ws.composerOpen = true; drawWriting(); };
      const retry = $("#wsRetryBtn", wrap);
      if (retry) retry.onclick = () => { ws.error = null; ws.loading = true; drawWriting(); loadWriting(); };

      // Reader
      const dl = $("#wsDownloadBtn", wrap);
      if (dl && ws.active) dl.onclick = () => downloadWritingDocx(ws.active.id);
      const del = $("#wsDeleteBtn", wrap);
      // Locked from the first click rather than via withBusy: deleteWritingDraft opens its
      // own confirm, and a spinner labelled "Deleting…" while the dialog still asks "are you
      // sure?" would be a lie. Disabling alone stops a second click stacking a second dialog.
      if (del && ws.active) del.onclick = async () => {
        if (del.disabled) return;
        del.disabled = true;
        try { await deleteWritingDraft(ws.active.root_id); }
        finally { if (del.isConnected) del.disabled = false; }
      };
      const copy = $("#wsCopyBtn", wrap);
      if (copy && ws.active) copy.onclick = () => {
        const plain = String(ws.active.content_md || "").replace(/^#+\s*/gm, "").replace(/\*\*/g, "");
        navigator.clipboard.writeText(plain).then(
          () => toast("Copied to clipboard", "success"),
          () => toast("Couldn't copy — select the text instead.", "error"));
      };
      const refOpen = $("#wsRefineOpen", wrap);
      if (refOpen) refOpen.onclick = () => { ws.refineOpen = true; drawWriting(); };
      const refCancel = $("#wsRefineCancel", wrap);
      if (refCancel) refCancel.onclick = () => { ws.refineOpen = false; ws.refineText = ""; drawWriting(); };
      const refText = $("#wsRefineText", wrap);
      const refBtn = $("#wsRefineBtn", wrap);
      if (refText) refText.oninput = () => { ws.refineText = refText.value; if (refBtn && refBtn._syncValid) refBtn._syncValid(); };
      // Mirrors the handler's own "Describe the revision you want." check.
      if (refBtn) bindValidity(refBtn, wrap,
        () => !(ws.busy || writingInflight.has(cl.id)) && (ws.refineText || "").trim().length >= 3,
        "Describe the revision you want");
      if (refBtn) refBtn.onclick = refineWritingNow;
      $$(".ws-chip", wrap).forEach((c) => c.onclick = () => {
        ws.refineText = c.dataset.chip;
        const t = $("#wsRefineText", wrap);
        if (t) { t.value = ws.refineText; t.focus(); }
        if (refBtn && refBtn._syncValid) refBtn._syncValid();   // chip fills it in code, no event
      });
      $$(".ws-vbtn", wrap).forEach((b) => b.onclick = () => wsShowVersion(Number(b.dataset.version)));
      $$(".ws-hrow", wrap).forEach((r) => r.onclick = () => openWritingDraft(Number(r.dataset.root)));
    }

    function renderWriting() {
      body.innerHTML = `<div id="wsWrap"></div>`;
      if (ws.busy) {
        // Tabbed back mid-generation (same closure): hold, then the settling request redraws.
        $("#wsWrap").innerHTML = `<div class="cp-card"><div class="center-load"><div class="spinner dark"></div></div>
          <p class="muted" style="text-align:center;margin:0 0 14px">Rilono AI is writing — this takes up to a minute…</p></div>`;
        return;
      }
      // A draft from a previous render of this client settled after its DOM was replaced.
      if (writingDirty.has(cl.id)) { writingDirty.delete(cl.id); ws.drafts = null; ws.active = null; ws.versions = null; }
      if (ws.drafts === null && !ws.loading) { ws.loading = true; loadWriting(); }
      drawWriting();
    }

    function wsDocName(docType) {
      const names = (ws.catalog && ws.catalog.doc_names) || {};
      const forCountry = names[(cl.country && cl.country.code) || cl.destination_country_code || "US"] || {};
      return forCountry[docType] || (docType === "lor" ? "Letter of Recommendation" : "Statement of Purpose");
    }

    function showTab(tab) {
      $$(".cp-tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
      if (tab !== "interview") ivStopSpeak();
      if (tab === "overview") renderOverview();
      else if (tab === "documents") renderDocs();
      else if (tab === "notes") renderNotes();
      else if (tab === "emails") renderEmails();
      else if (tab === "payments") renderPayments();
      else if (tab === "universities") renderUniversities();
      else if (tab === "interview") renderInterview();
      else if (tab === "copilot") renderCopilot();
      else if (tab === "writing") renderWriting();
      else if (tab === "deepscan") renderDeepScan();
    }
    $$(".cp-tab").forEach((t) => t.onclick = () => showTab(t.dataset.tab));
    showTab("overview");
  }

  // Deep Scan cross-render state: renderClientPage re-runs (status change, edit save)
  // mint a fresh `ds` closure, so a scan still running in an OLD closure must stay
  // visible to the new one. `deepScanInflight` blocks a double-run (and double-charge)
  // per client; `deepScanDirty` tells the next renderDeepScan to refetch because a scan
  // settled while its closure's DOM was already replaced.
  const deepScanInflight = new Set();
  const deepScanDirty = new Set();

  // Same cross-render guards for the Writing Studio: one generation per client at a time
  // (so a stray second click can't double-charge), and a dirty flag so a draft that lands
  // after its closure's DOM was replaced is refetched by the next render.
  const writingInflight = new Set();
  const writingDirty = new Set();

  /* Escalating button label for the 20-60s writing calls, so the wait reads as progress
     rather than a stuck spinner. Returns stop(); call it in a finally block. */
  function wsProgressTicker(buttonId, baseLabel) {
    const startedAt = Date.now();
    const paint = () => {
      const btn = document.getElementById(buttonId);
      if (!btn) return;
      const s = Math.round((Date.now() - startedAt) / 1000);
      const label = s < 8 ? `${baseLabel}…` : s < 25 ? `${baseLabel}… · ${s}s` : `Still writing… ${s}s`;
      btn.innerHTML = `<span class="spinner"></span> ${esc(label)}`;
    };
    const timer = setInterval(paint, 1000);
    return () => clearInterval(timer);
  }

  // Letter conventions that must stay on their own line — mirrors the same guard in
  // app/enterprise_writing.py so the on-screen document matches the exported Word file.
  const WS_SALUTATION_RE = /^(dear\b.{0,80}|to whom it may concern)[,:]?$/i;
  const WS_SIGNOFF_RE = /^(sincerely|yours sincerely|yours faithfully|yours truly|respectfully|respectfully yours|kind regards|warm regards|best regards|regards|mit freundlichen grüßen)[,.]?$/i;

  /* Render the restrained Markdown the writing prompts ask for: paragraphs, headings,
     bullets, **bold**, --- rules. Everything is escaped first and only known structure is
     re-introduced, so AI text can never inject markup. [PLACEHOLDER: …] is highlighted —
     it's the one thing the counselor must act on before the document goes out. */
  function wsMarkdownToHtml(md) {
    const escaped = esc(String(md || ""));
    const inline = (s) => s
      .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
      .replace(/\[PLACEHOLDER:([^\]]*)\]/gi, '<span class="ws-ph">[PLACEHOLDER:$1]</span>');
    const out = [];
    escaped.split(/\n\s*\n/).forEach((rawBlock) => {
      const block = rawBlock.trim();
      if (!block) return;
      if (/^(-{3,}|\*{3,}|_{3,})$/.test(block)) { out.push('<hr class="ws-hr">'); return; }
      let pending = [];
      const flush = () => {
        if (!pending.length) return;
        out.push(`<p>${inline(pending.join(" "))}</p>`);
        pending = [];
      };
      block.split("\n").forEach((raw) => {
        const line = raw.trim();
        if (!line) return;
        const heading = /^#{1,6}\s+(.*)$/.exec(line);
        if (heading) { flush(); out.push(`<h4>${inline(heading[1])}</h4>`); return; }
        const item = /^(?:[-*•]|\d+[.)])\s+(.*)$/.exec(line);
        if (item) { flush(); out.push(`<li>${inline(item[1])}</li>`); return; }
        if (WS_SALUTATION_RE.test(line) || WS_SIGNOFF_RE.test(line)) {
          flush(); out.push(`<p class="ws-line">${inline(line)}</p>`); return;
        }
        pending.push(line);
      });
      flush();
    });
    // Wrap each run of consecutive list items in a single <ul>.
    return out.join("").replace(/(?:<li>[\s\S]*?<\/li>)+/g, (m) => `<ul>${m}</ul>`);
  }

  // Set by the Universities tab so these inline-onclick handlers can redraw it, and redraw
  // the journey stepper the shortlist feeds.
  let _uniRefresh = null;
  let _uniStageSync = null;

  // One in-flight row action per shortlist entry. Both handlers below reach _uniStageSync,
  // which can open its own confirm dialog and move the client's journey stage — so a status
  // change racing a delete on the same row is not just a wasted request, it is two stage
  // moves from one intent. Keyed by entry so unrelated rows stay independent.
  const _uniBusy = new Set();

  async function setUniStatus(clientId, entryId, status, el) {
    if (_uniBusy.has(entryId)) return;
    _uniBusy.add(entryId);
    if (el) el.disabled = true;
    try {
      await api(`/clients/${clientId}/universities/${entryId}`, { method: "PATCH", body: { status } });
      if (_uniRefresh) await _uniRefresh();
      if (_uniStageSync) await _uniStageSync(clientId, status);
    } catch (ex) { toast(ex.message, "error"); }
    finally {
      _uniBusy.delete(entryId);
      // _uniRefresh() repaints the row, so on the happy path this node is already detached.
      if (el && el.isConnected) el.disabled = false;
    }
  }

  async function removeUni(clientId, entryId, el) {
    if (_uniBusy.has(entryId)) return;
    // Claimed before the confirm: confirmModal closes before it resolves and this ✕ lives in
    // the page, so otherwise a second click could open a second dialog for the same row.
    _uniBusy.add(entryId);
    if (el) el.disabled = true;
    try {
      const ok = await confirmModal("Remove this university from the shortlist?", {
        title: "Remove university", okText: "Remove",
      });
      if (!ok) return;
      await api(`/clients/${clientId}/universities/${entryId}`, { method: "DELETE" });
      toast("Removed from shortlist", "success");
      if (_uniRefresh) await _uniRefresh();
      if (_uniStageSync) await _uniStageSync(clientId, null);
    } catch (ex) { toast(ex.message, "error"); }
    finally {
      _uniBusy.delete(entryId);
      if (el && el.isConnected) el.disabled = false;
    }
  }

  async function setStatus(id, status) {
    try {
      await api(`/clients/${id}/status`, { method: "PATCH", body: { status } });
      toast("Status updated", "success");
      if (state.view === "clientPage" && state.activeClient === id) {
        const data = await api("/clients/" + id); renderClientPage(data);
      } else if (state.view === "clients") loadAndRenderClientList();
    } catch (ex) { toast(ex.message, "error"); }
  }
  async function editClient(id) {
    // Always refetch: state.clients is only refreshed by the list view, and the form now
    // submits every field — so prefilling from a stale snapshot would blank whatever was
    // written since (an in-pane edit, or the AI's passport auto-fill).
    const cl = (await api("/clients/" + id)).client;
    await ensureTeam();
    openClientForm(cl);
  }
  // Executes the delete. The ONLY UI path here is the type-to-confirm "Danger zone"
  // inside Edit details — there is deliberately no one-click delete control. Throws on
  // failure so the caller can surface the error; navigates away on success.
  async function deleteClient(id) {
    await api("/clients/" + id, { method: "DELETE" });
    toast("Client deleted", "success");
    if (state.view === "clientPage") navigate(state.clientReturnView || "clients");
    else loadAndRenderClientList();
  }

  /* ============================================================
     TEAM
     ============================================================ */
  let teamMembersCache = null;
  async function ensureTeam() {
    if (teamMembersCache) return teamMembersCache;
    try { const d = await api("/team"); teamMembersCache = d.members; applyAccessPayload(d); return d.members; }
    catch (e) { teamMembersCache = []; return []; }
  }

  /* ---- Team is five jobs, so it is five sub-tabs -------------------------------------
     Members (anyone who can see the team) · Roles & permissions (roles.manage) ·
     Offices (branches.view) · Access log (audit.view) · My access (everyone, always).
     Deliberately sub-tabs and not sidebar entries: the sidebar is the workspace's map,
     and "who may do what" is one destination on it, not four.
     The active tab travels in ?tab= so a link to it survives a refresh. */
  const TEAM_TABS = [
    { key: "members", ic: "👥", label: "Members", cap: null },
    { key: "roles", ic: "🔐", label: "Roles &amp; permissions", cap: "roles.manage" },
    { key: "branches", ic: "🏢", label: "Offices", cap: "branches.view" },
    { key: "log", ic: "📜", label: "Access log", cap: "audit.view" },
    { key: "myaccess", ic: "🪪", label: "My access", cap: null },
  ];
  /* Row-menu actions lock on the (action, member) pair rather than on the button: the menu
     is closed the instant it is clicked, but the user can reopen it and click again while
     the request is still in flight, and the row is only re-rendered once it returns — so by
     then the button is a different node and a per-element guard would have been thrown away.
     Only mutating actions are held; the modal-openers are read-only and idempotent. */
  const tmActionInflight = new Set();
  const TM_MUTATING_ACTS = new Set(["resend", "deactivate", "reactivate", "remove"]);

  const teamUi = {
    tab: "members",
    meta: null, metaError: null,
    team: null, teamError: null,
    includeInactive: false,
    filters: { q: "", role: "", branch: "", status: "" },
    selected: new Set(),
    branchList: null, branchError: null, showArchivedBranches: false,
    log: {
      rows: [], total: 0, hasMore: false, loading: false, error: null, loaded: false,
      filters: { action: "", target_user_id: "", days: "30" },
    },
    mine: null, mineError: null,
  };
  let teamPendingTab = null;

  function teamVisibleTabs() { return TEAM_TABS.filter((t) => !t.cap || can(t.cap)); }
  // Called from navigate() BEFORE syncUrl rewrites the address bar, which is the only
  // moment ?tab= is still readable.
  function teamConsumeTab() {
    const tabs = teamVisibleTabs();
    let want = teamPendingTab;
    teamPendingTab = null;
    if (!want) { try { want = new URLSearchParams(location.search).get("tab"); } catch (e) { want = null; } }
    if (want && tabs.some((t) => t.key === want)) teamUi.tab = want;
    if (!tabs.some((t) => t.key === teamUi.tab)) teamUi.tab = (tabs[0] || TEAM_TABS[0]).key;
  }
  function teamGoTab(key) { teamPendingTab = key; navigate("team"); }
  function tmSelfId() { return (state.me && state.me.user && state.me.user.id) || null; }
  function tmMemberById(uid) {
    return ((teamUi.team || {}).members || []).find((m) => m.user_id === uid) || null;
  }
  function tmMount() { return $("#tmPanel"); }
  function tmLoadingInto(mount) {
    if (mount) mount.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
  }
  // Nothing in this section can be drawn without /team/meta (it carries the capability
  // registry, the role presets and the office list).
  function tmMetaReady(mount) {
    if (teamUi.metaError) { mount.innerHTML = errBox(teamUi.metaError); return false; }
    if (!teamUi.meta) { tmLoadingInto(mount); return false; }
    return true;
  }
  function tmActorCaps() {
    const a = (teamUi.meta || {}).actor_capabilities;
    if (!Array.isArray(a) || a.indexOf("*") !== -1) return null;    // owner: everything
    return a;
  }
  function tmIsOwner() { return !!(state.access && state.access.is_owner); }

  async function renderTeam() {
    teamUi.selected = new Set();
    const c = $("#content");
    c.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
    if (!teamUi.meta && !teamUi.metaError) {
      try {
        teamUi.meta = await api("/team/meta");
        if (teamUi.meta && teamUi.meta.me) applyAccessPayload({ access: teamUi.meta.me });
      } catch (ex) { teamUi.metaError = ex; }
    }
    if (state.view !== "team") return;
    teamConsumeTab();
    teamDrawShell();
    teamDrawPanel();
  }
  // Re-fetch everything this section shows. Called after any mutation so counts, badges
  // and the office list can never disagree with what was just changed.
  async function teamRefresh() {
    teamUi.meta = null; teamUi.metaError = null;
    teamUi.team = null; teamUi.teamError = null;
    teamUi.branchList = null; teamUi.branchError = null;
    teamUi.log.loaded = false; teamUi.log.rows = []; teamUi.log.total = 0;
    teamUi.mine = null; teamUi.mineError = null;
    teamMembersCache = null;
    await renderTeam();
  }

  function teamTabCount(key) {
    const meta = teamUi.meta || {};
    if (key === "members") {
      const n = (teamUi.team && teamUi.team.members) ? teamUi.team.members.length : (meta.seats && meta.seats.used);
      return n ? `<b>${n}</b>` : "";
    }
    if (key === "branches") {
      const n = (meta.branches || []).filter((b) => b.is_active !== false).length;
      return n ? `<b>${n}</b>` : "";
    }
    if (key === "roles") {
      const n = (meta.custom_roles || []).filter((r) => r.is_active !== false).length;
      return n ? `<b>${n}</b>` : "";
    }
    return "";
  }
  // A branch-scoped member with no office assigned can see nothing at all — say so
  // instead of letting them stare at empty lists.
  function teamScopeBanner() {
    const a = state.access || {};
    if (a.data_scope !== "branch" || (a.branch_ids || []).length) return "";
    return `<div class="tm-banner warn"><div class="tm-banner-ic">⚠️</div><div class="tm-banner-txt">
      <b>You're not assigned to an office yet.</b>
      <span>Your access is limited to your own office, but you haven't been added to one — so no client records are in scope. Ask a workspace admin to add you to an office.</span>
    </div></div>`;
  }

  function teamDrawShell() {
    const c = $("#content");
    const tabs = teamVisibleTabs();
    // Switching tabs rebuilds this markup, which would drop keyboard focus onto <body> and
    // strand a keyboard user mid-tablist. Remember whether a tab had focus and give it back.
    const hadTabFocus = !!(document.activeElement && document.activeElement.classList &&
      document.activeElement.classList.contains("tm-tab"));
    c.innerHTML = `
      ${trialBanner()}
      ${teamScopeBanner()}
      <div class="tm-tabs" role="tablist" aria-label="Team sections">
        ${tabs.map((t) => `<button type="button" class="tm-tab" role="tab" data-tmtab="${t.key}"
          aria-selected="${teamUi.tab === t.key}" tabindex="${teamUi.tab === t.key ? "0" : "-1"}"><span class="ic">${t.ic}</span> ${t.label}${teamTabCount(t.key)}</button>`).join("")}
      </div>
      <div id="tmPanel" role="tabpanel"></div>`;
    $$(".tm-tab", c).forEach((b) => {
      b.onclick = () => {
        if (teamUi.tab === b.dataset.tmtab) return;
        teamUi.tab = b.dataset.tmtab;
        syncUrl("/enterprise/team?tab=" + teamUi.tab, { replace: true });
        teamDrawShell();
        teamDrawPanel();
      };
      // Same arrow-key behaviour as the Help & Support tabs.
      b.onkeydown = (e) => {
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
        e.preventDefault();
        const list = $$(".tm-tab");
        const i = list.indexOf(b);
        const next = list[(i + (e.key === "ArrowRight" ? 1 : list.length - 1)) % list.length];
        if (next) { next.focus(); next.click(); }
      };
    });
    if (hadTabFocus) {
      const active = $(`.tm-tab[data-tmtab="${teamUi.tab}"]`, c);
      if (active) active.focus();
    }
    tmWireMenuDismiss();
  }
  function teamDrawPanel() {
    const t = teamUi.tab;
    if (t === "roles") return tmDrawRoles();
    if (t === "branches") return tmDrawBranches();
    if (t === "log") return tmDrawLog();
    if (t === "myaccess") return tmDrawMyAccess();
    return tmDrawMembers();
  }

  /* ---------------- shared bits ---------------- */
  const RL_BADGE_CLASS = {
    owner: "owner", admin: "admin", branch_manager: "manager",
    counsellor: "counsellor", finance: "finance", viewer: "viewer", custom: "custom",
  };
  function roleBadgeHtml(roleKey, roleLabel) {
    const cls = RL_BADGE_CLASS[roleKey] || "custom";
    return `<span class="rl-badge ${cls}">${esc(roleLabel || roleKey || "Member")}</span>`;
  }
  const SCOPE_FALLBACK_LABEL = {
    all: "Entire workspace", branch: "Their office only", assigned: "Only their own clients",
  };
  function scopeMeta(key) {
    const list = ((teamUi.meta || {}).scopes) || [];
    return list.find((s) => s.key === key) || null;
  }
  function scopeChipHtml(scope, label) {
    const k = SCOPE_FALLBACK_LABEL[scope] ? scope : "assigned";
    const m = scopeMeta(k);
    return `<span class="tm-scope-chip" data-scope="${k}">${esc(label || (m && m.label) || SCOPE_FALLBACK_LABEL[k])}</span>`;
  }
  // Offices as chips, collapsed past three so a member in eight offices doesn't blow up
  // the row height.
  function branchChipsHtml(names, primaryName) {
    const list = (names || []).filter(Boolean);
    if (!list.length) return `<span class="tm-hint">—</span>`;
    const shown = list.slice(0, 3);
    const rest = list.length - shown.length;
    return `<span class="br-chips">${shown.map((n) =>
      `<span class="br-chip${primaryName && n === primaryName ? " is-primary" : ""}">${esc(n)}</span>`).join("")}${
      rest > 0 ? `<span class="br-chip more">+${rest}</span>` : ""}</span>`;
  }

  /* The ⋯ row menu. .tm-menu is position:fixed — an absolutely-positioned menu inside the
     table would be cropped by both .client-table's overflow:hidden and the wrapper's
     horizontal scroll — so its coordinates come from the trigger's own rect. */
  function tmCloseMenus() { $$(".tm-menu").forEach((m) => m.classList.add("hidden")); }
  let tmMenuDismissWired = false;
  function tmWireMenuDismiss() {
    if (tmMenuDismissWired) return;
    tmMenuDismissWired = true;
    document.addEventListener("click", (e) => {
      if (!(e.target.closest && e.target.closest(".tm-menu-wrap"))) tmCloseMenus();
    });
    window.addEventListener("scroll", tmCloseMenus, true);
    window.addEventListener("resize", tmCloseMenus);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") tmCloseMenus(); });
  }
  function tmPositionMenu(trigger, menu) {
    menu.classList.remove("hidden");
    const r = trigger.getBoundingClientRect();
    const w = menu.offsetWidth || 210;
    const h = menu.offsetHeight || 220;
    const left = Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8));
    let top = r.bottom + 6;
    if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 6);
    menu.style.left = left + "px";
    menu.style.top = top + "px";
  }

  /* ---- The capability matrix -------------------------------------------------------
     ONE component with three users: the member editor (tri-state Inherit / Allow / Block
     layered on whatever the role already grants), the role editor (Allowed / Not allowed)
     and My access (read-only). Rows the ACTOR does not hold itself are disabled — nobody
     hands out more than they have — and owner-only rows are omitted entirely for
     non-owners rather than dangled as a checkbox that always refuses. */
  function capMatrixHtml(selected, actorCaps, opts) {
    opts = opts || {};
    const mode = opts.mode || "override";
    const prefix = opts.idPrefix || "cap";
    const meta = teamUi.meta || {};
    const caps = meta.capabilities || [];
    if (!caps.length) return `<div class="tm-hint">The permission list isn't available right now.</div>`;
    const grants = new Set((selected && selected.grants) || []);
    const denies = new Set((selected && selected.denies) || []);
    const base = new Set((selected && selected.base) || []);
    const actor = actorCaps == null ? null : new Set(actorCaps);
    const actorHas = (k) => !actor || actor.has(k);
    // Owner-only capabilities (refunds, the payout account, transferring ownership) are
    // stripped from every non-owner by the resolution engine, so they can never be granted
    // to a member or written into a role — not even by the owner. Showing them in an editor
    // as three permanently-locked rows is dead UI, so they only appear where they're a
    // statement of fact: the read-only views.
    const showOwnerOnly = mode === "readonly" && !!opts.isOwner;

    const order = ((meta.sections || []).slice());
    caps.forEach((cp) => { if (order.indexOf(cp.section) === -1) order.push(cp.section); });

    let allowed = 0, total = 0;
    const body = order.map((sec) => {
      let secOn = 0, secTotal = 0;
      const rows = caps.filter((cp) => cp.section === sec && (showOwnerOnly || !cp.owner_only)).map((cp) => {
        const k = cp.key;
        const inherited = base.has(k);
        const isGrant = grants.has(k);
        const isDeny = denies.has(k);
        const on = mode === "role" ? isGrant : (isDeny ? false : (isGrant || inherited));
        total += 1; secTotal += 1;
        if (on) { allowed += 1; secOn += 1; }
        const locked = !actorHas(k);
        const held = isGrant || isDeny;
        const stateAttr = isDeny ? "block" : (on ? "allow" : "");
        // A locked row the subject ALREADY holds is echoed back on save (data-capheld),
        // because silently dropping it from a full-replacement payload would strip the
        // permission just because the editor can't grant it themselves.
        const keep = locked && held ? ' data-capheld="1"' : "";
        let control;
        if (mode === "readonly") {
          // The same three states read differently depending on whose access you're
          // looking at: "From your role" is only true on the My access tab.
          control = `<span class="cap-state" data-state="${stateAttr}">${
            isDeny ? "Blocked" : isGrant ? esc(opts.grantLabel || "Added for you")
              : inherited ? esc(opts.baseLabel || "From your role") : "Not allowed"}</span>`;
        } else if (mode === "role") {
          control = `<select class="cap-state" data-state="${stateAttr}" data-capsel="${esc(k)}"${locked ? " disabled" : ""}${keep}>
            <option value="" ${isGrant ? "" : "selected"}>Not allowed</option>
            <option value="allow" ${isGrant ? "selected" : ""}>Allowed</option>
          </select>`;
        } else {
          control = `<select class="cap-state" data-state="${stateAttr}" data-capsel="${esc(k)}"${locked ? " disabled" : ""}${keep}>
            <option value="" ${held ? "" : "selected"}>Inherit — ${inherited ? "allowed" : "not allowed"}</option>
            <option value="allow" ${isGrant ? "selected" : ""}>Allow</option>
            <option value="deny" ${isDeny ? "selected" : ""}>Block</option>
          </select>`;
        }
        // Exactly two grid children: the sentence, then the one control. The lock sits
        // beside the control rather than as a third child, which would wrap to its own row.
        const cell = locked
          ? `<span style="display:inline-flex;align-items:center;gap:8px">${control}<span class="cap-lock" title="You don't hold this permission yourself, so you can't grant it">🔒</span></span>`
          : control;
        return `<div class="cap-row${cp.dangerous ? " cap-danger" : ""}${locked ? " locked" : ""}" data-cap="${esc(k)}" data-capbase="${inherited ? "1" : "0"}">
          <div><b>${esc(cp.label)}</b>${cp.dangerous ? "<em>Sensitive</em>" : ""}<span>${esc(cp.desc || "")}</span></div>
          ${cell}
        </div>`;
      }).join("");
      return rows ? `<div class="cap-sec"><div class="cap-sec-h">${esc(sec)} <b>${secOn}/${secTotal}</b></div>${rows}</div>` : "";
    }).join("");

    return `<div class="cap-matrix" id="${esc(prefix)}Matrix" data-capmode="${esc(mode)}">${body}
      <div class="cap-summary"><b>${allowed}</b> of ${total} permissions allowed</div></div>`;
  }
  // Live count + the colour state on each row, recomputed on every change. The <select>
  // IS the .cap-state element, so its data-state attribute is what changes colour.
  function capMatrixWire(root) {
    const box = $(".cap-matrix", root);
    if (!box) return;
    const sum = $(".cap-summary", box);
    const rowIsOn = (row) => {
      const sel = $("[data-capsel]", row);
      if (!sel) {
        const st = $(".cap-state", row);
        return !!(st && st.dataset.state === "allow");
      }
      let on;
      if (sel.value === "allow") on = true;
      else if (sel.value === "deny") on = false;
      else on = row.dataset.capbase === "1";
      sel.dataset.state = sel.value === "deny" ? "block" : (on ? "allow" : "");
      return on;
    };
    const recount = () => {
      let allowed = 0, total = 0;
      // Per-section counts too — a stale "6/9" beside a section you just changed is
      // worse than no count at all.
      $$(".cap-sec", box).forEach((sec) => {
        let secOn = 0, secTotal = 0;
        $$(".cap-row", sec).forEach((row) => {
          secTotal += 1;
          if (rowIsOn(row)) secOn += 1;
        });
        allowed += secOn; total += secTotal;
        const badge = $(".cap-sec-h b", sec);
        if (badge) badge.textContent = secOn + "/" + secTotal;
      });
      if (sum) sum.innerHTML = `<b>${allowed}</b> of ${total} permissions allowed`;
    };
    $$("[data-capsel]", box).forEach((sel) => sel.onchange = recount);
    recount();
  }
  function readCapMatrix(root) {
    const grants = [], denies = [], capabilities = [];
    $$("[data-capsel]", root).forEach((sel) => {
      const k = sel.dataset.capsel;
      if (sel.disabled && sel.dataset.capheld !== "1") return;
      if (sel.value === "allow") { grants.push(k); capabilities.push(k); }
      else if (sel.value === "deny") denies.push(k);
    });
    return { grants: grants, denies: denies, capabilities: capabilities };
  }

  /* ---- role radios + scope radios + office picker, shared by invite / edit / bulk ---- */
  function tmAssignablePresets() {
    return ((teamUi.meta || {}).role_presets || [])
      .filter((r) => r.assignable !== false && r.key !== "owner" && r.key !== "custom");
  }
  function tmActiveCustomRoles() {
    return ((teamUi.meta || {}).custom_roles || []).filter((r) => r.is_active !== false);
  }
  function tmRoleChoiceValue(roleKey, customRoleId) {
    return (roleKey === "custom" && customRoleId) ? "custom:" + customRoleId : "preset:" + (roleKey || "viewer");
  }
  // Built from /team/meta, never from a hardcoded ["admin","editor","viewer"] — a
  // workspace's own roles have to be pickable or they may as well not exist.
  function tmRoleRadiosHtml(name, current) {
    const rows = [];
    const row = (val, label, desc, scope, scopeLocked, caps) =>
      `<label class="rl-row${current === val ? " selected" : ""}">
        <input type="radio" name="${esc(name)}" value="${esc(val)}" ${current === val ? "checked" : ""}
          data-scope="${esc(scope || "")}" data-scopelocked="${scopeLocked ? "1" : "0"}"
          data-caps="${esc(JSON.stringify(caps || []))}"/>
        <span><b>${esc(label)}</b><span>${esc(desc || "")}</span></span>
      </label>`;
    tmAssignablePresets().forEach((r) => {
      rows.push(row("preset:" + r.key, r.label, r.description, r.data_scope, r.scope_locked, r.capabilities));
    });
    const customs = tmActiveCustomRoles();
    if (customs.length) {
      rows.push(`<div class="cap-sec-h">Your workspace's own roles</div>`);
      customs.forEach((r) => {
        rows.push(row("custom:" + r.id, r.name, r.description, r.data_scope, false, r.capabilities));
      });
    }
    return `<div class="rl-list">${rows.join("")}</div>`;
  }
  function tmScopeRadiosHtml(name, current) {
    const list = ((teamUi.meta || {}).scopes) || [
      { key: "all", label: SCOPE_FALLBACK_LABEL.all, desc: "" },
      { key: "branch", label: SCOPE_FALLBACK_LABEL.branch, desc: "" },
      { key: "assigned", label: SCOPE_FALLBACK_LABEL.assigned, desc: "" },
    ];
    return `<div class="rl-list">${list.map((s) => `<label class="rl-row${current === s.key ? " selected" : ""}">
      <input type="radio" name="${esc(name)}" value="${esc(s.key)}" ${current === s.key ? "checked" : ""}/>
      <span><b>${esc(s.label)}</b><span>${esc(s.desc || "")}</span></span></label>`).join("")}</div>`;
  }
  function tmBranchPickerHtml(name, selectedIds, primaryId) {
    const list = ((teamUi.meta || {}).branches || []).filter((b) => b.is_active !== false);
    if (!list.length) {
      return `<div class="br-picker-empty">No offices yet — add one on the Offices tab first.</div>`;
    }
    const sel = new Set((selectedIds || []).map(Number));
    // .br-picker label puts its <span> on the right as the secondary meta, so the office
    // name is bare text and the city/code is the span.
    return `<div class="br-picker">${list.map((b) => `<label>
        <input type="checkbox" name="${esc(name)}" value="${b.id}" ${sel.has(Number(b.id)) ? "checked" : ""}/>
        ${esc(b.name)}${(b.city || b.code) ? `<span>${esc(b.city || b.code)}</span>` : ""}</label>`).join("")}</div>
      <div class="field" style="margin-top:10px"><label>Primary office</label>
        <select name="primary_branch_id"><option value="">— None —</option>
          ${list.map((b) => `<option value="${b.id}" ${Number(primaryId) === Number(b.id) ? "selected" : ""}>${esc(b.name)}</option>`).join("")}
        </select></div>`;
  }
  // Keeps the scope block honest as the role changes: a scope-locked preset (Owner, Admin)
  // has no choice to offer, and the office picker only matters at "their office only".
  function tmWireRoleScope(root, roleName, scopeName) {
    const sync = () => {
      const picked = $(`input[name="${roleName}"]:checked`, root);
      const scopeWrap = $("[data-scopewrap]", root);
      const branchWrap = $("[data-branchwrap]", root);
      const locked = picked && picked.dataset.scopelocked === "1";
      if (scopeWrap) {
        scopeWrap.classList.toggle("hidden", !!locked);
        if (locked && picked) {
          const hint = $("[data-scopelockedhint]", root);
          if (hint) hint.classList.remove("hidden");
        } else {
          const hint = $("[data-scopelockedhint]", root);
          if (hint) hint.classList.add("hidden");
        }
      }
      // Default the scope radios to the role's own default the first time a role is picked.
      if (!locked && picked && picked.dataset.scope) {
        const already = $(`input[name="${scopeName}"]:checked`, root);
        if (!already) {
          const target = $(`input[name="${scopeName}"][value="${picked.dataset.scope}"]`, root);
          if (target) target.checked = true;
        }
      }
      const scopeVal = (($(`input[name="${scopeName}"]:checked`, root) || {}).value) ||
        (picked && picked.dataset.scope) || "assigned";
      if (branchWrap) branchWrap.classList.toggle("hidden", locked || scopeVal !== "branch");
      $$(".rl-row", root).forEach((r) => {
        const input = $("input", r);
        r.classList.toggle("selected", !!(input && input.checked));
      });
    };
    $$(`input[name="${roleName}"]`, root).forEach((i) => i.onchange = sync);
    $$(`input[name="${scopeName}"]`, root).forEach((i) => i.onchange = sync);
    sync();
  }
  function tmReadBranchPicker(form, name) {
    return $$(`input[name="${name}"]:checked`, form).map((el) => parseInt(el.value, 10)).filter((n) => !isNaN(n));
  }

  /* ============================ MEMBERS ============================ */
  async function tmDrawMembers() {
    const mount = tmMount(); if (!mount) return;
    if (!tmMetaReady(mount)) return;
    if (!teamUi.team && !teamUi.teamError) {
      tmLoadingInto(mount);
      try {
        const qs = (teamUi.includeInactive && can("team.manage")) ? "?include_inactive=1" : "";
        const d = await api("/team" + qs);
        applyAccessPayload(d);
        teamUi.team = d;
        teamMembersCache = d.members;
      } catch (ex) { teamUi.teamError = ex; }
      if (state.view !== "team" || teamUi.tab !== "members") return;
      teamDrawShell();
    }
    const m2 = tmMount(); if (!m2) return;
    if (teamUi.teamError) { m2.innerHTML = errBox(teamUi.teamError); return; }
    tmPaintMembers();
  }

  function tmFilteredMembers() {
    const f = teamUi.filters;
    const q = (f.q || "").trim().toLowerCase();
    return ((teamUi.team || {}).members || []).filter((m) => {
      if (q) {
        const hay = ((m.full_name || "") + " " + (m.email || "") + " " + (m.job_title || "")).toLowerCase();
        if (hay.indexOf(q) === -1) return false;
      }
      if (f.role && String(m.role_key || "") !== f.role) return false;
      // "" = active only (and the server didn't send the rest), "all" = both,
      // "suspended" = only the deactivated ones. One control instead of a status filter
      // plus a redundant "show deactivated" checkbox that half-overlapped it.
      if (f.status !== "all") {
        const st = m.status || (m.is_active === false ? "suspended" : "active");
        if (f.status === "suspended" && st !== "suspended") return false;
        if (f.status === "" && st === "suspended") return false;
      }
      if (f.branch) {
        const ids = (m.branch_ids || []).map(String);
        if (String(m.primary_branch_id || "") !== f.branch && ids.indexOf(f.branch) === -1) return false;
      }
      return true;
    });
  }

  function tmPaintMembers() {
    const mount = tmMount(); if (!mount) return;
    // Repainting replaces the search box mid-typing — remember the caret so the filter
    // doesn't yank focus out from under the user. (Same idiom as the credit ledger.)
    const focused = document.activeElement;
    const keepCaret = focused && focused.id === "tmQ" ? focused.selectionStart : null;

    const meta = teamUi.meta || {};
    const d = teamUi.team || {};
    const rows = tmFilteredMembers();
    const canManage = can("team.manage");
    const canRoles = can("roles.manage");
    const selfId = tmSelfId();
    const branches = (meta.branches || []).filter((b) => b.is_active !== false);
    const filtered = !!(teamUi.filters.q || teamUi.filters.role || teamUi.filters.branch || teamUi.filters.status);
    const seats = meta.seats || {};

    const roleOpts = [`<option value="">All roles</option>`].concat(
      ((meta.role_presets || []).filter((r) => r.key !== "custom").map((r) =>
        `<option value="${esc(r.key)}" ${teamUi.filters.role === r.key ? "selected" : ""}>${esc(r.label)}</option>`)),
      tmActiveCustomRoles().length ? [`<option value="custom" ${teamUi.filters.role === "custom" ? "selected" : ""}>Custom roles</option>`] : []
    ).join("");

    const toolbar = `<div class="tm-toolbar">
      <input id="tmQ" class="tm-input" placeholder="Search name, email or job title…" value="${esc(teamUi.filters.q)}" autocomplete="off"/>
      <select id="tmRole" class="select-mini" aria-label="Filter by role">${roleOpts}</select>
      ${branches.length > 1 ? `<select id="tmBranch" class="select-mini" aria-label="Filter by office">
        <option value="">All offices</option>
        ${branches.map((b) => `<option value="${b.id}" ${teamUi.filters.branch === String(b.id) ? "selected" : ""}>${esc(b.name)}</option>`).join("")}
      </select>` : ""}
      ${canManage ? `<select id="tmStatus" class="select-mini" aria-label="Filter by status">
        <option value="">Active</option>
        <option value="all" ${teamUi.filters.status === "all" ? "selected" : ""}>Active + deactivated</option>
        <option value="suspended" ${teamUi.filters.status === "suspended" ? "selected" : ""}>Deactivated</option>
      </select>` : ""}
      ${filtered ? `<button class="btn btn-ghost btn-sm" id="tmClear">Clear</button>` : ""}
      <div class="spacer"></div>
      ${canManage ? `<button class="btn btn-primary btn-sm" id="tmInvite">+ Invite member</button>` : ""}
    </div>`;

    const body = rows.length ? rows.map((m) => {
      const suspended = (m.status === "suspended") || m.is_active === false;
      const isSelf = m.user_id === selfId;
      const [a1, a2] = avatarColor(m.email || m.full_name);
      const overrides = Number(m.override_count || ((m.capability_grants || []).length + (m.capability_denies || []).length));
      return `<tr data-tmrow="${m.user_id}">
        ${canManage ? `<td class="tm-pick"><input type="checkbox" class="tm-check" data-uid="${m.user_id}" ${
          teamUi.selected.has(m.user_id) ? "checked" : ""} ${isSelf ? "disabled" : ""} aria-label="Select ${esc(m.full_name || m.email)}"/></td>` : ""}
        <td><div class="tm-meta${suspended ? " is-off" : ""}">
          <div class="tm-av${suspended ? " is-off" : ""}"${suspended ? "" : ` style="background:linear-gradient(135deg,${a1},${a2})"`}>${esc(initials(m.full_name || m.email).toUpperCase())}</div>
          <div><b>${esc(m.full_name || m.email)}${isSelf ? "<em>you</em>" : ""}</b>
            <span>${esc(m.email)}${m.job_title ? " · " + esc(m.job_title) : ""}${suspended ? " · deactivated" : ""}</span></div>
        </div></td>
        <td>${roleBadgeHtml(m.role_key, m.role_label)}${overrides > 0
          ? `<span class="tm-override" title="${overrides} individual permission ${overrides === 1 ? "override" : "overrides"} on top of this role">±${overrides}</span>` : ""}</td>
        <td>${scopeChipHtml(m.data_scope || (m.is_owner ? "all" : "assigned"), m.scope_label)}</td>
        <td>${branchChipsHtml(m.branch_names, m.primary_branch_name)}</td>
        <td class="tm-num">${m.assigned_client_count != null ? m.assigned_client_count : "—"}</td>
        <td class="tm-num">${m.last_active_at ? esc(notifAgo(m.last_active_at)) : "—"}</td>
        <td>${tmRowMenuHtml(m, { canManage, canRoles, isSelf, suspended })}</td>
      </tr>`;
    }).join("")
      : `<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:26px">${
        filtered ? "No members match these filters." : "No team members yet."}</td></tr>`;

    mount.innerHTML = `
      ${toolbar}
      <div class="card"><div class="card-body" style="padding:0">
        <div class="tm-tablewrap"><table class="client-table tm-table"><thead><tr>
          ${canManage ? `<th class="tm-pick"><input type="checkbox" id="tmCheckAll" aria-label="Select all members"/></th>` : ""}
          <th>Member</th><th>Role</th><th>Access scope</th><th>Offices</th>
          <th class="tm-num">Clients</th><th class="tm-num">Last active</th><th></th>
        </tr></thead><tbody>${body}</tbody></table></div>
      </div></div>
      ${canManage ? `<p class="tm-hint" style="margin-top:12px">Invited members get an email to set their password and join.${
        seats.used != null ? ` Seats used: ${seats.used}/${seats.max === -1 || seats.max == null ? "∞" : seats.max}.` : ""}</p>` : ""}
      <div id="tmBulkMount"></div>`;

    // ---- filters (debounced search, caret preserved) ----
    const q = $("#tmQ", mount);
    if (q) {
      let timer = null;
      q.oninput = () => {
        clearTimeout(timer);
        timer = setTimeout(() => { teamUi.filters.q = q.value; tmPaintMembers(); }, 220);
      };
      q.onkeydown = (e) => {
        if (e.key === "Enter") { clearTimeout(timer); teamUi.filters.q = q.value; tmPaintMembers(); }
      };
      if (keepCaret != null) {
        q.focus();
        try { q.setSelectionRange(keepCaret, keepCaret); } catch (e) { /* not a text input */ }
      }
    }
    const bindFilter = (id, key) => {
      const el = $(id, mount);
      if (el) el.onchange = () => { teamUi.filters[key] = el.value; tmPaintMembers(); };
    };
    bindFilter("#tmRole", "role"); bindFilter("#tmBranch", "branch");
    // Status is the one filter the SERVER has to know about: deactivated members are not
    // in the default /team payload at all, so asking for them means refetching.
    const st = $("#tmStatus", mount);
    if (st) st.onchange = () => {
      teamUi.filters.status = st.value;
      const needInactive = st.value !== "";
      if (needInactive !== teamUi.includeInactive) {
        teamUi.includeInactive = needInactive;
        teamUi.team = null; teamUi.teamError = null;
        tmDrawMembers();
        return;
      }
      tmPaintMembers();
    };
    const clear = $("#tmClear", mount);
    if (clear) clear.onclick = () => {
      const wasInactive = teamUi.includeInactive;
      teamUi.filters = { q: "", role: "", branch: "", status: "" };
      teamUi.includeInactive = false;
      if (wasInactive) { teamUi.team = null; teamUi.teamError = null; tmDrawMembers(); return; }
      tmPaintMembers();
    };
    const invite = $("#tmInvite", mount);
    if (invite) invite.onclick = () => tmOpenInvite();

    // ---- selection + bulk bar ----
    $$(".tm-check", mount).forEach((cb) => cb.onchange = () => {
      const uid = parseInt(cb.dataset.uid, 10);
      if (cb.checked) teamUi.selected.add(uid); else teamUi.selected.delete(uid);
      const tr = cb.closest("tr");
      if (tr) tr.classList.toggle("is-picked", cb.checked);
      tmDrawBulkBar();
    });
    const all = $("#tmCheckAll", mount);
    if (all) all.onchange = () => {
      $$(".tm-check", mount).forEach((cb) => {
        if (cb.disabled) return;
        cb.checked = all.checked;
        const uid = parseInt(cb.dataset.uid, 10);
        if (all.checked) teamUi.selected.add(uid); else teamUi.selected.delete(uid);
        const tr = cb.closest("tr");
        if (tr) tr.classList.toggle("is-picked", all.checked);
      });
      tmDrawBulkBar();
    };
    $$(".tm-check:checked", mount).forEach((cb) => {
      const tr = cb.closest("tr"); if (tr) tr.classList.add("is-picked");
    });

    tmWireRowMenus(mount);
    tmDrawBulkBar();
  }

  function tmRowMenuHtml(m, ctx) {
    const items = [];
    if (ctx.canRoles && !ctx.isSelf && !m.is_owner) items.push(["access", "Edit access", false]);
    if (ctx.canManage || ctx.isSelf) items.push(["profile", "Edit profile", false]);
    // "Never signed in" rather than "invite_accepted_at is null": that column is not
    // backfilled for members who joined before invites were tracked, and offering to
    // re-invite a colleague who has been working here for a year is nonsense.
    if (ctx.canManage && !ctx.isSelf && !m.invite_accepted_at && !m.last_active_at) {
      items.push(["resend", "Resend invite", false]);
    }
    if (ctx.canManage && !ctx.isSelf && !m.is_owner) {
      items.push(ctx.suspended ? ["reactivate", "Reactivate", false] : ["deactivate", "Deactivate", true]);
      items.push(["remove", "Remove from workspace", true]);
    }
    if (!ctx.isSelf && !m.is_owner && (can("org.transfer_ownership") || ctx.canManage)) {
      items.push(["transfer", "Transfer ownership", true]);
    }
    if (!items.length) return `<span class="tm-hint">—</span>`;
    let lastSafe = true;
    const rendered = items.map(([act, label, danger]) => {
      const rule = (lastSafe && danger) ? "<hr>" : "";
      lastSafe = !danger;
      return `${rule}<button type="button"${danger ? ' class="danger"' : ""} data-tmact="${act}" data-uid="${m.user_id}">${esc(label)}</button>`;
    }).join("");
    return `<span class="tm-menu-wrap">
      <button type="button" class="btn btn-ghost btn-xs" data-tmmenu="${m.user_id}"
        aria-label="Actions for ${esc(m.full_name || m.email)}">⋯</button>
      <div class="tm-menu hidden">
        <div class="tm-menu-label">${esc(m.full_name || m.email)}</div>
        ${rendered}
      </div></span>`;
  }
  function tmWireRowMenus(root) {
    $$("[data-tmmenu]", root).forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();
        const menu = b.parentNode.querySelector(".tm-menu");
        if (!menu) return;
        const wasOpen = !menu.classList.contains("hidden");
        tmCloseMenus();
        if (!wasOpen) tmPositionMenu(b, menu);
      };
    });
    $$("[data-tmact]", root).forEach((b) => {
      b.onclick = async (e) => {
        e.stopPropagation();
        tmCloseMenus();
        const uid = parseInt(b.dataset.uid, 10);
        const act = b.dataset.tmact;
        const key = act + ":" + uid;
        const guarded = TM_MUTATING_ACTS.has(act);
        if (guarded) {
          if (tmActionInflight.has(key)) return;
          tmActionInflight.add(key);
        }
        try {
          if (act === "access") tmOpenAccessModal(uid);
          else if (act === "profile") tmOpenProfileModal(uid);
          else if (act === "resend") await tmResendInvite(uid);
          else if (act === "deactivate") await tmDeactivate(uid);
          else if (act === "reactivate") await tmReactivate(uid);
          else if (act === "remove") await removeMember(uid);
          else if (act === "transfer") tmOpenTransferOwnership(uid);
        } finally {
          if (guarded) tmActionInflight.delete(key);
        }
      };
    });
  }

  /* ---- bulk bar ---- */
  function tmDrawBulkBar() {
    const mount = $("#tmBulkMount");
    if (!mount) return;
    const n = teamUi.selected.size;
    if (!n) { mount.innerHTML = ""; return; }
    mount.innerHTML = `<div class="tm-bulkbar">
      <b>${n} selected</b>
      ${can("roles.manage") ? `<button class="btn btn-soft btn-sm" data-bulk="set_role">Change role</button>` : ""}
      ${can("roles.manage") ? `<button class="btn btn-soft btn-sm" data-bulk="set_scope">Change access scope</button>` : ""}
      ${can("branches.manage") ? `<button class="btn btn-soft btn-sm" data-bulk="set_branches">Set offices</button>` : ""}
      ${can("branches.manage") ? `<button class="btn btn-soft btn-sm" data-bulk="add_branch">Add to an office</button>` : ""}
      ${can("team.manage") ? `<button class="btn btn-danger btn-sm" data-bulk="deactivate">Deactivate</button>` : ""}
      <div class="spacer"></div>
      <button class="tm-bulkbar-clear" data-bulk="clear">Clear selection</button>
    </div>`;
    $$("[data-bulk]", mount).forEach((b) => b.onclick = () => {
      const act = b.dataset.bulk;
      if (act === "clear") {
        teamUi.selected = new Set();
        tmPaintMembers();
        return;
      }
      tmOpenBulkModal(act);
    });
  }

  function tmOpenBulkModal(action) {
    const ids = Array.from(teamUi.selected);
    if (!ids.length) return;
    if (ids.length > 100) { toast("Select at most 100 members at a time.", "error"); return; }
    const titles = {
      set_role: "Change role", set_scope: "Change access scope",
      set_branches: "Set offices", add_branch: "Add to an office", deactivate: "Deactivate members",
    };
    let inner = "";
    if (action === "set_role") inner = tmRoleRadiosHtml("bulk_role", "");
    else if (action === "set_scope") inner = tmScopeRadiosHtml("bulk_scope", "") +
      `<div data-branchwrap class="hidden" style="margin-top:12px"><div class="cap-sec-h">Which offices?</div>${tmBranchPickerHtml("bulk_branch_ids", [], "")}</div>`;
    else if (action === "set_branches") inner = tmBranchPickerHtml("bulk_branch_ids", [], "");
    else if (action === "add_branch") {
      const list = ((teamUi.meta || {}).branches || []).filter((b) => b.is_active !== false);
      inner = list.length
        ? `<div class="field"><label>Office</label><select name="bulk_single_branch">${
          list.map((b) => `<option value="${b.id}">${esc(b.name)}</option>`).join("")}</select></div>`
        : `<div class="br-picker-empty">No offices yet — add one on the Offices tab first.</div>`;
    } else if (action === "deactivate") {
      inner = `<p class="tm-hint">They lose access immediately and their sessions are signed out. Anyone still holding client records or calendar events will be skipped — reassign those first.</p>`;
    }
    openModal(`<div class="modal-head"><h3>${esc(titles[action] || "Apply to selected")}</h3>
      <button class="x" onclick="__ent.closeModal()">×</button></div>
      <form id="tmBulkForm"><div class="modal-body">
        <p class="tm-hint">Applying to <b>${ids.length}</b> ${ids.length === 1 ? "member" : "members"}.</p>
        ${inner}
        <div id="tmBulkError" class="auth-error hidden"></div>
        <div id="tmBulkResult"></div>
      </div><div class="modal-foot">
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="submit" class="btn ${action === "deactivate" ? "btn-danger" : "btn-primary"}" id="tmBulkSubmit">Apply</button>
      </div></form>`, { wide: action === "set_role" || action === "set_scope" });

    const form = $("#tmBulkForm");
    // Mirrors the inline errors the handler raises after the click. Delegated on the form so
    // the office <select> that appears when scope flips to "branch" is covered as it arrives.
    // "deactivate" has nothing to pick, so its predicate is simply true.
    bindValidity($("#tmBulkSubmit"), form, () => {
      if (action === "set_role") return !!$('input[name="bulk_role"]:checked', form);
      if (action === "set_scope") {
        const picked = $('input[name="bulk_scope"]:checked', form);
        if (!picked) return false;
        if (picked.value !== "branch") return true;
        const sel = form.bulk_single_branch;
        return !sel || !!sel.value;
      }
      if (action === "add_branch") return !!(form.bulk_single_branch && form.bulk_single_branch.value);
      return true;
    }, "Choose an option above first");
    if (action === "set_scope") tmWireRoleScope(form, "bulk_role", "bulk_scope");
    $$(".rl-row input", form).forEach((i) => i.onchange = () => {
      $$(".rl-row", form).forEach((r) => {
        const el = $("input", r);
        r.classList.toggle("selected", !!(el && el.checked));
      });
      if (action === "set_scope") {
        const wrap = $("[data-branchwrap]", form);
        const picked = $('input[name="bulk_scope"]:checked', form);
        if (wrap) wrap.classList.toggle("hidden", !picked || picked.value !== "branch");
      }
    });

    form.onsubmit = async (e) => {
      e.preventDefault();
      const btn = $("#tmBulkSubmit"); const err = $("#tmBulkError");
      err.classList.add("hidden");
      const body = { user_ids: ids, action: action };
      if (action === "set_role") {
        const picked = $('input[name="bulk_role"]:checked', form);
        if (!picked) { err.textContent = "Pick a role."; err.classList.remove("hidden"); return; }
        const [kind, val] = picked.value.split(":");
        if (kind === "custom") { body.role_key = "custom"; body.custom_role_id = parseInt(val, 10); }
        else body.role_key = val;
      } else if (action === "set_scope") {
        const picked = $('input[name="bulk_scope"]:checked', form);
        if (!picked) { err.textContent = "Pick an access scope."; err.classList.remove("hidden"); return; }
        body.data_scope = picked.value;
        if (picked.value === "branch") body.branch_ids = tmReadBranchPicker(form, "bulk_branch_ids");
      } else if (action === "set_branches") {
        body.branch_ids = tmReadBranchPicker(form, "bulk_branch_ids");
      } else if (action === "add_branch") {
        const sel = form.bulk_single_branch;
        if (!sel || !sel.value) { err.textContent = "Pick an office."; err.classList.remove("hidden"); return; }
        body.branch_id = parseInt(sel.value, 10);
      }
      btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
      let res;
      try { res = await api("/team/bulk", { method: "POST", body: body }); }
      catch (ex) {
        err.textContent = errMessage(ex); err.classList.remove("hidden");
        btn.disabled = false; btn.textContent = "Apply";
        return;
      }
      const applied = (res.applied || []).length;
      const skipped = res.skipped || [];
      // Never claim a clean sweep: a skipped member is the whole point of this response.
      if (!skipped.length) {
        closeModal();
        toast(`Updated ${applied} ${applied === 1 ? "member" : "members"}`, "success");
        teamUi.selected = new Set();
        await teamRefresh();
        return;
      }
      const nameOf = (uid) => {
        const m = tmMemberById(uid);
        return (m && (m.full_name || m.email)) || ("User #" + uid);
      };
      $("#tmBulkResult").innerHTML = `<div class="tm-banner" style="margin-top:14px">
        <div class="tm-banner-ic">ℹ️</div>
        <div class="tm-banner-txt"><b>${applied} updated, ${skipped.length} skipped.</b>
          <span>${skipped.map((s) => `${esc(nameOf(s.user_id))} — ${esc(s.reason || "not allowed")}`).join("<br>")}</span></div>
      </div>`;
      btn.disabled = false; btn.textContent = "Done";
      btn.onclick = async (ev) => {
        ev.preventDefault();
        closeModal();
        teamUi.selected = new Set();
        await teamRefresh();
      };
    };
  }

  /* ---- invite ---- */
  function tmOpenInvite() {
    const meta = teamUi.meta || {};
    if (!(meta.role_presets || []).length) { toast("Roles aren't available right now — try again.", "error"); return; }
    const defaultRole = tmRoleChoiceValue("counsellor", null);
    openModal(`<div class="modal-head"><h3>Invite a team member</h3>
      <button class="x" onclick="__ent.closeModal()">×</button></div>
      <form id="tmInviteForm"><div class="modal-body">
        <div class="mw-grid mw-sec">
          <div class="field"><label>Email *</label><input type="email" name="email" required placeholder="teammate@company.com"/></div>
          <div class="field"><label>Full name</label><input name="full_name" placeholder="Their name"/></div>
          <div class="field"><label>Job title</label><input name="job_title" maxlength="80" placeholder="e.g. Senior counsellor"/></div>
          <div class="field"><label>Phone</label><input name="phone" inputmode="tel" placeholder="Optional"/></div>
        </div>
        <div class="cp-sub-label">Role</div>
        ${tmRoleRadiosHtml("invite_role", defaultRole)}
        <div data-scopewrap>
          <div class="cp-sub-label">What client data can they see?</div>
          ${tmScopeRadiosHtml("invite_scope", "")}
        </div>
        <div data-scopelockedhint class="tm-hint hidden">This role always covers the entire workspace.</div>
        <div data-branchwrap class="hidden">
          <div class="cp-sub-label">Which offices?</div>
          ${tmBranchPickerHtml("invite_branch_ids", [], "")}
        </div>
        <details class="cap-fold"><summary>Fine-tune individual permissions</summary>
          <p class="tm-hint">You can also do this later from the member's ⋯ menu, once they've joined.</p>
        </details>
        <div class="tm-hint" style="margin-top:12px">They'll get an email to set their password and join your workspace.</div>
        <div id="tmInviteError" class="auth-error hidden"></div>
      </div><div class="modal-foot">
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary" id="tmInviteSubmit">Send invite</button>
      </div></form>`, { wide: true });

    const form = $("#tmInviteForm");
    tmWireRoleScope(form, "invite_role", "invite_scope");
    form.onsubmit = async (e) => {
      e.preventDefault();
      const btn = $("#tmInviteSubmit"); const err = $("#tmInviteError");
      err.classList.add("hidden");
      const picked = $('input[name="invite_role"]:checked', form);
      if (!picked) { err.textContent = "Pick a role."; err.classList.remove("hidden"); return; }
      const [kind, val] = picked.value.split(":");
      const body = {
        email: (form.email.value || "").trim(),
        full_name: (form.full_name.value || "").trim() || null,
        job_title: (form.job_title.value || "").trim() || null,
        phone: (form.phone.value || "").trim() || null,
      };
      if (kind === "custom") { body.role_key = "custom"; body.custom_role_id = parseInt(val, 10); }
      else body.role_key = val;
      // `role` is still sent so an older server (which validates the legacy column) keeps
      // working; the server prefers role_key when it understands it.
      body.role = (body.role_key === "admin") ? "admin" : (body.role_key === "viewer" ? "viewer" : "editor");
      const scopePicked = $('input[name="invite_scope"]:checked', form);
      if (picked.dataset.scopelocked !== "1" && scopePicked) body.data_scope = scopePicked.value;
      if (scopePicked && scopePicked.value === "branch") body.branch_ids = tmReadBranchPicker(form, "invite_branch_ids");
      const primary = form.primary_branch_id;
      if (primary && primary.value) body.primary_branch_id = parseInt(primary.value, 10);
      btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
      try {
        await api("/team/users", { method: "POST", body: body });
        toast("Invitation sent", "success");
        closeModal();
        await teamRefresh();
      } catch (ex) {
        if (ex.status === 402) { closeModal(); toast(errMessage(ex), "error"); navigate("credits"); return; }
        err.textContent = errMessage(ex); err.classList.remove("hidden");
        btn.disabled = false; btn.textContent = "Send invite";
      }
    };
  }

  /* ---- edit access ---- */
  async function tmOpenAccessModal(userId) {
    const m = tmMemberById(userId);
    openModal(`<div class="modal-head"><h3>Edit access</h3>
      <button class="x" onclick="__ent.closeModal()">×</button></div>
      <div class="modal-body"><div class="center-load"><div class="spinner dark"></div></div></div>`, { wide: true });
    let d;
    try { d = await api(`/team/users/${userId}/access`); }
    catch (ex) {
      openModal(`<div class="modal-head"><h3>Edit access</h3>
        <button class="x" onclick="__ent.closeModal()">×</button></div>
        <div class="modal-body">${errBox(ex)}</div>
        <div class="modal-foot"><button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Close</button></div>`, { wide: true });
      return;
    }
    const who = d.member || d.user || m || {};
    const name = who.full_name || who.email || (m && (m.full_name || m.email)) || "this member";
    const roleKey = d.role_key || who.role_key || "viewer";
    const scope = d.data_scope || who.data_scope || "";
    const grants = d.capability_grants || [];
    const denies = d.capability_denies || [];
    // The role's own capabilities are the "inherit" baseline the overrides sit on top of.
    const preset = (roleKey === "custom")
      ? tmActiveCustomRoles().find((r) => r.id === (d.custom_role_id || who.custom_role_id))
      : ((teamUi.meta || {}).role_presets || []).find((r) => r.key === roleKey);
    const base = (preset && preset.capabilities) || d.role_capabilities || [];
    const branchIds = d.branch_ids || who.branch_ids || [];
    const primaryId = d.primary_branch_id || who.primary_branch_id || "";
    const current = tmRoleChoiceValue(roleKey, d.custom_role_id || who.custom_role_id);

    openModal(`<div class="modal-head"><h3>Access for ${esc(name)}</h3>
      <button class="x" onclick="__ent.closeModal()">×</button></div>
      <form id="tmAccessForm"><div class="modal-body">
        <div class="cp-sub-label">Role</div>
        ${tmRoleRadiosHtml("acc_role", current)}
        <div data-scopewrap>
          <div class="cp-sub-label">What client data can they see?</div>
          ${tmScopeRadiosHtml("acc_scope", scope)}
        </div>
        <div data-scopelockedhint class="tm-hint hidden">This role always covers the entire workspace.</div>
        <div data-branchwrap class="hidden">
          <div class="cp-sub-label">Which offices?</div>
          ${tmBranchPickerHtml("acc_branch_ids", branchIds, primaryId)}
        </div>
        <details class="cap-fold"${(grants.length || denies.length) ? " open" : ""}>
          <summary>Fine-tune individual permissions</summary>
          <p class="tm-hint">Everything here is layered on top of the role. <b>Inherit</b> follows the role, <b>Allow</b> adds a permission just for ${esc(name)}, and <b>Block</b> takes one away even if the role grants it.</p>
          ${capMatrixHtml({ grants: grants, denies: denies, base: base }, tmActorCaps(), { mode: "override", idPrefix: "acc", isOwner: tmIsOwner() })}
        </details>
        <div id="tmAccessError" class="auth-error hidden"></div>
      </div><div class="modal-foot">
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary" id="tmAccessSubmit">Save access</button>
      </div></form>`, { wide: true });

    const form = $("#tmAccessForm");
    tmWireRoleScope(form, "acc_role", "acc_scope");
    capMatrixWire(form);
    // Changing the role changes what "Inherit" means, so redraw the matrix's baseline.
    $$('input[name="acc_role"]', form).forEach((i) => i.addEventListener("change", () => {
      let caps = [];
      try { caps = JSON.parse(i.dataset.caps || "[]"); } catch (e) { caps = []; }
      const holder = $(".cap-fold", form);
      if (!holder) return;
      const read = readCapMatrix(form);
      const rebuilt = capMatrixHtml({ grants: read.grants, denies: read.denies, base: caps },
        tmActorCaps(), { mode: "override", idPrefix: "acc", isOwner: tmIsOwner() });
      const old = $(".cap-matrix", holder);
      if (old) { old.outerHTML = rebuilt; capMatrixWire(form); }
    }));

    form.onsubmit = async (e) => {
      e.preventDefault();
      const btn = $("#tmAccessSubmit"); const err = $("#tmAccessError");
      err.classList.add("hidden");
      const picked = $('input[name="acc_role"]:checked', form);
      if (!picked) { err.textContent = "Pick a role."; err.classList.remove("hidden"); return; }
      const [kind, val] = picked.value.split(":");
      const body = {};
      if (kind === "custom") { body.role_key = "custom"; body.custom_role_id = parseInt(val, 10); }
      else { body.role_key = val; body.custom_role_id = null; }
      const scopePicked = $('input[name="acc_scope"]:checked', form);
      if (picked.dataset.scopelocked !== "1" && scopePicked) body.data_scope = scopePicked.value;
      if (scopePicked && scopePicked.value === "branch") {
        body.branch_ids = tmReadBranchPicker(form, "acc_branch_ids");
        const primary = form.primary_branch_id;
        body.primary_branch_id = primary && primary.value ? parseInt(primary.value, 10) : null;
      }
      const read = readCapMatrix(form);
      body.capability_grants = read.grants;
      body.capability_denies = read.denies;
      btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
      try {
        await api(`/team/users/${userId}/access`, { method: "PATCH", body: body });
        toast("Access updated", "success");
        closeModal();
        await teamRefresh();
      } catch (ex) {
        err.textContent = errMessage(ex); err.classList.remove("hidden");
        btn.disabled = false; btn.textContent = "Save access";
      }
    };
  }

  /* ---- edit profile (self-serve or team.manage) ---- */
  function tmOpenProfileModal(userId) {
    const m = tmMemberById(userId) || {};
    openModal(`<div class="modal-head"><h3>Edit profile</h3>
      <button class="x" onclick="__ent.closeModal()">×</button></div>
      <form id="tmProfileForm"><div class="modal-body">
        <div class="field"><label>Full name</label><input name="full_name" value="${esc(m.full_name || "")}" maxlength="120"/></div>
        <div class="field"><label>Job title</label><input name="job_title" value="${esc(m.job_title || "")}" maxlength="80" placeholder="e.g. Senior counsellor"/></div>
        <div class="field"><label>Phone</label><input name="phone" value="${esc(m.phone || "")}" inputmode="tel" maxlength="32"/></div>
        <div class="tm-hint">Email addresses can't be changed here — they identify the account.</div>
        <div id="tmProfileError" class="auth-error hidden"></div>
      </div><div class="modal-foot">
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary" id="tmProfileSubmit">Save</button>
      </div></form>`);
    $("#tmProfileForm").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target; const btn = $("#tmProfileSubmit"); const err = $("#tmProfileError");
      err.classList.add("hidden");
      btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
      try {
        await api(`/team/users/${userId}/profile`, { method: "PATCH", body: {
          full_name: (f.full_name.value || "").trim() || null,
          job_title: (f.job_title.value || "").trim() || null,
          phone: (f.phone.value || "").trim() || null,
        } });
        toast("Profile updated", "success");
        closeModal();
        await teamRefresh();
      } catch (ex) {
        err.textContent = errMessage(ex); err.classList.remove("hidden");
        btn.disabled = false; btn.textContent = "Save";
      }
    };
  }

  async function tmResendInvite(userId) {
    try {
      await api(`/team/users/${userId}/resend-invite`, { method: "POST" });
      toast("Invitation resent", "success");
    } catch (ex) { toast(errMessage(ex), "error"); }
  }

  /* ---- deactivate (with the 409 reassignment picker) ---- */
  async function tmDeactivate(userId, extra) {
    const m = tmMemberById(userId) || {};
    const name = m.full_name || m.email || "this member";
    if (!extra) {
      const ok = await confirmModal(
        `${name} loses access immediately and is signed out everywhere. Their client records and calendar events stay exactly where they are.`,
        { title: "Deactivate member?", okText: "Deactivate" });
      if (!ok) return;
    }
    try {
      await api(`/team/users/${userId}/deactivate`, { method: "POST", body: extra || {} });
      toast("Member deactivated", "success");
      await teamRefresh();
    } catch (ex) {
      const det = errDetail(ex);
      if (ex.status === 409 && det) { tmOpenDeactivateReassign(userId, det); return; }
      toast(errMessage(ex), "error");
    }
  }
  function tmOpenDeactivateReassign(userId, det) {
    const m = tmMemberById(userId) || {};
    const name = m.full_name || m.email || "this member";
    const others = ((teamUi.team || {}).members || [])
      .filter((x) => x.user_id !== userId && x.is_active !== false && (x.status || "active") === "active");
    const clients = Number(det.assigned_client_count || 0);
    const events = Number(det.open_event_count || 0);
    // "— Leave them assigned to X —" used to be the default here, but the server refuses a
    // deactivation that leaves records owned (enterprise_team.py re-raises the same 409), so
    // that option promised an outcome it could never deliver. A disabled placeholder instead,
    // with the submit held until every picker has a real target.
    const picker = (id, label, count) => `<div class="field"><label>${esc(label)}</label>
      <select name="${id}"><option value="" disabled selected>Choose someone…</option>
        ${others.map((o) => `<option value="${o.user_id}">${esc(o.full_name || o.email)}</option>`).join("")}
      </select><div class="tm-hint">${count} ${count === 1 ? "record" : "records"}</div></div>`;
    openModal(`<div class="modal-head"><h3>Reassign ${esc(name)}'s work</h3>
      <button class="x" onclick="__ent.closeModal()">×</button></div>
      <form id="tmDeacForm"><div class="modal-body">
        <p class="tm-hint">${esc(det.message || "This member still owns records.")}</p>
        ${clients ? picker("reassign_clients_to_user_id", "Move their clients to", clients) : ""}
        ${events ? picker("reassign_events_to_user_id", "Move their calendar events to", events) : ""}
        ${!others.length ? `<div class="br-picker-empty">There's nobody else active to move this work to.</div>` : ""}
        <div class="field"><label>Reason (optional)</label><input name="reason" maxlength="200" placeholder="Left the company, on leave…"/></div>
        <div id="tmDeacError" class="auth-error hidden"></div>
      </div><div class="modal-foot">
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">${others.length ? "Cancel" : "Close"}</button>
        ${others.length ? `<button type="submit" class="btn btn-danger" id="tmDeacSubmit">Deactivate</button>` : ""}
      </div></form>`);
    // With nobody to reassign to there is no submit at all — the button above is omitted,
    // because every click it could receive would fail. Otherwise it waits for a target.
    bindValidity($("#tmDeacSubmit"), $("#tmDeacForm"),
      () => $$("#tmDeacForm select").every((s) => !!s.value), "Choose who takes over their work first");
    $("#tmDeacForm").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target; const btn = $("#tmDeacSubmit"); const err = $("#tmDeacError");
      err.classList.add("hidden");
      const body = { reason: (f.reason.value || "").trim() || null };
      if (f.reassign_clients_to_user_id && f.reassign_clients_to_user_id.value) {
        body.reassign_clients_to_user_id = parseInt(f.reassign_clients_to_user_id.value, 10);
      }
      if (f.reassign_events_to_user_id && f.reassign_events_to_user_id.value) {
        body.reassign_events_to_user_id = parseInt(f.reassign_events_to_user_id.value, 10);
      }
      await withBusy(btn, "", async () => {
        try {
          await api(`/team/users/${userId}/deactivate`, { method: "POST", body: body });
          toast("Member deactivated", "success");
          closeModal();
          await teamRefresh();
        } catch (ex) {
          err.textContent = errMessage(ex); err.classList.remove("hidden");
        }
      });
    };
  }
  async function tmReactivate(userId) {
    const m = tmMemberById(userId) || {};
    const ok = await confirmModal(
      `${m.full_name || m.email || "This member"} gets their access back with the role and scope they had before.`,
      { title: "Reactivate member?", okText: "Reactivate", danger: false });
    if (!ok) return;
    try {
      await api(`/team/users/${userId}/reactivate`, { method: "POST", body: {} });
      toast("Member reactivated", "success");
      await teamRefresh();
    } catch (ex) {
      if (ex.status === 402) { toast(errMessage(ex), "error"); navigate("credits"); return; }
      toast(errMessage(ex), "error");
    }
  }
  async function removeMember(uid) {
    const m = tmMemberById(uid) || {};
    if (!(await confirmModal(
      `${m.full_name || m.email || "They"} will lose access to this workspace immediately. Deactivating instead keeps their name on the records they created.`,
      { title: "Remove member?", okText: "Remove" }))) return;
    try {
      await api(`/team/users/${uid}`, { method: "DELETE" });
      toast("Member removed", "success");
      await teamRefresh();
    } catch (ex) { toast(errMessage(ex), "error"); }
  }

  /* ---- transfer ownership: type their email, then a code emailed to YOU ----
     The address on screen is readable by anyone already holding the session, so typing it
     back proves nothing on its own. Ownership carries refunds and the payout bank account
     and only the new owner can hand it back, so step 2 asks for a 6-digit code sent to our
     own inbox — which a stolen session can't open. */
  function tmOpenTransferOwnership(userId) {
    const m = tmMemberById(userId) || {};
    const email = m.email || "";
    const who = m.full_name || email || "This member";
    let resendTimer = null, resendUntil = 0;

    function stopResendTimer() { if (resendTimer) { clearInterval(resendTimer); resendTimer = null; } }
    function tickResend() {
      const link = $("#tmTransferResend");
      if (!link) { stopResendTimer(); return; }   // modal closed (overlay/Escape) — stop ticking
      const left = Math.ceil((resendUntil - Date.now()) / 1000);
      if (left > 0) { link.disabled = true; link.textContent = `Resend code in ${left}s`; }
      else { link.disabled = false; link.textContent = "Resend code"; stopResendTimer(); }
    }
    function startResendCooldown(seconds) {
      resendUntil = Date.now() + seconds * 1000;
      stopResendTimer();
      resendTimer = setInterval(tickResend, 1000);
      tickResend();
    }
    async function requestCode(typed) {
      return api("/organization/transfer-ownership/send-code", {
        method: "POST", body: { target_user_id: userId, confirm_email: typed },
      });
    }

    /* Step 1 — confirm WHO gets the workspace. */
    function renderStep1(prefill) {
      stopResendTimer();
      openModal(`<div class="modal-head"><h3>Transfer ownership</h3>
        <button class="x" onclick="__ent.closeModal()">×</button></div>
        <form id="tmTransferForm"><div class="modal-body">
          <p class="tm-hint">${esc(who)} becomes the workspace owner and gets every permission, including refunds and the payout bank account. You keep Admin. <b>This can't be undone by you afterwards</b> — only the new owner can transfer it back.</p>
          <div class="field" style="margin-top:14px"><label>Type <b>${esc(email)}</b> to confirm</label>
            <input name="confirm_email" autocomplete="off" placeholder="${esc(email)}" value="${esc(prefill || "")}"/></div>
          <p class="tm-hint">🔒 Next we'll email a 6-digit code to your own address. Ownership doesn't move until you enter it.</p>
          <div id="tmTransferError" class="auth-error hidden" style="margin-top:16px"></div>
        </div><div class="modal-foot">
          <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
          <button type="submit" class="btn btn-danger" id="tmTransferSubmit" disabled>Email me a code</button>
        </div></form>`);
      // Same shape as the delete-client confirmation: the button stays dead until the typed
      // address actually matches. The handler's own re-check below remains authoritative.
      bindValidity($("#tmTransferSubmit"), $("#tmTransferForm"),
        () => ($("#tmTransferForm").confirm_email.value || "").trim().toLowerCase() === String(email).toLowerCase(),
        "Type their email address exactly to confirm");
      $("#tmTransferForm").onsubmit = async (e) => {
        e.preventDefault();
        const f = e.target; const btn = $("#tmTransferSubmit"); const err = $("#tmTransferError");
        err.classList.add("hidden");
        const typed = (f.confirm_email.value || "").trim();
        if (typed.toLowerCase() !== String(email).toLowerCase()) {
          err.textContent = "That doesn't match their email address.";
          err.classList.remove("hidden");
          return;
        }
        btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
        try {
          renderStep2(typed, (await requestCode(typed)) || {});
        } catch (ex) {
          err.textContent = errMessage(ex); err.classList.remove("hidden");
          btn.disabled = false; btn.textContent = "Email me a code";
        }
      };
    }

    /* Step 2 — prove the inbox, then hand over. */
    function renderStep2(typed, data) {
      const masked = data.masked_email || "your email address";
      const mins = data.expires_in_minutes || 10;
      openModal(`<div class="modal-head"><h3>Confirm it's you</h3>
        <button class="x" onclick="__ent.closeModal()">×</button></div>
        <form id="tmTransferCodeForm"><div class="modal-body">
          <div class="tm-otp-sent"><span>📬</span><div>We emailed a 6-digit code to <b>${esc(masked)}</b>. It expires in ${esc(String(mins))} minutes and only works for this transfer.</div></div>
          <div class="field"><label>Enter the code to make <b>${esc(who)}</b> the owner</label>
            <input name="code" class="tm-otp-input" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="000000"/></div>
          <div class="tm-otp-actions">
            <button type="button" class="tm-otp-link" id="tmTransferResend">Resend code</button>
            <button type="button" class="tm-otp-link" id="tmTransferBack">Back</button>
          </div>
          <div id="tmTransferError" class="auth-error hidden"></div>
        </div><div class="modal-foot">
          <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
          <button type="submit" class="btn btn-danger" id="tmTransferSubmit" disabled>Transfer ownership</button>
        </div></form>`);
      const codeInput = $("#tmTransferCodeForm").code;
      // Held until all six digits are in. Synced by hand after every programmatic fill
      // (the sandbox dev_code, and the fresh one a resend returns) — those assign .value,
      // which fires no input event, and would otherwise leave the button dead on a full box.
      const transferSync = bindValidity($("#tmTransferSubmit"), [codeInput],
        () => (codeInput.value || "").trim().length === 6, "Enter the 6-digit code we emailed you");
      if (data.dev_code) { codeInput.value = data.dev_code; transferSync(); }   // local sandbox without an email provider
      codeInput.focus();
      codeInput.addEventListener("input", () => {
        codeInput.value = (codeInput.value || "").replace(/\D/g, "").slice(0, 6);
        transferSync();
      });
      startResendCooldown(30);

      $("#tmTransferBack").onclick = () => renderStep1(typed);
      $("#tmTransferResend").onclick = async () => {
        const link = $("#tmTransferResend"); const err = $("#tmTransferError");
        err.classList.add("hidden");
        link.disabled = true; link.textContent = "Sending…";
        try {
          const again = await requestCode(typed);
          if (again && again.dev_code) { codeInput.value = again.dev_code; transferSync(); }
          toast("New code sent", "success");
          startResendCooldown(30);
        } catch (ex) {
          err.textContent = errMessage(ex); err.classList.remove("hidden");
          link.disabled = false; link.textContent = "Resend code";
        }
      };

      $("#tmTransferCodeForm").onsubmit = async (e) => {
        e.preventDefault();
        const btn = $("#tmTransferSubmit"); const err = $("#tmTransferError");
        err.classList.add("hidden");
        const code = (codeInput.value || "").trim();
        if (code.length !== 6) {
          err.textContent = "Enter the 6-digit code we emailed you.";
          err.classList.remove("hidden");
          return;
        }
        btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
        try {
          await api("/organization/transfer-ownership", {
            method: "POST", body: { target_user_id: userId, confirm_email: typed, code },
          });
          stopResendTimer();
          toast("Ownership transferred", "success");
          closeModal();
          // OUR own capabilities just changed (owner → admin), so nothing cached is
          // trustworthy: drop it all and re-boot, which re-reads /me and re-routes here.
          teamUi.meta = null; teamUi.metaError = null;
          teamUi.team = null; teamUi.teamError = null;
          teamUi.mine = null; teamUi.mineError = null;
          teamMembersCache = null;
          await boot();
        } catch (ex) {
          err.textContent = errMessage(ex); err.classList.remove("hidden");
          btn.disabled = false; btn.textContent = "Transfer ownership";
        }
      };
    }

    renderStep1("");
  }

  /* ============================ ROLES & PERMISSIONS ============================ */
  function tmDrawRoles() {
    const mount = tmMount(); if (!mount) return;
    if (!can("roles.manage")) {
      mount.innerHTML = deniedCard("You don't have permission to manage roles and permissions. Ask a workspace admin for access.");
      return;
    }
    if (!tmMetaReady(mount)) return;
    const meta = teamUi.meta;
    const presets = (meta.role_presets || []).filter((r) => r.key !== "custom");
    const customs = (meta.custom_roles || []).filter((r) => r.is_active !== false);
    const limit = (meta.limits && meta.limits.max_custom_roles) || 20;

    const capCount = (r) => (r.capabilities || []).length;
    const scopeText = (s) => esc((scopeMeta(s) || {}).label || SCOPE_FALLBACK_LABEL[s] || "—");
    const presetCard = (r) => `<div class="rl-card${r.key === "owner" ? " is-primary" : ""}">
      <div class="rl-card-top"><h4>${esc(r.label)}</h4>${roleBadgeHtml(r.key, "Built-in")}</div>
      <p>${esc(r.description || "")}</p>
      <div class="rl-card-facts">
        <span><b>${capCount(r)}</b> permissions</span>
        <span>${scopeText(r.data_scope)}</span>
      </div>
      <div class="rl-card-acts">
        <button class="btn btn-ghost btn-sm" data-rlview="${esc(r.key)}">View permissions</button>
        ${r.key === "owner" ? "" : `<button class="btn btn-soft btn-sm" data-rlduppreset="${esc(r.key)}">Duplicate to customise</button>`}
      </div>
    </div>`;
    const customCard = (r) => `<div class="rl-card">
      <div class="rl-card-top"><h4>${esc(r.name)}</h4>${roleBadgeHtml("custom", "Custom")}</div>
      <p>${esc(r.description || "")}</p>
      <div class="rl-card-facts">
        <span><b>${capCount(r)}</b> permissions</span>
        <span>${scopeText(r.data_scope)}</span>
        <span><b>${r.member_count || 0}</b> ${r.member_count === 1 ? "member" : "members"}</span>
      </div>
      <div class="rl-card-acts">
        <button class="btn btn-soft btn-sm" data-rledit="${r.id}">Edit</button>
        <button class="btn btn-ghost btn-sm" data-rldup="${r.id}">Duplicate</button>
        <button class="btn btn-ghost btn-sm" data-rlarchive="${r.id}">Archive</button>
      </div>
    </div>`;

    mount.innerHTML = `
      <div class="tm-toolbar">
        <div><b>Your workspace's own roles</b>
          <div class="tm-hint">${customs.length} of ${limit} used. Start from a built-in role and change what it can do.</div></div>
        <div class="spacer" style="flex:1"></div>
        <button class="btn btn-primary btn-sm" id="rlCreate" ${customs.length >= limit ? "disabled" : ""}>+ Create role</button>
      </div>
      ${customs.length
        ? `<div class="rl-grid">${customs.map(customCard).join("")}</div>`
        : `<div class="card"><div class="card-body tm-hint">No custom roles yet. The built-in roles below cover most teams — duplicate one when you need to change what it can do.</div></div>`}
      <div class="cp-sub-label" style="margin-top:22px">Built-in roles</div>
      <div class="rl-grid">${presets.map(presetCard).join("")}</div>`;

    const create = $("#rlCreate", mount);
    if (create) create.onclick = () => tmOpenRoleEditor(null, null);
    $$("[data-rlview]", mount).forEach((b) => b.onclick = () => tmViewPresetRole(b.dataset.rlview));
    $$("[data-rlduppreset]", mount).forEach((b) => b.onclick = () => tmOpenRoleEditor(null, b.dataset.rlduppreset));
    $$("[data-rledit]", mount).forEach((b) => b.onclick = () => tmOpenRoleEditor(parseInt(b.dataset.rledit, 10), null));
    $$("[data-rldup]", mount).forEach((b) => b.onclick = () => tmDuplicateRole(parseInt(b.dataset.rldup, 10)));
    $$("[data-rlarchive]", mount).forEach((b) => b.onclick = () => tmArchiveRole(parseInt(b.dataset.rlarchive, 10)));
  }

  function tmViewPresetRole(key) {
    const r = ((teamUi.meta || {}).role_presets || []).find((x) => x.key === key);
    if (!r) return;
    openModal(`<div class="modal-head"><h3>${esc(r.label)}</h3>
      <button class="x" onclick="__ent.closeModal()">×</button></div>
      <div class="modal-body">
        <p class="tm-hint">${esc(r.description || "")}</p>
        <p class="tm-hint">Data scope: <b>${esc((scopeMeta(r.data_scope) || {}).label || SCOPE_FALLBACK_LABEL[r.data_scope] || "—")}</b>${
          r.scope_locked ? " (fixed for this role)" : ""}</p>
        ${capMatrixHtml({ base: r.capabilities || [] }, null,
          { mode: "readonly", idPrefix: "rlv", isOwner: true, baseLabel: "Allowed" })}
      </div>
      <div class="modal-foot"><button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Close</button></div>`, { wide: true });
  }

  function tmOpenRoleEditor(roleId, basePresetKey) {
    const meta = teamUi.meta || {};
    const existing = roleId ? tmActiveCustomRoles().find((r) => r.id === roleId) : null;
    const preset = basePresetKey ? (meta.role_presets || []).find((r) => r.key === basePresetKey) : null;
    const seed = existing || preset || {};
    const caps = (existing && existing.capabilities) || (preset && preset.capabilities) || [];
    const scope = seed.data_scope || "assigned";
    const name = existing ? existing.name : (preset ? preset.label + " (copy)" : "");
    openModal(`<div class="modal-head"><h3>${existing ? "Edit role" : "Create a role"}</h3>
      <button class="x" onclick="__ent.closeModal()">×</button></div>
      <form id="tmRoleForm"><div class="modal-body">
        <div class="mw-grid mw-sec">
          <div class="field span2"><label>Role name *</label>
            <input name="name" required maxlength="60" value="${esc(name)}" placeholder="e.g. Senior counsellor"/></div>
          <div class="field span3"><label>Description</label>
            <input name="description" maxlength="200" value="${esc(seed.description || "")}" placeholder="What this role is for"/></div>
        </div>
        <div class="cp-sub-label">What client data can this role see?</div>
        ${tmScopeRadiosHtml("role_scope", scope)}
        <div class="cp-sub-label">Permissions</div>
        ${capMatrixHtml({ grants: caps, base: [] }, tmActorCaps(), { mode: "role", idPrefix: "rle", isOwner: tmIsOwner() })}
        <div id="tmRoleError" class="auth-error hidden"></div>
      </div><div class="modal-foot">
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary" id="tmRoleSubmit">${existing ? "Save role" : "Create role"}</button>
      </div></form>`, { wide: true });
    const form = $("#tmRoleForm");
    capMatrixWire(form);
    $$('input[name="role_scope"]', form).forEach((i) => i.onchange = () => {
      $$(".rl-row", form).forEach((r) => {
        const el = $("input", r);
        r.classList.toggle("selected", !!(el && el.checked));
      });
    });
    form.onsubmit = async (e) => {
      e.preventDefault();
      const btn = $("#tmRoleSubmit"); const err = $("#tmRoleError");
      err.classList.add("hidden");
      const read = readCapMatrix(form);
      if (!read.capabilities.length) {
        err.textContent = "Pick at least one permission for this role.";
        err.classList.remove("hidden");
        return;
      }
      const scopePicked = $('input[name="role_scope"]:checked', form);
      const body = {
        name: (form.name.value || "").trim(),
        description: (form.description.value || "").trim() || null,
        capabilities: read.capabilities,
        data_scope: (scopePicked && scopePicked.value) || "assigned",
      };
      if (!existing && basePresetKey) body.based_on_role_key = basePresetKey;
      btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
      try {
        if (existing) await api(`/roles/${existing.id}`, { method: "PATCH", body: body });
        else await api("/roles", { method: "POST", body: body });
        toast(existing ? "Role updated" : "Role created", "success");
        closeModal();
        await teamRefresh();
      } catch (ex) {
        err.textContent = errMessage(ex); err.classList.remove("hidden");
        btn.disabled = false; btn.textContent = existing ? "Save role" : "Create role";
      }
    };
  }

  async function tmDuplicateRole(roleId) {
    const r = tmActiveCustomRoles().find((x) => x.id === roleId);
    const name = await promptModal("What should the copy be called?", {
      title: "Duplicate role", okText: "Duplicate", value: ((r && r.name) || "Role") + " (copy)",
    });
    if (!name || !name.trim()) return;
    try {
      await api(`/roles/${roleId}/duplicate`, { method: "POST", body: { name: name.trim() } });
      toast("Role duplicated", "success");
      await teamRefresh();
    } catch (ex) { toast(errMessage(ex), "error"); }
  }

  async function tmArchiveRole(roleId) {
    const r = tmActiveCustomRoles().find((x) => x.id === roleId);
    const ok = await confirmModal(
      `“${(r && r.name) || "This role"}” stops being assignable. Roles are archived rather than deleted so the access log keeps making sense.`,
      { title: "Archive role?", okText: "Archive" });
    if (!ok) return;
    try {
      await api(`/roles/${roleId}/archive`, { method: "POST", body: {} });
      toast("Role archived", "success");
      await teamRefresh();
    } catch (ex) {
      const det = errDetail(ex);
      if (ex.status === 409) { tmOpenRoleArchiveMove(roleId, det, r); return; }
      toast(errMessage(ex), "error");
    }
  }
  function tmOpenRoleArchiveMove(roleId, det, role) {
    const n = Number((det && det.member_count) || 0);
    const others = tmActiveCustomRoles().filter((r) => r.id !== roleId);
    openModal(`<div class="modal-head"><h3>Move members off this role</h3>
      <button class="x" onclick="__ent.closeModal()">×</button></div>
      <form id="tmRoleArchForm"><div class="modal-body">
        <p class="tm-hint">${esc((det && det.message) ||
          `${n} ${n === 1 ? "member is" : "members are"} still on “${(role && role.name) || "this role"}”. Pick where they should go.`)}</p>
        <div class="field"><label>Move ${n || "these"} ${n === 1 ? "member" : "members"} to</label>
          <select name="move_members_to">
            <option value="viewer">Viewer — read only</option>
            ${others.map((r) => `<option value="custom:${r.id}">${esc(r.name)}</option>`).join("")}
          </select></div>
        <div id="tmRoleArchError" class="auth-error hidden"></div>
      </div><div class="modal-foot">
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="submit" class="btn btn-danger" id="tmRoleArchSubmit">Move &amp; archive</button>
      </div></form>`);
    $("#tmRoleArchForm").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target; const btn = $("#tmRoleArchSubmit"); const err = $("#tmRoleArchError");
      err.classList.add("hidden");
      btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
      try {
        await api(`/roles/${roleId}/archive`, { method: "POST", body: { move_members_to: f.move_members_to.value } });
        toast("Role archived", "success");
        closeModal();
        await teamRefresh();
      } catch (ex) {
        err.textContent = errMessage(ex); err.classList.remove("hidden");
        btn.disabled = false; btn.innerHTML = "Move &amp; archive";
      }
    };
  }

  /* ============================ OFFICES ============================ */
  async function tmDrawBranches() {
    const mount = tmMount(); if (!mount) return;
    if (!can("branches.view")) {
      mount.innerHTML = deniedCard("You don't have permission to view offices. Ask a workspace admin for access.");
      return;
    }
    if (!tmMetaReady(mount)) return;
    if (teamUi.showArchivedBranches && !teamUi.branchList && !teamUi.branchError) {
      tmLoadingInto(mount);
      try { teamUi.branchList = await api("/branches?include_archived=1"); }
      catch (ex) { teamUi.branchError = ex; }
      if (state.view !== "team" || teamUi.tab !== "branches") return;
    }
    tmPaintBranches();
  }

  function tmPaintBranches() {
    const mount = tmMount(); if (!mount) return;
    const meta = teamUi.meta || {};
    const fromMeta = meta.branches || [];
    // The archived view needs its own fetch; merge the counts meta already has so a card
    // doesn't lose its numbers just because "show archived" is on.
    let list = fromMeta;
    if (teamUi.showArchivedBranches && teamUi.branchList) {
      const counts = {};
      fromMeta.forEach((b) => { counts[b.id] = b; });
      list = (teamUi.branchList.branches || teamUi.branchList || []).map((b) =>
        Object.assign({}, b, {
          member_count: b.member_count != null ? b.member_count : (counts[b.id] || {}).member_count,
          client_count: b.client_count != null ? b.client_count : (counts[b.id] || {}).client_count,
        }));
    }
    const canManage = can("branches.manage");
    const limit = (meta.limits && meta.limits.max_branches) || 50;
    const activeCount = list.filter((b) => b.is_active !== false).length;

    const card = (b) => {
      const archived = b.is_active === false;
      const num = (v) => (v == null ? "—" : v);
      return `<div class="br-card${b.is_default ? " is-default" : ""}${archived ? " br-archived" : ""}">
        <div class="br-card-top">
          <h4>${esc(b.name)}</h4>
          ${b.is_default ? `<span class="br-default-pill">Default</span>` : ""}
          ${archived ? `<span class="br-chip br-archived">Archived</span>` : ""}
          ${b.code ? `<div class="br-card-code">${esc(b.code)}</div>` : ""}
        </div>
        <div class="br-card-sub">${esc([b.city, b.state_region, b.country_code].filter(Boolean).join(", ")) || "No address on file"}</div>
        <div class="br-card-stats">
          <button type="button" class="br-card-stat" data-drill="members" data-bid="${b.id}"
            aria-label="Show the ${num(b.member_count)} team members in ${esc(b.name)}">
            <b>${num(b.member_count)}</b><span>${b.member_count === 1 ? "member" : "members"}</span></button>
          <button type="button" class="br-card-stat" data-drill="clients" data-bid="${b.id}"
            aria-label="Show the ${num(b.client_count)} clients filed under ${esc(b.name)}">
            <b>${num(b.client_count)}</b><span>${b.client_count === 1 ? "client" : "clients"}</span></button>
        </div>
        ${canManage ? `<div class="br-card-acts">
          ${archived
            ? `<button class="btn btn-soft btn-sm" data-bract="reactivate" data-bid="${b.id}">Reactivate</button>`
            : `<button class="btn btn-soft btn-sm" data-bract="edit" data-bid="${b.id}">Edit</button>
               ${b.is_default ? "" : `<button class="btn btn-ghost btn-sm" data-bract="default" data-bid="${b.id}">Make default</button>`}
               <button class="btn btn-ghost btn-sm" data-bract="assign" data-bid="${b.id}">Assign team</button>
               ${b.is_default ? "" : `<button class="btn btn-ghost btn-sm" data-bract="archive" data-bid="${b.id}">Archive</button>`}`}
        </div>` : ""}
      </div>`;
    };

    mount.innerHTML = `
      ${teamUi.branchError ? errBox(teamUi.branchError) : ""}
      <div class="tm-toolbar">
        <div><b>Offices</b><div class="tm-hint">${activeCount} of ${limit} used. Every client belongs to one office, which is what "their office only" access means.</div></div>
        <div class="spacer" style="flex:1"></div>
        <label class="tm-hint" for="brShowArchived" style="display:flex;align-items:center;gap:6px">
          <input type="checkbox" id="brShowArchived" aria-label="Show archived offices" ${
            teamUi.showArchivedBranches ? "checked" : ""}/> Show archived</label>
        ${canManage ? `<button class="btn btn-primary btn-sm" id="brCreate" ${activeCount >= limit ? "disabled" : ""}>+ Add office</button>` : ""}
      </div>
      ${list.length
        ? `<div class="br-grid">${list.map(card).join("")}</div>`
        : `<div class="card"><div class="card-body tm-hint">No offices yet.${canManage ? " Add your first one — every existing client will keep working, they just won't be filed under an office until you set one." : ""}</div></div>`}`;

    const showArch = $("#brShowArchived", mount);
    if (showArch) showArch.onchange = () => {
      teamUi.showArchivedBranches = showArch.checked;
      teamUi.branchList = null; teamUi.branchError = null;
      tmDrawBranches();
    };
    const create = $("#brCreate", mount);
    if (create) create.onclick = () => tmOpenBranchEditor(null);
    $$("[data-drill]", mount).forEach((b) => b.onclick = () => {
      const bid = b.dataset.bid;
      if (b.dataset.drill === "members") {
        teamUi.filters = { q: "", role: "", branch: String(bid), status: "" };
        teamUi.tab = "members";
        syncUrl("/enterprise/team?tab=members", { replace: true });
        teamDrawShell();
        teamDrawPanel();
      } else {
        state.filters.branch_id = String(bid);
        openClientsFiltered({});
      }
    });
    $$("[data-bract]", mount).forEach((b) => b.onclick = () => {
      const bid = parseInt(b.dataset.bid, 10);
      const act = b.dataset.bract;
      if (act === "edit") tmOpenBranchEditor(bid);
      else if (act === "default") tmSetDefaultBranch(bid);
      else if (act === "assign") tmOpenBranchMembers(bid);
      else if (act === "archive") tmArchiveBranch(bid);
      else if (act === "reactivate") tmReactivateBranch(bid);
    });
  }

  function tmBranchById(id) {
    const fromMeta = ((teamUi.meta || {}).branches || []).find((b) => b.id === id);
    if (fromMeta) return fromMeta;
    const all = (teamUi.branchList && (teamUi.branchList.branches || teamUi.branchList)) || [];
    return all.find((b) => b.id === id) || null;
  }

  // ---- Office time zones ---------------------------------------------------
  // The server validates the office zone against the IANA tz database, so the picker has
  // to emit real zone names — a free-text box let "IST" and "GMT+5:30" through, which look
  // configured and load as nothing. Intl ships the whole list natively (ES2022); the
  // fallback covers the older browsers where supportedValuesOf is missing.
  const TZ_FALLBACK = [
    "Asia/Kolkata", "Asia/Dubai", "Asia/Karachi", "Asia/Dhaka", "Asia/Kathmandu",
    "Asia/Colombo", "Asia/Singapore", "Asia/Manila", "Asia/Tokyo", "Asia/Shanghai",
    "Europe/London", "Europe/Dublin", "Europe/Paris", "Europe/Berlin", "Europe/Madrid",
    "Europe/Amsterdam", "Europe/Lisbon", "Europe/Rome", "Europe/Zurich", "Europe/Moscow",
    "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
    "America/Toronto", "America/Vancouver", "America/Sao_Paulo",
    "Australia/Sydney", "Australia/Melbourne", "Australia/Perth", "Australia/Brisbane",
    "Pacific/Auckland", "Africa/Lagos", "Africa/Nairobi", "Africa/Johannesburg", "UTC",
  ];

  // Older browser ICU still reports the PRE-rename IANA names — Chrome here lists
  // "Asia/Calcutta" and has no "Asia/Kolkata" at all — while newer ICU reports the modern
  // ones. Left alone, the string in the database would depend on whose laptop created the
  // office, and an Indian consultancy would be offered "Calcutta". Both spellings are links
  // to the same rules, so this map only buys one stable, non-archaic value; a rename it
  // misses is cosmetic, never wrong.
  const TZ_MODERN = {
    "Asia/Calcutta": "Asia/Kolkata",
    "Asia/Rangoon": "Asia/Yangon",
    "Asia/Saigon": "Asia/Ho_Chi_Minh",
    "Asia/Katmandu": "Asia/Kathmandu",
    "Asia/Dacca": "Asia/Dhaka",
    "Asia/Thimbu": "Asia/Thimphu",
    "Europe/Kiev": "Europe/Kyiv",
    "America/Godthab": "America/Nuuk",
    "America/Buenos_Aires": "America/Argentina/Buenos_Aires",
    "Atlantic/Faeroe": "Atlantic/Faroe",
    "Pacific/Ponape": "Pacific/Pohnpei",
    "Pacific/Truk": "Pacific/Chuuk",
  };

  function tzModern(name) {
    const mapped = TZ_MODERN[name];
    // Only move to the modern name if this browser can actually format it — an ICU too old
    // to know "Asia/Kolkata" must keep offering the spelling it does know.
    return mapped && tzIsValid(mapped) ? mapped : name;
  }

  function tzIsValid(name) {
    if (!name) return false;
    try { new Intl.DateTimeFormat("en-US", { timeZone: name }); return true; } catch (e) { return false; }
  }

  function tzBrowser() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (e) { return ""; }
  }

  function tzOffsetLabel(name) {
    try {
      const part = new Intl.DateTimeFormat("en-US", { timeZone: name, timeZoneName: "shortOffset" })
        .formatToParts(new Date()).find((p) => p.type === "timeZoneName");
      return part ? part.value : "";
    } catch (e) { return ""; }
  }

  // ~600 zones × one Intl formatter each is a visible pause, so the markup is built once
  // per page load and the current value applied to the live <select> afterwards. Offsets
  // are therefore a snapshot — good enough for a label, and a DST flip mid-session only
  // misprints the hint, never the stored value.
  let _tzOptionsHtml = null;
  let _tzListIsFallback = false;

  function tzOptionsHtml() {
    if (_tzOptionsHtml !== null) return _tzOptionsHtml;
    let names;
    try { names = Intl.supportedValuesOf("timeZone"); } catch (e) { names = null; }
    if (!names || !names.length) { names = TZ_FALLBACK.slice(); _tzListIsFallback = true; }
    const groups = new Map();
    const seen = new Set(["UTC"]);   // rendered separately below
    names.forEach((raw) => {
      const n = tzModern(raw);
      if (seen.has(n)) return;   // both spellings present on some ICU builds
      seen.add(n);
      const region = n.indexOf("/") > 0 ? n.slice(0, n.indexOf("/")) : "Other";
      if (!groups.has(region)) groups.set(region, []);
      groups.get(region).push(n);
    });
    // supportedValuesOf omits UTC, which is a legitimate answer for an org that would
    // rather not pick a city — offer it up top rather than stranded in "Other".
    let html = `<option value="">Not set</option><option value="UTC">UTC</option>`;
    Array.from(groups.keys()).sort().forEach((region) => {
      const opts = groups.get(region).sort().map((n) => {
        const off = tzOffsetLabel(n);
        const city = (n.indexOf("/") > 0 ? n.slice(region.length + 1) : n).replace(/_/g, " ");
        return `<option value="${esc(n)}">${esc(city)}${off ? " · " + esc(off) : ""}</option>`;
      }).join("");
      html += `<optgroup label="${esc(region.replace(/_/g, " "))}">${opts}</optgroup>`;
    });
    _tzOptionsHtml = html;
    return html;
  }

  /** Point a freshly-rendered office <select> at `stored`. Returns a note to show under the
   *  field, "" when the value landed cleanly.
   *
   *  What counts as valid is membership in the option list, NOT whether Intl accepts it:
   *  Chrome takes CLDR abbreviations the server's tz database has never heard of ("IST",
   *  "PST", and "EST" — which it resolves to America/Panama, almost certainly not what
   *  anyone meant). Gating on Intl would show those as selected and then 422 on save. */
  function tzApplyValue(sel, stored, isEdit) {
    const raw = (stored || "").trim() || (isEdit ? "" : tzBrowser());
    if (!raw) return "";
    const has = (v) => v && Array.prototype.some.call(sel.options, (o) => o.value === v);
    const want = tzModern(raw);
    if (has(want)) { sel.value = want; return ""; }

    // On an ICU too old for supportedValuesOf the list is TZ_FALLBACK, so a legitimate zone
    // will often be missing. Carry it over rather than accusing the office of bad data.
    if (_tzListIsFallback && tzIsValid(want)) {
      const opt = document.createElement("option");
      opt.value = want;
      opt.textContent = want.replace(/_/g, " ");
      sel.insertBefore(opt, sel.options[1] || null);
      sel.value = want;
      return "";
    }

    // Free text left over from before this was a picker. Interpret it where Intl can, but
    // say so out loud — the reading is a guess, and a wrong guess about a time zone is the
    // kind of thing nobody notices until a reminder fires on the wrong day.
    let resolved = "";
    try {
      resolved = tzModern(Intl.DateTimeFormat(undefined, { timeZone: want }).resolvedOptions().timeZone || "");
    } catch (e) { resolved = ""; }
    if (has(resolved)) {
      sel.value = resolved;
      return `Saved as “${raw}” — reading that as ${resolved.replace(/_/g, " ")}. Change it if that's wrong.`;
    }
    sel.value = "";
    return `Saved as “${raw}”, which isn't a zone we can resolve. Pick the office's zone — saving now clears it.`;
  }

  function tmOpenBranchEditor(branchId) {
    const b = branchId ? (tmBranchById(branchId) || {}) : {};
    openModal(`<div class="modal-head"><h3>${branchId ? "Edit office" : "Add an office"}</h3>
      <button class="x" onclick="__ent.closeModal()">×</button></div>
      <form id="tmBranchForm"><div class="modal-body">
        <div class="mw-grid mw-sec">
          <div class="field span2"><label>Office name *</label>
            <input name="name" required maxlength="80" value="${esc(b.name || "")}" placeholder="e.g. Banjara Hills"/></div>
          <div class="field"><label>Short code</label>
            <input name="code" maxlength="16" value="${esc(b.code || "")}" placeholder="e.g. HYD-BH"/></div>
          <div class="field"><label>City</label><input name="city" maxlength="60" value="${esc(b.city || "")}"/></div>
          <div class="field"><label>State / region</label><input name="state_region" maxlength="60" value="${esc(b.state_region || "")}"/></div>
          <div class="field"><label>Country code</label>
            <input name="country_code" maxlength="2" value="${esc(b.country_code || "")}" placeholder="IN"/></div>
          <div class="field span3"><label>Address</label><input name="address_line" maxlength="200" value="${esc(b.address_line || "")}"/></div>
          <div class="field"><label>Phone</label><input name="phone" inputmode="tel" maxlength="32" value="${esc(b.phone || "")}"/></div>
          <div class="field"><label>Email</label><input type="email" name="email" maxlength="120" value="${esc(b.email || "")}"/></div>
          <div class="field"><label>Time zone</label>
            <select name="timezone" id="tmBranchTz">${tzOptionsHtml()}</select>
            <div class="hint" id="tmBranchTzHint"></div></div>
        </div>
        ${branchId ? `<div class="tm-hint">Renaming an office updates it on every client filed under it.</div>` : ""}
        <div id="tmBranchError" class="auth-error hidden"></div>
      </div><div class="modal-foot">
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary" id="tmBranchSubmit">${branchId ? "Save office" : "Add office"}</button>
      </div></form>`, { wide: true });
    const tzWarning = tzApplyValue($("#tmBranchTz"), b.timezone, !!branchId);
    const tzHint = $("#tmBranchTzHint");
    tzHint.textContent = tzWarning
      || (branchId ? "" : "Pre-filled from your device — change it if this office sits elsewhere.");
    tzHint.classList.toggle("tm-tz-warn", !!tzWarning);
    $("#tmBranchForm").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target; const btn = $("#tmBranchSubmit"); const err = $("#tmBranchError");
      err.classList.add("hidden");
      const body = {};
      ["name", "code", "city", "state_region", "country_code", "address_line", "phone", "email", "timezone"].forEach((k) => {
        if (!f[k]) return;
        const v = (f[k].value || "").trim();
        if (k === "name") { body.name = v; return; }
        body[k] = v || null;
      });
      if (body.country_code) body.country_code = body.country_code.toUpperCase();
      btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
      try {
        if (branchId) await api(`/branches/${branchId}`, { method: "PATCH", body: body });
        else await api("/branches", { method: "POST", body: body });
        toast(branchId ? "Office updated" : "Office added", "success");
        closeModal();
        await teamRefresh();
      } catch (ex) {
        err.textContent = errMessage(ex); err.classList.remove("hidden");
        btn.disabled = false; btn.textContent = branchId ? "Save office" : "Add office";
      }
    };
  }

  async function tmSetDefaultBranch(branchId) {
    try {
      await api(`/branches/${branchId}/set-default`, { method: "POST", body: {} });
      toast("Default office updated", "success");
      await teamRefresh();
    } catch (ex) { toast(errMessage(ex), "error"); }
  }
  async function tmReactivateBranch(branchId) {
    try {
      await api(`/branches/${branchId}/reactivate`, { method: "POST", body: {} });
      toast("Office reactivated", "success");
      await teamRefresh();
    } catch (ex) { toast(errMessage(ex), "error"); }
  }
  async function tmArchiveBranch(branchId) {
    const b = tmBranchById(branchId) || {};
    const ok = await confirmModal(
      `“${b.name || "This office"}” stops being available for new clients. It's archived, not deleted, so its history stays readable.`,
      { title: "Archive office?", okText: "Archive" });
    if (!ok) return;
    try {
      await api(`/branches/${branchId}/archive`, { method: "POST", body: {} });
      toast("Office archived", "success");
      await teamRefresh();
    } catch (ex) {
      const det = errDetail(ex);
      if (ex.status === 409 && det) { tmOpenBranchArchiveMove(branchId, det); return; }
      toast(errMessage(ex), "error");
    }
  }
  function tmOpenBranchArchiveMove(branchId, det) {
    const b = tmBranchById(branchId) || {};
    const others = ((teamUi.meta || {}).branches || []).filter((x) => x.is_active !== false && x.id !== branchId);
    const clients = Number(det.client_count || 0);
    const members = Number(det.member_count || 0);
    // Same false affordance as the deactivate modal: the server refuses to archive an office
    // whose clients or members have nowhere to go, so "— Leave them where they are —" could
    // never succeed. Placeholder instead, and the submit waits for a real destination.
    const pick = (nm, label, count) => `<div class="field"><label>${esc(label)}</label>
      <select name="${nm}"><option value="" disabled selected>Choose an office…</option>
        ${others.map((o) => `<option value="${o.id}">${esc(o.name)}</option>`).join("")}
      </select><div class="tm-hint">${count} ${count === 1 ? "record" : "records"}</div></div>`;
    openModal(`<div class="modal-head"><h3>Move ${esc(b.name || "this office")}'s work</h3>
      <button class="x" onclick="__ent.closeModal()">×</button></div>
      <form id="tmBrArchForm"><div class="modal-body">
        <p class="tm-hint">${esc(det.message || "This office still has clients or members attached.")}</p>
        ${clients ? pick("reassign_clients_to_branch_id", "Move clients to", clients) : ""}
        ${members ? pick("reassign_members_to_branch_id", "Move members to", members) : ""}
        ${!others.length ? `<div class="br-picker-empty">There's no other active office to move them to. Add one first.</div>` : ""}
        <div id="tmBrArchError" class="auth-error hidden"></div>
      </div><div class="modal-foot">
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">${others.length ? "Cancel" : "Close"}</button>
        ${others.length ? `<button type="submit" class="btn btn-danger" id="tmBrArchSubmit">Move &amp; archive</button>` : ""}
      </div></form>`);
    bindValidity($("#tmBrArchSubmit"), $("#tmBrArchForm"),
      () => $$("#tmBrArchForm select").every((s) => !!s.value), "Choose where the work moves to first");
    $("#tmBrArchForm").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target; const btn = $("#tmBrArchSubmit"); const err = $("#tmBrArchError");
      err.classList.add("hidden");
      const body = {};
      if (f.reassign_clients_to_branch_id && f.reassign_clients_to_branch_id.value) {
        body.reassign_clients_to_branch_id = parseInt(f.reassign_clients_to_branch_id.value, 10);
      }
      if (f.reassign_members_to_branch_id && f.reassign_members_to_branch_id.value) {
        body.reassign_members_to_branch_id = parseInt(f.reassign_members_to_branch_id.value, 10);
      }
      // withBusy restores the button's original markup, which also retires the old
      // `innerHTML = "Move &amp; archive"` restore — that double-escaped, so any failure
      // left the button reading literally "Move &amp; archive".
      await withBusy(btn, "", async () => {
        try {
          await api(`/branches/${branchId}/archive`, { method: "POST", body: body });
          toast("Office archived", "success");
          closeModal();
          await teamRefresh();
        } catch (ex) {
          err.textContent = errMessage(ex); err.classList.remove("hidden");
        }
      });
    };
  }

  async function tmOpenBranchMembers(branchId) {
    const b = tmBranchById(branchId) || {};
    openModal(`<div class="modal-head"><h3>${esc(b.name || "Office")} — team</h3>
      <button class="x" onclick="__ent.closeModal()">×</button></div>
      <div class="modal-body"><div class="center-load"><div class="spinner dark"></div></div></div>`);
    let d;
    try { d = await api(`/branches/${branchId}/members`); }
    catch (ex) {
      openModal(`<div class="modal-head"><h3>${esc(b.name || "Office")} — team</h3>
        <button class="x" onclick="__ent.closeModal()">×</button></div>
        <div class="modal-body">${errBox(ex)}</div>
        <div class="modal-foot"><button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Close</button></div>`);
      return;
    }
    const rows = (d.members || d || []);
    openModal(`<div class="modal-head"><h3>${esc(b.name || "Office")} — team</h3>
      <button class="x" onclick="__ent.closeModal()">×</button></div>
      <div class="modal-body">
        ${rows.length ? `<div style="display:grid;gap:12px">${rows.map((m) => {
          const [b1, b2] = avatarColor(m.email || m.full_name);
          return `<div class="tm-meta">
            <div class="tm-av" style="background:linear-gradient(135deg,${b1},${b2})">${esc(initials(m.full_name || m.email).toUpperCase())}</div>
            <div><b>${esc(m.full_name || m.email)}</b><span>${esc(m.email || "")}${
              m.role_label ? " · " + esc(m.role_label) : ""}${m.is_primary ? " · primary office" : ""}</span></div>
          </div>`;
        }).join("")}</div>`
          : `<div class="br-picker-empty">Nobody is assigned to this office yet.</div>`}
        <p class="tm-hint" style="margin-top:14px">Add or remove people from an office in the Members tab — open their ⋯ menu and choose <b>Edit access</b>.</p>
      </div>
      <div class="modal-foot"><button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Close</button></div>`);
  }

  /* ============================ ACCESS LOG ============================ */
  // Icon + tone per audited action. Anything unrecognised still renders (a new server-side
  // action must never produce a blank row).
  const AL_ICONS = {
    member_invited: ["✉️", "info"], member_added: ["👤", "ok"], member_removed: ["🚫", "danger"],
    member_deactivated: ["🚫", "warn"], member_reactivated: ["✅", "ok"],
    member_role_changed: ["🔀", "info"], member_access_changed: ["🔐", "warn"],
    member_profile_updated: ["✏️", "info"], member_branches_changed: ["🏢", "info"],
    role_created: ["🔐", "ok"], role_updated: ["🔐", "info"], role_archived: ["🗄️", "warn"],
    role_duplicated: ["🔐", "info"],
    branch_created: ["🏢", "ok"], branch_updated: ["🏢", "info"], branch_archived: ["🗄️", "warn"],
    branch_reactivated: ["✅", "ok"], branch_default_changed: ["📌", "info"],
    clients_reassigned: ["🔀", "warn"], ownership_transferred: ["👑", "danger"],
    // The audited action is `owner_transferred` (the notification type is the -ship one).
    owner_transferred: ["👑", "danger"], owner_transfer_code_sent: ["🔑", "warn"],
  };
  function alValue(v) {
    if (v == null || v === "") return "—";
    if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
    if (typeof v === "boolean") return v ? "Yes" : "No";
    if (typeof v === "object") {
      // The audit's nested shapes (e.g. {granted:[…], blocked:[…]}) read as prose. Nobody
      // auditing who-changed-what should have to parse braces and quotes to do it.
      try {
        const parts = Object.keys(v).map((k) => {
          const inner = v[k];
          const txt = Array.isArray(inner) ? (inner.length ? inner.join(", ") : "none")
            : (inner == null || inner === "" ? "none" : String(inner));
          return String(k).replace(/_/g, " ") + ": " + txt;
        });
        return parts.length ? parts.join(" · ") : "—";
      } catch (e) { return "—"; }
    }
    return String(v);
  }
  function alDetailHtml(row) {
    let d = row.detail != null ? row.detail : row.detail_json;
    if (typeof d === "string") { try { d = JSON.parse(d); } catch (e) { d = null; } }
    if (!d || typeof d !== "object") return "";
    const before = d.before || {};
    const after = d.after || {};
    const keys = Array.from(new Set(Object.keys(before).concat(Object.keys(after))));
    if (!keys.length) return "";
    return `<details class="al-detail"><summary>What changed</summary><div class="al-detail-grid">
      ${keys.map((k) => `<span>${esc(String(k).replace(/_/g, " "))}</span>
        <b><del>${esc(alValue(before[k]))}</del> <ins>${esc(alValue(after[k]))}</ins></b>`).join("")}
    </div></details>`;
  }

  async function tmDrawLog() {
    const mount = tmMount(); if (!mount) return;
    if (!can("audit.view")) {
      mount.innerHTML = deniedCard("You don't have permission to view the access log. Ask a workspace admin for access.");
      return;
    }
    if (!teamUi.log.loaded && !teamUi.log.loading) { tmLoadingInto(mount); await tmLoadLog(true); }
    tmPaintLog();
  }
  async function tmLoadLog(reset) {
    const L = teamUi.log;
    if (reset) { L.rows = []; L.total = 0; L.hasMore = false; }
    L.loading = true; L.error = null;
    const p = new URLSearchParams();
    p.set("limit", "50");
    p.set("offset", String(L.rows.length));
    if (L.filters.action) p.set("action", L.filters.action);
    if (L.filters.target_user_id) p.set("target_user_id", L.filters.target_user_id);
    if (L.filters.days) p.set("days", L.filters.days);
    try {
      const d = await api("/team/access-log?" + p.toString());
      const rows = d.entries || d.log || d.rows || [];
      L.rows = L.rows.concat(rows);
      L.total = d.total != null ? d.total : L.rows.length;
      L.hasMore = d.has_more != null ? !!d.has_more : L.rows.length < L.total;
    } catch (ex) { L.error = ex; }
    L.loading = false;
    L.loaded = true;
  }
  function tmPaintLog() {
    const mount = tmMount(); if (!mount) return;
    const L = teamUi.log;
    const members = ((teamUi.team || {}).members || []);
    const actions = Array.from(new Set(L.rows.map((r) => r.action).filter(Boolean))).sort();
    const rows = L.rows.map((r) => {
      const [ic, tone] = AL_ICONS[r.action] || ["📜", "info"];
      const actor = r.actor_name || (r.actor_user_id ? "User #" + r.actor_user_id : "System");
      const target = r.target_name || "";
      return `<div class="al-row">
        <div class="al-icon" data-tone="${tone}">${ic}</div>
        <div class="al-main">
          <b>${esc(r.summary || String(r.action || "").replace(/_/g, " "))}</b>
          <div class="al-meta">${esc(actor)}${target ? " → " + esc(target) : ""} · ${esc(notifAgo(r.created_at))}${
            r.ip_address ? " · " + esc(r.ip_address) : ""}</div>
          ${alDetailHtml(r)}
        </div>
      </div>`;
    }).join("");

    mount.innerHTML = `
      <div class="tm-toolbar">
        <select id="alDays" class="tm-input" aria-label="Time range">
          <option value="7" ${L.filters.days === "7" ? "selected" : ""}>Last 7 days</option>
          <option value="30" ${L.filters.days === "30" ? "selected" : ""}>Last 30 days</option>
          <option value="90" ${L.filters.days === "90" ? "selected" : ""}>Last 90 days</option>
          <option value="" ${L.filters.days === "" ? "selected" : ""}>All time</option>
        </select>
        <select id="alAction" class="tm-input" aria-label="Filter by action">
          <option value="">All changes</option>
          ${actions.map((a) => `<option value="${esc(a)}" ${L.filters.action === a ? "selected" : ""}>${esc(String(a).replace(/_/g, " "))}</option>`).join("")}
        </select>
        <select id="alMember" class="tm-input" aria-label="Filter by member">
          <option value="">Anyone</option>
          ${members.map((m) => `<option value="${m.user_id}" ${L.filters.target_user_id === String(m.user_id) ? "selected" : ""}>${esc(m.full_name || m.email)}</option>`).join("")}
        </select>
      </div>
      ${L.error ? errBox(L.error) : ""}
      ${rows
        ? `<div class="al-list">${rows}</div>`
        : (L.error ? "" : `<div class="al-empty"><b>Nothing recorded yet</b>Role changes, office changes and permission overrides all show up here, with who made them and what changed.</div>`)}
      ${L.hasMore ? `<div style="text-align:center;margin-top:16px">
        <button class="btn btn-ghost btn-sm" id="alMore" ${L.loading ? "disabled" : ""}>${L.loading ? "Loading…" : "Load more"}</button></div>` : ""}`;

    const bind = (id, key) => {
      const el = $(id, mount);
      if (el) el.onchange = async () => {
        L.filters[key] = el.value;
        tmLoadingInto(mount);
        await tmLoadLog(true);
        if (state.view === "team" && teamUi.tab === "log") tmPaintLog();
      };
    };
    bind("#alDays", "days"); bind("#alAction", "action"); bind("#alMember", "target_user_id");
    const more = $("#alMore", mount);
    if (more) more.onclick = async () => {
      more.disabled = true; more.textContent = "Loading…";
      await tmLoadLog(false);
      if (state.view === "team" && teamUi.tab === "log") tmPaintLog();
    };
  }

  /* ============================ MY ACCESS ============================ */
  async function tmDrawMyAccess() {
    const mount = tmMount(); if (!mount) return;
    if (!tmMetaReady(mount)) return;
    if (!teamUi.mine && !teamUi.mineError) {
      tmLoadingInto(mount);
      try { teamUi.mine = await api("/team/my-access"); }
      catch (ex) { teamUi.mineError = ex; }
      if (state.view !== "team" || teamUi.tab !== "myaccess") return;
    }
    if (teamUi.mineError) { mount.innerHTML = errBox(teamUi.mineError); return; }
    const d = teamUi.mine || {};
    // The contract describes this payload's contents but not its exact field names, so
    // read it tolerantly and fall back to the session's own access block.
    const acc = d.access || d.me || state.access || {};
    const added = d.added || d.capability_grants || [];
    const blocked = d.blocked || d.capability_denies || [];
    // Fall back to the role preset's own capability list, so the matrix can never read
    // "Not allowed" for everything just because the payload named that field differently.
    let inherited = d.inherited || d.role_capabilities || [];
    if (!inherited.length) {
      const rp = (acc.role_key === "custom")
        ? tmActiveCustomRoles().find((r) => r.id === acc.custom_role_id)
        : (((teamUi.meta || {}).role_presets) || []).find((r) => r.key === acc.role_key);
      inherited = (rp && rp.capabilities) || (Array.isArray(acc.capabilities) && acc.capabilities.indexOf("*") === -1 ? acc.capabilities : []);
    }
    const branches = d.branches || acc.branches || [];
    const scope = acc.data_scope || "assigned";
    const scopeInfo = scopeMeta(scope) || {};
    const roleDesc = d.role_description ||
      ((((teamUi.meta || {}).role_presets) || []).find((r) => r.key === acc.role_key) || {}).description || "";
    const effectiveCount = Array.isArray(d.capabilities || acc.capabilities)
      ? (d.capabilities || acc.capabilities).length : null;

    mount.innerHTML = `
      <div class="card"><div class="card-body">
        <div class="rl-card-top" style="margin-bottom:8px">${roleBadgeHtml(acc.role_key, acc.role_label)}</div>
        ${roleDesc ? `<p class="tm-hint">${esc(roleDesc)}</p>` : ""}
        <div class="cp-sub-label">What you can see</div>
        <p style="margin:0 0 4px;font-size:14px">${esc(scopeInfo.label || SCOPE_FALLBACK_LABEL[scope] || "Only your own clients")}</p>
        <p class="tm-hint">${esc(scopeInfo.desc || (scope === "assigned"
          ? "Clients assigned to you, plus ones you created."
          : scope === "branch" ? "Every client filed under your office." : "Every client in the workspace."))}</p>
        ${scope === "branch" ? `<div class="cp-sub-label">Your offices</div>
          ${branches.length
            ? `<span class="br-chips">${branches.map((b) => `<span class="br-chip${
                Number(acc.primary_branch_id) === Number(b.id || b) ? " is-primary" : ""}">${esc(b.name || b)}</span>`).join("")}</span>`
            : `<p class="tm-hint">You're not assigned to an office yet, so no client records are in scope. Ask a workspace admin to add you to one.</p>`}` : ""}
        ${effectiveCount != null ? `<p class="tm-hint" style="margin-top:14px">${effectiveCount} permissions in total${
          added.length ? ` · ${added.length} added just for you` : ""}${blocked.length ? ` · ${blocked.length} blocked` : ""}.</p>` : ""}
      </div></div>
      <details class="cap-fold" open><summary>Everything you're allowed to do</summary>
        ${capMatrixHtml({ base: inherited, grants: added, denies: blocked }, null,
          { mode: "readonly", idPrefix: "mine", isOwner: !!acc.is_owner })}
      </details>
      <p class="tm-hint" style="margin-top:14px">Need something you can't do? Ask a workspace admin — they can change this from Team → Members.</p>`;
  }

  /* ============================================================
     BILLING
     ============================================================ */
  async function renderBilling() {
    const c = $("#content");
    c.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
    let d;
    try { d = await api("/billing/subscription"); } catch (ex) { c.innerHTML = errBox(ex); return; }
    state.subscription = d.subscription; updatePlanChip();
    const sub = d.subscription;
    const canManage = can("billing.manage");

    const pct = (used, max) => (max === -1 ? 0 : Math.min(100, Math.round((used / Math.max(1, max)) * 100)));
    const cap = (v) => (v === -1 || v == null ? "∞" : Number(v).toLocaleString());
    state.billingCoupon = state.billingCoupon || null;
    state.billingPlans = d.plans || [];
    const bCoupon = state.billingCoupon;

    // Prices are quoted EX-GST ("₹2,999/month + GST"), so the card shows the subtotal and
    // names the tax rather than folding it in. The charged total is spelled out underneath
    // so nobody meets it for the first time inside the Razorpay modal.
    const planPriceBlock = (p) => {
      if (p.is_free) return `<div class="price">${esc(p.monthly_display)}<small>/mo</small></div>
        <div class="price-off" style="color:var(--text-2)">${esc(p.price_note)}</div>`;
      const taxLine = p.tax_minor
        ? `<div class="price-tax">+ ${esc(p.tax_label || "tax")} · ${esc(p.total_display)}/mo charged</div>` : "";
      // `taxLine` already names the tax AND the charged total, so a separate "+ GST" note
      // above it would say the same thing twice.
      if (!bCoupon) return `<div class="price">${esc(p.monthly_display)}<small>/mo</small></div>${taxLine}`;
      // Discount applies to the ex-tax subtotal — same order as the server's
      // checkout_quote(), so the preview here and the order there always agree.
      const sub2 = Math.max(0, Math.round(p.monthly_paise * (100 - bCoupon.percent) / 100));
      const tax2 = Math.round(sub2 * (p.tax_percent || 0) / 100);
      return `<div class="price">${fmtMoney(sub2, p.currency || "INR")}<small>/mo</small><span class="price-was">${esc(p.monthly_display)}</span></div>
        <div class="price-off">${esc(bCoupon.percent_display)} off applied</div>
        ${p.tax_percent ? `<div class="price-tax">+ ${esc(p.tax_label)} · ${esc(fmtMoney(sub2 + tax2, p.currency || "INR"))}/mo charged</div>` : ""}`;
    };

    const planCard = (p) => {
      const isCurrent = sub.plan === p.key;
      const isSandbox = p.is_free;
      return `<div class="plan-card ${p.is_popular ? "popular" : ""} ${isCurrent ? "current-plan" : ""}">
        ${p.is_popular ? `<div class="pop-tag">Most popular</div>` : ""}
        <h3>${esc(p.label)}</h3><div class="tagline">${esc(p.tagline)}</div>
        ${planPriceBlock(p)}
        <div class="plan-caps">
          <div><b>${cap(p.max_seats)}</b><span>users</span></div>
          <div><b>${cap(p.max_clients)}</b><span>active clients</span></div>
          <div><b>${Number(p.included_credits).toLocaleString()}</b><span>AI credits${p.credits_recur ? "/mo" : " once"}</span></div>
        </div>
        <ul>${p.features.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>
        ${isCurrent ? `<div class="plan-current-tag">✓ Current plan</div>`
          : (isSandbox ? `<div class="plan-current-tag" style="color:var(--muted)">Where every workspace starts</div>`
          : (canManage ? `<button class="btn ${p.is_popular ? "btn-primary" : "btn-ghost"} btn-block" onclick="__ent.checkout('${p.key}',this)">${sub.is_sandbox ? "Choose " + esc(p.label) : "Switch to " + esc(p.label)}</button>`
            : `<div class="plan-current-tag" style="color:var(--muted)">Ask an admin to upgrade</div>`))}
      </div>`;
    };

    const allowance = Number(sub.included_credits || 0);
    c.innerHTML = `
      <div class="card" style="margin-bottom:24px"><div class="card-body" style="display:flex;align-items:center;gap:24px;flex-wrap:wrap">
        <div style="flex:1;min-width:220px">
          <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)">Current plan</div>
          <div style="font-size:24px;font-weight:760;margin:4px 0">${esc(sub.plan_label)} ${sub.is_sandbox ? `<span style="font-size:13px;color:var(--warning);font-weight:600">· ${sub.trial_expired ? "evaluation ended" : sub.trial_days_left + " days left"}</span>` : ""}</div>
          <div style="font-size:13px;color:var(--text-2)">${
            sub.current_period_end && !sub.is_sandbox
              // Say which of the two it is. "Renews" on a plan with no mandate is a promise
              // the system does not keep — nothing auto-charges, and the org would lapse
              // silently while believing it was covered.
              ? (sub.auto_renews ? "Renews automatically on " + fmtDate(sub.current_period_end)
                 : sub.cancel_at_period_end ? "Auto-renewal off — ends " + fmtDate(sub.current_period_end)
                 : "Ends " + fmtDate(sub.current_period_end) + " — renew manually")
            : sub.trial_ends_at ? "Sandbox ends " + fmtDate(sub.trial_ends_at) : ""
          }${sub.monthly_display && !sub.is_sandbox ? ` · ${esc(sub.monthly_display)}/mo${sub.tax_label ? " + " + esc(sub.tax_label) : ""}` : ""}</div>
          ${sub.mandate_status === "halted" ? `<div style="font-size:13px;color:var(--warning);margin-top:6px"><b>Your card was declined.</b> Update it and renew to keep your plan.</div>` : ""}
          ${canManage && sub.auto_renews ? `<button type="button" class="btn btn-ghost btn-sm" style="margin-top:8px;padding-left:0" onclick="__ent.cancelPlanRenewal(this)">Turn off auto-renewal</button>` : ""}
        </div>
        <div style="flex:1;min-width:240px">
          <div style="display:flex;justify-content:space-between;font-size:13px"><span style="color:var(--text-2)">Active clients</span><b>${sub.clients_used} / ${cap(sub.max_clients)}</b></div>
          <div class="usage-bar"><div class="usage-fill" style="width:${pct(sub.clients_used, sub.max_clients)}%"></div></div>
          <div style="display:flex;justify-content:space-between;font-size:13px;margin-top:10px"><span style="color:var(--text-2)">Team seats</span><b>${sub.seats_used} / ${cap(sub.max_seats)}</b></div>
          <div class="usage-bar"><div class="usage-fill" style="width:${pct(sub.seats_used, sub.max_seats)}%"></div></div>
        </div>
        ${allowance ? `<div style="flex:0 0 auto;min-width:170px;text-align:right">
          <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)">AI credits included</div>
          <div style="font-size:24px;font-weight:760;margin:4px 0">${allowance.toLocaleString()}</div>
          <div style="font-size:13px;color:var(--text-2)">${sub.credits_recur ? "every month" : "one-time"} · <a href="#" onclick="__ent.go('credits');return false">see balance</a></div>
        </div>` : ""}
      </div></div>
      ${sub.grandfathered ? `<div class="card" style="margin-bottom:18px;border-left:4px solid var(--warning,#f59e0b)"><div class="card-body">
        <b>Choose a plan by ${sub.grace_ends_at ? esc(fmtDate(sub.grace_ends_at)) : "the deadline"}</b>
        <div style="font-size:13px;color:var(--text-2);margin-top:4px">
          Your workspace was created before Rilono plans launched, so nothing is limited for now${sub.over_cap ? " — including the clients and seats already above these caps, which you keep either way" : ""}.
          Pick a plan below before then and nothing changes for your team.
        </div>
      </div></div>` : (sub.trial_expired ? `<div class="card" style="margin-bottom:18px;border-left:4px solid var(--warning,#f59e0b)"><div class="card-body">
        <b>Your 14-day sandbox evaluation has ended.</b>
        <div style="font-size:13px;color:var(--text-2);margin-top:4px">Everything in your workspace is intact and readable. Choose a plan below to start adding clients and team members again.</div>
      </div></div>` : "")}
      ${canManage && d.plans.length ? couponRow(bCoupon, "applyBillingCoupon", "removeBillingCoupon", "billingCouponInput", "plans") : ""}
      <div class="plan-grid">${d.plans.map(planCard).join("")}</div>
      ${!d.plans.length ? "" : `<p style="text-align:center;color:var(--muted);font-size:13px;margin-top:18px">
        Prices are per month and exclusive of GST. Secure payments via Razorpay. Cancel anytime.<br>
        Your plan's AI credits refresh each billing period; unused credits from the allowance don't carry over. Need more? Top up any time in <a href="#" onclick="__ent.go('credits');return false">Credits</a>.
      </p>`}`;
  }

  async function cancelPlanRenewal(el) {
    if (el && el.disabled) return;
    // Cancelling stops the NEXT charge only — the period already paid for is kept, so this
    // is not destructive and does not need a scary confirmation. It does need an in-app
    // dialog rather than the browser's: native confirm() shows the raw "acme.lvh.me says"
    // chrome, and it froze the page instead of locking the button, so the click was live
    // again the moment it closed.
    const ok = await confirmModal(
      "Your plan stays active until the end of the period you've already paid for.",
      { title: "Turn off auto-renewal?", okText: "Turn it off", danger: false });
    if (!ok) return;
    await withBusy(el, "", async () => {
      try {
        const r = await api("/billing/cancel", { method: "POST", body: {} });
        state.subscription = r.subscription;
        updatePlanChip();
        toast(r.message || "Auto-renewal is off.", "success");
        renderBilling();
      } catch (ex) { toast(ex.message, "error"); }
    });
  }

  async function applyBillingCoupon() {
    const input = $("#billingCouponInput");
    const code = ((input && input.value) || "").trim();
    if (!code) { toast("Enter a discount code.", "error"); return; }
    const paid = (state.billingPlans || []).filter((p) => !p.is_free && p.monthly_paise > 0);
    if (!paid.length) { toast("No paid plans available for discounts.", "error"); return; }
    await withBusy($("#billingCouponInputApply"), "", async () => {
      let res;
      try {
        res = await api("/coupons/validate", { method: "POST", body: { code, context: "billing", plan: paid[0].key, billing_cycle: state.billingCycle } });
      } catch (ex) { toast(ex.message || "Invalid discount code.", "error"); return; }
      state.billingCoupon = { code: res.code, percent: res.percent_off, percent_display: res.percent_display };
      toast(res.percent_display + " discount applied.", "success");
      renderBilling();
    });
  }
  function removeBillingCoupon() { state.billingCoupon = null; renderBilling(); }

  // A plan checkout stays "in flight" well past its first await: POST /billing/checkout
  // creates a Razorpay order or mandate, and the attempt is only really over once the
  // payment sheet closes. Left unguarded, a second click during that window opens a second
  // order — and on the recurring path a second MANDATE — so the flag spans the whole thing
  // and is released on every way out, including the user simply dismissing the sheet.
  let checkoutBusy = false;
  async function checkout(plan, el) {
    if (checkoutBusy) return;
    checkoutBusy = true;
    if (el) el.disabled = true;
    let released = false;
    const release = () => {
      if (released) return;
      released = true;
      checkoutBusy = false;
      // renderBilling() swaps the card out on the success path; then this is a no-op.
      if (el && el.isConnected) el.disabled = false;
    };
    let res;
    const couponCode = state.billingCoupon ? state.billingCoupon.code : undefined;
    try { res = await api("/billing/checkout", { method: "POST", body: { plan, billing_cycle: state.billingCycle, coupon_code: couponCode } }); }
    catch (ex) { toast(ex.message, "error"); release(); return; }
    if (res.action === "contact_sales") { toast(res.message || "Please contact sales.", "error"); release(); return; }
    // A 100%-off coupon covers the whole charge, so there is no Razorpay step — the server
    // has already activated the plan and granted the credits.
    if (res.action === "activated") {
      state.subscription = res.subscription;
      if (res.wallet) { state.credits = res.wallet; creditsUi.wallet = null; }
      state.billingCoupon = null;
      updatePlanChip();
      toast(res.message || "Plan activated!", "success");
      release();
      renderBilling();
      return;
    }
    if (res.action !== "checkout") { toast("Checkout unavailable.", "error"); release(); return; }
    if (typeof Razorpay === "undefined") { toast("Payment library failed to load. Please refresh.", "error"); release(); return; }

    // The Razorpay modal opens on `res.amount`, which is the GST-INCLUSIVE total. The
    // subtotal shown on the plan card is deliberately smaller, so the description spells
    // out the breakdown — meeting an unexplained larger number at the payment sheet is
    // exactly how a correct charge gets reported as a billing bug.
    const parts = [res.plan_label + " plan · monthly"];
    if (res.tax_paise) {
      parts.push(`${res.subtotal_display} + ${res.tax_label} ${res.tax_display} = ${res.total_display}`);
    }
    // Recurring checkout authorises a MANDATE, not a single charge, so Razorpay is opened on
    // `subscription_id` instead of `order_id` — passing the wrong one silently produces a
    // one-off payment and the plan never renews.
    const isSub = res.checkout_mode === "subscription";
    if (isSub) parts.push("auto-renews monthly");
    const rzp = new Razorpay({
      key: res.razorpay_key_id,
      amount: res.amount,
      currency: res.currency,
      name: res.organization_name || "Rilono",
      description: parts.join(" · "),
      ...(isSub ? { subscription_id: res.subscription_id } : { order_id: res.order_id }),
      prefill: checkoutPrefill(res.prefill),
      theme: { color: "#6366f1" },
      // Closing the sheet without paying ends the attempt — without this the plan button
      // would stay dead until the page was reloaded.
      modal: { ondismiss: release },
      handler: async function (resp) {
        try {
          const v = await api("/billing/verify", { method: "POST", body: {
            // The recurring row is keyed on the subscription id (Razorpay sends no order_id
            // for a mandate), so that is what the server looks the payment up by.
            razorpay_order_id: isSub ? res.subscription_id : resp.razorpay_order_id,
            razorpay_payment_id: resp.razorpay_payment_id,
            razorpay_signature: resp.razorpay_signature,
          }});
          state.subscription = v.subscription;
          // The plan grant lands during verify, so refresh the cached wallet too —
          // otherwise the Credits page shows a stale balance until the next hard reload.
          if (v.wallet) { state.credits = v.wallet; creditsUi.wallet = null; }
          updatePlanChip();
          toast(v.message || "Plan activated!", "success");
          renderBilling();
        } catch (ex) { toast("Payment verification failed: " + ex.message, "error"); }
        finally { release(); }
      },
    });
    rzp.on("payment.failed", () => { toast("Payment was not completed.", "error"); release(); });
    rzp.open();
  }

  /* ============================================================
     CREDITS — prepaid wallet (the revenue model)
     ============================================================ */
  // Short badge label + accent colour per billable feature — keeps the usage
  // bars and the ledger badges visually consistent.
  const CREDIT_ACTION_META = {
    deep_scan: { label: "Deep Scan", color: "#f59e0b" },
    mock_interview: { label: "Mock interview", color: "#ec4899" },
    ai_copilot: { label: "AI assistant", color: "#6366f1" },
    copilot_client: { label: "Client copilot", color: "#818cf8" },
    university_match: { label: "University shortlist", color: "#0ea5e9" },
    course_finder: { label: "Course Finder", color: "#10b981" },
    writing_studio: { label: "SOP / LOR draft", color: "#8b5cf6" },
    other: { label: "Usage", color: "#64748b" },
  };
  const creditActionColor = (key) => (CREDIT_ACTION_META[key] || {}).color || "#6366f1";

  // Visual identity (badge label + accent colour) for one ledger entry.
  function creditTxnMeta(t) {
    // reference_type is checked FIRST: a plan grant is written as type "bonus" and an
    // expiry as type "adjustment", so matching on `type` first would label every monthly
    // allowance "Bonus" and every forfeiture "Adjustment" — the ledger would never once
    // name the plan that is now the main source of credits.
    if (t.reference_type === "plan_credits") return { label: t.credits < 0 ? "Plan credits expired" : "Plan credits", color: t.credits < 0 ? "#94a3b8" : "#6366f1" };
    if (t.type === "topup") return { label: "Top-up", color: "#10b981" };
    if (t.type === "bonus") return { label: "Bonus", color: "#8b5cf6" };
    if (t.action_key === "infra_fee" || t.reference_type === "infra_payment") return { label: "Infra fee", color: "#0ea5e9" };
    if (t.type === "adjustment") return { label: "Adjustment", color: "#0ea5e9" };
    if (t.action_key && CREDIT_ACTION_META[t.action_key]) return CREDIT_ACTION_META[t.action_key];
    if (t.type === "debit") return { label: "Usage", color: "#64748b" };
    return { label: t.type || "—", color: "#64748b" };
  }
  function creditBadge(meta) {
    return `<span class="status-pill" style="background:${meta.color}1a;color:${meta.color};white-space:nowrap">` +
      `<span class="sd" style="background:${meta.color}"></span>${esc(meta.label)}</span>`;
  }
  function usageBar(pct, color) {
    const v = Math.max(0, Math.min(100, Number(pct) || 0));
    return `<div style="height:6px;border-radius:6px;background:var(--bg-2);overflow:hidden;margin-top:6px">` +
      `<div style="height:100%;width:${v}%;background:${color};border-radius:6px"></div></div>`;
  }

  /* ---- Credits & Billing is two jobs, so it is two tabs ----------------------
     "Plans & top-up" (default) is the money-IN view: balance, what things cost,
     packages, and the purchase receipts. "Analytics" is the money-OUT view: where
     the credits went, on which clients, by whom, when — and how long the balance
     will last. They share the wallet payload; analytics loads on demand. */
  const creditsUi = {
    tab: "buy",
    range: 30,          // a preset day-count, or "custom" (then `custom` below applies)
    custom: { start: "", end: "" },
    bucket: "auto",     // timeline / breakdown grouping: auto | day | week | month
    breakdownAll: false,   // breakdown table: show every period, not just the first page
    breakdownQuiet: false, // ...including the ones with no spend at all
    wallet: null,       // /credits/wallet payload
    analytics: null,    // /credits/analytics payload for the active range
    payments: null,     // /credits/payments payload (admins only)
    ledger: { rows: [], total: 0, offset: 0, loading: false, error: null },
    // `period` is the drill-down set by clicking a row in the breakdown table:
    // it narrows the ledger to one day/week/month inside the selected range.
    filters: { kind: "", action: "", member_id: "", client_id: "", q: "", period: null },
  };
  const CREDIT_RANGES = [
    { days: 7, label: "7 days" },
    { days: 30, label: "30 days" },
    { days: 90, label: "90 days" },
    { days: 365, label: "12 months" },
    { days: 0, label: "All time" },
  ];
  const CREDIT_BUCKETS = [
    { key: "auto", label: "Auto" },
    { key: "day", label: "Day" },
    { key: "week", label: "Week" },
    { key: "month", label: "Month" },
  ];
  const CREDIT_BREAKDOWN_PAGE = 14;   // periods shown before "show all"

  function crIsCustomRange() { return creditsUi.range === "custom"; }
  // A custom range only becomes real once BOTH halves are filled in — until then the
  // request keeps the last preset, so a half-typed date can't blank the whole tab.
  function crCustomReady() {
    return crIsCustomRange() && !!creditsUi.custom.start && !!creditsUi.custom.end;
  }

  /* The active window as query params. One helper feeds the analytics request, the
     ledger request and the CSV export, so the three can never describe different
     periods. `withPeriod` additionally applies the breakdown drill-down. */
  function crRangeParams(params, withPeriod) {
    const period = withPeriod ? creditsUi.filters.period : null;
    if (period) {
      params.set("start", period.start);
      params.set("end", period.end);
    } else if (crCustomReady()) {
      params.set("start", creditsUi.custom.start);
      params.set("end", creditsUi.custom.end);
    } else {
      params.set("days", String(crIsCustomRange() ? 30 : creditsUi.range));
    }
    return params;
  }
  // Identifies the window + grouping a cached analytics payload was fetched for.
  function crRangeSig() {
    return crRangeParams(new URLSearchParams(), false).toString() + "&g=" + creditsUi.bucket;
  }

  async function renderCredits() {
    const c = $("#content");
    if (!creditsUi.wallet) c.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
    let d;
    try {
      d = await api("/credits/wallet");
    } catch (ex) {
      if (state.view !== "credits") return;
      c.innerHTML = errBox(ex); return;
    }
    if (state.view !== "credits") return;   // user moved on while we were loading
    creditsUi.wallet = d;
    // Every entry into this view (and every top-up, which re-enters through here)
    // starts from fresh data — the per-tab caches below only survive tab switches.
    creditsUi.analytics = null;
    creditsUi.payments = null;
    creditsUi.ledger = { rows: [], total: 0, offset: 0, loading: false, error: null };
    state.credits = d.wallet || {};
    state.creditPackages = d.packages || [];
    state.creditCoupon = state.creditCoupon || null;
    updatePlanChip();
    creditsDraw();
  }

  // Shell: plan-allowance panel + balance + tabs. The active tab paints into #crPanel.
  function creditsDraw() {
    if (state.view !== "credits") return;
    const c = $("#content");
    const d = creditsUi.wallet || {};
    const w = d.wallet || {};
    const canBuy = can("credits.purchase");
    const canManagePlan = can("billing.manage");

    // Where credits COME FROM. The plan's monthly allowance is the primary source now;
    // top-up packs below are overage. This panel replaced the ₹999 infrastructure-fee
    // banner that stood here until 2026-08-02 — `w.infra_fee` is still sent but is pinned
    // dormant, so nothing renders it any more.
    const pc = w.plan_credits || {};
    const included = Number(pc.included_credits || 0);
    const left = Number(pc.remaining_this_period || 0);
    const usedPct = included > 0 ? Math.min(100, Math.round(((included - left) / included) * 100)) : 0;
    const planPanel = included > 0
      ? `<div class="card" style="margin-bottom:18px;border-left:4px solid var(--success,#10b981)">
          <div class="card-body" style="display:flex;align-items:center;gap:20px;flex-wrap:wrap">
            <div style="flex:1;min-width:250px">
              <div style="font-weight:700;margin-bottom:4px">${esc(pc.plan_label || "Your plan")} includes ${included.toLocaleString()} AI credits${pc.recurring ? " every month" : ""}</div>
              <div style="font-size:13px;color:var(--text-2)">
                ${left.toLocaleString()} of this ${pc.recurring ? "month's" : "grant's"} credits left.
                ${pc.recurring && pc.renews_at ? `Refreshes ${fmtDate(pc.renews_at)}.` : ""}
                ${pc.recurring && !pc.rollover ? " Unused plan credits don't carry over." : ""}
              </div>
              <div class="usage-bar" style="margin-top:8px"><div class="usage-fill" style="width:${usedPct}%"></div></div>
            </div>
            ${canManagePlan ? `<button class="btn btn-ghost" onclick="__ent.go('billing')">Manage plan</button>` : ""}
          </div>
        </div>`
      : (canManagePlan
        ? `<div class="card" style="margin-bottom:18px;border-left:4px solid var(--warning,#f59e0b)">
            <div class="card-body" style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
              <div style="flex:1;min-width:240px">
                <div style="font-weight:700;margin-bottom:4px">Your plan doesn't include monthly AI credits</div>
                <div style="font-size:13px;color:var(--text-2)">Starter, Growth and Scale include 1,000 / 3,500 / 10,000 credits every month. Right now you're paying per top-up.</div>
              </div>
              <button class="btn btn-primary" onclick="__ent.go('billing')">See plans</button>
            </div>
          </div>`
        : "");

    const usage = (creditsUi.wallet || {}).usage || {};
    const spentAll = usage.total_spent_credits || 0;

    c.innerHTML = `
      ${planPanel}
      <div class="card cr-wallet"><div class="card-body cr-wallet-body">
        <div class="cr-wallet-main">
          <div class="cr-eyebrow">Rilono Credits balance</div>
          <div class="cr-balance">${w.balance_credits} <span>credits</span></div>
          <div class="cr-worth">Worth ${esc(fmtInr(w.balance_value_inr != null ? w.balance_value_inr : (w.balance_credits || 0) * (w.credit_value_inr || 10)))} · 1 credit = ${esc(fmtInr(w.credit_value_inr || 10))}</div>
          ${w.low_balance ? `<div class="cr-lowbal">⚠ Low balance — top up to keep using premium AI.</div>` : ""}
        </div>
        <div class="cr-wallet-stats">
          <div><span>Purchased</span><b>${w.lifetime_purchased_credits || 0}</b><em>all time</em></div>
          <div><span>Spent</span><b>${w.lifetime_spent_credits || 0}</b><em>${esc(fmtInr(spentAll * (w.credit_value_inr || 10)))} of AI</em></div>
        </div>
        ${canBuy ? `<button class="btn btn-primary" id="crTopUpBtn">Top up credits</button>` : ""}
      </div></div>

      <div class="cr-tabs">
        <button class="cr-tab ${creditsUi.tab === "buy" ? "active" : ""}" data-crtab="buy">💳 Top up &amp; pricing</button>
        <button class="cr-tab ${creditsUi.tab === "analytics" ? "active" : ""}" data-crtab="analytics">📊 Usage analytics</button>
      </div>
      <div id="crPanel"></div>`;

    const topBtn = $("#crTopUpBtn");
    if (topBtn) topBtn.onclick = () => {
      creditsUi.tab = "buy";
      creditsDraw();
      const grid = $(".plan-grid");
      if (grid) grid.scrollIntoView({ behavior: "smooth", block: "center" });
    };
    $$(".cr-tab", c).forEach((b) => b.onclick = () => {
      if (creditsUi.tab === b.dataset.crtab) return;
      creditsUi.tab = b.dataset.crtab;
      creditsDraw();
    });

    if (creditsUi.tab === "analytics") crDrawAnalytics();
    else crDrawBuy();
  }

  /* ---------------- Tab 1 · Plans, pricing & purchase history ---------------- */
  function crDrawBuy() {
    const panel = $("#crPanel");
    if (!panel) return;
    const d = creditsUi.wallet || {};
    const w = d.wallet || {};
    const canManage = can("credits.purchase");
    const packages = d.packages || [];
    const actions = w.actions || [];
    const freeTier = w.free_tier || {};
    const coupon = state.creditCoupon;
    // How many of an action a credit total buys, priced from the SERVER's action list.
    // These used to be hard-coded divisors (5 and 20) and had silently drifted: a Deep
    // Scan is 20 credits, so a 100-credit pack was advertised as 20 audits when it buys 5.
    // Reading w.actions means a price change in enterprise_credits.ACTIONS can never again
    // leave the pack cards overstating what a pack does.
    const actionUnits = (list, key, totalCredits) => {
      const a = (list || []).find((x) => x && x.key === key);
      const cost = a && Number(a.credits) > 0 ? Number(a.credits) : 0;
      return cost ? Math.floor(Number(totalCredits || 0) / cost) : "—";
    };

    // `amount_paise` on a package is the minor unit of the package's OWN currency (the
    // legacy field name survived the multi-currency migration), and `amount_display` is
    // the server's rendering of it. Show the server's string; only the coupon preview is
    // computed here, and it stays in the package's currency. Other currencies are offered
    // at checkout, where the server quotes them — never converted client-side.
    const priceBlock = (p) => {
      const listed = p.amount_display || fmtMoney(p.amount_paise, p.currency || "INR");
      if (!coupon) return `<div class="price">${esc(listed)}</div>`;
      const discounted = Math.max(0, Math.round(p.amount_paise * (100 - coupon.percent) / 100));
      return `<div class="price">${esc(fmtMoney(discounted, p.currency || "INR"))}<span class="price-was">${esc(listed)}</span></div>
        <div class="price-off">${esc(coupon.percent_display)} off applied</div>`;
    };
    const pkgCard = (p) => `<div class="plan-card ${p.is_popular ? "popular" : ""}">
        ${p.is_popular ? `<div class="pop-tag">Best value</div>` : ""}
        <h3>${esc(p.label)}</h3><div class="tagline">${esc(p.tagline)}</div>
        ${priceBlock(p)}
        <ul>
          <li><b>${p.total_credits} credits</b>${p.bonus_credits ? ` <span style="color:var(--success,#10b981)">(+${p.bonus_credits} bonus)</span>` : ""}</li>
          <li>Worth ${fmtInr(p.value_inr)} of AI actions</li>
          <li>≈ ${actionUnits(actions, "deep_scan", p.total_credits)} Deep Scans or ${actionUnits(actions, "mock_interview", p.total_credits)} interviews</li>
        </ul>
        ${canManage
          ? `<button class="btn ${p.is_popular ? "btn-primary" : "btn-ghost"} btn-block" onclick="__ent.topup('${p.key}')">Buy ${esc(p.label)}</button>`
          : `<div class="plan-current-tag" style="color:var(--muted)">Ask an admin to top up</div>`}
      </div>`;

    const actionRows = actions.map((a) =>
      `<div class="cr-price-row">
        <div><b>${esc(a.label)}</b><div class="cr-price-desc">${esc(a.description || "")}</div></div>
        <div class="cr-price-amt"><b>${a.credits} cr</b><div>${esc(fmtInr(a.price_inr != null ? a.price_inr : (a.credits || 0) * 10))}</div></div>
      </div>`).join("");

    // What the agency gets without spending a credit — stated next to the prices
    // rather than buried in each action's description.
    const freeItems = [
      // The active-client cap is the PLAN's, not a free-tier allowance — it belongs on
      // Plans & Billing, not in the "what costs no credits" grid.
      freeTier.deep_scans_per_client
        ? `<b>First Deep Scan free</b> on every client<span class="cr-free-sub">up to ${freeTier.deep_scans_monthly_cap}/month</span>` : "",
      freeTier.interview_previews
        ? `<b>${freeTier.interview_previews} staff interview previews</b><span class="cr-free-sub">${freeTier.interview_previews_left} left</span>` : "",
      freeTier.copilot_msgs_daily
        ? `<b>${freeTier.copilot_msgs_daily} AI assistant messages/day</b><span class="cr-free-sub">${freeTier.copilot_msgs_left_today} left today</span>` : "",
      `<b>Unlimited catalog browsing</b><span class="cr-free-sub">Course Finder</span>`,
    ].filter(Boolean);

    // Anyone opening this tab is here to buy — the packs lead, and the
    // "what's free" / per-action pricing that justifies the spend sits below.
    panel.innerHTML = `
      <h3 style="margin:0 0 12px">Top up your wallet</h3>
      ${canManage ? couponRow(coupon, "applyCreditCoupon", "removeCreditCoupon", "creditCouponInput", "top-ups") : ""}
      <div class="plan-grid">${packages.map(pkgCard).join("")}</div>
      <p style="text-align:center;color:var(--muted);font-size:13px;margin:14px 0 28px">Secure top-ups via Razorpay (UPI, cards, NetBanking).${
        pkgCurrencies(packages).length > 1 ? " Pick your billing currency at checkout." : ""} Purchased top-up credits never expire; your plan's monthly allowance refreshes each period.</p>

      <div class="card cr-free-card"><div class="card-body">
        <div class="cr-free-head">Included free ${infoTip(
          "The core CRM, the first Deep Scan on each client, a few staff interview previews and a daily AI-assistant allowance cost nothing. Credits are only spent once you go past these.",
          "What's free")}</div>
        <div class="cr-free-grid">${freeItems.map((f) => `<div class="cr-free-item">${f}</div>`).join("")}</div>
      </div></div>

      <div class="card"><div class="card-head"><h3>What each AI action costs</h3>
        <span class="cr-head-note">1 credit = ${esc(fmtInr(w.credit_value_inr || 10))} · top-ups never expire</span></div>
        <div class="card-body">${actionRows || '<div class="muted">No billable actions configured.</div>'}</div></div>

      <div id="crPurchases" style="margin-top:26px"></div>`;

    crDrawPurchases();
  }

  /* ---- Purchase history (money in). It carries amounts and payment references, so it
     follows the capability that buys credits rather than plain wallet visibility. ---- */
  function crDrawPurchases() {
    const mount = $("#crPurchases");
    if (!mount) return;
    if (!can("credits.purchase")) {
      mount.innerHTML = deniedCard("You don't have permission to buy credits, so top-up receipts aren't shown here. Ask a workspace admin for access.");
      return;
    }
    const p = creditsUi.payments;
    if (!p) {
      mount.innerHTML = `<div class="card"><div class="card-body"><div class="center-load" style="min-height:90px"><div class="spinner dark"></div></div></div></div>`;
      crLoadPayments();
      return;
    }
    if (p.error) {
      mount.innerHTML = `<div class="card"><div class="card-body">${errBox(p.error)}</div></div>`;
      return;
    }
    const rows = p.payments || [];
    const statusPill = (s) => {
      const map = {
        verified: ["Paid", "#10b981"],
        partially_refunded: ["Part refunded", "#f59e0b"],
        refunded: ["Refunded", "#64748b"],
        failed: ["Failed", "#ef4444"],
      };
      const [label, color] = map[s] || [s || "—", "#64748b"];
      return `<span class="status-pill" style="background:${color}1a;color:${color};white-space:nowrap"><span class="sd" style="background:${color}"></span>${esc(label)}</span>`;
    };
    // A receipt row is denominated in the currency it was charged in, so render from
    // `currency` + the minor-unit amounts whenever the row carries them. The `*_display`
    // strings are only a fallback for rows served before the endpoint learned about
    // currency — those are all genuinely INR, which is why the fallback is safe.
    const rowMoney = (r, minor, display) => (r.currency ? fmtMoney(minor, r.currency) : (display || ""));
    const body = rows.length ? rows.map((r) => `<tr>
        <td style="white-space:nowrap">${fmtDate(r.verified_at || r.created_at)}</td>
        <td><b>${esc(r.label)}</b>${r.coupon_code ? `<div class="cr-sub">🎟 ${esc(r.coupon_code)}${r.coupon_percent_off ? ` · ${r.coupon_percent_off}% off` : ""}</div>` : ""}${
          r.tax_paise ? `<div class="cr-sub">incl. ${esc(r.tax_label || "tax")} ${esc(rowMoney(r, r.tax_paise, r.tax_display))}</div>` : ""}</td>
        <td style="text-align:right">${
          r.kind === "credits" ? `+${r.total_credits}${r.bonus_credits ? ` <span class="cr-sub-inline">(${r.bonus_credits} bonus)</span>` : ""}`
          : (r.kind === "plan" && r.total_credits ? `+${r.total_credits} <span class="cr-sub-inline">included</span>` : "—")}</td>
        <td style="text-align:right;white-space:nowrap"><b>${esc(rowMoney(r, r.net_amount_paise, r.net_amount_display))}</b>${
          r.refunded_amount_paise ? `<div class="cr-sub">${esc(rowMoney(r, r.refunded_amount_paise, r.refunded_display))} refunded</div>` : ""}</td>
        <td>${statusPill(r.status)}</td>
        <td class="cr-sub" style="white-space:nowrap">${esc(r.created_by_name || "—")}<div>${esc(r.payment_reference || "")}</div></td>
      </tr>`).join("")
      : `<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:22px">No purchases yet — your plan and any top-ups will appear here.</td></tr>`;
    // The header's "₹X paid" comes from the endpoint, which adds `collected_paise` across
    // rows and formats the result as INR. That is a true statement only while every row is
    // INR, so once the history is mixed — or single-currency but not INR — the money
    // figure is DROPPED rather than relabelled: a cross-currency sum is money in no
    // currency at all, and the revenue-status rules that decide what counts live on the
    // server, so it can't honestly be re-derived here.
    const rowCurrencies = rows.reduce((acc, r) => {
      const code = r.currency || "INR";
      if (acc.indexOf(code) === -1) acc.push(code);
      return acc;
    }, []);
    const sum = p.summary || {};
    const onlyInr = rowCurrencies.every((code) => code === "INR");
    const collectedNote = onlyInr ? ` · ${esc(sum.collected_display || "₹0")} paid` : "";

    mount.innerHTML = `
      <div class="card"><div class="card-head"><h3>Purchase history</h3>
        <span class="cr-head-note">${sum.count || 0} ${sum.count === 1 ? "payment" : "payments"}${
          rowCurrencies.length > 1 ? ` in ${rowCurrencies.length} currencies` : ""}${collectedNote} · ${sum.credits_purchased || 0} credits bought</span></div>
        <div class="card-body" style="padding:0;overflow-x:auto">
          <table class="client-table cr-table"><thead><tr>
            <th>Date</th><th>Item</th><th style="text-align:right">Credits</th>
            <th style="text-align:right">Paid</th><th>Status</th><th>Bought by / reference</th>
          </tr></thead><tbody>${body}</tbody></table>
        </div></div>`;
  }

  async function crLoadPayments() {
    try {
      creditsUi.payments = await api("/credits/payments?limit=100");
    } catch (ex) {
      creditsUi.payments = { error: ex, payments: [] };
    }
    if (state.view === "credits" && creditsUi.tab === "buy") crDrawPurchases();
  }

  /* ---------------- Tab 2 · Usage analytics ---------------- */
  function crDrawAnalytics() {
    const panel = $("#crPanel");
    if (!panel) return;
    const custom = crIsCustomRange();
    const today = calYmd(new Date());
    panel.innerHTML = `
      <div class="cr-rangebar">
        <span class="cr-rangelabel">Period</span>
        ${CREDIT_RANGES.map((r) => `<button class="cr-range ${r.days === creditsUi.range ? "active" : ""}" data-crrange="${r.days}">${esc(r.label)}</button>`).join("")}
        <button class="cr-range ${custom ? "active" : ""}" data-crrange="custom">📅 Custom range</button>
        ${custom ? `<span class="cr-custom">
          <input type="date" class="cr-input cr-date" id="crFrom" max="${today}" value="${esc(creditsUi.custom.start)}" aria-label="From date">
          <span class="cr-custom-sep">→</span>
          <input type="date" class="cr-input cr-date" id="crTo" max="${today}" value="${esc(creditsUi.custom.end)}" aria-label="To date">
        </span>` : ""}
        <span class="cr-rangespacer"></span>
        <span class="cr-granwrap">
          <span class="cr-rangelabel">Group by</span>
          ${CREDIT_BUCKETS.map((b) => `<button class="cr-gran ${b.key === creditsUi.bucket ? "active" : ""}" data-crgran="${b.key}">${esc(b.label)}</button>`).join("")}
        </span>
      </div>
      <div id="crAnaBody"><div class="center-load"><div class="spinner dark"></div></div></div>`;

    // Switching the window invalidates the drill-down with it: a day picked out of
    // "last 7 days" is not necessarily inside the window that replaces it.
    const reload = (resetPeriod) => {
      if (resetPeriod) creditsUi.filters.period = null;
      creditsUi.analytics = null;
      creditsUi.breakdownAll = false;
      crDrawAnalytics();
    };
    $$("[data-crrange]", panel).forEach((b) => b.onclick = () => {
      const raw = b.dataset.crrange;
      const next = raw === "custom" ? "custom" : Number(raw);
      if (next === creditsUi.range && next !== "custom") return;
      creditsUi.range = next;
      if (next === "custom" && !creditsUi.custom.start && !creditsUi.custom.end) {
        // Seed the pickers with the window they were just looking at, so opening
        // "Custom" shows the same data rather than an empty chart.
        const back = new Date();
        back.setDate(back.getDate() - 29);
        creditsUi.custom = { start: calYmd(back), end: calYmd(new Date()) };
      }
      reload(true);
    });
    $$("[data-crgran]", panel).forEach((b) => b.onclick = () => {
      if (b.dataset.crgran === creditsUi.bucket) return;
      creditsUi.bucket = b.dataset.crgran;
      // Regrouping drops the drill-down too: a day picked out of a daily table is
      // no longer a row once the table is weekly, so the highlight would vanish
      // while the ledger stayed narrowed to a period nothing on screen names.
      reload(true);
    });
    const from = $("#crFrom", panel);
    const to = $("#crTo", panel);
    const applyDates = () => {
      const nextStart = (from && from.value) || "";
      const nextEnd = (to && to.value) || "";
      if (nextStart === creditsUi.custom.start && nextEnd === creditsUi.custom.end) return;
      creditsUi.custom = { start: nextStart, end: nextEnd };
      if (!nextStart || !nextEnd) return;   // half-filled: keep showing what's on screen
      reload(true);
    };
    if (from) from.onchange = applyDates;
    if (to) to.onchange = applyDates;

    if (creditsUi.analytics && creditsUi.analytics._sig === crRangeSig()) {
      crDrawAnalyticsBody();
    } else {
      crLoadAnalytics();
    }
  }

  async function crLoadAnalytics() {
    const sig = crRangeSig();
    const params = crRangeParams(new URLSearchParams(), false);
    if (creditsUi.bucket && creditsUi.bucket !== "auto") params.set("bucket", creditsUi.bucket);
    let res;
    try {
      res = await api("/credits/analytics?" + params.toString());
    } catch (ex) {
      if (state.view !== "credits" || creditsUi.tab !== "analytics") return;
      const body = $("#crAnaBody");
      if (body) body.innerHTML = errBox(ex);
      return;
    }
    // Guard the async gap: the user may have switched range/grouping/tab/view meanwhile.
    if (state.view !== "credits" || creditsUi.tab !== "analytics" || crRangeSig() !== sig) return;
    res._sig = sig;
    creditsUi.analytics = res;
    crDrawAnalyticsBody();
    crLoadLedger(true);
  }

  function crDrawAnalyticsBody() {
    const body = $("#crAnaBody");
    if (!body) return;
    const a = (creditsUi.analytics || {}).analytics || {};
    const s = a.summary || {};
    const burn = a.burn || {};
    const w = (creditsUi.wallet || {}).wallet || {};
    const creditInr = w.credit_value_inr || 10;
    const rangeLabel = (a.range || {}).label || "";
    // Reads inside a sentence; the server lowercases presets and leaves a custom
    // window's date span capitalised ("₹570 · 2 Jul – 15 Jul 2026").
    const rangeSub = (a.range || {}).sub_label || rangeLabel.toLowerCase();

    if (!s.action_count) {
      // Nothing spent — but an org that has only topped up still has ledger rows
      // worth seeing, so keep the ledger whenever there was any movement at all.
      const anyMovement = !!s.added_credits;
      body.innerHTML = `<div class="card" style="margin-bottom:${anyMovement ? "24px" : "0"}"><div class="card-body" style="text-align:center;padding:46px 20px">
        <div style="font-size:34px">📊</div>
        <h3 style="margin:10px 0 6px">No credits spent in ${esc(rangeLabel || "this period")}</h3>
        <p class="muted" style="margin:0 auto;max-width:440px;font-size:13.5px">
          Once your team runs Deep Scans, mock interviews, shortlists or SOP drafts, this tab shows exactly
          where every credit went — which client, which staff member, when and why.</p>
        ${crIsCustomRange() ? `<button class="btn btn-ghost btn-sm" style="margin-top:14px" id="crWiden">Widen to all time</button>` : ""}
      </div></div>${anyMovement ? `<div id="crLedgerMount"></div>` : ""}`;
      const widen = $("#crWiden", body);
      if (widen) widen.onclick = () => {
        creditsUi.range = 0;
        creditsUi.filters.period = null;
        creditsUi.analytics = null;
        crDrawAnalytics();
      };
      if (anyMovement) crDrawLedger();
      return;
    }

    const kpi = (icon, color, label, value, sub, tip) => `
      <div class="kpi">
        <div class="kpi-top"><div class="kpi-ic" style="background:${color}">${icon}</div></div>
        <div class="kpi-label">${esc(label)}${tip ? infoTip(tip, label) : ""}</div>
        <div class="kpi-value">${value}</div>
        <div class="kpi-sub">${sub}</div>
      </div>`;

    const runway = burn.days_remaining == null
      ? "No spend yet"
      : (burn.days_remaining > 400 ? "400+ days" : `${burn.days_remaining} ${burn.days_remaining === 1 ? "day" : "days"} left`);
    const runwayTone = burn.days_remaining != null && burn.days_remaining <= 14 ? "var(--danger)" : "var(--text)";

    const kpis = `<div class="kpi-grid">
      ${kpi("💸", "#6366f1", "Credits spent", `${s.spent_credits}`,
        `${esc(fmtInr(s.spent_credits * creditInr))} · ${esc(rangeSub)}`)}
      ${kpi("⚡", "#ec4899", "AI actions run", `${s.action_count}`,
        `${s.avg_credits_per_action} credits per action on average`)}
      ${kpi("🎓", "#0ea5e9", "Clients served", `${s.clients_touched}`,
        `${s.avg_credits_per_client} credits per client on average`)}
      ${kpi("⏳", burn.days_remaining != null && burn.days_remaining <= 14 ? "#ef4444" : "#10b981", "Runway",
        `<span style="color:${runwayTone}">${esc(runway)}</span>`,
        burn.runs_out_on ? `At ${burn.daily_credits}/day, empty by ${fmtDate(burn.runs_out_on)}` : "Based on the last 30 days",
        "Runway is always measured against your last 30 days of spend, so changing the period above doesn't move it.")}
    </div>`;

    const tl = a.timeline || {};
    const bucketWord = { day: "day", week: "week", month: "month" }[tl.bucket] || "day";
    // Asking for days across three years is unreadable, so the server widens the
    // grouping. Say so, rather than showing weeks under a button marked "Day".
    const widened = tl.requested_bucket && tl.requested_bucket !== "auto" && tl.requested_bucket !== tl.bucket
      ? ` · too long to chart by ${esc(tl.requested_bucket)}, grouped by ${esc(bucketWord)}`
      : "";
    const chart = `
      <div class="card" style="margin-bottom:24px">
        <div class="card-head"><h3>When credits were spent</h3>
          <span class="cr-head-note">${esc(rangeLabel)} · by ${esc(bucketWord)} · peak ${tl.peak_credits || 0} cr${widened}</span></div>
        <div class="card-body">${crChart(tl)}</div>
      </div>`;

    const byAction = (a.by_action || []).filter((x) => x.credits_spent > 0);
    const featureRows = byAction.map((x) => {
      const color = creditActionColor(x.key);
      return `<div class="cr-split-row">
        <div class="cr-split-top">
          <div><b>${esc(x.label)}</b> <span class="cr-sub-inline">· ${x.units} ${x.units === 1 ? "use" : "uses"}</span></div>
          <div class="cr-split-amt"><b>${x.credits_spent} cr</b><span> · ${x.share_pct}%</span></div>
        </div>
        ${usageBar(x.share_pct, color)}
        <div class="cr-sub">${esc(x.value_display)}${x.price_credits ? ` · ${x.price_credits} cr each` : ""}</div>
      </div>`;
    }).join("");

    const byMember = (a.by_member || []).filter((m) => m.credits_spent > 0);
    const memberRows = byMember.length ? byMember.map((m) => {
      const col = avatarColor(m.name)[0];
      return `<div class="cr-member-row" ${m.user_id ? `data-crmember="${m.user_id}" role="button" tabindex="0" title="Filter the ledger to ${esc(m.name)}"` : ""}>
        <span class="cr-avatar" style="background:${col}">${esc(initials(m.name))}</span>
        <div class="cr-member-main">
          <div class="cr-member-name">${esc(m.name)}</div>
          <div class="cr-sub">${m.units} ${m.units === 1 ? "action" : "actions"}${m.last_used_at ? ` · last ${fmtDate(m.last_used_at)}` : ""}</div>
        </div>
        <div class="cr-split-amt"><b>${m.credits_spent} cr</b><div class="cr-sub">${m.share_pct}%</div></div>
      </div>`;
    }).join("") : `<div class="muted" style="padding:14px 0">No team usage in this period.</div>`;

    const split = `
      <div class="cr-split">
        <div class="card"><div class="card-head"><h3>Where credits go</h3>
          <span class="cr-head-note">by feature</span></div>
          <div class="card-body">${featureRows || '<div class="muted">Nothing spent yet.</div>'}</div></div>
        <div class="card"><div class="card-head"><h3>Who spent them</h3>
          <span class="cr-head-note">by team member</span></div>
          <div class="card-body">${memberRows}</div></div>
      </div>`;

    const clients = (a.by_client || []).filter((x) => x.credits_spent > 0);
    const clientRows = clients.length ? clients.map((x) => {
      const chips = (x.actions || []).slice(0, 4).map((act) => {
        const col = creditActionColor(act.key);
        return `<span class="cr-chip" style="background:${col}14;color:${col}">${esc((CREDIT_ACTION_META[act.key] || {}).label || act.label)} · ${act.credits_spent}</span>`;
      }).join("");
      const clickable = x.client_id && x.exists;
      return `<tr ${clickable ? `data-crclient="${x.client_id}" title="Open ${esc(x.name)}"` : `style="cursor:default"`}>
        <td><b>${esc(x.name)}</b>${x.is_rollup ? "" : (x.exists ? "" : ` <span class="cr-sub-inline">(removed)</span>`)}</td>
        <td class="cr-chips">${chips || '<span class="cr-sub">—</span>'}</td>
        <td style="text-align:right">${x.units}</td>
        <td style="text-align:right;white-space:nowrap"><b>${x.credits_spent} cr</b><div class="cr-sub">${esc(x.value_display)}</div></td>
        <td style="text-align:right">${x.share_pct}%</td>
        <td style="white-space:nowrap" class="cr-sub">${x.last_used_at ? fmtDate(x.last_used_at) : "—"}</td>
      </tr>`;
    }).join("") : `<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:22px">No per-client spend in this period.</td></tr>`;

    const clientCard = `
      <div class="card" style="margin-bottom:24px"><div class="card-head"><h3>Which clients your credits went on</h3>
        <span class="cr-head-note">${s.clients_touched} ${s.clients_touched === 1 ? "client" : "clients"}${s.unattributed_credits ? ` · ${s.unattributed_credits} cr org-wide (AI assistant & general searches)` : ""}</span></div>
        <div class="card-body" style="padding:0;overflow-x:auto">
          <table class="client-table cr-table"><thead><tr>
            <th>Client</th><th>What it was spent on</th><th style="text-align:right">Actions</th>
            <th style="text-align:right">Credits</th><th style="text-align:right">Share</th><th>Last used</th>
          </tr></thead><tbody>${clientRows}</tbody></table>
        </div></div>`;

    body.innerHTML = `${kpis}${chart}${crBreakdownCard(tl)}${split}${clientCard}<div id="crLedgerMount"></div>`;

    $$("[data-crclient]", body).forEach((tr) => tr.onclick = () => openClient(Number(tr.dataset.crclient)));
    $$("[data-crmember]", body).forEach((el) => {
      const pick = () => { creditsUi.filters.member_id = el.dataset.crmember; crLoadLedger(true, true); };
      el.onclick = pick;
      el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } };
    });
    crWireBreakdown(body, tl);
    crDrawLedger();
  }

  /* ---- Spend timeline. A plain CSS bar chart: it reflows with the card, needs
     no chart library, and every bar carries its own hover readout. ---- */
  function crBucketLabel(key, bucket, short) {
    if (!key) return "";
    if (bucket === "month") {
      const [y, m] = key.split("-").map(Number);
      return new Date(y, (m || 1) - 1, 1).toLocaleDateString(undefined, { month: "short", year: short ? "2-digit" : "numeric" });
    }
    const d = parseDateValue(key);
    if (!d) return key;
    // Weekly buckets only appear on the 12-month view, which spans a year
    // boundary — without the year "Jul 21" and "Jul 27" look like the same month.
    const opts = bucket === "week"
      ? { day: "numeric", month: "short", year: short ? "2-digit" : "numeric" }
      : { day: "numeric", month: "short", year: short ? undefined : "numeric" };
    const label = d.toLocaleDateString(undefined, opts);
    return bucket === "week" && !short ? `Week of ${label}` : label;
  }

  /* The calendar span one bucket key covers. Drilling into a bar or a table row
     asks the ledger for exactly these dates, so "35 cr on 2 Jul" and the entries
     listed underneath it are always the same 35 credits. */
  function crBucketRange(key, bucket) {
    if (!key) return null;
    if (bucket === "month") {
      const [y, m] = String(key).split("-").map(Number);
      const first = new Date(y, (m || 1) - 1, 1);
      const last = new Date(y, m || 1, 0);          // day 0 of next month = last of this
      return { start: calYmd(first), end: calYmd(last) };
    }
    const d = parseDateValue(key);
    if (!d) return null;
    if (bucket === "week") {
      const end = new Date(d);
      end.setDate(end.getDate() + 6);
      return { start: calYmd(d), end: calYmd(end) };
    }
    return { start: calYmd(d), end: calYmd(d) };
  }

  /* The same span, trimmed to the window on screen. A bucket at either end of the
     range is a PARTIAL period — "Jul 2026" inside a 1–15 Jul range summarises a
     fortnight, and a week key is the Monday, which can sit days before the range
     starts — so the calendar span would pull in entries the row never counted. */
  function crWindowedBucketRange(key, bucket) {
    const span = crBucketRange(key, bucket);
    if (!span) return null;
    const win = ((creditsUi.analytics || {}).analytics || {}).range || {};
    return {
      start: win.start_date && span.start < win.start_date ? win.start_date : span.start,
      end: win.end_date && span.end > win.end_date ? win.end_date : span.end,
    };
  }

  // "Thu · 2 Jul 2026", with today/yesterday called out — a day-by-day table is
  // read by scanning down it, and a weekday is what makes a pattern visible.
  function crPeriodLabel(key, bucket) {
    if (bucket !== "day") return crBucketLabel(key, bucket);
    const d = parseDateValue(key);
    if (!d) return crBucketLabel(key, bucket);
    const today = calYmd(new Date());
    const yest = new Date(); yest.setDate(yest.getDate() - 1);
    const stamp = key === today ? "Today" : (key === calYmd(yest) ? "Yesterday" : d.toLocaleDateString(undefined, { weekday: "short" }));
    return `${stamp} · ${d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}`;
  }

  /* ---- Period-by-period breakdown: the chart's numbers as a table you can read,
     sort down and drill into. This is the "what did we spend it on, day by day"
     answer the bar chart can only gesture at. ---- */
  function crBreakdownCard(tl) {
    const bucket = (tl || {}).bucket || "day";
    const all = ((tl || {}).points || []).slice().reverse();   // newest period first
    const spent = all.filter((p) => p.credits > 0);
    const quiet = all.length - spent.length;
    const source = creditsUi.breakdownQuiet ? all : spent;
    const shown = creditsUi.breakdownAll ? source : source.slice(0, CREDIT_BREAKDOWN_PAGE);
    const heading = { day: "Day-by-day breakdown", week: "Week-by-week breakdown", month: "Month-by-month breakdown" }[bucket]
      || "Period breakdown";
    const noun = { day: "day", week: "week", month: "month" }[bucket] || "period";
    const peak = Math.max(1, (tl || {}).peak_credits || 0);
    const active = creditsUi.filters.period;

    const rows = shown.length ? shown.map((p) => {
      const chips = (p.actions || []).map((act) => {
        const col = creditActionColor(act.key);
        const label = (CREDIT_ACTION_META[act.key] || {}).label || act.label;
        return `<span class="cr-chip" style="background:${col}14;color:${col}" title="${esc(label)} · ${act.units} ${act.units === 1 ? "use" : "uses"} · ${act.credits} credits">${esc(label)} · ${act.credits}</span>`;
      }).join("");
      const isActive = !!(active && active.key === p.key);
      return `<tr class="cr-day-row ${isActive ? "active" : ""}" data-crperiod="${esc(p.key)}"
          title="Show the ledger entries for ${esc(crPeriodLabel(p.key, bucket))}">
        <td style="white-space:nowrap"><b>${esc(crPeriodLabel(p.key, bucket))}</b>${
          isActive ? `<div class="cr-sub" style="color:var(--primary-600)">Showing in ledger ↓</div>` : ""}</td>
        <td class="cr-chips">${chips || '<span class="cr-sub">No spend</span>'}</td>
        <td style="text-align:right">${p.units || 0}</td>
        <td style="text-align:right">${p.clients || 0}</td>
        <td style="text-align:right;white-space:nowrap"><b>${p.credits} cr</b><div class="cr-sub">${esc(p.value_display || "")}</div></td>
        <td class="cr-day-share">${usageBar(Math.round((p.credits / peak) * 100), "#6366f1")}
          <span class="cr-sub">${p.share_pct}% of period</span></td>
      </tr>`;
    }).join("")
      : `<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:22px">No spend in this period.</td></tr>`;

    const more = source.length > shown.length
      ? `<button class="btn btn-ghost btn-sm" id="crDayMore">Show all ${source.length} ${source.length === 1 ? noun : noun + "s"}</button>`
      : (creditsUi.breakdownAll && source.length > CREDIT_BREAKDOWN_PAGE
        ? `<button class="btn btn-ghost btn-sm" id="crDayLess">Show fewer</button>` : "");

    return `
      <div class="card" style="margin-bottom:24px"><div class="card-head"><h3>${esc(heading)}</h3>
        <span class="cr-head-note">${spent.length} active ${spent.length === 1 ? noun : noun + "s"}${
          quiet ? ` · ${quiet} with no spend` : ""} · click a row to see the entries</span></div>
        ${(tl || {}).truncated ? `<div class="card-body"><div class="cr-day-warn">⚠ This period has more entries than one report can read.
          The totals above are complete, but the oldest ${esc(noun)}s in this table may be understated — narrow the dates for an exact split.</div></div>` : ""}
        <div class="card-body cr-day-tools">
          ${quiet ? `<label class="cr-day-toggle"><input type="checkbox" id="crDayQuiet" ${creditsUi.breakdownQuiet ? "checked" : ""}> Show ${noun}s with no spend</label>` : ""}
          <button class="btn btn-soft btn-sm" id="crDayExport" title="Download this breakdown as CSV — opens directly in Excel">⬇ Export breakdown</button>
        </div>
        <div class="card-body" style="padding:0;overflow-x:auto">
          <table class="client-table cr-table"><thead><tr>
            <th>${esc(noun.charAt(0).toUpperCase() + noun.slice(1))}</th><th>What it went on</th>
            <th style="text-align:right">Actions</th><th style="text-align:right">Clients</th>
            <th style="text-align:right">Credits</th><th>Share</th>
          </tr></thead><tbody>${rows}</tbody></table>
        </div>
        ${more ? `<div class="card-body" style="text-align:center">${more}</div>` : ""}
      </div>`;
  }

  function crWireBreakdown(root, tl) {
    const bucket = (tl || {}).bucket || "day";
    const quiet = $("#crDayQuiet", root);
    if (quiet) quiet.onchange = () => {
      creditsUi.breakdownQuiet = quiet.checked;
      crDrawAnalyticsBody();
    };
    const more = $("#crDayMore", root);
    if (more) more.onclick = () => { creditsUi.breakdownAll = true; crDrawAnalyticsBody(); };
    const less = $("#crDayLess", root);
    if (less) less.onclick = () => { creditsUi.breakdownAll = false; crDrawAnalyticsBody(); };
    const exp = $("#crDayExport", root);
    if (exp) exp.onclick = () => crExportBreakdown(tl);
    $$("[data-crperiod]", root).forEach((tr) => tr.onclick = () => crPickPeriod(tr.dataset.crperiod, bucket));
    // The bars drill into exactly the same period the table rows do.
    $$("[data-crbar]", root).forEach((el) => {
      const pick = () => crPickPeriod(el.dataset.crbar, bucket);
      el.onclick = pick;
      el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } };
    });
  }

  // Clicking a period narrows the ledger below to it (clicking it again clears the
  // drill-down). Only the LEDGER moves — the cards above keep describing the whole
  // window, so the row's own numbers stay on screen to compare against.
  function crPickPeriod(key, bucket) {
    const active = creditsUi.filters.period;
    if (active && active.key === key) {
      creditsUi.filters.period = null;
    } else {
      const span = crWindowedBucketRange(key, bucket);
      if (!span) return;
      creditsUi.filters.period = { key, bucket, start: span.start, end: span.end, label: crPeriodLabel(key, bucket) };
    }
    crDrawAnalyticsBody();
    crLoadLedger(true, true);
    const mount = $("#crLedgerMount");
    if (mount && creditsUi.filters.period) mount.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function crExportBreakdown(tl) {
    const bucket = (tl || {}).bucket || "day";
    const points = ((tl || {}).points || []).slice().reverse();
    if (!points.length) { toast("Nothing to export for this period.", "error"); return; }
    // Same formula-injection guard and BOM as the ledger export.
    const cell = (v) => {
      if (typeof v === "number") return String(v);
      let s = v === null || v === undefined ? "" : String(v);
      if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
      return `"${s.replace(/"/g, '""')}"`;
    };
    // One column per billable feature, named by the server's own label — a key the
    // client doesn't know about yet must not reach the spreadsheet as "copilot_client".
    const features = (((creditsUi.wallet || {}).wallet || {}).actions || []).filter((x) => x && x.key);
    const headers = ["Period", "Starts", "Ends", "Credits", "Value (INR)", "Actions", "Clients", "Share %"]
      .concat(features.map((x) => ((CREDIT_ACTION_META[x.key] || {}).label || x.label || x.key) + " (cr)"))
      .concat(["Other usage (cr)"]);
    const body = points.map((p) => {
      const span = crWindowedBucketRange(p.key, bucket) || {};
      const byKey = {};
      (p.actions || []).forEach((a) => { byKey[a.key] = a.credits; });
      return [
        crPeriodLabel(p.key, bucket), span.start || "", span.end || "",
        p.credits, p.credits * (((creditsUi.wallet || {}).wallet || {}).credit_value_inr || 10),
        p.units || 0, p.clients || 0, p.share_pct || 0,
      ].concat(features.map((x) => byKey[x.key] || 0)).concat([byKey.other || 0]);
    });
    const csv = [headers, ...body].map((r) => r.map(cell).join(",")).join("\r\n");
    const range = ((creditsUi.analytics || {}).analytics || {}).range || {};
    const stamp = `${range.start_date || "start"}_${range.end_date || calYmd(new Date())}`;
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `rilono-credits-by-${bucket}-${stamp}.csv`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 0);
    toast(`Exported ${points.length} ${points.length === 1 ? bucket : bucket + "s"}`, "success");
  }

  function crChart(tl) {
    const points = (tl && tl.points) || [];
    if (!points.length) return `<div class="muted" style="padding:20px 0;text-align:center">No spend in this period.</div>`;
    const peak = Math.max(1, tl.peak_credits || 0);
    const bucket = tl.bucket;
    const active = creditsUi.filters.period;
    const bars = points.map((p) => {
      const pct = p.credits > 0 ? Math.max(4, Math.round((p.credits / peak) * 100)) : 0;
      // The hover readout carries the same split the table row does, so the chart
      // answers "spent on what" without having to scroll down to read it.
      const parts = (p.actions || []).map((x) => `${(CREDIT_ACTION_META[x.key] || {}).label || x.label} ${x.credits}`);
      const title = `${crBucketLabel(p.key, bucket)} — ${p.credits} ${p.credits === 1 ? "credit" : "credits"}${
        p.units ? ` · ${p.units} ${p.units === 1 ? "action" : "actions"}` : ""}${
        parts.length ? `\n${parts.join(" · ")}` : ""}`;
      return `<div class="cr-bar-slot ${active && active.key === p.key ? "active" : ""}" title="${esc(title)}"
          ${p.credits ? `data-crbar="${esc(p.key)}" role="button" tabindex="0"` : ""}>
        ${p.credits
          ? `<div class="cr-bar" style="height:${pct}%"></div>`
          : `<div class="cr-bar cr-bar-zero"></div>`}
      </div>`;
    }).join("");
    const mid = points[Math.floor(points.length / 2)];
    // A slot can't shrink below 2px + its 2px gap, so past ~200 bars the row is wider
    // than the card and would paint over the page instead of clipping. Asking for a
    // year day-by-day is a legitimate thing to want, so the plot scrolls sideways at a
    // legible bar width rather than being squeezed or silently regrouped — the axis
    // labels travel inside the same scroller so they keep naming the bars beneath them.
    const MIN_BAR_PX = 5;
    const wide = points.length > 120;
    const plotWidth = wide ? ` style="min-width:${points.length * MIN_BAR_PX}px"` : "";
    return `
      <div class="cr-chart-wrap">
        <div class="cr-chart-y"><span>${peak}</span><span>0</span></div>
        <div class="cr-chart-scroll">
          <div class="cr-chart"${plotWidth}>${bars}</div>
          <div class="cr-chart-x"${plotWidth}>
            <span>${esc(crBucketLabel(points[0].key, bucket, true))}</span>
            <span>${esc(crBucketLabel(mid.key, bucket, true))}</span>
            <span>${esc(crBucketLabel(points[points.length - 1].key, bucket, true))}</span>
          </div>
        </div>
      </div>
      ${wide ? `<div class="cr-sub" style="margin-top:8px;text-align:right">← scroll to see the whole period · ${points.length} ${esc(bucket)}s</div>` : ""}`;
  }

  /* ---- The ledger: every credit movement, filterable. This is the audit trail
     behind every number above — who, when, on whom, why, and the running balance. */
  function crLedgerQuery(extra) {
    const f = creditsUi.filters;
    const params = new URLSearchParams();
    params.set("limit", String((extra && extra.limit) || 25));
    params.set("offset", String((extra && extra.offset) || 0));
    // The selected window — narrowed to one day/week/month when a breakdown row
    // is picked, so the ledger under the table lists exactly that row's entries.
    crRangeParams(params, true);
    if (f.kind) params.set("kind", f.kind);
    if (f.action) params.set("action", f.action);
    if (f.member_id) params.set("member_id", f.member_id);
    if (f.client_id) params.set("client_id", f.client_id);
    if (f.q) params.set("q", f.q);
    return params.toString();
  }

  // Typing in the search box fires a request per keystroke-burst; a slow earlier
  // response must never overwrite a newer one, so only the latest request applies.
  let crLedgerSeq = 0;

  async function crLoadLedger(reset, redraw) {
    const L = creditsUi.ledger;
    const seq = ++crLedgerSeq;
    L.loading = true;
    if (reset) { L.rows = []; L.offset = 0; L.total = 0; L.error = null; }
    if (redraw) crDrawLedger();
    let res;
    try {
      res = await api("/credits/transactions?" + crLedgerQuery({ limit: 25, offset: L.offset }));
    } catch (ex) {
      if (seq !== crLedgerSeq) return;
      L.error = ex; L.loading = false; crDrawLedger(); return;
    }
    if (seq !== crLedgerSeq) return;   // superseded by a newer filter change
    if (state.view !== "credits" || creditsUi.tab !== "analytics") { L.loading = false; return; }
    L.rows = L.rows.concat(res.transactions || []);
    L.total = res.total || 0;
    L.offset = L.rows.length;
    L.hasMore = !!res.has_more;
    L.loading = false;
    crDrawLedger();
  }

  function crDrawLedger() {
    const mount = $("#crLedgerMount");
    if (!mount) return;
    // Re-rendering replaces the search box mid-typing — remember the caret so the
    // debounced refresh doesn't yank focus out from under the user.
    const focused = document.activeElement;
    const keepCaret = focused && focused.id === "crQ" ? focused.selectionStart : null;
    const L = creditsUi.ledger;
    const f = creditsUi.filters;
    const a = (creditsUi.analytics || {}).analytics || {};
    const members = (a.by_member || []).filter((m) => m.user_id);
    const clients = (a.by_client || []).filter((c) => c.client_id && !c.is_rollup);
    const actions = (a.by_action || []).filter((x) => x.units > 0);
    const filtered = !!(f.kind || f.action || f.member_id || f.client_id || f.q || f.period);
    // Most debits are described with the action's own name, which the badge
    // already shows — collect those labels so the row doesn't say it twice.
    const actionLabels = new Set(
      (((creditsUi.wallet || {}).wallet || {}).actions || []).map((x) => x.label)
    );

    const rows = L.rows.length ? L.rows.map((t) => {
      const pos = t.credits > 0;
      const meta = creditTxnMeta(t);
      const who = t.client_name
        ? `<b class="cr-link" data-crrowclient="${t.reference_id}">${esc(t.client_name)}</b>`
        : `<span class="cr-sub-inline">${t.credits > 0 ? "Wallet" : "Org-wide"}</span>`;
      // The badge already names the feature — only add the description when it
      // says something more (a top-up package, a support note, a bundle count).
      const why = (t.description && t.description !== meta.label && !actionLabels.has(t.description))
        ? t.description : "";
      return `<tr>
        <td style="white-space:nowrap">${fmtDateTime(t.created_at)}</td>
        <td>${creditBadge(meta)}</td>
        <td>${who}${why ? `<div class="cr-sub">${esc(why)}</div>` : ""}</td>
        <td class="cr-sub">${esc(t.created_by_name || "System")}</td>
        <td style="text-align:right;color:${pos ? "var(--success,#10b981)" : "var(--text)"};font-weight:600">${t.credits === 0 ? "—" : (pos ? "+" : "") + t.credits}</td>
        <td style="text-align:right">${t.balance_after}</td>
      </tr>`;
    }).join("")
      : `<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:22px">${L.loading ? "Loading…" : (filtered ? "No entries match these filters." : "No credit activity in this period.")}</td></tr>`;

    const periodLabel = f.period ? f.period.label : ((a.range || {}).label || "");
    mount.innerHTML = `
      <div class="card"><div class="card-head"><h3>Credit ledger</h3>
        <span class="cr-head-note">${L.total} ${L.total === 1 ? "entry" : "entries"} · showing ${L.rows.length}${
          periodLabel ? ` · ${esc(periodLabel)}` : ""}</span></div>
        ${f.period ? `<div class="card-body cr-drill">
          <span class="cr-drill-chip">📅 ${esc(f.period.label)}<button id="crDrillClear" title="Show the whole period again" aria-label="Clear the ${esc(f.period.bucket)} filter">×</button></span>
          <span class="cr-sub">Only entries from this ${esc(f.period.bucket)} — the cards above still cover ${esc((a.range || {}).label || "the selected period")}.</span>
        </div>` : ""}
        <div class="card-body">
          <div class="cr-filters">
            <input id="crQ" class="cr-input" placeholder="Search client, note or member…" value="${esc(f.q)}" />
            <select id="crKind" class="cr-input">
              <option value="">All activity</option>
              <option value="debit" ${f.kind === "debit" ? "selected" : ""}>Spend only</option>
              <option value="topup" ${f.kind === "topup" ? "selected" : ""}>Top-ups only</option>
              <option value="bonus" ${f.kind === "bonus" ? "selected" : ""}>Bonuses</option>
              <option value="adjustment" ${f.kind === "adjustment" ? "selected" : ""}>Adjustments</option>
            </select>
            <select id="crAction" class="cr-input">
              <option value="">All features</option>
              ${actions.map((x) => `<option value="${esc(x.key)}" ${f.action === x.key ? "selected" : ""}>${esc(x.label)}</option>`).join("")}
            </select>
            <select id="crMember" class="cr-input">
              <option value="">Everyone</option>
              ${members.map((m) => `<option value="${m.user_id}" ${String(f.member_id) === String(m.user_id) ? "selected" : ""}>${esc(m.name)}</option>`).join("")}
            </select>
            <select id="crClient" class="cr-input">
              <option value="">All clients</option>
              ${clients.map((c) => `<option value="${c.client_id}" ${String(f.client_id) === String(c.client_id) ? "selected" : ""}>${esc(c.name)}</option>`).join("")}
            </select>
            ${filtered ? `<button class="btn btn-ghost btn-sm" id="crClear">Clear</button>` : ""}
            <button class="btn btn-soft btn-sm" id="crExport" ${(!L.total || L.loading) ? 'disabled title="Nothing to export for these filters"' : 'title="Download these entries as CSV — opens directly in Excel"'}>⬇ Export</button>
          </div>
        </div>
        <div class="card-body" style="padding:0;overflow-x:auto">
          <table class="client-table cr-table"><thead><tr>
            <th>When</th><th>Activity</th><th>On whom / why</th><th>Member</th>
            <th style="text-align:right">Credits</th><th style="text-align:right">Balance</th>
          </tr></thead><tbody>${rows}</tbody></table>
        </div>
        ${L.error ? `<div class="card-body">${errBox(L.error)}</div>` : ""}
        ${L.hasMore ? `<div class="card-body" style="text-align:center">
          <button class="btn btn-ghost btn-sm" id="crMore" ${L.loading ? "disabled" : ""}>${L.loading ? "Loading…" : `Load 25 more (${L.total - L.rows.length} left)`}</button>
        </div>` : ""}
      </div>`;

    const q = $("#crQ");
    if (q) {
      let timer = null;
      q.oninput = () => {
        clearTimeout(timer);
        timer = setTimeout(() => { creditsUi.filters.q = q.value.trim(); crLoadLedger(true, true); }, 350);
      };
      q.onkeydown = (e) => {
        if (e.key === "Enter") { clearTimeout(timer); creditsUi.filters.q = q.value.trim(); crLoadLedger(true, true); }
      };
      if (keepCaret != null) {
        q.focus();
        try { q.setSelectionRange(keepCaret, keepCaret); } catch (e) { /* not a text input */ }
      }
    }
    const bind = (id, key) => {
      const el = $(id);
      if (el) el.onchange = () => { creditsUi.filters[key] = el.value; crLoadLedger(true, true); };
    };
    bind("#crKind", "kind"); bind("#crAction", "action");
    bind("#crMember", "member_id"); bind("#crClient", "client_id");
    const clear = $("#crClear");
    if (clear) clear.onclick = () => {
      const hadPeriod = !!creditsUi.filters.period;
      creditsUi.filters = { kind: "", action: "", member_id: "", client_id: "", q: "", period: null };
      // Dropping the drill-down un-highlights the bar and the table row too.
      if (hadPeriod) crDrawAnalyticsBody();
      crLoadLedger(true, true);
    };
    const drill = $("#crDrillClear");
    if (drill) drill.onclick = (e) => {
      e.stopPropagation();
      creditsUi.filters.period = null;
      crDrawAnalyticsBody();
      crLoadLedger(true, true);
    };
    const more = $("#crMore");
    if (more) more.onclick = () => crLoadLedger(false, true);
    const exp = $("#crExport");
    if (exp) exp.onclick = () => crExportLedger();
    $$("[data-crrowclient]", mount).forEach((el) => el.onclick = () => openClient(Number(el.dataset.crrowclient)));
  }

  /* Export the filtered ledger as CSV. Pulls the whole matching set (not just the
     rows on screen) so the download matches what the filters describe. */
  async function crExportLedger() {
    const btn = $("#crExport");
    if (btn) { btn.disabled = true; btn.textContent = "Preparing…"; }
    let res;
    try {
      res = await api("/credits/transactions?" + crLedgerQuery({ limit: 2000, offset: 0 }));
    } catch (ex) {
      toast(ex.message || "Couldn't build the export.", "error");
      if (btn) { btn.disabled = false; btn.textContent = "⬇ Export"; }
      return;
    }
    const rows = res.transactions || [];
    if (btn) { btn.disabled = false; btn.textContent = "⬇ Export"; }
    if (!rows.length) { toast("Nothing to export for these filters.", "error"); return; }

    // A cell starting with = + - @ is executed as a formula by Excel, and these
    // rows carry free-text notes — prefix-quote them. The BOM keeps ₹ intact.
    const cell = (v) => {
      if (typeof v === "number") return String(v);   // keep credits/balance numeric in Excel
      let s = v === null || v === undefined ? "" : String(v);
      if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
      return `"${s.replace(/"/g, '""')}"`;
    };
    const headers = ["When", "Type", "Feature", "Client", "Description", "Member", "Credits", "Balance after"];
    const body = rows.map((t) => [
      t.created_at ? new Date(t.created_at).toLocaleString() : "",
      t.type,
      (CREDIT_ACTION_META[t.action_key] || {}).label || (t.action_key || ""),
      t.client_name || "",
      t.description || "",
      t.created_by_name || "System",
      t.credits,
      t.balance_after,
    ]);
    const csv = [headers, ...body].map((r) => r.map(cell).join(",")).join("\r\n");
    const stamp = new Date().toISOString().slice(0, 10);
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `rilono-credit-ledger-${stamp}.csv`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 0);
    toast(`Exported ${rows.length} ${rows.length === 1 ? "entry" : "entries"}`, "success");
    if (res.has_more) toast("Export capped at 2,000 entries — narrow the period to get the rest.", "error");
  }

  async function applyCreditCoupon() {
    const input = $("#creditCouponInput");
    const code = ((input && input.value) || "").trim();
    if (!code) { toast("Enter a discount code.", "error"); return; }
    const pkgs = state.creditPackages || [];
    if (!pkgs.length) { toast("No packages available.", "error"); return; }
    await withBusy($("#creditCouponInputApply"), "", async () => {
      let res;
      try {
        res = await api("/coupons/validate", { method: "POST", body: { code, context: "credits", package: pkgs[0].key } });
      } catch (ex) { toast(ex.message || "Invalid discount code.", "error"); return; }
      state.creditCoupon = { code: res.code, percent: res.percent_off, percent_display: res.percent_display, free: !!res.free };
      toast(res.free ? `${res.percent_display} off — this top-up is free.` : res.percent_display + " discount applied.", "success");
      renderCredits();
    });
  }
  function removeCreditCoupon() { state.creditCoupon = null; renderCredits(); }

  // ---- Credit top-up checkout (order-review modal with live coupon + breakdown) ----
  let checkoutCtx = null;

  // The price ladder the server published for a package: one owner-chosen price per
  // currency, each with the amount AND the server's own rendering of it. Nothing on this
  // screen converts anything — picking a currency picks which quoted price to send back
  // as a hint, and the server still decides the amount it charges.
  function pkgOptions(pkg) {
    const opts = ((pkg || {}).price_options || []).filter((o) => o && o.currency);
    if (opts.length) return opts;
    // Payload without a ladder (older build): the one currency the package was quoted in.
    return [{
      currency: (pkg || {}).currency || "INR",
      amount_minor: Number((pkg || {}).amount_paise || 0),
      display: (pkg || {}).amount_display || fmtMoney((pkg || {}).amount_paise, (pkg || {}).currency || "INR"),
    }];
  }
  function pkgCurrencies(packages) {
    const seen = [];
    (packages || []).forEach((p) => pkgOptions(p).forEach((o) => {
      if (seen.indexOf(o.currency) === -1) seen.push(o.currency);
    }));
    return seen;
  }
  function checkoutOption() {
    const opts = pkgOptions(checkoutCtx.pkg);
    return opts.find((o) => o.currency === checkoutCtx.currency) || opts[0];
  }

  function openCreditCheckout(pkgKey) {
    const pkg = (state.creditPackages || []).find((p) => p.key === pkgKey);
    if (!pkg) { toast("Package unavailable.", "error"); return; }
    // Default to the currency the package was quoted in; the server applies the same
    // precedence (last billed → org country → INR) when we send no hint at all.
    checkoutCtx = {
      pkg,
      coupon: state.creditCoupon || null,
      currency: pkg.currency || pkgOptions(pkg)[0].currency,
    };
    renderCheckout();
  }

  function checkoutBreakdown() {
    const opt = checkoutOption();
    const currency = opt.currency;
    // Server-quoted, never converted: `amount_minor` is already in this currency's minor
    // unit. Only the coupon preview is arithmetic, and it stays inside one currency.
    const base = Number(opt.amount_minor || 0);
    const c = checkoutCtx.coupon;
    const discount = c ? Math.max(0, base - Math.max(0, Math.round(base * (100 - c.percent) / 100))) : 0;
    const total = Math.max(0, base - discount);
    // Mirrors /credits/topup/checkout exactly: it grants the top-up outright only when a
    // COUPON takes the amount under money.min_charge_minor(currency), and otherwise
    // creates a real order. enterprise_coupons.is_free_checkout()'s flat MIN_CHECKOUT_PAISE
    // = 100 is "₹1", so reusing it here called a $0.60 order free — the modal said "Get 100
    // credits — free", the server created a $0.60 order anyway and Razorpay opened asking
    // for money. The floor is per-currency; so is this test.
    return { base, discount, total, currency, free: !!c && total < minChargeMinor(currency) };
  }

  /* ============================================================
     FINANCE — collect student payments (Razorpay Route linked
     account). Phase 1: onboarding. Analytics + usage billing will
     nest here as sub-views later.
     ============================================================ */
  const ACCT_BUSINESS_TYPES = [
    ["proprietorship", "Sole proprietorship"],
    ["partnership", "Partnership"],
    ["llp", "LLP"],
    ["private_limited", "Private limited"],
    ["public_limited", "Public limited"],
    ["trust", "Trust"],
    ["society", "Society"],
    ["ngo", "NGO"],
    ["individual", "Individual"],
  ];

  function acctStatusChip(status) {
    const map = {
      activated: ["Active", "var(--success,#10b981)"],
      under_review: ["Under review", "var(--warning,#f59e0b)"],
      needs_clarification: ["Action needed", "var(--danger,#ef4444)"],
      settlement_submitted: ["Submitted", "var(--warning,#f59e0b)"],
      product_requested: ["In progress", "var(--warning,#f59e0b)"],
      stakeholder_added: ["In progress", "var(--warning,#f59e0b)"],
      created: ["In progress", "var(--warning,#f59e0b)"],
      suspended: ["Suspended", "var(--danger,#ef4444)"],
      not_started: ["Not connected", "var(--muted,#94a3b8)"],
    };
    const [label, color] = map[status] || ["Not connected", "var(--muted,#94a3b8)"];
    return `<span class="plan-current-tag" style="color:${color}">${esc(label)}</span>`;
  }

  function acctOnboardingForm(la) {
    la = la || {};
    const opt = (v, l) => `<option value="${v}"${la.business_type === v ? " selected" : ""}>${esc(l)}</option>`;
    return `<div class="card"><div class="card-body" style="max-width:860px">
      <div style="font-weight:800;font-size:16px;margin-bottom:4px">Connect your company bank account</div>
      <div style="font-size:13px;color:var(--text-2);margin-bottom:20px;line-height:1.55">
        Razorpay verifies your business (KYC) and settles collected payments directly to this account.
        We store only the last 4 digits — your full details stay with Razorpay.
        <br><b>India-registered businesses only</b> — Razorpay Route needs an Indian bank account,
        a business PAN and an IFSC code, and settles in INR.
      </div>

      <div class="cp-sub-label">Business details</div>
      <div class="field">
        <label>Legal business name *</label>
        <input id="acctLegalName" type="text" autocomplete="off" value="${esc(la.legal_business_name || "")}" placeholder="As registered — matches your PAN &amp; bank account">
      </div>
      <div class="field-row">
        <div class="field"><label>Business type *</label>
          <select id="acctBizType">${ACCT_BUSINESS_TYPES.map(([v, l]) => opt(v, l)).join("")}</select></div>
        <div class="field"><label>Business PAN *</label>
          <input id="acctPan" type="text" maxlength="10" autocomplete="off" value="${esc(la.business_pan_placeholder || "")}" placeholder="ABCDE1234F" style="text-transform:uppercase"></div>
      </div>
      <div class="field-row">
        <div class="field"><label>Contact name *</label>
          <input id="acctContactName" type="text" autocomplete="off" value="${esc(la.contact_name || "")}" placeholder="Owner / authorised signatory"></div>
        <div class="field"><label>Contact email *</label>
          <input id="acctContactEmail" type="email" autocomplete="off" value="${esc(la.contact_email || "")}" placeholder="finance@yourcompany.com"></div>
      </div>
      <div class="field-row">
        <div class="field"><label>Contact phone</label>
          <input id="acctContactPhone" type="text" autocomplete="off" value="${esc(la.contact_phone || "")}" placeholder="10-digit mobile"></div>
        <div class="field"><label>GST number <span style="color:var(--muted);font-weight:500">(optional)</span></label>
          <input id="acctGst" type="text" autocomplete="off" value="${esc(la.gst_number || "")}" placeholder="22ABCDE1234F1Z5" style="text-transform:uppercase"></div>
      </div>

      <div class="cp-sub-label" style="margin-top:6px">Settlement bank account</div>
      <div class="field-row">
        <div class="field"><label>Bank account number *</label>
          <input id="acctBankNum" type="text" inputmode="numeric" autocomplete="off" placeholder="Where payouts are settled"></div>
        <div class="field"><label>IFSC code *</label>
          <input id="acctIfsc" type="text" autocomplete="off" value="${esc(la.bank_ifsc || "")}" placeholder="HDFC0001234" style="text-transform:uppercase"></div>
      </div>
      <div class="field">
        <label>Account holder / beneficiary name *</label>
        <input id="acctBeneficiary" type="text" autocomplete="off" value="${esc(la.beneficiary_name || "")}" placeholder="Must match the bank account &amp; legal name">
      </div>

      <div class="consent-field" style="margin-bottom:10px">
        <input id="acctAttestService" type="checkbox">
        <label for="acctAttestService">My organization directly provides the visa/education service the student is paying for.</label>
      </div>
      <div class="consent-field">
        <input id="acctAttestTurnover" type="checkbox">
        <label for="acctAttestTurnover">The details above are accurate and my business is eligible to receive these payments.</label>
      </div>

      <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-top:6px">
        <button class="btn btn-primary" id="acctSaveBtn" onclick="__ent.saveBank()" disabled>Connect bank account</button>
        <span style="font-size:12px;color:var(--muted)">🔒 Secured by Razorpay · funds are never held by Rilono</span>
      </div>
      <div style="font-size:12px;color:var(--muted);margin-top:10px;line-height:1.6">
        By connecting, you agree to the <a href="/terms" target="_blank" rel="noopener">Rilono Terms</a>
        (&ldquo;Payment Collection for Consultancies&rdquo;), the
        <a href="/privacy" target="_blank" rel="noopener">Privacy Policy</a> and
        <a href="/dpa" target="_blank" rel="noopener">DPA</a>, and you authorise Rilono to accept
        <a href="https://razorpay.com/terms/" target="_blank" rel="noopener">Razorpay's terms</a> for linked
        accounts on your organization's behalf to activate collection.
      </div>
    </div></div>`;
  }

  /* ================================================================
     FINANCE — the consultancy's own books, not just the payout account.

     One server-built ledger (/finance/books) feeds every tab: money the
     platform already knows about (collected payments, the Rilono fee on
     them, credit top-ups, refunds, lost chargebacks) is DERIVED, and only
     money it can't see (cash fees, salaries, rent, ads, commissions) is
     hand-recorded — so the ledger and the analytics can never disagree.
     Company money is admin-only; everyone else sees the payout status.
     ================================================================ */
  const finUi = {
    tab: "overview",
    range: "this_month",
    custom: { start: "", end: "" },
    summary: null,        // /finance/summary — payout account + fee config
    analytics: null,      // /finance/analytics for the active period
    savings: null,        // /finance/savings for the active period
    settings: null,       // hourly cost, opening balance, FY start, baselines
    categories: null,     // selectable category lists from the server
    clients: null,        // lazily loaded for the entry form's client picker
    ledger: { kind: "income", rows: [], total: 0, offset: 0, loading: false, error: null, totals: null, note: null },
    filters: { category: "", source: "", client_id: "", q: "" },
  };
  const FIN_RANGES = [
    { key: "this_month", label: "This month" },
    { key: "last_month", label: "Last month" },
    { key: "this_quarter", label: "This quarter" },
    { key: "this_fy", label: "This FY" },
    { key: "last_12m", label: "12 months" },
    { key: "all", label: "All time" },
  ];
  const FIN_TABS = [
    { key: "overview", label: "📊 Overview" },
    { key: "income", label: "↘ Income" },
    { key: "expenses", label: "↗ Costs" },
    { key: "savings", label: "⚡ Saved with Rilono" },
    { key: "account", label: "🏦 Payout account" },
  ];
  // Category hues. Income leans green/teal, costs warm/violet, and anything
  // Rilono bills sits in the brand indigo so platform cost reads as its own thing.
  const FIN_CAT_COLORS = {
    student_fee: "#10b981", rilono_refund: "#818cf8", service_fee: "#0ea5e9", university_commission: "#14b8a6",
    test_prep: "#22c55e", visa_filing: "#06b6d4", document_service: "#84cc16",
    travel_forex: "#2dd4bf", other_income: "#64748b",
    salaries: "#f97316", agent_commission: "#f59e0b", rent_utilities: "#ef4444",
    marketing: "#ec4899", software: "#8b5cf6", travel_events: "#f43f5e",
    professional: "#a855f7", office: "#94a3b8", taxes: "#dc2626",
    bank_charges: "#fb7185", chargeback: "#b91c1c", student_refund: "#f43f5e",
    rilono_platform: "#6366f1", rilono_credits: "#818cf8", rilono_infra: "#4f46e5",
    other_expense: "#64748b",
  };
  function finCatColor(key) { return FIN_CAT_COLORS[key] || "#64748b"; }
  // A net figure: minus sign OUTSIDE the currency symbol, and never "-₹0".
  function finNet(paise) {
    const n = Number(paise || 0);
    return (n < 0 ? "−" : "") + fmtDisplay(Math.abs(n), "INR");
  }
  function finPct(value) {
    if (value == null) return "";
    const n = Number(value);
    // A first month with revenue against a near-empty one produces "+2383.3%", which reads
    // as a glitch rather than growth. Past 999% the exact figure carries no information.
    if (Math.abs(n) > 999) return (n > 0 ? "+" : "−") + "999%+";
    return (n > 0 ? "+" : "") + n.toFixed(n % 1 === 0 ? 0 : 1) + "%";
  }
  function finRangeQuery(extra) {
    const params = new URLSearchParams();
    params.set("range_key", finUi.range);
    if (finUi.range === "custom") {
      if (finUi.custom.start) params.set("start", finUi.custom.start);
      if (finUi.custom.end) params.set("end", finUi.custom.end);
    }
    Object.entries(extra || {}).forEach(([k, v]) => {
      if (v !== "" && v != null) params.set(k, String(v));
    });
    return params.toString();
  }
  function finInvalidateRange() {
    finUi.analytics = null;
    finUi.savings = null;
    finUi.ledger = { ...finUi.ledger, rows: [], total: 0, offset: 0, error: null, totals: null, note: null };
  }
  // Called after every successful write. Saving from Overview must also drop the LEDGER
  // cache, or the Income/Costs tab keeps showing rows from before the edit.
  function finAfterWrite() {
    finInvalidateRange();
    if (finUi.tab === "overview") finDrawOverview();
    else if (finUi.tab === "savings") finDrawSavings();
    else finLoadLedger(true, true);
  }

  async function renderFinance() {
    const c = $("#content");
    if (!finUi.summary) c.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
    let d;
    try { d = await api("/finance/summary"); }
    catch (ex) {
      if (state.view !== "finance") return;
      c.innerHTML = errBox(ex); return;
    }
    if (state.view !== "finance") return;   // user moved on while we were loading
    finUi.summary = d;
    // Every entry into the view starts from fresh data; the per-tab caches below
    // only survive tab switches.
    finInvalidateRange();
    finDraw();
  }

  // Shell: payout banner (only when something needs doing) + tabs. The active
  // tab paints into #finPanel.
  function finDraw() {
    if (state.view !== "finance") return;
    const c = $("#content");
    const d = finUi.summary || {};
    const la = d.linked_account;
    const fee = d.fee || {};
    // Two independent capabilities meet in this view: the company books (P&L, costs,
    // savings — which additionally need workspace-wide data scope, because a branch's
    // slice of the books is not a book) and the payout bank account.
    const canBooks = can("finance.books") && isOrgScope();
    const canPayout = can("finance.payout_account");
    const connected = !!(la && la.activation_status && la.activation_status !== "not_started");

    // Without either, all we report is whether collection is live at all.
    if (!canBooks && !canPayout) {
      c.innerHTML = `<div class="card"><div class="card-body" style="color:var(--text-2);line-height:1.7">
        <div style="font-weight:800;font-size:16px;color:var(--text);margin-bottom:6px">Finance</div>
        ${connected
          ? `Your organization's payout account is ${acctStatusChip(la.activation_status)}.`
          : "No payout account is connected yet, so student payments can't be collected online."}
        <br>${can("finance.books") && !isOrgScope()
          ? "The company books cover the whole workspace, so they're only shown to members whose access isn't limited to one office."
          : "You don't have permission to view the company books. Ask a workspace admin for access."}
      </div></div>`;
      return;
    }

    // Only offer the tabs this member can actually open, and keep the active tab legal.
    const tabs = FIN_TABS.filter((t) => (t.key === "account" ? canPayout : canBooks));
    if (!tabs.some((t) => t.key === finUi.tab)) finUi.tab = tabs[0].key;

    const needsBank = !connected || !la.is_payable;
    // Don't nudge a non-Indian org towards a form Razorpay Route can never activate for
    // them — the Payout account tab explains why instead (see acctCountryBlockedCard).
    const bankBanner = (needsBank && canPayout && orgIsIndian() && finUi.tab !== "account")
      ? `<div class="fin-nudge">
          <div class="fin-nudge-ic">🏦</div>
          <div class="fin-nudge-txt">
            <b>${connected ? "Your payout account is still being verified" : "Connect your bank to collect student payments online"}</b>
            <span>${connected
              ? "Razorpay is checking your details. Until it clears, you can still record payments you collected offline."
              : `Send students a secure pay link and have the money settle straight into your own account. Rilono keeps ${esc(String(fee.percent))}%, min ${esc(fmtInrExact(fee.min_fee_rupees))} — and never holds your funds.`}</span>
          </div>
          <button class="btn btn-primary" id="finGoAccount">${connected ? "Check status" : "Connect bank"}</button>
        </div>`
      : "";

    c.innerHTML = `
      ${bankBanner}
      <div class="fin-tabs">
        ${tabs.map((t) => `<button class="fin-tab ${finUi.tab === t.key ? "active" : ""}" data-fintab="${t.key}">${t.label}${
          t.key === "account" && needsBank ? ' <span class="fin-dot"></span>' : ""}</button>`).join("")}
      </div>
      <div id="finPanel"></div>`;

    const go = $("#finGoAccount");
    if (go) go.onclick = () => { finUi.tab = "account"; finDraw(); };
    $$(".fin-tab", c).forEach((b) => b.onclick = () => {
      if (finUi.tab === b.dataset.fintab) return;
      finUi.tab = b.dataset.fintab;
      finDraw();
    });

    if (finUi.tab === "overview") finDrawOverview();
    else if (finUi.tab === "income") finDrawLedger("income");
    else if (finUi.tab === "expenses") finDrawLedger("expense");
    else if (finUi.tab === "savings") finDrawSavings();
    else finDrawAccount();
  }

  /* ---- Shared period selector. Every data tab carries the same one so the
     answer to "which period am I looking at?" is always in the same place. ---- */
  function finRangeBar(extraRight) {
    const custom = finUi.range === "custom";
    return `<div class="fin-rangebar">
      <span class="fin-rangelabel">Period</span>
      ${FIN_RANGES.map((r) => `<button class="fin-range ${finUi.range === r.key ? "active" : ""}" data-finrange="${r.key}">${esc(r.label)}</button>`).join("")}
      <button class="fin-range ${custom ? "active" : ""}" data-finrange="custom">Custom</button>
      ${custom ? `<span class="fin-custom">
        <input type="date" class="fin-input" id="finFrom" value="${esc(finUi.custom.start || "")}" aria-label="From date">
        <span class="fin-custom-sep">→</span>
        <input type="date" class="fin-input" id="finTo" value="${esc(finUi.custom.end || "")}" aria-label="To date">
      </span>` : ""}
      <span class="fin-rangespacer"></span>
      ${extraRight ? `<span class="fin-actions">${extraRight}</span>` : ""}
    </div>`;
  }

  function finWireRangeBar(root) {
    $$("[data-finrange]", root).forEach((b) => b.onclick = () => {
      const key = b.dataset.finrange;
      if (key === finUi.range && key !== "custom") return;
      finUi.range = key;
      finInvalidateRange();
      finDraw();
    });
    const from = $("#finFrom", root);
    const to = $("#finTo", root);
    const apply = () => {
      const nextStart = (from && from.value) || "";
      const nextEnd = (to && to.value) || "";
      if (!nextStart || !nextEnd) return;   // wait for both halves; don't touch state yet
      if (nextStart === finUi.custom.start && nextEnd === finUi.custom.end) return;
      finUi.custom.start = nextStart;
      finUi.custom.end = nextEnd;
      finInvalidateRange();
      finDraw();
    };
    if (from) from.onchange = apply;
    if (to) to.onchange = apply;
    const exp = $("#finExportBtn", root);
    if (exp) exp.onclick = () => finExport(exp);
    const set = $("#finSettingsBtn", root);
    if (set) set.onclick = () => finOpenSettings();
  }

  // Editing the assumptions writes to the books (finance.books_manage); the export is its
  // own capability because it walks out of the building as a file.
  function finToolbarActionsHtml() {
    return (can("finance.books_manage")
      ? `<button class="btn btn-ghost btn-sm" id="finSettingsBtn" title="Hourly cost, opening balance, financial year">⚙ Assumptions</button>` : "") +
      (can("finance.export")
        ? `<button class="btn btn-soft btn-sm" id="finExportBtn">⬇ Export book</button>` : "");
  }

  /* ---------------- Tab 1 · Overview (the P&L) ---------------- */
  function finDrawOverview() {
    const panel = $("#finPanel");
    if (!panel) return;
    panel.innerHTML = finRangeBar(finToolbarActionsHtml()) +
      `<div id="finOvBody"><div class="center-load"><div class="spinner dark"></div></div></div>`;
    finWireRangeBar(panel);
    if (finUi.analytics && finUi.analytics._key === finRangeQuery()) finDrawOverviewBody();
    else finLoadAnalytics();
  }

  async function finLoadAnalytics() {
    const stamp = finRangeQuery();
    let res;
    try { res = await api("/finance/analytics?" + stamp); }
    catch (ex) {
      if (state.view !== "finance" || finUi.tab !== "overview") return;
      const body = $("#finOvBody");
      if (body) body.innerHTML = errBox(ex);
      return;
    }
    if (state.view !== "finance" || finUi.tab !== "overview" || finRangeQuery() !== stamp) return;
    res._key = stamp;
    finUi.analytics = res;
    finUi.settings = res.settings || finUi.settings;
    finDrawOverviewBody();
  }

  function finDrawOverviewBody() {
    const body = $("#finOvBody");
    if (!body) return;
    const a = finUi.analytics || {};
    const t = a.totals || {};
    const prev = a.previous;
    const rec = a.receivables || {};
    const col = a.collections || {};
    const cash = a.cash || {};
    const rangeLabel = (a.range || {}).label || "";
    const profit = Number(t.net_paise || 0) >= 0;

    if (!t.entry_count) {
      body.innerHTML = `<div class="card"><div class="card-body" style="text-align:center;padding:44px 20px">
        <div style="font-size:34px">📒</div>
        <h3 style="margin:10px 0 6px">Nothing in the books for ${esc(rangeLabel.toLowerCase())}</h3>
        <p class="fin-muted" style="margin:0 auto 18px;max-width:520px;font-size:13.5px;line-height:1.65">
          Payments you collect through Rilono land here on their own. Add the money Rilono can't see —
          fees taken in cash, university commissions, salaries, rent, ads — and this becomes your live P&amp;L.</p>
        ${can("finance.books_manage") ? `<div class="fin-empty-cta">
          <button class="btn btn-primary" onclick="__ent.finAdd('income')">+ Record income</button>
          <button class="btn btn-ghost" onclick="__ent.finAdd('expense')">+ Record a cost</button>
        </div>` : ""}
      </div></div>`;
      return;
    }

    const delta = (pct, invert) => {
      if (pct == null) return "";
      const good = invert ? Number(pct) <= 0 : Number(pct) >= 0;
      return `<span class="fin-delta ${good ? "up" : "down"}">${esc(finPct(pct))}</span>`;
    };
    const kpi = (icon, color, label, value, sub, tip) => `
      <div class="kpi">
        <div class="kpi-top"><div class="kpi-ic" style="background:${color}">${icon}</div></div>
        <div class="kpi-label">${esc(label)}${tip ? infoTip(tip, label) : ""}</div>
        <div class="kpi-value">${value}</div>
        <div class="kpi-sub">${sub}</div>
      </div>`;

    const kpis = `<div class="kpi-grid">
      ${kpi("↘", "linear-gradient(135deg,#10b981,#34d399)", "Money in", fmtDisplay(t.income_paise, "INR"),
        `${t.income_count} ${t.income_count === 1 ? "entry" : "entries"} ${prev
          ? delta(prev.income_change_pct) + (prev.label ? ` <span class="fin-vs">vs ${esc(prev.label)}</span>` : "")
          : "· " + esc(rangeLabel.toLowerCase())}`)}
      ${kpi("↗", "linear-gradient(135deg,#f97316,#fb923c)", "Money out", fmtDisplay(t.expense_paise, "INR"),
        `${t.expense_count} ${t.expense_count === 1 ? "entry" : "entries"} ${prev ? delta(prev.expense_change_pct, true) : ""}`)}
      ${kpi(profit ? "📈" : "📉", profit ? "linear-gradient(135deg,#6366f1,#8b5cf6)" : "linear-gradient(135deg,#ef4444,#f87171)",
        profit ? "Net profit" : "Net loss",
        `<span style="color:${profit ? "var(--success,#10b981)" : "var(--danger,#ef4444)"}">${esc(finNet(t.net_paise))}</span>`,
        `${t.margin_is_meaningful === false ? "no income yet" : t.margin_pct + "% margin"} ${prev ? delta(prev.net_change_pct) : ""}`,
        "Margin is net profit as a share of money in, for this period only.")}
      ${kpi("⏳", Number(rec.overdue_paise || 0) > 0 ? "linear-gradient(135deg,#ef4444,#f87171)" : "linear-gradient(135deg,#0ea5e9,#22d3ee)",
        "Still owed to you", fmtDisplay(rec.total_paise, "INR"),
        rec.count ? `${rec.count} unpaid ${rec.count === 1 ? "request" : "requests"}${Number(rec.overdue_paise) ? ` · ${fmtDisplay(rec.overdue_paise, "INR")} overdue` : ""}` : "Everything raised has been paid",
        "Payment requests raised on your clients that haven't been paid yet. Not affected by the period above — an old invoice is still owed today.")}
    </div>`;

    const tl = a.timeline || {};
    const chart = `<div class="card fin-card"><div class="card-head">
        <h3>Money in vs money out</h3>
        <span class="fin-head-note">
          <span class="fin-key in"></span>In <span class="fin-key out"></span>Out · ${esc(rangeLabel)}
        </span></div>
      <div class="card-body">${finChart(tl)}</div></div>`;

    const catRows = (list, empty) => (list && list.length)
      ? list.map((x) => `<div class="fin-split-row">
          <div class="fin-split-top">
            <div><b>${esc(x.label)}</b> <span class="fin-sub-inline">· ${x.count} ${x.count === 1 ? "entry" : "entries"}${x.auto ? " · automatic" : ""}</span></div>
            <div class="fin-split-amt"><b>${fmtDisplay(x.amount_paise, "INR")}</b><span> · ${x.share_pct}%</span></div>
          </div>
          ${usageBar(x.share_pct, finCatColor(x.key))}
        </div>`).join("")
      : `<div class="fin-empty">${empty}</div>`;

    const split = `<div class="grid-2 even">
      <div class="card"><div class="card-head"><h3>Where the money came from</h3><span class="fin-head-note">income by category</span></div>
        <div class="card-body">${catRows(a.income_by_category, "No income recorded in this period.")}</div></div>
      <div class="card"><div class="card-head"><h3>Where it went</h3><span class="fin-head-note">costs by category</span></div>
        <div class="card-body">${catRows(a.expense_by_category, "No costs recorded in this period.")}</div></div>
    </div>`;

    // Cash + collections: the two "can I pay my bills" questions.
    const cashCard = `<div class="card"><div class="card-head"><h3>Cash position</h3>
        <span class="fin-head-note">${cash.is_configured ? `opening ${fmtDisplay(cash.opening_paise, "INR")}${cash.opening_on ? ` on ${fmtDate(cash.opening_on)}` : ""}` : "not set up"}</span></div>
      <div class="card-body">
        ${cash.is_configured
          ? `<div class="fin-bignum ${Number(cash.balance_paise) < 0 ? "neg" : ""}">${esc(finNet(cash.balance_paise))}</div>
             <div class="fin-sub">Opening balance ${cash.movement_paise >= 0 ? "plus" : "minus"} everything in your books since then.</div>`
          : `<div class="fin-empty" style="text-align:left">
              Set your opening bank balance in <b>⚙ Assumptions</b> and Rilono will keep a running cash
              position from your books.
              <div style="margin-top:10px"><button class="btn btn-ghost btn-sm" id="finCashSetup">Set opening balance</button></div>
            </div>`}
        <div class="fin-facts">
          <div><span>Collected this period</span><b>${fmtDisplay(col.collected_paise, "INR")}</b></div>
          <div><span>Collection rate</span><b>${col.collection_rate_pct}%</b></div>
          <div><span>Avg days to pay</span><b>${col.avg_days_to_pay == null ? "—" : col.avg_days_to_pay}</b></div>
          <div><span>Avg payment size</span><b>${fmtDisplay(col.avg_invoice_paise, "INR")}</b></div>
          <div><span>Online vs offline</span><b>${col.online_share_pct}% online</b></div>
          <div><span>Refunded</span><b>${fmtDisplay(col.refunded_paise, "INR")}</b></div>
        </div>
      </div></div>`;

    const save = a._savings;   // filled in by finLoadOverviewSavings()
    const savingsTeaser = `<div class="card fin-accent" id="finSaveTeaser"><div class="card-head">
        <h3>Saved with Rilono</h3><span class="fin-head-note">${esc(rangeLabel)}</span></div>
      <div class="card-body">
        ${save ? `
          <div class="fin-bignum">${esc(save.totals.hours_display)}<span> hours</span></div>
          <div class="fin-sub">≈ ${save.totals.workdays} working days of counsellor time, worth
            <b>${fmtDisplay(save.totals.value_paise, "INR")}</b> at ${fmtDisplay(save.hourly_cost_paise, "INR")}/hour.</div>
          <div class="fin-facts">
            <div><span>You paid Rilono</span><b>${fmtDisplay(save.rilono_cost.total_paise, "INR")}</b></div>
            <div><span>Net gain</span><b class="${save.is_net_positive ? "ok" : "warn"}">${esc(finNet(save.net_paise))}</b></div>
            <div><span>Return</span><b>${save.roi_multiple == null ? "—" : save.roi_multiple + "×"}</b></div>
          </div>
          <button class="btn btn-ghost btn-sm" style="margin-top:14px" onclick="__ent.finTab('savings')">See the full breakdown →</button>`
          : `<div class="center-load" style="padding:30px"><div class="spinner dark"></div></div>`}
      </div></div>`;

    const agingRows = (rec.aging || []).filter((b) => b.count).map((b) => `
      <div class="fin-split-row">
        <div class="fin-split-top">
          <div><b>${esc(b.label)}</b> <span class="fin-sub-inline">· ${b.count} ${b.count === 1 ? "request" : "requests"}</span></div>
          <div class="fin-split-amt"><b>${fmtDisplay(b.amount_paise, "INR")}</b><span> · ${b.share_pct}%</span></div>
        </div>
        ${usageBar(b.share_pct, b.key === "not_due" ? "#0ea5e9" : (b.key === "d60_plus" ? "#b91c1c" : "#f59e0b"))}
      </div>`).join("");

    const chaseRows = (rec.oldest || []).map((i) => `
      <tr${i.client_id ? ` data-finclient="${i.client_id}" title="Open ${esc(i.client_name)}"` : ""}>
        <td><b>${esc(i.client_name)}</b>${i.invoice_number ? `<div class="fin-sub">${esc(i.invoice_number)}</div>` : ""}</td>
        <td class="hide-sm fin-sub">${i.raised_on ? fmtDate(i.raised_on) : "—"}</td>
        <td class="hide-sm fin-sub">${i.due_date ? fmtDate(i.due_date) : "—"}</td>
        <td style="text-align:right"><b>${fmtDisplay(i.amount_paise, "INR")}</b></td>
        <td style="text-align:right">${i.days_late > 0
          ? `<span class="fin-status warn">${i.days_late}d late</span>`
          : `<span class="fin-status pend">Not due</span>`}</td>
      </tr>`).join("");

    const receivablesCard = rec.count ? `
      <div class="card"><div class="card-head"><h3>Who owes you</h3>
        <span class="fin-head-note">${rec.count} unpaid · ${fmtDisplay(rec.total_paise, "INR")}</span></div>
        <div class="card-body">${agingRows}</div>
        <div class="card-body" style="padding:0;overflow-x:auto;border-top:1px solid var(--border)">
          <table class="client-table fin-table"><thead><tr>
            <th>Client</th><th class="hide-sm">Raised</th><th class="hide-sm">Due</th>
            <th style="text-align:right">Amount</th><th style="text-align:right">Status</th>
          </tr></thead><tbody>${chaseRows}</tbody></table>
        </div>
        <div class="card-body fin-sub" style="border-top:1px solid var(--border)">
          Open a client and use their <b>Payments</b> tab to resend the pay link or record money taken offline.
        </div></div>` : "";

    const clients = (a.by_client || {}).clients || [];
    const clientRows = clients.length ? clients.map((x) => `
      <tr${x.client_id && x.exists ? ` data-finclient="${x.client_id}" title="Open ${esc(x.name)}"` : ' style="cursor:default"'}>
        <td><b>${esc(x.name)}</b>${x.is_rollup || x.exists ? "" : ' <span class="fin-sub-inline">(removed)</span>'}</td>
        <td style="text-align:right">${fmtDisplay(x.income_paise, "INR")}</td>
        <td style="text-align:right" class="hide-sm">${fmtDisplay(x.expense_paise, "INR")}</td>
        <td style="text-align:right"><b>${esc(finNet(x.net_paise))}</b></td>
        <td style="text-align:right" class="hide-sm">${x.margin_pct}%</td>
      </tr>`).join("")
      : `<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:22px">No money attributed to a client yet.</td></tr>`;

    const un = a.by_client || {};
    const clientCard = `<div class="card"><div class="card-head"><h3>Profit per client</h3>
        <span class="fin-head-note">fees in, direct costs out${
          Number(un.unassigned_income_paise) || Number(un.unassigned_expense_paise)
            ? ` · ${fmtDisplay(un.unassigned_income_paise, "INR")} in / ${fmtDisplay(un.unassigned_expense_paise, "INR")} out not tied to a client` : ""}</span></div>
      <div class="card-body" style="padding:0;overflow-x:auto">
        <table class="client-table fin-table"><thead><tr>
          <th>Client</th><th style="text-align:right">Income</th>
          <th style="text-align:right" class="hide-sm">Direct costs</th>
          <th style="text-align:right">Net</th><th style="text-align:right" class="hide-sm">Margin</th>
        </tr></thead><tbody>${clientRows}</tbody></table>
      </div>
      <div class="card-body fin-sub" style="border-top:1px solid var(--border)">
        Tag an income or cost entry with a client and it lands in this table — that's how a case's real
        margin shows up (agent commission, ad spend, the Rilono fee on their payment).
      </div></div>`;

    const dims = a.dimensions || {};
    const dimCard = (title, note, list, empty) => `
      <div class="card"><div class="card-head"><h3>${esc(title)}</h3><span class="fin-head-note">${esc(note)}</span></div>
        <div class="card-body">${(list && list.length) ? list.map((x, i) => `
          <div class="fin-split-row">
            <div class="fin-split-top">
              <div><b>${esc(x.label)}</b> <span class="fin-sub-inline">· ${x.clients} ${x.clients === 1 ? "client" : "clients"} · avg ${fmtDisplay(x.clients ? Math.round(x.amount_paise / x.clients) : 0, "INR")}</span></div>
              <div class="fin-split-amt"><b>${fmtDisplay(x.amount_paise, "INR")}</b><span> · ${x.share_pct}%</span></div>
            </div>
            ${usageBar(x.share_pct, ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6"][i % 6])}
          </div>`).join("") : `<div class="fin-empty">${empty}</div>`}
        </div></div>`;

    const dimsRow = `<div class="grid-2 even">
      ${dimCard("Revenue by destination", "which countries pay", dims.destinations, "Attribute income to clients to see this.")}
      ${dimCard("Revenue by lead source", "which channels pay back", dims.lead_sources, "Set a lead source on your clients to see which marketing pays.")}
    </div>`;

    const members = a.by_member || [];
    const branches = dims.branches || [];
    const teamRow = (members.length || branches.length) ? `<div class="grid-2 even">
      <div class="card"><div class="card-head"><h3>Who collected it</h3><span class="fin-head-note">by team member</span></div>
        <div class="card-body">${members.length ? members.map((m) => `
          <div class="fin-member-row">
            <span class="fin-avatar" style="background:${avatarColor(m.name)[0]}">${esc(initials(m.name))}</span>
            <div class="fin-member-main">
              <div class="fin-member-name">${esc(m.name)}</div>
              <div class="fin-sub">${m.payments} ${m.payments === 1 ? "payment" : "payments"} collected</div>
            </div>
            <div class="fin-split-amt"><b>${fmtDisplay(m.amount_paise, "INR")}</b><div class="fin-sub">${m.share_pct}%</div></div>
          </div>`).join("") : `<div class="fin-empty">No payments collected in this period.</div>`}
        </div></div>
      ${branches.length
        ? dimCard("Revenue by branch", "by office", branches, "Set a branch on your clients to compare offices.")
        : `<div class="card"><div class="card-head"><h3>Biggest costs</h3><span class="fin-head-note">by payee</span></div>
            <div class="card-body">${(a.top_counterparties || []).length ? (a.top_counterparties || []).map((x, i) => `
              <div class="fin-split-row">
                <div class="fin-split-top">
                  <div><b>${esc(x.name)}</b> <span class="fin-sub-inline">· ${x.count} ${x.count === 1 ? "payment" : "payments"}</span></div>
                  <div class="fin-split-amt"><b>${fmtDisplay(x.amount_paise, "INR")}</b><span> · ${x.share_pct}%</span></div>
                </div>
                ${usageBar(x.share_pct, ["#f97316", "#ef4444", "#8b5cf6", "#ec4899", "#f59e0b", "#64748b"][i % 6])}
              </div>`).join("") : `<div class="fin-empty">No costs recorded in this period.</div>`}
            </div></div>`}
    </div>` : "";

    const trend = a.trend || {};
    const series = trend.series || [];
    const trendPeak = Math.max(1, ...series.map((p) => Math.max(p.income_paise, p.expense_paise)));
    const trendCard = series.length ? `
      <div class="card"><div class="card-head"><h3>Last 6 months</h3>
        <span class="fin-head-note">${trend.projection ? `next month tracking ${esc(finNet(trend.projection.net_paise))}` : "month by month"}</span></div>
        <div class="card-body" style="padding:0;overflow-x:auto">
          <table class="client-table fin-table"><thead><tr>
            <th>Month</th><th style="text-align:right">In</th><th style="text-align:right">Out</th>
            <th style="text-align:right">Net</th><th class="hide-sm" style="width:34%">Shape</th>
          </tr></thead><tbody>
          ${series.map((p) => `<tr style="cursor:default">
            <td><b>${esc(p.label)}</b>${p.is_partial ? ' <span class="fin-sub-inline">so far</span>' : ""}</td>
            <td style="text-align:right">${fmtDisplay(p.income_paise, "INR")}</td>
            <td style="text-align:right">${fmtDisplay(p.expense_paise, "INR")}</td>
            <td style="text-align:right"><b style="color:${p.net_paise >= 0 ? "var(--success,#10b981)" : "var(--danger,#ef4444)"}">${esc(finNet(p.net_paise))}</b></td>
            <td class="hide-sm"><div class="fin-mini">
              <div class="fin-mini-bar in" style="width:${Math.round((p.income_paise / trendPeak) * 100)}%"></div>
              <div class="fin-mini-bar out" style="width:${Math.round((p.expense_paise / trendPeak) * 100)}%"></div>
            </div></td>
          </tr>`).join("")}
          </tbody></table>
        </div>
        ${trend.projection ? `<div class="card-body fin-sub" style="border-top:1px solid var(--border)">
          At the average of your last ${trend.projection.months_used} complete months, <b>${esc(trend.projection.label)}</b>
          lands near ${fmtDisplay(trend.projection.income_paise, "INR")} in and ${fmtDisplay(trend.projection.expense_paise, "INR")} out
          (${esc(finNet(trend.projection.net_paise))} net). An estimate from your own history, not a forecast model.
        </div>` : ""}
      </div>` : "";

    const truncated = a.truncated ? `<div class="fin-notice">⚠ ${esc(a.truncated_note || "")}</div>` : "";

    body.innerHTML = `${truncated}${kpis}${chart}${split}
      <div class="grid-2 even">${cashCard}${savingsTeaser}</div>
      ${receivablesCard}${clientCard}${dimsRow}${teamRow}${trendCard}`;

    $$("[data-finclient]", body).forEach((tr) => tr.onclick = () => openClient(Number(tr.dataset.finclient)));
    const setup = $("#finCashSetup", body);
    if (setup) setup.onclick = () => finOpenSettings();
    if (!save) finLoadOverviewSavings();
  }

  // The savings teaser rides along on the overview but loads separately, so a
  // slower ROI query never delays the P&L.
  async function finLoadOverviewSavings() {
    const stamp = finRangeQuery();
    let res;
    try { res = await api("/finance/savings?" + stamp); }
    catch (ex) {
      if (state.view !== "finance" || finUi.tab !== "overview" || finRangeQuery() !== stamp) return;
      const card = $("#finSaveTeaser .card-body");
      if (card) card.innerHTML = `<div class="fin-empty">Couldn't load your savings just now.</div>`;
      return;
    }
    if (state.view !== "finance" || finUi.tab !== "overview" || finRangeQuery() !== stamp) return;
    res._key = stamp;
    finUi.savings = res;
    if (finUi.analytics) finUi.analytics._savings = res;
    finDrawOverviewBody();
  }

  /* ---- Paired in/out column chart. Same dependency-free approach as the
     credits chart: it reflows with the card and each column carries its own
     hover readout. ---- */
  function finChart(tl) {
    const points = (tl && tl.points) || [];
    if (!points.length) return `<div class="fin-empty">No entries in this period.</div>`;
    const peak = Math.max(1, Number(tl.peak_paise) || 0);
    const bars = points.map((p) => {
      const ih = p.income_paise > 0 ? Math.max(4, Math.round((p.income_paise / peak) * 100)) : 0;
      const eh = p.expense_paise > 0 ? Math.max(4, Math.round((p.expense_paise / peak) * 100)) : 0;
      const title = `${crBucketLabel(p.key, tl.bucket)} — in ${fmtDisplay(p.income_paise, "INR")} · out ${fmtDisplay(p.expense_paise, "INR")} · net ${finNet(p.net_paise)}`;
      return `<div class="fin-bar-slot" title="${esc(title)}">
        ${ih ? `<div class="fin-bar in" style="height:${ih}%"></div>` : `<div class="fin-bar fin-bar-zero"></div>`}
        ${eh ? `<div class="fin-bar out" style="height:${eh}%"></div>` : `<div class="fin-bar fin-bar-zero"></div>`}
      </div>`;
    }).join("");
    const mid = points[Math.floor(points.length / 2)];
    return `
      <div class="fin-chart-wrap">
        <div class="fin-chart-y"><span>${esc(fmtDisplay(peak, "INR"))}</span><span>0</span></div>
        <div class="fin-chart">${bars}</div>
      </div>
      <div class="fin-chart-x">
        <span>${esc(crBucketLabel(points[0].key, tl.bucket, true))}</span>
        <span>${esc(crBucketLabel(mid.key, tl.bucket, true))}</span>
        <span>${esc(crBucketLabel(points[points.length - 1].key, tl.bucket, true))}</span>
      </div>`;
  }

  /* ---------------- Tabs 2 & 3 · The ledgers ---------------- */
  function finDrawLedger(kind) {
    const panel = $("#finPanel");
    if (!panel) return;
    if (finUi.ledger.kind !== kind) {
      finUi.ledger = { kind, rows: [], total: 0, offset: 0, loading: false, error: null, totals: null, note: null };
      finUi.filters = { category: "", source: "", client_id: "", q: "" };
    }
    const isIncome = kind === "income";
    panel.innerHTML = finRangeBar(`
      ${can("finance.books_manage") ? `<button class="btn btn-primary btn-sm" id="finAddBtn">+ Record ${isIncome ? "income" : "a cost"}</button>` : ""}
      ${finToolbarActionsHtml()}`) +
      `<div id="finLedgerMount"><div class="center-load"><div class="spinner dark"></div></div></div>`;
    finWireRangeBar(panel);
    const add = $("#finAddBtn", panel);
    if (add) add.onclick = () => finAddEntry(kind);
    if (finUi.ledger.rows.length || finUi.ledger.totals) finDrawLedgerBody();
    else finLoadLedger(true);
  }

  let finLedgerSeq = 0;
  async function finLoadLedger(reset, redraw) {
    const L = finUi.ledger;
    if (reset) { L.rows = []; L.offset = 0; L.total = 0; }
    L.loading = true;
    L.error = null;
    if (redraw) finDrawLedgerBody();
    const seq = ++finLedgerSeq;
    const f = finUi.filters;
    const query = finRangeQuery({
      kind: L.kind, limit: 25, offset: L.offset,
      category: f.category, source: f.source, client_id: f.client_id, q: f.q,
    });
    let res;
    try { res = await api("/finance/books?" + query); }
    catch (ex) {
      if (seq !== finLedgerSeq) return;
      L.loading = false; L.error = ex;
      finDrawLedgerBody();
      return;
    }
    if (seq !== finLedgerSeq || state.view !== "finance") return;
    const page = res.ledger || {};
    L.rows = L.rows.concat(page.rows || []);
    L.offset = L.rows.length;
    L.total = page.total || 0;
    L.totals = res.totals || null;
    L.periodTotals = res.period_totals || null;
    L.note = res.truncated ? res.truncated_note : null;
    L.loading = false;
    finUi.settings = res.settings || finUi.settings;
    finUi.categories = res.categories || finUi.categories;
    finDrawLedgerBody();
  }

  function finDrawLedgerBody() {
    const mount = $("#finLedgerMount");
    if (!mount) return;
    const L = finUi.ledger;
    const f = finUi.filters;
    const isIncome = L.kind === "income";
    const filtered = !!(f.category || f.source || f.client_id || f.q);
    const cats = ((finUi.categories || {})[L.kind] || []);
    const sources = (finUi.categories || {}).sources || {};
    const totals = L.totals || {};
    const shown = isIncome ? totals.income_paise : totals.expense_paise;

    const focused = document.activeElement;
    const keepCaret = focused && focused.id === "finQ" ? focused.selectionStart : null;

    const rows = L.rows.map((r) => {
      const color = finCatColor(r.category);
      // A projected month of a monthly series isn't editable in place — its template
      // usually sits outside the period on screen — so those rows act on the SERIES.
      const isSeries = !r.editable && r.recurring && r.entry_id;
      const label = esc((r.description || r.category_label) + " · " + fmtDisplay(r.amount_paise, "INR"));
      const acts = (r.editable || isSeries)
        ? `<button class="btn btn-ghost btn-xs" data-finact="edit" data-finid="${r.entry_id}" data-finrow="${esc(r.id)}">${isSeries ? "Edit series" : "Edit"}</button>
           <button class="btn btn-ghost btn-xs danger" data-finact="delete" data-finid="${r.entry_id}"
             data-finseries="${isSeries || r.recurring ? "1" : ""}" data-finlabel="${label}">Delete</button>`
        : `<span class="fin-lock" title="${esc(r.locked_reason || "Recorded automatically.")}">🔒 auto</span>`;
      return `<tr style="cursor:default">
        <td style="white-space:nowrap">${fmtDate(r.occurred_on)}</td>
        <td>
          <b>${esc(r.description || r.category_label)}</b>
          <div class="fin-rowmeta">
            <span class="fin-chip" style="background:${color}14;color:${color}">${esc(r.category_label)}</span>
            ${r.recurring ? '<span class="fin-chip" style="background:#eef2ff;color:#4338ca">↻ monthly</span>' : ""}
            ${r.counterparty ? `<span class="fin-sub-inline">${esc(r.counterparty)}</span>` : ""}
            ${r.reference ? `<span class="fin-sub-inline">#${esc(r.reference)}</span>` : ""}
          </div>
        </td>
        <td class="hide-sm">${r.client_name
          ? (r.client_id ? `<span class="fin-link" data-finclient="${r.client_id}" role="button" tabindex="0">${esc(r.client_name)}</span>` : esc(r.client_name))
          : '<span class="fin-sub">—</span>'}</td>
        <td class="hide-sm fin-sub">${esc(r.method_label || r.source_label)}</td>
        <td style="text-align:right;white-space:nowrap"><b>${fmtDisplay(r.amount_paise, "INR")}</b>${
          r.tax_paise ? `<div class="fin-sub">incl. tax ${fmtDisplay(r.tax_paise, "INR")}</div>` : ""}</td>
        <td style="text-align:right;white-space:nowrap">${acts}</td>
      </tr>`;
    }).join("");

    const emptyRow = `<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:26px">
      ${L.loading ? "Loading…" : (filtered
        ? "No entries match these filters."
        : `Nothing recorded yet for this period. ${isIncome
            ? "Payments collected through Rilono appear here automatically — add anything you took in cash or as a university commission."
            : "Add salaries, rent, ads and agent commissions to see your true profit."}`)}
    </td></tr>`;

    mount.innerHTML = `
      ${L.note ? `<div class="fin-notice">⚠ ${esc(L.note)}</div>` : ""}
      <div class="fin-chips">
        <div class="fin-moneychip"><span>${isIncome ? "Money in" : "Money out"}${filtered ? " (filtered)" : ""}</span>
          <b class="${isIncome ? "ok" : ""}">${fmtDisplay(shown, "INR")}</b></div>
        <div class="fin-moneychip"><span>Entries</span><b>${L.total}</b></div>
        ${L.periodTotals ? `<div class="fin-moneychip"><span>Net for the period</span>
          <b class="${Number(L.periodTotals.net_paise) >= 0 ? "ok" : "warn"}">${esc(finNet(L.periodTotals.net_paise))}</b></div>` : ""}
      </div>
      <div class="card">
        <div class="card-body">
          <div class="fin-filters">
            <input id="finQ" class="fin-input" placeholder="Search description, payee, client…" value="${esc(f.q)}">
            <select id="finCat" class="fin-input">
              <option value="">All categories</option>
              ${cats.map((c) => `<option value="${esc(c.key)}" ${f.category === c.key ? "selected" : ""}>${esc(c.label)}</option>`).join("")}
            </select>
            <select id="finSrc" class="fin-input">
              <option value="">Recorded &amp; automatic</option>
              ${Object.entries(sources).map(([k, v]) => `<option value="${esc(k)}" ${f.source === k ? "selected" : ""}>${esc(v)}</option>`).join("")}
            </select>
            ${filtered ? `<button class="btn btn-ghost btn-sm" id="finClear">Clear</button>` : ""}
          </div>
        </div>
        <div class="card-body" style="padding:0;overflow-x:auto;border-top:1px solid var(--border)">
          <table class="client-table fin-table"><thead><tr>
            <th style="white-space:nowrap">Date</th><th>What</th>
            <th class="hide-sm">Client</th><th class="hide-sm">How</th>
            <th style="text-align:right">Amount</th><th style="text-align:right">&nbsp;</th>
          </tr></thead><tbody>${rows || emptyRow}</tbody></table>
        </div>
        ${L.error ? `<div class="card-body">${errBox(L.error)}</div>` : ""}
        ${L.rows.length < L.total ? `<div class="card-body" style="text-align:center;border-top:1px solid var(--border)">
          <button class="btn btn-ghost btn-sm" id="finMore" ${L.loading ? "disabled" : ""}>${
            L.loading ? "Loading…" : `Load 25 more (${L.total - L.rows.length} left)`}</button>
        </div>` : ""}
      </div>`;

    const q = $("#finQ", mount);
    if (q) {
      let timer = null;
      q.oninput = () => {
        clearTimeout(timer);
        timer = setTimeout(() => { finUi.filters.q = q.value.trim(); finLoadLedger(true, true); }, 350);
      };
      q.onkeydown = (e) => {
        if (e.key === "Enter") { e.preventDefault(); clearTimeout(timer); finUi.filters.q = q.value.trim(); finLoadLedger(true, true); }
      };
      if (keepCaret != null) { q.focus(); try { q.setSelectionRange(keepCaret, keepCaret); } catch (e) { /* ignore */ } }
    }
    const bind = (sel, key) => {
      const el = $(sel, mount);
      if (el) el.onchange = () => { finUi.filters[key] = el.value; finLoadLedger(true, true); };
    };
    bind("#finCat", "category");
    bind("#finSrc", "source");
    const clear = $("#finClear", mount);
    if (clear) clear.onclick = () => { finUi.filters = { category: "", source: "", client_id: "", q: "" }; finLoadLedger(true, true); };
    const more = $("#finMore", mount);
    if (more) more.onclick = () => finLoadLedger(false, true);
    $$("[data-finclient]", mount).forEach((el) => {
      const open = () => openClient(Number(el.dataset.finclient));
      el.onclick = open;
      el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } };
    });
    $$("[data-finact]", mount).forEach((btn) => btn.onclick = async () => {
      const id = Number(btn.dataset.finid);
      if (btn.dataset.finact === "edit") { finEditEntry(id); return; }
      if (btn.disabled) return;
      const series = !!btn.dataset.finseries;
      // Locked before the confirm: the row lives in the table, not the dialog, so it stays
      // clickable the moment confirmModal closes — long enough to stack a second dialog and
      // a second DELETE for the same ledger entry.
      btn.disabled = true;
      try {
        if (!(await confirmModal(
          series
            ? `This removes every month of the series, not just this one. ${btn.dataset.finlabel || ""}`.trim()
            : `Delete this entry? ${btn.dataset.finlabel || ""}`.trim(),
          { title: series ? "Delete the whole series?" : "Delete entry?", okText: "Delete" },
        ))) return;
        await api(`/finance/entries/${id}`, { method: "DELETE" });
        toast("Entry deleted.", "success");
        finAfterWrite();   // repaints the table, so this node is gone by now
      } catch (ex) { toast(ex.message || "Couldn't delete that entry.", "error"); }
      finally { if (btn.isConnected) btn.disabled = false; }
    });
  }

  /* ---------------- Tab 4 · Saved with Rilono ---------------- */
  function finDrawSavings() {
    const panel = $("#finPanel");
    if (!panel) return;
    panel.innerHTML = finRangeBar(finToolbarActionsHtml()) +
      `<div id="finSaveBody"><div class="center-load"><div class="spinner dark"></div></div></div>`;
    finWireRangeBar(panel);
    if (finUi.savings && finUi.savings._key === finRangeQuery()) finDrawSavingsBody();
    else finLoadSavings();
  }

  async function finLoadSavings() {
    const stamp = finRangeQuery();
    let res;
    try { res = await api("/finance/savings?" + stamp); }
    catch (ex) {
      if (state.view !== "finance" || finUi.tab !== "savings") return;
      const body = $("#finSaveBody");
      if (body) body.innerHTML = errBox(ex);
      return;
    }
    if (state.view !== "finance" || finUi.tab !== "savings" || finRangeQuery() !== stamp) return;
    res._key = stamp;
    finUi.savings = res;
    finUi.settings = res.settings || finUi.settings;
    finDrawSavingsBody();
  }

  function finDrawSavingsBody() {
    const body = $("#finSaveBody");
    if (!body) return;
    const s = finUi.savings || {};
    const t = s.totals || {};
    const cost = s.rilono_cost || {};
    const rangeLabel = (s.range || {}).label || "";
    const used = (s.activities || []).filter((a) => a.units > 0);

    if (!t.units) {
      body.innerHTML = `<div class="card"><div class="card-body" style="text-align:center;padding:44px 20px">
        <div style="font-size:34px">⚡</div>
        <h3 style="margin:10px 0 6px">No platform activity in ${esc(rangeLabel.toLowerCase())}</h3>
        <p class="fin-muted" style="margin:0 auto;max-width:520px;font-size:13.5px;line-height:1.65">
          Once your team runs Deep Scans, sends mock interviews, drafts statements, collects documents by
          link or lets clients self-serve their portal, this tab counts the hours that work would have
          taken by hand — priced at your own hourly cost.</p>
      </div></div>`;
      return;
    }

    const hero = `<div class="card fin-accent" style="margin-bottom:20px"><div class="card-body fin-hero">
      <div class="fin-hero-main">
        <div class="fin-eyebrow">Staff time Rilono took off your team · ${esc(rangeLabel)}</div>
        <div class="fin-hero-num">${esc(t.hours_display)} <span>hours</span></div>
        <div class="fin-sub">That's about <b>${t.workdays} working days</b> across ${t.units} pieces of work,
          worth <b>${fmtDisplay(t.value_paise, "INR")}</b> at your ${fmtDisplay(s.hourly_cost_paise, "INR")}/hour cost.</div>
      </div>
      <div class="fin-hero-side">
        <div class="fin-hero-stat"><span>You paid Rilono</span><b>${fmtDisplay(cost.total_paise, "INR")}</b></div>
        <div class="fin-hero-stat"><span>${s.is_net_positive ? "Net gain" : "Net cost"}</span>
          <b class="${s.is_net_positive ? "ok" : "warn"}">${esc(finNet(s.net_paise))}</b></div>
        <div class="fin-hero-stat"><span>Return on spend</span>
          <b>${s.roi_multiple == null ? "—" : s.roi_multiple + "×"}</b></div>
      </div>
    </div></div>`;

    const rows = used.map((a) => `
      <tr style="cursor:default">
        <td><b>${a.icon} ${esc(a.label)}</b>
          <div class="fin-sub">${esc(a.manual_equivalent)}</div></td>
        <td style="text-align:right">${a.units}</td>
        <td style="text-align:right;white-space:nowrap">${a.minutes_each} min${a.is_custom ? ' <span class="fin-sub-inline">yours</span>' : ""}</td>
        <td style="text-align:right"><b>${a.hours}h</b></td>
        <td style="text-align:right;white-space:nowrap"><b>${fmtDisplay(a.value_paise, "INR")}</b>
          <div class="fin-sub">${a.share_pct}% of the time</div></td>
      </tr>`).join("");

    const table = `<div class="card"><div class="card-head"><h3>Where the time went</h3>
        <span class="fin-head-note">${used.length} ${used.length === 1 ? "feature" : "features"} used · ${esc(rangeLabel)}</span></div>
      <div class="card-body" style="padding:0;overflow-x:auto">
        <table class="client-table fin-table"><thead><tr>
          <th>What Rilono did${infoTip("Each row counts real completed work in your account — stored Deep Scans, finished interviews, drafts, documents collected by secure link, portals your clients actually opened. Free actions count too.", "What Rilono did")}</th>
          <th style="text-align:right">Times</th>
          <th style="text-align:right">By hand</th>
          <th style="text-align:right">Saved</th>
          <th style="text-align:right">Worth</th>
        </tr></thead><tbody>${rows}</tbody></table>
      </div>
      <div class="card-body" style="border-top:1px solid var(--border);display:flex;gap:12px;align-items:center;flex-wrap:wrap">
        <span class="fin-sub" style="flex:1;min-width:260px">${esc(s.method_note || "")}</span>
        <button class="btn btn-ghost btn-sm" id="finTuneBtn">⚙ Change these assumptions</button>
      </div></div>`;

    const costCard = `<div class="card" style="margin-top:20px"><div class="card-head"><h3>What Rilono cost you</h3>
        <span class="fin-head-note">${esc(rangeLabel)} · from your own expense ledger</span></div>
      <div class="card-body">
        <div class="fin-facts">
          <div><span>AI credit top-ups</span><b>${fmtDisplay(cost.credits_paise, "INR")}</b></div>
          <div><span>Rilono plan</span><b>${fmtDisplay(cost.plan_paise != null ? cost.plan_paise : 0, "INR")}</b></div>
          ${cost.infra_paise ? `<div><span>Infrastructure fee <em style="font-weight:400;color:var(--muted)">(retired)</em></span><b>${fmtDisplay(cost.infra_paise, "INR")}</b></div>` : ""}
          <div><span>Collection fee on payments</span><b>${fmtDisplay(cost.platform_fee_paise, "INR")}</b></div>
          <div><span>Total</span><b>${fmtDisplay(cost.total_paise, "INR")}</b></div>
        </div>
        <div class="fin-sub" style="margin-top:12px">
          These are the same rows you'll find in <b>Costs</b> under the Rilono categories — the ROI above is
          your saved time minus exactly this.
        </div>
      </div></div>`;

    body.innerHTML = hero + table + costCard;
    const tune = $("#finTuneBtn", body);
    if (tune) tune.onclick = () => finOpenSettings("minutes");
  }

  /* ---------------- Tab 5 · Payout account (the original page) ---------------- */
  function finDrawAccount() {
    const panel = $("#finPanel");
    if (!panel) return;
    const d = finUi.summary || {};
    const la = d.linked_account;
    const fee = d.fee || {};
    const enabled = !!d.payments_enabled;
    const connected = !!(la && la.activation_status && la.activation_status !== "not_started");

    const intro = `<div class="card" style="margin-bottom:18px"><div class="card-body">
      <div style="font-weight:800;font-size:16px;margin-bottom:6px">Collect payments from your students</div>
      <div style="font-size:13.5px;color:var(--text-2);line-height:1.6">
        Connect your company bank account, then raise a payment request for any student and collect it online.
        Payments are processed securely by <b>Razorpay</b> and settled straight to <b>your</b> bank —
        Rilono connects you and keeps a small fee (<b>${esc(String(fee.percent))}%</b>, min ${esc(fmtInrExact(fee.min_fee_rupees))}) and
        <b>never holds your money</b>. See the <a href="/terms" target="_blank" rel="noopener">Terms</a> &mdash;
        &ldquo;Payment Collection for Consultancies&rdquo;.
      </div>
      <div style="font-size:12.5px;color:var(--muted);line-height:1.6;margin-top:10px">
        Student collection is <b>INR-only</b>: invoices are raised in INR and settle to your bank in INR.
        Students abroad can still pay an INR invoice with a foreign card — their own bank does the
        conversion and may add a fee.
      </div>
    </div></div>`;

    const notEnabledBanner = !enabled ? `<div class="card" style="margin-bottom:18px;border-left:4px solid var(--warning,#f59e0b)"><div class="card-body">
        <b>Online collection is being activated.</b> You can connect your bank details now; you'll be able to
        collect student payments as soon as it goes live.</div></div>` : "";

    if (connected) {
      const reqs = (la.requirements || []).filter(Boolean);
      const reqList = reqs.length
        ? `<ul style="margin:8px 0 0;padding-left:18px;font-size:13px;color:var(--text-2)">${reqs.map((r) => `<li>${esc(typeof r === "string" ? r : (r.reason_code || r.field_reference || JSON.stringify(r)))}</li>`).join("")}</ul>`
        : "";
      const ready = la.is_payable;
      const statusCard = `<div class="card" style="margin-bottom:18px"><div class="card-body">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap">
          <div>
            <div style="font-weight:800;font-size:15px;margin-bottom:2px">Payout account ${acctStatusChip(la.activation_status)}</div>
            <div style="font-size:13px;color:var(--text-2)">
              ${esc(la.legal_business_name || "Your business")}${la.bank_account_last4 ? ` · A/C ••••${esc(la.bank_account_last4)}` : ""}${la.bank_ifsc ? ` · ${esc(la.bank_ifsc)}` : ""}
            </div>
            ${reqList}
          </div>
          <button class="btn btn-ghost" onclick="__ent.refreshBank(this)">Refresh status</button>
        </div></div></div>`;
      const next = ready
        ? `<div class="card"><div class="card-body" style="color:var(--text-2)">
            <b style="color:var(--success,#10b981)">✓ You're connected and ready to receive payouts.</b>
            <br>Open any client's <b>Payments</b> tab to raise a payment request — collected money books itself
            into your <b>Income</b> ledger automatically.</div></div>`
        : `<div class="card"><div class="card-body" style="color:var(--text-2)">
            Razorpay is verifying your account. This usually takes a short while — use <b>Refresh status</b> to check.
            ${reqs.length ? " Please resolve the items above to continue." : ""}</div></div>`;
      panel.innerHTML = intro + statusCard + next;
      return;
    }

    // Route onboarding is India-only, and the form is the proof: it asks for a business
    // PAN, a GST number and an IFSC code, and the server strips every non-digit from the
    // account number before sending it on — which quietly destroys an IBAN. A non-Indian
    // org that filled this in would pass validation and then never be settlable, so the
    // form is replaced by an explanation rather than hidden or left as a trap. The intro
    // and "being activated" banner go with it: both promise a connection flow that will
    // never open for this org.
    if (!orgIsIndian()) {
      panel.innerHTML = acctCountryBlockedCard();
      const goSet = $("#acctGoSettings");
      if (goSet) goSet.onclick = (e) => { e.preventDefault(); navigate("settings"); };
      return;
    }
    panel.innerHTML = intro + notEnabledBanner + acctOnboardingForm(la);
    // The same set the handler checks after the click — the six starred fields plus the two
    // eligibility ticks. Delegated on the panel so the checkboxes' change events land too.
    // PAN and GST are deliberately out: the handler doesn't require them either.
    bindValidity($("#acctSaveBtn"), panel,
      () => allFilled([$("#acctLegalName"), $("#acctContactName"), $("#acctContactEmail"),
        $("#acctBankNum"), $("#acctIfsc"), $("#acctBeneficiary")])
        && $("#acctAttestService").checked && $("#acctAttestTurnover").checked,
      "Fill in the required (*) fields and confirm both eligibility checkboxes");
  }

  // The org's country from Settings. Unset counts as India: every org that predates the
  // country field is Indian, and blocking them would break a live payout flow.
  function orgIsIndian() {
    const cc = ((state.me && state.me.organization && state.me.organization.country_code) || "").trim().toUpperCase();
    return !cc || cc === "IN";
  }

  function acctCountryBlockedCard() {
    const cc = ((state.me && state.me.organization && state.me.organization.country_code) || "").trim().toUpperCase();
    return `<div class="card"><div class="card-body" style="max-width:860px">
      <div style="font-weight:800;font-size:16px;margin-bottom:6px">Student collection isn't available in your country yet</div>
      <div style="font-size:13.5px;color:var(--text-2);line-height:1.65">
        Collecting student payments runs on Razorpay Route, which onboards <b>India-registered businesses only</b> —
        it needs a business PAN, an IFSC code and an Indian bank account, and it settles in INR. Your organization is
        set to <b>${esc(cc || "a country outside India")}</b> in Settings, so we can't connect a payout account for you:
        you would be able to fill the form in, but Razorpay could never settle the money to you.
      </div>
      <div style="font-size:13px;color:var(--text-2);line-height:1.65;margin-top:12px">
        Everything else works normally. You can still <b>record payments you collect yourself</b> on each client's
        Payments tab, and they book into your Income ledger exactly like online collections do. Credit top-ups and
        credit top-ups are unaffected — those <b>are</b> charged in your own currency.
      </div>
      <div style="font-size:12.5px;color:var(--muted);line-height:1.6;margin-top:12px">
        If your business <i>is</i> registered in India, change the company country in
        <a href="#" id="acctGoSettings">Settings</a> and this form will appear.
      </div>
    </div></div>`;
  }

  /* ---------------- Recording an entry ---------------- */
  async function finEnsureClients() {
    if (finUi.clients) return finUi.clients;
    try {
      const d = await api("/clients?limit=500");
      finUi.clients = (d.clients || []).map((c) => ({ id: c.id, name: c.full_name }));
    } catch (ex) { finUi.clients = []; }
    return finUi.clients;
  }

  async function finOpenEntry(entry, kind) {
    const clients = await finEnsureClients();
    const cats = ((finUi.categories || {})[kind] || []).filter((c) => !c.auto);
    const methods = (finUi.categories || {}).payment_methods || [];
    const isIncome = kind === "income";
    const editing = !!entry;
    const today = new Date().toISOString().slice(0, 10);
    const v = entry || {};
    // Editing a monthly template changes every month it produced, so say so in the
    // title and label the date as what it really is: where the series starts.
    const isSeries = editing && !!v.repeat_monthly;

    openModal(`
      <div class="modal-head"><h3>${isSeries ? "Edit monthly series" : (editing ? "Edit entry" : (isIncome ? "Record income" : "Record a cost"))}</h3>
        <button class="x" onclick="__ent.closeModal()">×</button></div>
      <form id="finEntryForm"><div class="modal-body">
        ${isSeries ? `<div class="fin-notice">↻ This is a monthly series. Saving changes updates
          <b>every month</b> it has booked, not just one.</div>` : ""}
        <p class="fin-sub" style="margin:0 0 16px">${isIncome
          ? "For money Rilono can't already see — a fee taken in cash or by bank transfer outside the app, a university commission, coaching income. Payments collected through Rilono are already in your books."
          : "Salaries, rent, ads, agent commissions, software — everything that decides whether a case actually made money. Rilono's own fees are added for you."}</p>
        <div class="field-row">
          <div class="field"><label>Amount (₹) *</label>
            <input type="number" id="finAmt" min="1" step="0.01" inputmode="decimal"
              value="${v.amount_paise ? (Number(v.amount_paise) / 100) : ""}" placeholder="0.00"></div>
          <div class="field"><label>${isSeries ? "First month *" : "Date *"}</label>
            <input type="date" id="finDate" max="${today}" value="${esc(v.occurred_on || today)}">
            ${isSeries ? '<div class="hint">Every month from this date up to today is booked at this amount.</div>' : ""}</div>
        </div>
        <div class="field-row">
          <div class="field"><label>Category *</label>
            <select id="finCatSel">${cats.map((c) =>
              `<option value="${esc(c.key)}" ${v.category === c.key ? "selected" : ""}>${esc(c.label)}</option>`).join("")}</select></div>
          <div class="field"><label>${isIncome ? "Received by" : "Paid by"}</label>
            <select id="finMethod"><option value="">Not specified</option>${methods.map((m) =>
              `<option value="${esc(m.key)}" ${v.payment_method === m.key ? "selected" : ""}>${esc(m.label)}</option>`).join("")}</select></div>
        </div>
        <div class="field"><label>Description</label>
          <input type="text" id="finDesc" maxlength="300" value="${esc(v.description || "")}"
            placeholder="${isIncome ? "e.g. Second instalment — Rohan Sharma" : "e.g. Meta ads — August"}"></div>
        <div class="field-row">
          <div class="field"><label>${isIncome ? "Who paid you" : "Who you paid"}</label>
            <input type="text" id="finParty" maxlength="160" value="${esc(v.counterparty || "")}"
              placeholder="${isIncome ? "Student, university, partner…" : "Vendor or staff name"}"></div>
          <div class="field"><label>Client (optional)</label>
            <select id="finClientSel"><option value="">Not tied to a client</option>${clients.map((c) =>
              `<option value="${c.id}" ${Number(v.client_id) === c.id ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select></div>
        </div>
        <div class="field-row">
          <div class="field"><label>Reference</label>
            <input type="text" id="finRef" maxlength="120" value="${esc(v.reference || "")}" placeholder="Invoice / bill / UTR"></div>
          <div class="field"><label>Tax included (₹)</label>
            <input type="number" id="finTax" min="0" step="0.01" inputmode="decimal"
              value="${v.tax_paise ? (Number(v.tax_paise) / 100) : ""}" placeholder="GST portion, if any"></div>
        </div>
        <label class="fin-check"><input type="checkbox" id="finRepeat" ${v.repeat_monthly ? "checked" : ""}>
          <span><b>Repeats every month</b> — Rilono books it on the same date each month up to today
          (salary, rent, a subscription). Edit this entry to change every month at once.</span></label>
        <div class="field ${v.repeat_monthly ? "" : "hidden"}" id="finUntilWrap"><label>Stop repeating after (optional)</label>
          <input type="date" id="finUntil" value="${esc(v.repeat_until || "")}"></div>
        <div class="field"><label>Notes</label>
          <textarea id="finNotes" rows="2" maxlength="2000" placeholder="Anything you'd want to remember at audit time">${esc(v.notes || "")}</textarea></div>
        <div id="finEntryErr" class="auth-error hidden"></div>
      </div>
      <div class="modal-foot">
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary" id="finEntrySave">${editing ? "Save changes" : (isIncome ? "Record income" : "Record cost")}</button>
      </div></form>`, { wide: true });

    const repeat = $("#finRepeat");
    const untilWrap = $("#finUntilWrap");
    if (repeat && untilWrap) repeat.onchange = () => untilWrap.classList.toggle("hidden", !repeat.checked);

    $("#finEntryForm").onsubmit = async (e) => {
      e.preventDefault();
      const err = $("#finEntryErr");
      const fail = (msg) => { err.textContent = msg; err.classList.remove("hidden"); };
      err.classList.add("hidden");
      const rupees = parseFloat(($("#finAmt").value || "0"));
      if (!(rupees > 0)) return fail("Enter the amount.");
      const when = ($("#finDate").value || "").trim();
      if (!when) return fail("Pick the date this money moved.");
      const taxRupees = parseFloat(($("#finTax").value || "0")) || 0;
      if (taxRupees > rupees) return fail("The tax portion can't be more than the amount.");
      const body = {
        kind,
        category: $("#finCatSel").value,
        amount_paise: Math.round(rupees * 100),
        tax_paise: Math.round(taxRupees * 100),
        occurred_on: when,
        description: ($("#finDesc").value || "").trim(),
        counterparty: ($("#finParty").value || "").trim(),
        payment_method: $("#finMethod").value || null,
        reference: ($("#finRef").value || "").trim(),
        notes: ($("#finNotes").value || "").trim(),
        client_id: $("#finClientSel").value ? Number($("#finClientSel").value) : null,
        repeat_monthly: !!($("#finRepeat") || {}).checked,
        repeat_until: (($("#finUntil") || {}).value || "") || null,
      };
      const btn = $("#finEntrySave");
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span>';
      try {
        const res = entry
          ? await api(`/finance/entries/${entry.id}`, { method: "PATCH", body })
          : await api("/finance/entries", { method: "POST", body });
        toast(res.message || "Saved.", "success");
        closeModal();
        finAfterWrite();
      } catch (ex) {
        btn.disabled = false;
        btn.textContent = editing ? "Save changes" : (isIncome ? "Record income" : "Record cost");
        fail(ex.message || "Couldn't save that entry.");
      }
    };
  }

  // Entry rows come from the ledger cache, so an edit never needs a round trip.
  // A projected month of a series carries the template's own start date in
  // `series_start` — editing it must not move the series to the occurrence's date.
  function finEditEntry(entryId) {
    const row = (finUi.ledger.rows || []).find((r) => r.entry_id === entryId && (r.editable || r.recurring));
    if (!row) { toast("Reload the page and try that edit again.", "error"); return; }
    finOpenEntry({
      id: entryId,
      kind: row.kind,
      category: row.category,
      amount_paise: row.amount_paise,
      tax_paise: row.tax_paise,
      occurred_on: row.series_start || row.occurred_on,
      description: row.description,
      counterparty: row.counterparty,
      payment_method: row.method,
      reference: row.reference,
      notes: row.notes || "",
      client_id: row.client_id,
      repeat_monthly: row.recurring,
      repeat_until: row.repeat_until || "",
    }, row.kind);
  }

  async function finAddEntry(kind) {
    // Categories arrive with the ledger payload; fetch them if the user starts here.
    if (!finUi.categories) {
      try {
        const res = await api("/finance/books?" + finRangeQuery({ kind, limit: 1 }));
        finUi.categories = res.categories || null;
        finUi.settings = res.settings || finUi.settings;
      } catch (ex) { toast(ex.message || "Couldn't open the form.", "error"); return; }
    }
    finOpenEntry(null, kind);
  }

  /* ---------------- Assumptions (hourly cost, cash, FY, baselines) ---------------- */
  const FIN_MONTHS = ["January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"];

  async function finOpenSettings(focus) {
    let s = finUi.settings;
    if (!s) {
      try {
        const res = await api("/finance/books?" + finRangeQuery({ limit: 1 }));
        s = finUi.settings = res.settings;
        finUi.categories = res.categories || finUi.categories;
      } catch (ex) { toast(ex.message || "Couldn't load your settings.", "error"); return; }
    }
    const minutes = s.savings_minutes || {};
    const defaults = s.savings_defaults || {};
    const acts = (finUi.savings || {}).activities || [];
    // Fall back to the server's own key list when the savings tab hasn't loaded yet.
    const keys = acts.length ? acts.map((a) => ({ key: a.key, label: a.label, unit: a.unit }))
      : Object.keys(minutes).map((k) => ({ key: k, label: k.replace(/_/g, " "), unit: "" }));

    openModal(`
      <div class="modal-head"><h3>Finance assumptions</h3><button class="x" onclick="__ent.closeModal()">×</button></div>
      <form id="finSetForm"><div class="modal-body">
        <div class="fin-eyebrow">Your numbers</div>
        <p class="fin-sub" style="margin:4px 0 14px">These drive the cash position and turn saved time into
          money. They're yours — nothing here is a Rilono estimate.</p>
        <div class="field-row">
          <div class="field"><label>Blended staff cost per hour (₹)</label>
            <input type="number" id="finHourly" min="0" step="1" inputmode="decimal"
              value="${Number(s.hourly_cost_paise || 0) / 100}">
            <div class="hint">Salary + overheads ÷ hours worked. Default ₹${Number(s.hourly_cost_default_paise || 40000) / 100}.</div></div>
          <div class="field"><label>Financial year starts</label>
            <select id="finFy">${FIN_MONTHS.map((m, i) =>
              `<option value="${i + 1}" ${Number(s.fy_start_month) === i + 1 ? "selected" : ""}>${m}</option>`).join("")}</select>
            <div class="hint">Drives “This quarter” and “This FY”.</div></div>
        </div>
        <div class="field-row">
          <div class="field"><label>Opening bank balance (₹)</label>
            <input type="number" id="finOpen" min="0" step="0.01" inputmode="decimal"
              value="${Number(s.opening_balance_paise || 0) / 100}"></div>
          <div class="field"><label>As of</label>
            <input type="date" id="finOpenOn" value="${esc(s.opening_balance_on || "")}">
            <div class="hint">Cash position = this balance plus your books since that date.</div></div>
        </div>
        <div class="fin-eyebrow" style="margin-top:20px">How long these take you by hand</div>
        <p class="fin-sub" style="margin:4px 0 12px">Minutes per task without Rilono. Lower them if your team
          is faster — the savings figure follows your numbers, not ours.</p>
        <div class="fin-minutes">
          ${keys.map((a) => `<label class="fin-minute">
            <span>${esc(a.label)}${a.unit ? ` <em>per ${esc(a.unit)}</em>` : ""}</span>
            <input type="number" min="0" max="600" step="1" data-finmin="${esc(a.key)}"
              value="${Number(minutes[a.key] != null ? minutes[a.key] : (defaults[a.key] || 0))}">
          </label>`).join("")}
        </div>
        <div id="finSetErr" class="auth-error hidden"></div>
      </div>
      <div class="modal-foot">
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary" id="finSetSave">Save assumptions</button>
      </div></form>`, { wide: true });

    if (focus === "minutes") {
      const first = $("[data-finmin]");
      if (first) first.scrollIntoView({ block: "center" });
    }

    $("#finSetForm").onsubmit = async (e) => {
      e.preventDefault();
      const err = $("#finSetErr");
      err.classList.add("hidden");
      const savings = {};
      $$("[data-finmin]").forEach((el) => { savings[el.dataset.finmin] = Math.max(0, Math.round(Number(el.value) || 0)); });
      const openOn = ($("#finOpenOn").value || "").trim();
      const body = {
        hourly_cost_paise: Math.round((parseFloat($("#finHourly").value || "0") || 0) * 100),
        opening_balance_paise: Math.round((parseFloat($("#finOpen").value || "0") || 0) * 100),
        opening_balance_on: openOn || null,
        fy_start_month: Number($("#finFy").value) || 4,
        savings_minutes: savings,
      };
      const btn = $("#finSetSave");
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span>';
      try {
        const res = await api("/finance/settings", { method: "PUT", body });
        finUi.settings = res.settings || finUi.settings;
        toast(res.message || "Saved.", "success");
        closeModal();
        finInvalidateRange();
        finDraw();
      } catch (ex) {
        btn.disabled = false;
        btn.textContent = "Save assumptions";
        err.textContent = ex.message || "Couldn't save those settings.";
        err.classList.remove("hidden");
      }
    };
  }

  async function finExport(btn) {
    const label = btn ? btn.textContent : "";
    if (btn) { btn.disabled = true; btn.textContent = "Preparing…"; }
    try {
      await downloadFile(`${API}/finance/export?` + finRangeQuery({ fmt: "xlsx" }), 120000);
      toast("Your finance book is downloading.", "success");
    } catch (ex) {
      toast(ex.message || "Couldn't build that export.", "error");
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = label; }
    }
  }

  function finGoTab(tab) {
    finUi.tab = tab;
    finDraw();
    const c = $("#content");
    if (c) c.scrollIntoView({ block: "start" });
  }

  async function saveLinkedAccount() {
    // Belt and braces: the form isn't rendered outside India, but a stale tab could still
    // hold one. Submitting it would create a linked account that can never be settled.
    if (!orgIsIndian()) {
      toast("Payout accounts can only be connected for India-registered businesses.", "error");
      return;
    }
    const val = (id) => (($("#" + id) || {}).value || "").trim();
    const chk = (id) => !!(($("#" + id) || {}).checked);
    const body = {
      legal_business_name: val("acctLegalName"),
      business_type: (($("#acctBizType") || {}).value || ""),
      contact_name: val("acctContactName"),
      contact_email: val("acctContactEmail"),
      contact_phone: val("acctContactPhone"),
      business_pan: val("acctPan"),
      gst_number: val("acctGst"),
      bank_account_number: val("acctBankNum"),
      bank_ifsc: val("acctIfsc"),
      beneficiary_name: val("acctBeneficiary"),
      attested_service_delivery: chk("acctAttestService"),
      attested_turnover_ok: chk("acctAttestTurnover"),
    };
    if (!body.legal_business_name || !body.contact_name || !body.contact_email || !body.bank_account_number || !body.bank_ifsc || !body.beneficiary_name) {
      toast("Please fill in the required (*) fields.", "error"); return;
    }
    if (!body.attested_service_delivery || !body.attested_turnover_ok) {
      toast("Please confirm the two eligibility checkboxes.", "error"); return;
    }
    await withBusy($("#acctSaveBtn"), "Connecting…", async () => {
      try {
        const r = await api("/finance/linked-account", { method: "POST", body });
        toast(r.message || "Bank account saved.", "success");
        renderFinance();
      } catch (ex) {
        toast((ex && ex.message) || "Could not connect the bank account.", "error");
      }
    });
  }

  async function refreshLinkedAccount(btn) {
    return withBusy(btn, "Refreshing…", async () => {
      try {
        await api("/finance/linked-account/refresh", { method: "POST" });
        toast("Status refreshed.", "success");
        renderFinance();
      } catch (ex) {
        toast((ex && ex.message) || "Could not refresh status.", "error");
      }
    });
  }

  function renderCheckout() {
    const pkg = checkoutCtx.pkg;
    const c = checkoutCtx.coupon;
    const b = checkoutBreakdown();
    const opts = pkgOptions(pkg);
    const opt = checkoutOption();
    const totalCell = b.free ? `<span class="co-free">FREE</span>` : `<b>${esc(fmtMoney(b.total, b.currency))}</b>`;
    const proceedLabel = b.free ? `Get ${pkg.total_credits} credits — free` : `Pay ${esc(fmtMoney(b.total, b.currency))} securely`;
    // Every option is a price the owner set for that currency, not an FX conversion of
    // the INR one — so the label shows the server's own `display` string verbatim.
    const currencyBlock = opts.length > 1
      ? `<div class="field" style="margin:0">
           <label for="coCurrency">Billing currency</label>
           <select id="coCurrency">${opts.map((o) =>
             `<option value="${esc(o.currency)}"${o.currency === b.currency ? " selected" : ""}>${esc(o.currency)} · ${esc(o.display)}</option>`).join("")}</select>
         </div>`
      : "";
    const couponBlock = c
      ? `<div class="co-coupon applied">
           <div class="co-coupon-info"><span class="co-coupon-tag">🎟 ${esc(c.code)}</span><span class="co-coupon-msg">${esc(c.percent_display)} off applied</span></div>
           <button type="button" class="btn btn-ghost btn-sm" id="coRemove">Remove</button>
         </div>`
      : `<div class="co-coupon">
           <input id="coCouponInput" class="coupon-input" placeholder="Have a discount code?" maxlength="40"/>
           <button type="button" class="btn btn-soft btn-sm" id="coApply">Apply</button>
         </div>`;

    openModal(`
      <div class="modal-head"><h3>Checkout</h3><button class="x" onclick="__ent.closeModal()">×</button></div>
      <div class="modal-body co-modal">
        <div class="co-item">
          <div class="co-item-ic">⚡</div>
          <div class="co-item-main">
            <div class="co-item-title">${esc(pkg.label)}</div>
            <div class="co-item-sub">${pkg.total_credits} credits${pkg.bonus_credits ? ` <span class="co-bonus">incl. +${pkg.bonus_credits} bonus</span>` : ""} · worth ${fmtInr(pkg.value_inr)} of AI actions</div>
          </div>
          <div class="co-item-price">${esc(opt.display || fmtMoney(opt.amount_minor, opt.currency))}</div>
        </div>
        ${currencyBlock}
        ${couponBlock}
        <div id="coCouponErr" class="co-coupon-err hidden"></div>
        <div class="co-summary">
          <div class="co-line"><span>Subtotal</span><span>${esc(fmtMoney(b.base, b.currency))}</span></div>
          ${b.discount > 0 ? `<div class="co-line co-discount"><span>Discount · ${esc(c.code)} (${esc(c.percent_display)} off)</span><span>−${esc(fmtMoney(b.discount, b.currency))}</span></div>` : ""}
          <div class="co-line co-total"><span>Total payable</span><span>${totalCell}</span></div>
        </div>
        <div class="co-note">${b.free
          ? "✓ This order is fully covered by your discount — no payment needed."
          : "🔒 Secure payment via Razorpay · UPI, cards &amp; NetBanking"} · Top-up credits never expire.</div>
        ${b.free ? "" : chargeNote(b.total, b.currency)}
      </div>
      <div class="modal-foot">
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="button" class="btn btn-primary" id="coProceed">${proceedLabel}</button>
      </div>`);

    const ap = $("#coApply"); if (ap) ap.onclick = coApplyCheckoutCoupon;
    const rm = $("#coRemove"); if (rm) rm.onclick = coRemoveCheckoutCoupon;
    const ci = $("#coCouponInput"); if (ci) ci.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); coApplyCheckoutCoupon(); } };
    const cs = $("#coCurrency");
    if (cs) cs.onchange = () => { checkoutCtx.currency = cs.value; renderCheckout(); };
    $("#coProceed").onclick = creditCheckoutProceed;
  }

  async function coApplyCheckoutCoupon() {
    // Reached from the Apply click AND from Enter on the input, so the lock is checked
    // before anything else — otherwise the keyboard path walks straight past a button that
    // the click path had already disabled.
    const btn = $("#coApply"); if (btn && btn.disabled) return;
    const input = $("#coCouponInput");
    const code = ((input && input.value) || "").trim();
    if (!code) { toast("Enter a discount code.", "error"); return; }
    if (btn) { btn.disabled = true; btn.textContent = "…"; }
    let res;
    try {
      res = await api("/coupons/validate", { method: "POST", body: { code, context: "credits", package: checkoutCtx.pkg.key } });
    } catch (ex) {
      const er = $("#coCouponErr"); if (er) { er.textContent = ex.message || "Invalid discount code."; er.classList.remove("hidden"); }
      if (btn) { btn.disabled = false; btn.textContent = "Apply"; }
      return;
    }
    checkoutCtx.coupon = { code: res.code, percent: res.percent_off, percent_display: res.percent_display, free: !!res.free };
    state.creditCoupon = checkoutCtx.coupon;   // keep the credits page in sync
    renderCheckout();
  }

  function coRemoveCheckoutCoupon() {
    checkoutCtx.coupon = null;
    state.creditCoupon = null;
    renderCheckout();
  }

  async function creditCheckoutProceed() {
    const pkg = checkoutCtx.pkg;
    const couponCode = checkoutCtx.coupon ? checkoutCtx.coupon.code : undefined;
    const btn = $("#coProceed"); if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>'; }
    let res;
    // `currency` is only a HINT — the server re-reads the price book and is the sole
    // authority on the amount. We never send an amount.
    //
    // Send the currency of the price the buyer was actually SHOWN, not checkoutCtx's raw
    // value: checkoutOption() falls back to the first quoted option when ctx holds a
    // currency the package has no price for, so the two can disagree — and then the modal
    // would show ₹999 while the order was created in USD.
    const currency = checkoutBreakdown().currency;
    try { res = await api("/credits/topup/checkout", { method: "POST", body: { package: pkg.key, coupon_code: couponCode, currency } }); }
    catch (ex) { toast(ex.message, "error"); renderCheckout(); return; }

    if (res.action === "contact_sales") { toast(res.message || "Please contact us.", "error"); renderCheckout(); return; }
    if (res.action === "granted") {
      if (res.wallet) { state.credits = res.wallet; updatePlanChip(); }
      state.creditCoupon = null;
      closeModal();
      toast(res.message || "Credits added!", "success");
      renderCredits();
      return;
    }
    if (res.action !== "checkout") { toast("Top-up unavailable.", "error"); renderCheckout(); return; }
    if (typeof Razorpay === "undefined") { toast("Payment library failed to load. Please refresh.", "error"); renderCheckout(); return; }

    closeModal();   // hand off to Razorpay's own secure overlay
    const rzp = new Razorpay({
      key: res.razorpay_key_id,
      amount: res.amount,
      currency: res.currency,
      name: res.organization_name || "Rilono",
      description: res.package_label + " · " + res.total_credits + " credits",
      order_id: res.order_id,
      // Pass the server's prefill through untouched. Razorpay's docs are explicit that an
      // international payment FAILS on a dummy email/phone, so the server omits fields it
      // doesn't have rather than inventing them — do not fill in placeholders here.
      // https://razorpay.com/docs/payments/international-payments/?preferred-country=IN
      prefill: checkoutPrefill(res.prefill),
      theme: { color: "#6366f1" },
      handler: async function (resp) {
        try {
          const v = await api("/credits/topup/verify", { method: "POST", body: {
            razorpay_order_id: resp.razorpay_order_id,
            razorpay_payment_id: resp.razorpay_payment_id,
            razorpay_signature: resp.razorpay_signature,
          }});
          state.credits = v.wallet; state.creditCoupon = null; updatePlanChip();
          toast(v.message || "Credits added!", "success");
          renderCredits();
        } catch (ex) { toast("Payment verification failed: " + ex.message, "error"); }
      },
    });
    rzp.on("payment.failed", () => toast("Payment was not completed.", "error"));
    rzp.open();
  }

  // Currency picker for a charge that has no order-review screen of its own. Resolves to
  // the chosen ISO code, or null if dismissed. Every price shown is the server's own
  // `display` string for that currency — nothing is converted here.
  //
  // `cfg.selected` MUST be the currency the caller already quoted on screen. The options
  // arrive in price-book order (INR first), so without it the picker opens on ₹999 for an
  // org whose banner reads "$12.99/mo" — one click and they are charged in the wrong
  // currency, at a price they were never shown.
  function pickChargeCurrency(opts, cfg) {
    cfg = cfg || {};
    var selected = curCode(cfg.selected || (opts[0] || {}).currency);
    return new Promise(function (resolve) {
      var settled = false;
      function finish(val) {
        if (settled) return; settled = true;
        document.removeEventListener("keydown", onKey, true);
        $("#overlay").removeEventListener("click", onOverlay);
        closeModal();
        resolve(val);
      }
      function onKey(e) { if (e.key === "Escape") { e.stopPropagation(); finish(null); } }
      function onOverlay(e) { if (e.target === $("#overlay")) finish(null); }
      openModal(
        '<div class="modal-head"><h3>' + esc(cfg.title || "Choose a billing currency") + '</h3>' +
        '<button class="x" id="curClose" aria-label="Close">×</button></div>' +
        '<div class="modal-body">' +
        (cfg.intro ? '<p style="margin:0 0 14px;color:var(--text-2);font-size:14px;line-height:1.6">' + esc(cfg.intro) + '</p>' : "") +
        '<div class="field" style="margin:0"><label for="curPick">Billing currency</label>' +
        '<select id="curPick">' + opts.map(function (o) {
          return '<option value="' + esc(o.currency) + '"' +
            (curCode(o.currency) === selected ? ' selected' : '') + '>' + esc(o.currency) + ' · ' +
            esc(o.display || fmtMoney(o.amount_minor, o.currency)) + '</option>';
        }).join("") + '</select></div>' +
        '<div id="curNote"></div>' +
        '</div>' +
        '<div class="modal-foot"><button type="button" class="btn btn-ghost" id="curCancel">Cancel</button>' +
        '<button type="button" class="btn btn-primary" id="curOk">Continue to payment</button></div>'
      );
      var sel = $("#curPick");
      function paintNote() {
        var picked = opts.filter(function (o) { return o.currency === sel.value; })[0] || opts[0];
        $("#curNote").innerHTML = chargeNote(picked.amount_minor, picked.currency);
      }
      sel.onchange = paintNote;
      paintNote();
      $("#curClose").onclick = function () { finish(null); };
      $("#curCancel").onclick = function () { finish(null); };
      $("#curOk").onclick = function () { finish(sel.value); };
      document.addEventListener("keydown", onKey, true);
      $("#overlay").addEventListener("click", onOverlay);
      sel.focus();
    });
  }


  /* ============================================================
     SETTINGS
     ============================================================ */
  // Inline 24×24 outline icons, matching the sidebar/topbar set. Held as consts because
  // the async handlers below restore button contents on finish — they must put back
  // exactly what was rendered, not a text-only label.
  const ICON_UPLOAD = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="15" height="15"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>';
  const ICON_SHUFFLE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="15" height="15"><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/><circle cx="12" cy="12" r="3"/></svg>';
  const ICON_CAMERA = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>';
  const ICON_GLOBE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>';
  const ICON_COPY = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  const ICON_INFO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';
  // One source of truth for the two logo buttons — the template and the `finally`
  // blocks that restore them after a spinner must agree exactly.
  const BTN_UPLOAD_HTML = ICON_UPLOAD + "Upload logo";
  const BTN_REGEN_HTML = ICON_SHUFFLE + "Generate new";

  function renderSettings() {
    const c = $("#content");
    const org = state.me.organization || {};
    const canManage = can("settings.manage");
    // Company location — for records; the country also drives the portal display currency.
    const ORG_COUNTRIES = [
      ["", "— Select country —"],
      ["IN", "🇮🇳 India (INR ₹)"], ["US", "🇺🇸 United States (USD $)"], ["GB", "🇬🇧 United Kingdom (GBP £)"],
      ["CA", "🇨🇦 Canada (CAD)"], ["AU", "🇦🇺 Australia (AUD)"], ["AE", "🇦🇪 United Arab Emirates (AED)"],
      ["SG", "🇸🇬 Singapore (SGD)"], ["JP", "🇯🇵 Japan (JPY ¥)"],
      ["DE", "🇩🇪 Germany (EUR €)"], ["FR", "🇫🇷 France (EUR €)"], ["IE", "🇮🇪 Ireland (EUR €)"],
      ["NL", "🇳🇱 Netherlands (EUR €)"], ["IT", "🇮🇹 Italy (EUR €)"], ["ES", "🇪🇸 Spain (EUR €)"],
      ["NP", "🇳🇵 Nepal (shows USD)"], ["BD", "🇧🇩 Bangladesh (shows USD)"], ["LK", "🇱🇰 Sri Lanka (shows USD)"],
      ["PK", "🇵🇰 Pakistan (shows USD)"], ["NG", "🇳🇬 Nigeria (shows USD)"], ["XX", "🌐 Other (shows USD)"],
    ];
    const orgCC = (org.country_code || "").toUpperCase();
    const countryOpts = ORG_COUNTRIES.map(([v, l]) => `<option value="${v}" ${v === orgCC ? "selected" : ""}>${l}</option>`)
      .join("") + (orgCC && !ORG_COUNTRIES.some(([v]) => v === orgCC) ? `<option value="${esc(orgCC)}" selected>${esc(orgCC)}</option>` : "");
    const countryLabel = (ORG_COUNTRIES.find(([v]) => v === orgCC) || [])[1] || orgCC || "—";
    const dc = org.display_currency || { code: "INR", symbol: "₹", rate_from_inr: 1 };
    const curDesc = dc.code === "INR"
      ? "INR (₹)"
      : `${dc.code} · ₹1 ≈ ${dc.symbol}${Number(dc.rate_from_inr || 0).toFixed(4)} (live rate, refreshed daily)`;
    // A worked example beats quoting the raw rate — it shows what the conversion
    // actually does to a number the consultancy recognises.
    //
    // This setting is PRESENTATION ONLY and the copy has to say so, because the two real
    // currencies now differ from it and from each other: what Rilono bills you (chosen at
    // checkout, from a per-currency price list) and what you collect from students
    // (INR — Razorpay Route settles in nothing else). Claiming "payments are charged in
    // INR" here stopped being true the moment we started creating non-INR orders.
    const curNote = dc.code === "INR"
      ? "Amounts across this portal display in <b>INR (₹)</b>."
      : `Amounts display in <b>${esc(dc.code)}</b> — a ₹10,000 fee shows as ` +
        `<b>${esc(dc.symbol || "")}${(10000 * Number(dc.rate_from_inr || 0)).toLocaleString(undefined, { maximumFractionDigits: 0 })}</b> ` +
        "at today's rate, refreshed daily. This is display only: credit top-ups are " +
        "charged in the currency you pick at checkout, and student payments you collect are always in INR.";
    const portalHost = (org.subdomain_slug || "") + "." + rootDomain();
    const membership = state.me.membership || {};
    const role = membership.role || "";
    const bal = state.credits && state.credits.balance_credits != null ? state.credits.balance_credits : null;
    // Settings names the TIER the org is on. It used to say "Pay-as-you-go", which stopped
    // being true when plans replaced the credits-only model.
    const subx = state.subscription || {};
    const planLabel = subx.plan_label || null;
    const planPrice = subx.is_sandbox ? null : (subx.monthly_display || null);
    const planTax = subx.tax_label || null;
    const planIncl = Number(subx.included_credits || 0) || null;
    const planRecur = !!subx.credits_recur;
    c.innerHTML = `
      <div class="settings-page">
        <div class="set-hero">
          ${canManage
            ? `<button type="button" class="set-logo" id="heroLogoBtn" title="Replace logo" aria-label="Replace organization logo">
                 <img id="settingsLogo" src="${esc(org.logo_url || "")}" alt="" onerror="this.style.visibility='hidden'"/>
                 <span class="set-logo-ov">${ICON_CAMERA}Replace</span>
               </button>`
            : `<div class="set-logo"><img id="settingsLogo" src="${esc(org.logo_url || "")}" alt="" onerror="this.style.visibility='hidden'"/></div>`}
          <div class="set-hero-main">
            <h2 id="setHeroName">${esc(org.company_name || "Your organization")}</h2>
            <button type="button" class="set-url" id="copyPortalUrl" title="Copy portal URL">${ICON_GLOBE}<span>${esc(portalHost)}</span>${ICON_COPY}</button>
            <div class="set-facts">
              <span class="set-fact"><span class="sd"></span>${esc(role ? role.charAt(0).toUpperCase() + role.slice(1) : "Member")}</span>
              <span class="set-fact">${planLabel ? esc(planLabel) : "Rilono Credits"}${bal != null ? ` · <b>${bal}</b> cr` : ""}</span>
              <span class="set-fact">Showing amounts in <b>${esc(dc.code || "INR")}</b></span>
            </div>
          </div>
          ${canManage ? `
          <div class="set-hero-actions">
            <button class="btn btn-ghost btn-sm" id="uploadLogoBtn">${BTN_UPLOAD_HTML}</button>
            <button class="btn btn-ghost btn-sm" id="regenLogo" title="Draws a study-abroad emblem — mortarboard, globe, campus — until you upload your own logo">${BTN_REGEN_HTML}</button>
            <span class="set-hint">PNG, JPG or WebP · up to 2 MB</span>
            <input type="file" id="logoFile" accept="image/png,image/jpeg,image/webp" style="display:none"/>
          </div>` : ""}
        </div>

        <section class="set-sec">
          <div class="set-sec-desc">
            <h3>Organization branding</h3>
            <p>The name and logo on this portal, on your students' portal and on every email you send them.</p>
          </div>
          <div class="card"><div class="card-body">
            ${canManage ? `
            <div class="field"><label for="setCompany">Company name</label><input id="setCompany" value="${esc(org.company_name || "")}" maxlength="120"/></div>
            <div class="set-actions">
              <button class="btn btn-primary btn-sm" id="saveBranding">Save name</button>
            </div>` : `
            <div class="set-rows">
              <div class="set-row"><span class="set-row-k">Company name</span><span class="set-row-v">${esc(org.company_name || "—")}</span></div>
            </div>
            <div class="set-note">${ICON_INFO}<span>Only organization admins can change the company name or logo.</span></div>`}
          </div></div>
        </section>

        <section class="set-sec">
          <div class="set-sec-desc">
            <h3>Company location</h3>
            <p>Kept on your organization's record. The country also picks the currency amounts are displayed in.</p>
          </div>
          <div class="card"><div class="card-body">
            ${canManage ? `
            <div class="field-row">
              <div class="field"><label for="setCountry">Country</label><select id="setCountry">${countryOpts}</select></div>
              <div class="field"><label for="setState">State / Region</label><input id="setState" value="${esc(org.state_region || "")}" placeholder="e.g. Karnataka, California" maxlength="80"/></div>
            </div>
            <div class="set-actions">
              <button class="btn btn-primary btn-sm" id="saveLocation">Save location</button>
            </div>` : `
            <div class="set-rows">
              <div class="set-row"><span class="set-row-k">Country</span><span class="set-row-v">${esc(countryLabel)}</span></div>
              <div class="set-row"><span class="set-row-k">State / Region</span><span class="set-row-v">${esc(org.state_region || "—")}</span></div>
            </div>`}
            <div class="set-note">${ICON_INFO}<span>${curNote}</span></div>
          </div></div>
        </section>

        <section class="set-sec">
          <div class="set-sec-desc">
            <h3>Workspace</h3>
            <p>Where this portal lives and how it's billed.</p>
          </div>
          <div class="card"><div class="card-body">
            <div class="set-rows">
              <div class="set-row"><span class="set-row-k">Portal URL</span><span class="set-row-v">${esc(portalHost)}</span></div>
              <div class="set-row"><span class="set-row-k">Plan</span><span class="set-row-v">${esc(planLabel || "—")}${planPrice ? ` · ${esc(planPrice)}/mo${planTax ? " + " + esc(planTax) : ""}` : ""} &nbsp;<button type="button" class="link" id="setGoBilling">Manage plan</button></span></div>
              <div class="set-row"><span class="set-row-k">AI credits</span><span class="set-row-v">${bal != null ? `${bal} left` : "—"}${planIncl ? ` · ${planIncl.toLocaleString()} included${planRecur ? "/mo" : ""}` : ""} &nbsp;<button type="button" class="link" id="setGoCredits">Manage credits</button></span></div>
              <div class="set-row"><span class="set-row-k">Display currency</span><span class="set-row-v">${esc(curDesc)}</span></div>
              ${org.created_at ? `<div class="set-row"><span class="set-row-k">Workspace created</span><span class="set-row-v">${esc(fmtDate(org.created_at))}</span></div>` : ""}
            </div>
          </div></div>
        </section>

        <section class="set-sec set-sec-danger">
          <div class="set-sec-desc">
            <h3>Your account</h3>
            <p>The account you're signed in with on this device.</p>
          </div>
          <div class="card"><div class="card-body">
            <div>
              <div style="font-weight:700;font-size:14.5px">${esc(state.me.user.email)}</div>
              <div class="set-hint" style="margin-top:2px">Signed in as ${esc(role || "member")}${membership.joined_at ? ` · joined ${esc(fmtDate(membership.joined_at))}` : ""}</div>
            </div>
            <button class="btn btn-danger btn-sm" id="setSignout">Sign out</button>
          </div></div>
        </section>
      </div>`;

    $("#setSignout").onclick = () => { const b = $("#signoutBtn"); if (b) b.click(); };
    $("#setGoCredits").onclick = () => navigate("credits");
    const goBilling = $("#setGoBilling");
    if (goBilling) goBilling.onclick = () => navigate("billing");
    $("#copyPortalUrl").onclick = async () => {
      const url = org.portal_url || ("https://" + portalHost);
      // navigator.clipboard is undefined on insecure origins (local http portals),
      // so fall back to the old selection trick rather than failing outright.
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) await navigator.clipboard.writeText(url);
        else {
          const ta = document.createElement("textarea");
          ta.value = url; ta.style.position = "fixed"; ta.style.opacity = "0";
          document.body.appendChild(ta); ta.select();
          const ok = document.execCommand("copy");
          document.body.removeChild(ta);
          if (!ok) throw new Error("copy blocked");
        }
        toast("Portal URL copied", "success");
      } catch (ex) { toast("Couldn't copy — your portal URL is " + url, "error"); }
    };

    if (canManage) {
      $("#saveBranding").onclick = async () => {
        const name = $("#setCompany").value.trim(); if (name.length < 2) { toast("Enter a company name", "error"); return; }
        const btn = $("#saveBranding"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
        try { const r = await api("/organization/branding", { method: "PATCH", body: { company_name: name } });
          state.me.organization = Object.assign(state.me.organization, r.organization || {});
          $("#brandName").textContent = name;
          $("#setHeroName").textContent = name;   // the hero title is the live preview of this field
          toast("Saved", "success"); }
        catch (ex) { toast(ex.message, "error"); }
        finally { btn.disabled = false; btn.textContent = "Save name"; }
      };
      /* Three controls — Regenerate, Upload logo, and the hero tile — write the SAME logo,
         so each one guarding only itself is not enough: "Regenerate" while an upload is
         in flight is a genuine race whose winner decides the org's logo. One flag gates all
         three, and each writer disables the other two for its duration. */
      let logoBusy = false;
      const logoLock = (on) => {
        logoBusy = on;
        [$("#regenLogo"), $("#uploadLogoBtn"), $("#heroLogoBtn")].forEach((b) => { if (b) b.disabled = on; });
        const tile = $("#heroLogoBtn"); if (tile) tile.classList.toggle("busy", on);
      };
      $("#regenLogo").onclick = async () => {
        if (logoBusy) return;
        // .spinner is white-on-transparent — on a white .btn-ghost it needs the dark variant.
        const btn = $("#regenLogo"); btn.innerHTML = '<span class="spinner dark"></span>';
        logoLock(true);
        try { const r = await api("/organization/branding", { method: "PATCH", body: { generate_random_logo: true } });
          const url = (r.organization || {}).logo_url; if (url) { $("#settingsLogo").src = url; $("#settingsLogo").style.visibility = "visible"; $("#brandLogo").src = url; $("#brandLogo").style.display = ""; state.me.organization.logo_url = url; }
          toast("New logo generated", "success"); }
        catch (ex) { toast(ex.message, "error"); }
        finally { btn.innerHTML = BTN_REGEN_HTML; logoLock(false); }
      };
      // The pickers are gated too: without this the file dialog still opens mid-upload and
      // the second file lands the moment the first finishes.
      $("#uploadLogoBtn").onclick = () => { if (!logoBusy) $("#logoFile").click(); };
      $("#heroLogoBtn").onclick = () => { if (!logoBusy) $("#logoFile").click(); };
      $("#logoFile").onchange = async () => {
        if (logoBusy) return;
        const f = $("#logoFile").files && $("#logoFile").files[0];
        if (!f) return;
        if (f.size > 2 * 1024 * 1024) { toast("Logo must be under 2 MB", "error"); $("#logoFile").value = ""; return; }
        const btn = $("#uploadLogoBtn"); btn.innerHTML = '<span class="spinner dark"></span> Uploading…';
        logoLock(true);
        try {
          const fd = new FormData();
          fd.append("file", f);
          const res = await fetch(API + "/organization/logo", { method: "POST", credentials: "include", body: fd });
          const out = await res.json().catch(() => null);
          if (!res.ok) throw makePublicApiError(res, out, "We couldn't upload this logo. Please try again.");
          state.me.organization = Object.assign(state.me.organization, out.organization || {});
          const url = state.me.organization.logo_url;
          if (url) {
            $("#settingsLogo").src = url; $("#settingsLogo").style.visibility = "visible";
            const bl = $("#brandLogo"); if (bl) { bl.src = url; bl.style.display = ""; }
          }
          toast("Logo updated", "success");
        } catch (ex) { toast(ex.message, "error"); }
        finally { btn.innerHTML = BTN_UPLOAD_HTML; logoLock(false); $("#logoFile").value = ""; }
      };
      $("#saveLocation").onclick = async () => {
        const cc = $("#setCountry").value;
        const st = $("#setState").value.trim();
        const btn = $("#saveLocation"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
        try {
          const r = await api("/organization/branding", { method: "PATCH", body: { country_code: cc, state_region: st } });
          state.me.organization = Object.assign(state.me.organization, r.organization || {});
          const cur = (state.me.organization.display_currency || {});
          toast("Location saved — amounts now show in " + (cur.code || "INR"), "success");
          renderSettings();   // re-render with the new currency line
        } catch (ex) { toast(ex.message, "error"); btn.disabled = false; btn.textContent = "Save location"; }
      };
    }
  }

  /* ============================================================
     public bridge for inline handlers
     ============================================================ */
  /* ============================================================
     AI ASSISTANT (Rilono AI Assistant)

     ONE conversation, TWO surfaces: the full-page assistant view and the
     dock that floats bottom-right on every other view. Nothing renders
     into a single id any more — every paint fans out over
     [data-ai-thread] / [data-ai-suggest] / [data-ai-input], so a question
     asked from the dock is already in the thread when the member opens
     the full view, and vice versa. `data-ai-compact` marks the dock's
     copies, which get the shorter empty state and a trimmed chip list.
     ============================================================ */
  const AI_SEND_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M13 6l6 6-6 6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const AI_SPARKLE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 4.6L18.5 9l-4.6 1.9L12 15l-1.9-4.1L5.5 9l4.6-1.4L12 3z"/><path d="M19 14l.8 2 2 .8-2 .8L19 20l-.8-2.4-2-.8 2-.8L19 14z"/></svg>';
  const AI_DISABLED_PLACEHOLDER = "AI assistant isn't configured on this server yet.";

  function ensureAiHistory() {
    if (!state.aiHistory) state.aiHistory = [];
    return state.aiHistory;
  }

  // Enter sends, Shift+Enter newlines, and the box grows with the draft.
  function wireAiComposer(ta) {
    if (!ta) return;
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendAi(ta.value); }
    });
    ta.addEventListener("input", () => {
      ta.style.height = "auto";
      ta.style.height = Math.min(ta.scrollHeight, ta.dataset.aiMaxH ? Number(ta.dataset.aiMaxH) : 160) + "px";
      syncAiSend();
    });
    syncAiSend();
  }

  function renderAIAssistant() {
    ensureAiHistory();
    const c = $("#content");
    c.innerHTML = `
      <div class="ai-wrap">
        <div class="ai-head">
          <div class="ai-orb">✨</div>
          <div><h2>Rilono AI Assistant</h2><p>Ask anything about your clients, pipeline and activity — I read your live portal data to answer.</p></div>
          <div class="ai-head-actions">
            <button type="button" class="btn btn-ghost btn-sm" id="aiHistBtn">History</button>
            <button type="button" class="btn btn-sm" id="aiNewBtn">New chat</button>
          </div>
        </div>
        <div class="ai-thread" id="aiThread" data-ai-thread></div>
        <div class="ai-suggest" id="aiSuggest" data-ai-suggest></div>
        <form class="ai-input" id="aiForm">
          <textarea id="aiInput" data-ai-input data-ai-placeholder="e.g. Which clients need my attention today?"
            rows="1" placeholder="e.g. Which clients need my attention today?" maxlength="4000"></textarea>
          <button type="submit" class="ai-send" id="aiSend" data-ai-send aria-label="Send">${AI_SEND_ICON}</button>
        </form>
        <div class="ai-disclaimer">AI can make mistakes — verify important details against the client record.</div>
      </div>`;
    renderAiThread();
    loadAiMeta();
    const ta = $("#aiInput");
    $("#aiForm").onsubmit = (e) => { e.preventDefault(); sendAi(ta.value); };
    $("#aiNewBtn").onclick = () => startNewAiChat();
    $("#aiHistBtn").onclick = () => openAiHistory();
    wireAiComposer(ta);
    ta.focus();
  }

  // Pull "**Verdict:** … · **Readiness:** N/5" into a coloured badge; return {head, body}.
  function verdictBadge(text) {
    if (!text) return { head: "", body: text || "" };
    const lines = String(text).split(/\n/);
    let idx = -1;
    for (let i = 0; i < lines.length; i++) { if (/verdict\s*:/i.test(lines[i])) { idx = i; break; } }
    if (idx < 0) return { head: "", body: text };
    const line = lines[idx];
    const vm = line.match(/verdict\s*:\**\s*(likely approved|borderline|needs work)/i);
    const rm = line.match(/readiness\s*:\**\s*(\d+)\s*\/\s*5/i);
    if (!vm && !rm) return { head: "", body: text };
    lines.splice(idx, 1);
    const body = lines.join("\n").replace(/^\s+/, "");
    let head = '<div class="iv-fb-head">';
    if (vm) {
      const vl = vm[1].toLowerCase();
      const cls = vl.indexOf("approved") >= 0 ? "green" : (vl.indexOf("borderline") >= 0 ? "amber" : "red");
      head += `<span class="iv-verdict iv-v-${cls}">${esc(vm[1])}</span>`;
    }
    if (rm) {
      const n = Math.max(0, Math.min(5, parseInt(rm[1], 10)));
      let dots = "";
      for (let k = 0; k < 5; k++) dots += `<span class="iv-dot${k < n ? " on" : ""}"></span>`;
      head += `<span class="iv-ready">Readiness <b>${n}/5</b><span class="iv-dots">${dots}</span></span>`;
    }
    return { head: head + "</div>", body };
  }
  // Feedback with the verdict badge on top of the formatted body.
  function feedbackFormat(text) {
    const vb = verdictBadge(text);
    return vb.head + aiFormat(vb.body);
  }

  function aiFormat(text) {
    let t = esc(text);
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    const lines = t.split(/\n/);
    let html = "", inList = false;
    const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };
    for (const raw of lines) {
      const line = raw.replace(/\s+$/, "");
      const h = line.match(/^\s*(#{1,4})\s+(.*)$/);
      if (h) { closeList(); html += `<div class="ai-h">${h[2]}</div>`; continue; }
      const m = line.match(/^\s*[-*•]\s+(.*)$/);
      if (m) { if (!inList) { html += "<ul>"; inList = true; } html += "<li>" + m[1] + "</li>"; }
      else { closeList(); if (line.trim() === "") continue; html += "<p>" + line + "</p>"; }
    }
    closeList();
    return html || "<p></p>";
  }

  // The empty thread. The dock gets a shorter version — its panel is a third
  // the width of the full view, where the long paragraph reads as clutter.
  function aiEmptyHtml(compact) {
    if (state.aiMeta && !state.aiMeta.enabled) {
      return `<div class="ai-empty"><div class="ai-orb lg">🔌</div><h3>AI assistant unavailable</h3>
        <p>An administrator needs to enable Rilono AI on the server to use the Rilono AI Assistant.</p></div>`;
    }
    if (compact) {
      return `<div class="ai-empty"><div class="ai-orb lg">✨</div><h3>How can I help?</h3>
        <p>Ask about a client's progress, who needs attention today, or what changed this week.</p></div>`;
    }
    return `<div class="ai-empty"><div class="ai-orb lg">✨</div>
      <h3>How can I help?</h3>
      <p>I can answer questions about your clients, their progress, who needs attention, recent activity and your team's workload.</p></div>`;
  }

  function renderAiThread() {
    const hosts = $$("[data-ai-thread]");
    if (!hosts.length) return;
    ensureAiHistory();
    const body = !state.aiHistory.length ? null : state.aiHistory.map((m) => {
      if (m.role === "user") {
        return `<div class="ai-msg user"><div class="ai-bubble">${esc(m.content).replace(/\n/g, "<br>")}</div></div>`;
      }
      if (m.role === "typing") {
        return `<div class="ai-msg bot"><div class="ai-av">✨</div><div class="ai-bubble"><span class="ai-typing"><i></i><i></i><i></i></span></div></div>`;
      }
      return `<div class="ai-msg bot"><div class="ai-av">✨</div><div class="ai-bubble">${aiFormat(m.content)}</div></div>`;
    }).join("");
    hosts.forEach((h) => {
      h.innerHTML = body == null ? aiEmptyHtml(h.hasAttribute("data-ai-compact")) : body;
      h.scrollTop = h.scrollHeight;
    });
  }

  function renderAiSuggestions() {
    const boxes = $$("[data-ai-suggest]");
    if (!boxes.length) return;
    const meta = state.aiMeta;
    const list = (meta && meta.enabled && !ensureAiHistory().length) ? (meta.suggestions || []) : [];
    boxes.forEach((box) => {
      // The dock only has room for a couple of chips above the composer.
      const use = box.hasAttribute("data-ai-compact") ? list.slice(0, 3) : list;
      box.innerHTML = use.map((s) => `<button class="ai-chip" type="button">${esc(s)}</button>`).join("");
      $$(".ai-chip", box).forEach((ch) => ch.onclick = () => sendAi(ch.textContent));
    });
  }

  async function loadAiMeta() {
    if (state.aiMeta) { applyAiMeta(); return state.aiMeta; }
    try { state.aiMeta = await api("/ai/meta"); } catch (ex) { state.aiMeta = { enabled: false, suggestions: [] }; }
    applyAiMeta();
    return state.aiMeta;
  }
  function applyAiMeta() {
    const off = !!(state.aiMeta && !state.aiMeta.enabled);
    $$("[data-ai-input]").forEach((ta) => {
      ta.disabled = off;
      ta.placeholder = off ? AI_DISABLED_PLACEHOLDER : (ta.dataset.aiPlaceholder || ta.placeholder);
    });
    setAiBusy(!!state.aiBusy);
    if (off) renderAiThread();   // paints the "unavailable" card on every surface
    renderAiSuggestions();
  }

  // A send in flight (or a server without AI) locks the send buttons on both surfaces.
  function setAiBusy(on) {
    state.aiBusy = !!on;
    syncAiSend();
  }

  /* The full-page composer and the dock share one send state, so this is computed once and
     applied to every [data-ai-send]. The third term is the new one: the arrow used to be
     live over an empty box, and the click landed on `if (!msg) return` in sendAi — a dead
     click with no feedback at all. A draft in EITHER composer counts, because sendAi()
     called from a form submit takes whichever one has text. */
  function syncAiSend() {
    const off = !!(state.aiMeta && !state.aiMeta.enabled);
    const hasDraft = $$("[data-ai-input]").some((ta) => (ta.value || "").trim() !== "");
    $$("[data-ai-send]").forEach((b) => { b.disabled = state.aiBusy || off || !hasDraft; });
  }

  async function sendAi(text) {
    if (state.aiBusy) return;
    if (state.aiMeta && !state.aiMeta.enabled) return;
    const inputs = $$("[data-ai-input]");
    let msg = String(text == null ? "" : text).trim();
    // Called with no text (a form submit): take whichever composer has a draft.
    if (!msg) { for (const el of inputs) { const v = (el.value || "").trim(); if (v) { msg = v; break; } } }
    if (!msg) return;
    ensureAiHistory();
    // Only the FIRST turn of a thread sends local history — a known thread replays its
    // own server-side transcript, and stored answers can exceed the request schema's
    // 6000-char per-turn cap (sending them back would 422 the whole message). The same
    // cap is applied client-side for the first-turn payload.
    const priorHistory = state.aiConvId ? [] : state.aiHistory
      .filter((m) => (m.role === "user" || m.role === "model") && m.content)
      .slice(-12)
      .map((m) => ({ role: m.role, content: String(m.content).slice(0, 6000) }));
    state.aiHistory.push({ role: "user", content: msg });
    state.aiHistory.push({ role: "typing", content: "" });
    // Both composers hold the same conversation, so both drafts clear on send.
    inputs.forEach((el) => { el.value = ""; el.style.height = "auto"; });
    setAiBusy(true);
    renderAiThread(); renderAiSuggestions();
    try {
      // With a conversation_id the server replays its own stored transcript and
      // ignores `history`; client_threads tells it this client understands saved
      // threads (legacy SPAs without the flag stay fully stateless).
      const data = await api("/ai/chat", { method: "POST", body: { message: msg, history: priorHistory, conversation_id: state.aiConvId || null, client_threads: true }, timeout: AI_API_TIMEOUT_MS });
      state.aiHistory = state.aiHistory.filter((m) => m.role !== "typing");
      state.aiHistory.push({ role: "model", content: data.answer || "(no answer)" });
      // Remember the thread the server answered on (created on the first turn) and
      // invalidate the cached history list — its order/preview just changed.
      if (data.conversation_id) { state.aiConvId = data.conversation_id; state.aiConvs = null; }
      // Keep the credits chip in sync when a message debited the wallet.
      if (data.wallet) { state.credits = data.wallet; updatePlanChip(); }
      if (data.credits_meter) setAiMeter(data.credits_meter);
      markAiAnswerArrived();
    } catch (ex) {
      state.aiHistory = state.aiHistory.filter((m) => m.role !== "typing");
      // Out of credits for the assistant → explain in-thread and point to top-up.
      if (ex.status === 402) {
        state.aiHistory.push({ role: "model", content: ex.message || "You're out of Rilono Credits for the AI assistant. Top up to keep chatting." });
        toast(ex.message, "error");
        setAiBusy(false); renderAiThread(); markAiAnswerArrived();
        // Spend-only roles can't open the credits view — don't navigate them into a wall.
        if (can("credits.view")) navigate("credits");
        return;
      }
      // The thread this tab was continuing no longer exists (deleted in another tab, or
      // aged out). Clear the dead id — the next send starts a fresh thread that keeps
      // the on-screen context — instead of 404ing on every retry forever.
      if (ex.status === 404 && state.aiConvId) {
        state.aiConvId = null;
        state.aiConvs = null;
        state.aiHistory.push({ role: "model", content: "This conversation was deleted elsewhere, so I've started a fresh one — please send that message again." });
        setAiBusy(false); renderAiThread(); markAiAnswerArrived();
        return;
      }
      state.aiHistory.push({
        role: "model",
        content: "Sorry, I encountered an error. We are working on it, and this issue has been raised for review."
      });
      toast("AI assistant ran into a problem. Please try again.", "error");
      markAiAnswerArrived();
    } finally {
      setAiBusy(false);
      renderAiThread();
    }
  }

  /* ------------------------------------------------------------------
     SAVED THREADS — conversations persist server-side per member. The
     shared state is state.aiConvId (the thread the next send continues)
     and state.aiHistory (its transcript); "New chat" just clears both.
     ------------------------------------------------------------------ */
  function startNewAiChat() {
    if (state.aiBusy) return;
    state.aiConvId = null;
    state.aiHistory = [];
    renderAiThread(); renderAiSuggestions();
    const ta = state.view === "ai" ? $("#aiInput") : (aiDock.mounted ? $("#aiDockInput", aiDock.root) : null);
    if (ta && !ta.disabled) ta.focus();
  }

  async function loadAiConversation(id) {
    if (state.aiBusy) return;
    let data;
    try { data = await api(`/ai/conversations/${id}`); }
    catch (ex) { toast(ex.message || "Couldn't open that conversation.", "error"); return; }
    state.aiConvId = data.conversation.id;
    state.aiHistory = (data.messages || []).map((m) => ({ role: m.role === "user" ? "user" : "model", content: m.content || "" }));
    renderAiThread(); renderAiSuggestions();
    // Opened from the history modal on a non-assistant view → surface the dock so
    // the loaded thread is actually visible somewhere.
    if (state.view !== "ai" && aiDock.mounted && !aiDock.open) openAiDock();
  }

  async function openAiHistory() {
    let convs = state.aiConvs;
    if (!convs) {
      try { const r = await api("/ai/conversations"); convs = r.conversations || []; state.aiConvs = convs; state.aiRetentionDays = r.retention_days; }
      catch (ex) { toast(ex.message || "Couldn't load your chat history.", "error"); return; }
    }
    const retention = state.aiRetentionDays;
    openModal(`<div class="modal-head"><h3>Chat history</h3><button class="x" onclick="__ent.closeModal()">×</button></div>
      <div class="modal-body">
        <div class="ai-hist-list" id="aiHistList"></div>
        ${retention > 0 ? `<div class="ai-hist-note">Conversations are kept for ${retention} days, then deleted automatically.</div>` : ""}
      </div>`);
    renderAiHistoryList();
  }

  function renderAiHistoryList() {
    const box = $("#aiHistList");
    if (!box) return;
    const convs = state.aiConvs || [];
    if (!convs.length) {
      box.innerHTML = `<div class="ai-hist-empty">No saved conversations yet — ask the assistant something and it'll appear here.</div>`;
      return;
    }
    box.innerHTML = convs.map((c) => `
      <div class="ai-hist-row${c.id === state.aiConvId ? " current" : ""}" data-id="${c.id}">
        <button type="button" class="ai-hist-main">
          <span class="ai-hist-title">${esc(c.title || "New conversation")}</span>
          <span class="ai-hist-meta">${fmtDate(c.last_message_at)} · ${c.message_count} message${c.message_count === 1 ? "" : "s"}${c.id === state.aiConvId ? " · open now" : ""}</span>
        </button>
        <button type="button" class="ai-hist-del" title="Delete conversation" aria-label="Delete conversation">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a1 1 0 011-1h6a1 1 0 011 1v2"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg>
        </button>
      </div>`).join("");
    $$(".ai-hist-row", box).forEach((row) => {
      const id = Number(row.dataset.id);
      $(".ai-hist-main", row).onclick = () => {
        if (state.aiBusy) { toast("Wait for the current answer to finish first.", "error"); return; }
        closeModal();
        loadAiConversation(id);
      };
      $(".ai-hist-del", row).onclick = async () => {
        // Deleting the thread that's mid-answer would strand the in-flight turn (the
        // server falls back to a fresh thread, but the UI state would fork) — block it.
        if (state.aiBusy) { toast("Wait for the current answer to finish first.", "error"); return; }
        const conv = (state.aiConvs || []).find((c) => c.id === id);
        const ok = await confirmModal(
          `Delete “${(conv && conv.title) || "this conversation"}”? Its messages are removed for good.`,
          { title: "Delete conversation", okText: "Delete" },
        );
        // confirmModal shares #modal with the history list, so EVERY exit path below
        // reopens the list — cancelling a delete must not dump the user back on the page.
        if (!ok) { openAiHistory(); return; }
        try { await api(`/ai/conversations/${id}`, { method: "DELETE" }); }
        catch (ex) { toast(ex.message || "Couldn't delete that conversation.", "error"); openAiHistory(); return; }
        // Drop the row from the cache only if the cache still exists — when something
        // else invalidated it to null meanwhile, leave it null so the reopen refetches
        // instead of showing a fabricated empty list.
        if (state.aiConvs) state.aiConvs = state.aiConvs.filter((c) => c.id !== id);
        // Deleting the thread that's on screen clears the composer state too.
        if (state.aiConvId === id) { state.aiConvId = null; state.aiHistory = []; renderAiThread(); renderAiSuggestions(); }
        toast("Conversation deleted.", "success");
        openAiHistory();
      };
    });
  }

  /* ------------------------------------------------------------------
     DOCKED ASSISTANT — the bubble that sits bottom-right on every view
     except the assistant's own page (where it would only duplicate what
     is already on screen). The member's open/closed choice is remembered
     across page loads; the thread itself is the shared state.aiHistory.
     ------------------------------------------------------------------ */
  const AI_DOCK_OPEN_KEY = "rilono.ent.aiDockOpen";
  const aiDock = { mounted: false, open: false, root: null };

  function aiDockPref() {
    try { return localStorage.getItem(AI_DOCK_OPEN_KEY) === "1"; } catch (e) { return false; }
  }
  function setAiDockPref(open) {
    try { open ? localStorage.setItem(AI_DOCK_OPEN_KEY, "1") : localStorage.removeItem(AI_DOCK_OPEN_KEY); }
    catch (e) { /* private mode — the dock just won't be remembered */ }
  }

  // Answered while the panel is closed → put a dot on the bubble so the reply
  // isn't sitting there unseen.
  function markAiAnswerArrived() {
    if (!aiDock.mounted || aiDock.open) return;
    const dot = $("#aiDockDot", aiDock.root);
    if (dot) dot.classList.add("on");
  }
  function clearAiDockDot() {
    if (!aiDock.mounted) return;
    const dot = $("#aiDockDot", aiDock.root);
    if (dot) dot.classList.remove("on");
  }

  // The copilot meter that comes back with every answer: free daily messages
  // first, then one credit per bundle. Shown in the dock header so the cost of
  // the next question is never a surprise.
  function setAiMeter(meter) {
    if (meter) state.aiMeter = meter;
    const sub = aiDock.mounted ? $("#aiDockSub", aiDock.root) : null;
    const m = state.aiMeter;
    if (!sub || !m) return;
    const free = Number(m.free_remaining_today || 0);
    const per = Number(m.msgs_per_credit || 0);
    // A question that needed several lookups is metered as the several messages' worth
    // of work it was, so say so — otherwise the allowance appears to jump for no reason.
    const weight = Number(m.message_weight || 1);
    const weightNote = weight > 1 ? ` · last answer counted as ${weight}` : "";
    sub.textContent = (free > 0
      ? `${free} free message${free === 1 ? "" : "s"} left today`
      : (per ? `${per} messages per credit` : "Answers from your live portal data")) + weightNote;
  }

  function mountAiDock() {
    if (aiDock.mounted || !state.me || !can("ai.assistant")) return;
    const root = document.createElement("div");
    root.className = "aidock";
    root.id = "aiDock";
    root.innerHTML = `
      <section class="aidock-panel" id="aiDockPanel" role="dialog" aria-label="Rilono AI Assistant">
        <header class="aidock-head">
          <span class="aidock-orb" aria-hidden="true">${AI_SPARKLE_ICON}</span>
          <span class="aidock-id"><b>Rilono AI</b><small id="aiDockSub">Answers from your live portal data</small></span>
          <span class="aidock-acts">
            <button type="button" class="aidock-act" id="aiDockNew" title="New chat" aria-label="Start a new chat">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
            </button>
            <button type="button" class="aidock-act" id="aiDockHist" title="Chat history" aria-label="Open chat history">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>
            </button>
            <button type="button" class="aidock-act" id="aiDockExpand" title="Open the full assistant" aria-label="Open the full assistant">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M9 21H3v-6"/><path d="M21 3l-7 7"/><path d="M3 21l7-7"/></svg>
            </button>
            <button type="button" class="aidock-act" id="aiDockMin" title="Minimize" aria-label="Minimize the assistant">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 12h12"/></svg>
            </button>
          </span>
        </header>
        <div class="aidock-thread ai-thread" data-ai-thread data-ai-compact></div>
        <div class="aidock-suggest ai-suggest" data-ai-suggest data-ai-compact></div>
        <form class="aidock-form ai-input" id="aiDockForm">
          <textarea id="aiDockInput" data-ai-input data-ai-max-h="110" data-ai-placeholder="Ask about a client, stage or task…"
            rows="1" placeholder="Ask about a client, stage or task…" maxlength="4000"></textarea>
          <button type="submit" class="ai-send" data-ai-send aria-label="Send">${AI_SEND_ICON}</button>
        </form>
        <div class="aidock-foot">AI can make mistakes — verify against the client record.</div>
      </section>
      <button type="button" class="aidock-fab" id="aiDockFab" aria-expanded="false" aria-controls="aiDockPanel" aria-label="Ask Rilono AI">
        <span class="aidock-fab-ring" aria-hidden="true"></span>
        <span class="aidock-ic aidock-ic-ai" aria-hidden="true">${AI_SPARKLE_ICON}</span>
        <span class="aidock-ic aidock-ic-down" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg></span>
        <span class="aidock-dot" id="aiDockDot" aria-hidden="true"></span>
      </button>
      <span class="aidock-tip" aria-hidden="true">Ask Rilono AI</span>`;
    document.body.appendChild(root);
    aiDock.root = root;
    aiDock.mounted = true;
    document.body.classList.add("has-ai-dock");

    $("#aiDockFab", root).onclick = () => (aiDock.open ? closeAiDock() : openAiDock());
    $("#aiDockMin", root).onclick = () => closeAiDock();
    $("#aiDockNew", root).onclick = () => startNewAiChat();
    $("#aiDockHist", root).onclick = () => openAiHistory();
    $("#aiDockExpand", root).onclick = () => navigate("ai");   // syncAiDockVisibility tucks the dock away
    const ta = $("#aiDockInput", root);
    $("#aiDockForm", root).onsubmit = (e) => { e.preventDefault(); sendAi(ta.value); };
    wireAiComposer(ta);
    // Escape closes the dock — but only when it's the top-most thing on screen.
    // Capture phase on purpose: the app's own Escape handler is a bubble-phase
    // listener on document that strips .show, so reading the modal/drawer state
    // afterwards would always say "nothing open" and close both at once.
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape" || !aiDock.open) return;
      if ($("#modal").classList.contains("show") || $("#drawer").classList.contains("show")) return;
      closeAiDock();
    }, true);

    applyAiMeta();
    setAiMeter(null);
    syncAiDockVisibility();
  }

  function openAiDock(opts) {
    if (!aiDock.mounted) return;
    aiDock.open = true;
    aiDock.root.classList.add("is-open");
    document.body.classList.add("ai-dock-open");
    const fab = $("#aiDockFab", aiDock.root);
    if (fab) { fab.setAttribute("aria-expanded", "true"); fab.setAttribute("aria-label", "Minimize Rilono AI"); }
    clearAiDockDot();
    renderAiThread(); renderAiSuggestions(); applyAiMeta();
    if (!(opts && opts.restore)) { const ta = $("#aiDockInput", aiDock.root); if (ta && !ta.disabled) ta.focus(); }
    if (!(opts && opts.keepPref)) setAiDockPref(true);
  }

  function closeAiDock(opts) {
    if (!aiDock.mounted) return;
    aiDock.open = false;
    aiDock.root.classList.remove("is-open");
    document.body.classList.remove("ai-dock-open");
    const fab = $("#aiDockFab", aiDock.root);
    if (fab) {
      fab.setAttribute("aria-expanded", "false");
      fab.setAttribute("aria-label", "Ask Rilono AI");
      if (!(opts && opts.silent)) fab.focus();
    }
    if (!(opts && opts.keepPref)) setAiDockPref(false);
  }

  // Called on every navigation. The dock disappears on the assistant's own page
  // and comes back — still open, if that's how it was left — on the way out.
  function syncAiDockVisibility() {
    if (!aiDock.mounted) return;
    const hide = state.view === "ai";
    aiDock.root.classList.toggle("aidock-off", hide);
    if (hide) { if (aiDock.open) closeAiDock({ silent: true, keepPref: true }); return; }
    if (!aiDock.open && aiDockPref()) openAiDock({ restore: true, keepPref: true });
  }

  // Mount at boot, but only for members who may use the assistant and only when
  // the server actually has AI configured — a bubble that can only ever refuse
  // isn't worth the corner it occupies.
  async function initAiDock() {
    if (!state.me || !can("ai.assistant") || aiDock.mounted) return;
    const meta = await loadAiMeta();
    if (meta && meta.enabled) mountAiDock();
  }

  async function viewInterviewSession(clientId, sessionId) {
    let data;
    try { data = await api(`/clients/${clientId}/interview/sessions/${sessionId}`); }
    catch (ex) { toast(ex.message, "error"); return; }
    const s = data.session;
    const transcript = (s.transcript || []).map((m) => {
      const bot = m.role !== "user";
      return `<div class="ai-msg ${bot ? "bot" : "user"}">${bot ? '<div class="ai-av">🧑‍✈️</div>' : ""}<div class="ai-bubble">${bot ? aiFormat(m.content) : esc(m.content).replace(/\n/g, "<br>")}</div></div>`;
    }).join("");
    openModal(`<div class="modal-head"><h3>Mock interview · ${fmtDate(s.created_at)}</h3><button class="x" onclick="__ent.closeModal()">×</button></div>
      <div class="modal-body">
        <div class="cp-sub-label">📋 Feedback</div>
        <div class="iv-feedback" style="margin-bottom:18px">${feedbackFormat(s.feedback || "No feedback recorded.")}</div>
        <div class="cp-sub-label">Transcript</div>
        <div class="iv-thread" style="max-height:340px;overflow-y:auto">${transcript || '<div class="muted">No transcript.</div>'}</div>
      </div>
      <div class="modal-foot"><button class="btn btn-ghost" onclick="__ent.closeModal()">Close</button></div>`);
  }

  function deepScanPreviewType(doc) {
    const mime = String((doc && doc.mime_type) || "").toLowerCase();
    const filename = String((doc && doc.original_filename) || "").toLowerCase();
    if (mime === "application/pdf" || filename.endsWith(".pdf")) return "pdf";
    if (/^image\/(?:jpeg|png|webp|gif)$/.test(mime) || /\.(?:jpe?g|png|webp|gif)$/.test(filename)) return "image";
    return "file";
  }

  function deepScanFallbackMarkup(doc) {
    return `<div class="dsv-file-fallback">
      <div class="dsv-file-icon" aria-hidden="true">${docIcon(doc.original_filename)}</div>
      <div class="dsv-file-name">${esc(doc.original_filename || "Uploaded document")}</div>
      <div class="dsv-file-note">Secure file preview is unavailable, but the uploaded file is included in this audit.</div>
    </div>`;
  }

  function deepScanPreviewMarkup(doc) {
    const type = deepScanPreviewType(doc);
    const url = String(doc.download_url || "");
    const title = esc(doc.original_filename || "Uploaded document");
    if (type === "image") {
      return `<img class="dsv-preview-image" src="${esc(url)}" alt="First-page preview of ${title}" />`;
    }
    if (type === "pdf") {
      return `<div class="dsv-pdf-fallback">${deepScanFallbackMarkup(doc)}</div>
        <iframe class="dsv-preview-pdf" title="First page of ${title}" tabindex="-1"></iframe>`;
    }
    return deepScanFallbackMarkup(doc);
  }

  function startDeepScanVisualizer(documents) {
    const host = $("#deepScanVisualizer");
    const list = (documents || []).filter((doc) => doc && doc.download_url);
    const noop = { setPhase() {}, complete() {}, fail() {}, destroy() {} };
    if (!host || !list.length) return noop;

    let currentIndex = 0;
    let currentPhase = 0;
    let currentLabel = "Reading uploaded document";
    let currentElapsed = 0;
    let cycleTimer = null;
    let previewObjectUrl = null;
    let previewToken = 0;

    const releasePreview = () => {
      if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
      previewObjectUrl = null;
      previewToken += 1;
    };

    const applyPhase = () => {
      const phaseEl = $("[data-dsv-phase]", host);
      const elapsedEl = $("[data-dsv-elapsed]", host);
      if (phaseEl) phaseEl.textContent = currentLabel;
      if (elapsedEl) elapsedEl.textContent = `${currentElapsed}s`;
      $$("[data-dsv-step]", host).forEach((step) => {
        const stepIndex = Number(step.dataset.dsvStep);
        step.classList.toggle("active", currentPhase < 3 && stepIndex === currentPhase);
        step.classList.toggle("done", currentPhase >= 3 || stepIndex < currentPhase);
      });
    };

    const renderDocument = () => {
      // Host replaced by a tab switch / repaint: stop cycling (each PDF cycle re-fetches
      // the full credentialed blob) — the settle path's destroy() clears the timer.
      if (!host.isConnected) { releasePreview(); return; }
      releasePreview();
      const doc = list[currentIndex];
      const visibleIndex = currentIndex + 1;
      const fileType = deepScanPreviewType(doc) === "pdf" ? "PDF first page" : deepScanPreviewType(doc) === "image" ? "Image preview" : "Secure file";
      host.innerHTML = `<div class="dsv-layout">
        <div class="dsv-document-column">
          <div class="dsv-document-topline">
            <span class="dsv-live"><span class="dsv-live-dot"></span> Live document audit</span>
            <span class="dsv-count">${visibleIndex} of ${list.length}</span>
          </div>
          <div class="dsv-document" aria-label="Scanning ${esc(doc.original_filename || "uploaded document")}">
            <div class="dsv-preview">${deepScanPreviewMarkup(doc)}</div>
            <div class="dsv-grid" aria-hidden="true"></div>
            <div class="dsv-scan-beam" aria-hidden="true"><span></span></div>
            <i class="dsv-corner top-left" aria-hidden="true"></i>
            <i class="dsv-corner top-right" aria-hidden="true"></i>
            <i class="dsv-corner bottom-left" aria-hidden="true"></i>
            <i class="dsv-corner bottom-right" aria-hidden="true"></i>
          </div>
          <div class="dsv-file-meta">
            <div class="dsv-file-meta-copy">
              <strong title="${esc(doc.original_filename || "")}">${esc(doc.original_filename || "Uploaded document")}</strong>
              <span>${esc(doc.document_type || "Document")} · ${fileType} · ${fmtSize(doc.file_size)}</span>
            </div>
            <span class="dsv-lock" title="Served through an authenticated connection">Secure</span>
          </div>
        </div>
        <div class="dsv-analysis">
          <div class="dsv-eyebrow">Rilono document intelligence</div>
          <h3 data-dsv-phase>${esc(currentLabel)}</h3>
          <p>The audit is reading the actual uploaded file and comparing details across this student's document set.</p>
          <div class="dsv-steps">
            <div class="dsv-step" data-dsv-step="0"><span>1</span><div><b>Read document content</b><small>Names, dates, amounts and identifiers</small></div></div>
            <div class="dsv-step" data-dsv-step="1"><span>2</span><div><b>Cross-check records</b><small>Consistency across all uploaded files</small></div></div>
            <div class="dsv-step" data-dsv-step="2"><span>3</span><div><b>Prepare audit findings</b><small>Risks, gaps and recommended actions</small></div></div>
          </div>
          <div class="dsv-progress-row">
            <div class="dsv-progress-track"><span></span></div>
            <span class="dsv-elapsed" data-dsv-elapsed>${currentElapsed}s</span>
          </div>
          <div class="dsv-trust-note"><span aria-hidden="true">✓</span> Preview loaded from the private file already attached to this student.</div>
        </div>
      </div>`;

      const image = $(".dsv-preview-image", host);
      if (image) {
        image.onerror = () => {
          const preview = image.closest(".dsv-preview");
          if (preview) preview.innerHTML = deepScanFallbackMarkup(doc);
        };
      }
      const pdfFrame = $(".dsv-preview-pdf", host);
      if (pdfFrame) {
        const token = previewToken;
        fetch(doc.download_url, { credentials: "include" })
          .then((response) => {
            if (!response.ok) throw new Error("preview unavailable");
            return response.blob();
          })
          .then((blob) => {
            if (token !== previewToken || !pdfFrame.isConnected) return;
            previewObjectUrl = URL.createObjectURL(new Blob([blob], { type: "application/pdf" }));
            pdfFrame.src = `${previewObjectUrl}#page=1&view=FitH&toolbar=0&navpanes=0&scrollbar=0`;
          })
          .catch(() => {
            if (token === previewToken && pdfFrame.isConnected) pdfFrame.remove();
          });
      }
      applyPhase();
    };

    host.classList.remove("hidden", "is-complete", "is-error");
    renderDocument();
    if (list.length > 1) {
      cycleTimer = window.setInterval(() => {
        currentIndex = (currentIndex + 1) % list.length;
        renderDocument();
      }, 5200);
    }

    return {
      setPhase(phase, label, elapsed) {
        currentPhase = Math.max(0, Math.min(2, Number(phase) || 0));
        currentLabel = label || currentLabel;
        currentElapsed = Math.max(0, Number(elapsed) || 0);
        applyPhase();
      },
      complete() {
        currentPhase = 3;
        currentLabel = "Document audit complete";
        host.classList.add("is-complete");
        applyPhase();
      },
      fail() {
        currentLabel = "The audit could not be completed";
        host.classList.add("is-error");
        const phaseEl = $("[data-dsv-phase]", host);
        if (phaseEl) phaseEl.textContent = currentLabel;
      },
      destroy(delay) {
        if (cycleTimer) window.clearInterval(cycleTimer);
        cycleTimer = null;
        window.setTimeout(() => {
          host.classList.add("hidden");
          releasePreview();
        }, Math.max(0, Number(delay) || 0));
      },
    };
  }

  // --- Deep Scan report: render the stored structured findings (JSON, not markdown) ---
  function dsInline(s) {
    let t = esc(s);
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    t = t.replace(/`([^`]+)`/g, '<code style="background:var(--bg-2);padding:1px 5px;border-radius:5px;font-size:.92em">$1</code>');
    return t;
  }
  const DS_AREA_LABELS = {
    profile: "Profile", stage_records: "Case records", documents: "Documents", notes: "Notes",
    emails: "Emails", universities: "Universities", interviews: "Interviews", payments: "Payments",
  };
  const DS_CATEGORY_LABELS = {
    identity: "Identity", documents: "Documents", timeline: "Timeline", financial: "Financial",
    academic: "Academic", communication: "Communication", payments: "Payments",
    data_quality: "Data quality", process: "Process", other: "Other",
  };
  function dsSevMeta(sev) {
    if (sev === "critical") return { cls: "err", label: "Critical", bg: "#fee2e2", color: "#dc2626" };
    if (sev === "info") return { cls: "note", label: "Info", bg: "#e0e7ff", color: "#4338ca" };
    return { cls: "miss", label: "Warning", bg: "#fef3c7", color: "#b45309" };
  }
  function dsFindingHtml(f) {
    const sev = dsSevMeta(f.severity);
    const chips = [];
    if (DS_CATEGORY_LABELS[f.category]) chips.push(DS_CATEGORY_LABELS[f.category]);
    const area = DS_AREA_LABELS[f.area];
    if (area && area !== chips[0]) chips.push(area);
    return `<div class="ds-item ${sev.cls}"><div class="b">!</div><div class="ds-item-body">
      <div class="ds-item-top"><span class="tag" style="background:${sev.bg};color:${sev.color}">${sev.label}</span>
        ${chips.map((c) => `<span class="ds-chip">${esc(c)}</span>`).join("")}</div>
      <div class="ds-item-title">${dsInline(f.title || "Irregularity found")}</div>
      ${f.detail ? `<div class="ds-item-detail">${dsInline(f.detail)}</div>` : ""}
      ${(f.evidence || []).length ? `<div class="ds-evidence">${f.evidence.map((e) => `<div class="ds-ev">${dsInline(e)}</div>`).join("")}</div>` : ""}
      ${f.recommendation ? `<div class="ds-fix"><b>Fix:</b> ${dsInline(f.recommendation)}</div>` : ""}
    </div></div>`;
  }
  function deepScanResultHtml(scan) {
    const risk = (scan.risk_level || "medium").toLowerCase();
    const stats = scan.stats || {};
    const findings = Array.isArray(scan.findings) ? scan.findings : [];
    const checks = Array.isArray(scan.checks_passed) ? scan.checks_passed : [];
    const nCrit = stats.critical != null ? stats.critical : findings.filter((f) => f.severity === "critical").length;
    const nWarn = stats.warning != null ? stats.warning : findings.filter((f) => f.severity === "warning").length;
    const nInfo = stats.info != null ? stats.info : findings.filter((f) => f.severity === "info").length;
    const meta = ({ high: { ic: "⚠️", word: "High risk" }, medium: { ic: "⚡", word: "Medium risk" }, low: { ic: "✅", word: "Low risk" } })[risk] || { ic: "⚡", word: "Medium risk" };
    const analyzed = stats.documents_analyzed || 0;
    const total = stats.documents_total != null ? stats.documents_total : analyzed;
    const skipped = stats.documents_skipped || 0, overCap = stats.documents_over_cap || 0, failed = stats.extraction_failures || 0;
    const coverBits = [];
    if (skipped) coverBits.push(`${skipped} had no readable text yet`);
    if (overCap) coverBits.push(`${overCap} exceeded the per-scan limit`);
    if (failed) coverBits.push(`${failed} audited from a raw excerpt only`);
    const coverWarn = coverBits.length
      ? `<div class="ds-coverage">⚠️ Audited <b>${analyzed}</b> of <b>${total}</b> documents — ${coverBits.join("; ")}.${(skipped + overCap) > 0 ? " Re-run once they're ready for full coverage." : ""}</div>`
      : "";
    const when = [
      fmtDateTime(scan.created_at),
      scan.triggered_by_name ? "by " + esc(scan.triggered_by_name) : "",
      scan.credits_charged ? scan.credits_charged + " credits" : "Free scan",
      `<b>${analyzed}</b>&nbsp;of&nbsp;<b>${total}</b>&nbsp;document${total === 1 ? "" : "s"} audited`,
    ].filter(Boolean).join(" · ");
    return `
      <div class="ds-meta">${when}</div>
      ${coverWarn}
      <div class="ds-risk ${risk}"><div class="ds-ic">${meta.ic}</div>
        <div><div class="lvl">${meta.word}</div><div class="why">${scan.summary ? dsInline(scan.summary) : "See the findings below."}</div></div></div>
      <div class="ds-stats">
        <div class="ds-stat"><b style="color:${nCrit ? "#dc2626" : "#10b981"}">${nCrit}</b><span>Critical</span></div>
        <div class="ds-stat"><b style="color:${nWarn ? "#b45309" : "#10b981"}">${nWarn}</b><span>Warnings</span></div>
        <div class="ds-stat"><b style="color:#4338ca">${nInfo}</b><span>Info</span></div>
        <div class="ds-stat"><b style="color:#10b981">${checks.length}</b><span>Checks passed</span></div>
      </div>
      ${findings.length
        ? `<div class="ds-sec"><div class="ds-sec-h">🚩 Findings <span class="n">${findings.length}</span></div><div class="ds-list">${findings.map(dsFindingHtml).join("")}</div></div>`
        : `<div class="ds-sec"><div class="ds-sec-h">🚩 Findings</div><div class="ds-clear">✓ Nothing irregular found — the dossier looks clean and consistent.</div></div>`}
      ${checks.length ? `<div class="ds-sec"><div class="ds-sec-h">✅ Checks passed <span class="n">${checks.length}</span></div>
        <div class="ds-list">${checks.map((c) => `<div class="ds-item ok"><div class="b">✓</div><div>${dsInline(c)}</div></div>`).join("")}</div></div>` : ""}`;
  }

  /* ============================================================
     CALENDAR — timelines, deadlines & what's next
     ============================================================ */
  let calEventsById = {};
  // The org's operating zone, short form ("IST", "BST"). Event times are wall-clock in it,
  // so anywhere a clock time is shown on its own it needs this beside it. Filled from the
  // /calendar payload and reused by calDetailModal, which the dashboard also opens.
  let calTzLabel = "";
  // …and the org's own date, for the same reason. A "Today"/"Yesterday" label worked out from
  // the reader's clock disagrees with the server's `overdue` flag for anyone in a different
  // zone — the detail modal was rendering "⚠ Overdue" and "Today" side by side.
  let calTodayYmd = "";
  const calClock = (t) => (t ? (calTzLabel ? `${t} ${calTzLabel}` : t) : "");
  /* Set when the dashboard's "What's next" hands an event over. renderCalendar opens it once the
     month has loaded, so the modal's Save / Mark done / Delete all re-render the Calendar page
     they belong to instead of painting it over the dashboard the user was standing on. */
  let calPendingOpen = null;

  /* Reference files on an event. Mirrors ENTERPRISE_CAL_ATTACH_* and ALLOWED_EXT in
     app/enterprise_calendar_files.py — the allow-list is spelled out again rather than shared
     with SUP_ALLOWED_EXT because that one is declared much further down this IIFE and a
     `const` is not readable before its own initialiser runs. */
  const CAL_ATT_EXT = [
    ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic",
    ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt",
  ];
  const CAL_ATT_MAX_FILES = 6;
  const CAL_ATT_MAX_BYTES = 15 * 1024 * 1024;
  const CAL_ATT_MAX_TOTAL_BYTES = 40 * 1024 * 1024;

  function calState() {
    if (!state.cal) { const d = new Date(); state.cal = { year: d.getFullYear(), month: d.getMonth() }; }
    return state.cal;
  }
  function calYmd(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  function calParse(s) { const [y, m, d] = String(s).split("-").map(Number); return new Date(y, (m || 1) - 1, d || 1); }
  function calGridRange(y, m) {
    const first = new Date(y, m, 1);
    const start = new Date(first); start.setDate(1 - first.getDay());
    const last = new Date(y, m + 1, 0);
    const end = new Date(last); end.setDate(last.getDate() + (6 - last.getDay()));
    return { start, end };
  }
  function calRel(dateStr, todayStr) {
    const a = calParse(dateStr), b = calParse(todayStr);
    const days = Math.round((a - b) / 86400000);
    if (days === 0) return "Today";
    if (days === 1) return "Tomorrow";
    if (days === -1) return "Yesterday";
    if (days < 0) return `${-days} days ago`;
    return `in ${days} days`;
  }

  async function renderCalendar() {
    const c = $("#content");
    c.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
    const cs = calState();
    const { start, end } = calGridRange(cs.year, cs.month);
    let data, up, clientsResp;
    try {
      [data, up, clientsResp] = await Promise.all([
        api(`/calendar?start=${calYmd(start)}&end=${calYmd(end)}`),
        api(`/calendar/upcoming?days=21`),
        api(`/calendar/clients`),
      ]);
    } catch (ex) { c.innerHTML = errBox(ex); return; }
    state.calClients = (clientsResp && clientsResp.clients) || [];
    // Was `state.perms = data.permissions || state.perms` — a thin calendar payload
    // overwrote the whole session's permissions. applyAccessPayload only accepts them
    // alongside a resolved `access` block, so opening Calendar can't downgrade anything.
    applyAccessPayload(data);
    const canEdit = can("calendar.manage");
    state.calTypes = data.event_types || [];
    calTzLabel = data.timezone_label || "";
    calTodayYmd = data.today || "";
    const today = data.today;

    calEventsById = {};
    const byDate = {};
    (data.events || []).forEach((e) => { calEventsById[e.id] = e; (byDate[e.date] = byDate[e.date] || []).push(e); });
    (up.overdue || []).concat(up.upcoming || []).forEach((e) => { calEventsById[e.id] = e; });

    setCalendarBadge((up.overdue || []).length + (up.upcoming || []).length);

    // Build the month grid
    const dows = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    let cells = "";
    const cur = new Date(start);
    while (cur <= end) {
      const ds = calYmd(cur);
      const inMonth = cur.getMonth() === cs.month;
      const isToday = ds === today;
      const dayEvents = byDate[ds] || [];
      const chips = dayEvents.slice(0, 3).map((e) => `
        <div class="cal-ev ${e.is_done ? "done" : ""} ${e.overdue ? "overdue" : ""}" style="border-left-color:${e.color}"
             title="${esc(e.type_label)}: ${esc(e.title)}" onclick="event.stopPropagation(); __ent.calEvent('${e.id}')">
          ${e.time ? `<b>${esc(e.time)}</b> ` : ""}${esc(e.title)}${e.attachment_count ? ` <span class="cal-ev-clip" title="${e.attachment_count} reference file${e.attachment_count === 1 ? "" : "s"}">📎</span>` : ""}
        </div>`).join("");
      const more = dayEvents.length > 3 ? `<div class="cal-more">+${dayEvents.length - 3} more</div>` : "";
      cells += `<div class="cal-cell ${inMonth ? "" : "muted"} ${isToday ? "today" : ""}" ${canEdit ? `onclick="__ent.calAdd('${ds}')"` : ""}>
        <div class="cal-daynum">${cur.getDate()}</div>${chips}${more}</div>`;
      cur.setDate(cur.getDate() + 1);
    }

    const legend = (state.calTypes || []).map((t) =>
      `<span class="cal-legend-item"><span class="cal-dot" style="background:${t.color}"></span>${esc(t.label)}</span>`).join("");

    const monthLabel = new Date(cs.year, cs.month, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" });
    // Quick month + year pickers for jumping anywhere fast.
    const CAL_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
    const calNowYear = new Date().getFullYear();
    const calMinYear = Math.min(calNowYear - 6, cs.year);
    const calMaxYear = Math.max(calNowYear + 6, cs.year);
    const calMonthOpts = CAL_MONTHS.map((m, i) => `<option value="${i}" ${i === cs.month ? "selected" : ""}>${m}</option>`).join("");
    let calYearOpts = "";
    for (let y = calMinYear; y <= calMaxYear; y++) calYearOpts += `<option value="${y}" ${y === cs.year ? "selected" : ""}>${y}</option>`;

    // "What's next" side panel
    const upItem = (e) => `
      <div class="cal-up-item ${e.overdue ? "overdue" : ""}" onclick="__ent.calEvent('${e.id}')">
        <span class="cal-dot" style="background:${e.color}"></span>
        <div class="cal-up-meta">
          <b>${esc(e.title)}</b>
          <span>${esc(e.type_label)}${e.client_name && e.source !== "client" ? " · " + esc(e.client_name) : ""}${e.attachment_count ? " · 📎 " + e.attachment_count : ""}</span>
        </div>
        <div class="cal-up-when ${e.overdue ? "overdue" : ""}">${esc(calRel(e.date, today))}${e.time ? " · " + esc(calClock(e.time)) : ""}</div>
      </div>`;
    const overdueBlock = (up.overdue || []).length
      ? `<div class="cal-up-label overdue">⚠ Overdue (${up.overdue.length})</div>${up.overdue.map(upItem).join("")}` : "";
    const upcomingBlock = (up.upcoming || []).length
      ? `<div class="cal-up-label">Next ${up.horizon_days} days</div>${up.upcoming.map(upItem).join("")}`
      : (!overdueBlock ? `<div class="cal-up-empty">Nothing coming up. You're all caught up. 🎉</div>` : "");

    c.innerHTML = `
      <div class="cal-wrap">
        <div class="cal-main">
          <div class="cal-toolbar">
            <div class="cal-period">
              <select class="cal-select cal-select-month" onchange="__ent.calSetMonth(this.value)" aria-label="Month">${calMonthOpts}</select>
              <select class="cal-select cal-select-year" onchange="__ent.calSetYear(this.value)" aria-label="Year">${calYearOpts}</select>
            </div>
            <div class="cal-navbtns">
              <button class="btn btn-ghost btn-sm" onclick="__ent.calPrev()" aria-label="Previous month">‹</button>
              <button class="btn btn-ghost btn-sm" onclick="__ent.calToday()">Today</button>
              <button class="btn btn-ghost btn-sm" onclick="__ent.calNext()" aria-label="Next month">›</button>
            </div>
            ${canEdit ? `<button class="btn btn-primary btn-sm" onclick="__ent.calAdd()">+ Add reminder</button>` : ""}
          </div>
          <div class="cal-grid">
            ${dows.map((d) => `<div class="cal-dow">${d}</div>`).join("")}
            ${cells}
          </div>
          <div class="cal-legend">${legend}${
            // The grid chips stay bare — a zone on every one of them is noise at that density.
            // Saying it once here is what makes those bare times unambiguous.
            calTzLabel ? `<span class="cal-legend-tz">All times ${esc(calTzLabel)}</span>` : ""}</div>
        </div>
        <aside class="cal-side">
          <h3>What's next</h3>
          <div class="cal-upcoming">${overdueBlock}${upcomingBlock}</div>
        </aside>
      </div>`;

    // Arrived here from the dashboard's "What's next" — open the event now that the page behind
    // it (and state.calTypes / state.calClients, which the modal needs) is fully loaded.
    if (calPendingOpen) { const pendingId = calPendingOpen; calPendingOpen = null; calEvent(pendingId); }
  }

  function calPrev() { const c = calState(); const d = new Date(c.year, c.month - 1, 1); state.cal = { year: d.getFullYear(), month: d.getMonth() }; renderCalendar(); }
  function calNext() { const c = calState(); const d = new Date(c.year, c.month + 1, 1); state.cal = { year: d.getFullYear(), month: d.getMonth() }; renderCalendar(); }
  function calToday() { const d = new Date(); state.cal = { year: d.getFullYear(), month: d.getMonth() }; renderCalendar(); }
  function calSetMonth(m) { const c = calState(); state.cal = { year: c.year, month: parseInt(m, 10) }; renderCalendar(); }
  function calSetYear(y) { const c = calState(); state.cal = { year: parseInt(y, 10), month: c.month }; renderCalendar(); }

  function calEvent(id) {
    const e = calEventsById[id];
    if (!e) return;
    if (e.source === "client" && e.client_id) { navigate("clients"); openClient(e.client_id); return; }
    calDetailModal(e);
  }

  // "Edit" on the detail card. Re-reads calEventsById rather than trusting a copy captured in
  // an onclick string, so the form always opens on the event as the page last loaded it.
  function calEditEvent(id) {
    const e = calEventsById[id];
    if (!e || !can("calendar.manage") || e.editable === false) return;
    calEditModal(e, null, true);
  }

  function calOpenClient(clientId) {
    closeModal(); navigate("clients"); openClient(clientId);
  }

  function calAdd(dateStr) {
    if (!can("calendar.manage")) return;
    calEditModal(null, dateStr);
  }

  // "14:30" (what the server stores) → whatever 2:30 PM looks like where the reader is, with
  // the org's zone appended. Only the 12h/24h PRESENTATION follows the reader's locale — the
  // digits are the org's wall clock either way, which is exactly why the zone has to be said.
  function calTimeLabel(t) {
    const m = /^(\d{1,2}):([0-5]\d)$/.exec(String(t || "").trim());
    if (!m) return "";
    const shown = new Date(2000, 0, 1, Number(m[1]), Number(m[2]))
      .toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    return calTzLabel ? `${shown} ${calTzLabel}` : shown;
  }
  function calFullDate(iso) {
    const d = iso ? calParse(iso) : null;
    if (!d || isNaN(d)) return "No date";
    return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  }

  /* Clicking an event answers "what is this?" before it offers "change it". Opening straight
     into the form made every glance look like an edit, hid the notes and the client link behind
     form controls, and parked Delete one stray click away from someone only checking a date. */
  function calDetailModal(ev) {
    const canManage = can("calendar.manage") && ev.editable !== false && !!ev.event_id;
    // ev.color is a server-side constant, but it lands in a style attribute — keep it to a hex.
    const color = /^#[0-9a-f]{3,8}$/i.test(String(ev.color || "")) ? ev.color : "#6366f1";
    const timeLabel = calTimeLabel(ev.time);
    const rel = ev.date ? calRel(ev.date, calTodayYmd || calYmd(new Date())) : "";
    const isOverdue = !!ev.overdue && !ev.is_done;
    const status = ev.is_done
      ? `<span class="cal-dv-chip done">✓ Done</span>`
      : isOverdue ? `<span class="cal-dv-chip overdue">⚠ Overdue</span>` : "";
    const atts = ev.attachments || [];

    const clientVal = ev.client_id
      ? `<b>${esc(ev.client_name || "Client")}</b> <button type="button" class="cal-dv-link" onclick="__ent.calOpenClient(${Number(ev.client_id)})">Open profile →</button>`
      : `<span class="cal-dv-empty">Not linked to a client</span>`;
    const notifyRow = ev.client_id
      ? `<div class="cal-dv-row"><div class="cal-dv-k">Email reminder</div><div class="cal-dv-v">${
          ev.notify_client
            ? `On — <b>${esc(ev.client_name || "the client")}</b> is emailed when this is due`
            : `<span class="cal-dv-empty">Off — nothing is sent to the client</span>`}</div></div>`
      : "";

    openModal(`<div class="modal-head"><h3>Event details</h3><button class="x" onclick="__ent.closeModal()" aria-label="Close">×</button></div>
      <div class="modal-body">
        <div class="cal-dv-hero">
          <div class="cal-dv-badges">
            <span class="cal-dv-type"><span class="cal-dot" style="background:${color}"></span>${esc(ev.type_label || "Reminder")}</span>
            ${status}
          </div>
          <h4 class="cal-dv-title ${ev.is_done ? "is-done" : ""}">${esc(ev.title || "Untitled")}</h4>
          <div class="cal-dv-when ${isOverdue ? "overdue" : ""}">
            <span class="cal-dv-when-ic">📅</span>
            <b>${esc(calFullDate(ev.date))}${timeLabel ? " · " + esc(timeLabel) : ""}</b>
            ${rel ? `<span class="cal-dv-rel">${esc(rel)}</span>` : ""}
            ${timeLabel ? "" : `<span class="cal-dv-allday">No time set</span>`}
          </div>
        </div>
        <div class="cal-dv-rows">
          <div class="cal-dv-row"><div class="cal-dv-k">Client</div><div class="cal-dv-v">${clientVal}</div></div>
          ${notifyRow}
          ${ev.created_by_name ? `<div class="cal-dv-row"><div class="cal-dv-k">Added by</div><div class="cal-dv-v">${esc(ev.created_by_name)}</div></div>` : ""}
        </div>
        <div class="cal-dv-sec">
          <div class="cal-dv-sec-h">Notes</div>
          ${ev.notes
            ? `<div class="cal-dv-notes">${esc(ev.notes)}</div>`
            : `<div class="cal-dv-empty">No notes on this event.</div>`}
        </div>
        ${atts.length ? `<div class="cal-dv-sec">
          <div class="cal-dv-sec-h">Reference files · ${atts.length}</div>
          <div class="cal-att-list">${atts.map((a) => `
            <div class="cal-att-chip">
              <span class="cal-att-ic">${docIcon(a.filename)}</span>
              <a class="cal-att-name" href="${esc(a.download_url)}" target="_blank" rel="noopener" title="${esc(a.filename)}">${esc(a.filename)}</a>
              <span class="cal-att-meta">${esc(fmtSize(a.file_size))}</span>
            </div>`).join("")}</div>
        </div>` : ""}
      </div>
      <div class="modal-foot">
        ${canManage ? `<button type="button" class="btn btn-danger btn-sm" onclick="__ent.calDelete(${ev.event_id},this)">Delete</button>
          <button type="button" class="btn btn-ghost btn-sm" onclick="__ent.calToggleDone(${ev.event_id}, ${ev.is_done ? "false" : "true"},this)">${ev.is_done ? "Mark not done" : "✓ Mark done"}</button>` : ""}
        <div class="spacer" style="flex:1"></div>
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Close</button>
        ${canManage ? `<button type="button" class="btn btn-primary" onclick="__ent.calEditEvent('${esc(ev.id)}')">Edit</button>` : ""}
      </div>`);
  }

  // Dashboard "What's next" → wherever the item actually lives. A client key date opens the
  // client; a manual event routes through the Calendar rather than opening its modal in place,
  // because that modal's save/done/delete handlers all call renderCalendar().
  function dashEvent(id) {
    const e = calEventsById[id];
    if (e && e.source === "client" && e.client_id) { navigate("clients"); openClient(e.client_id); return; }
    calPendingOpen = e ? id : null;
    navigate("calendar");
  }

  // `backToDetail` — the form was reached from the detail card, so Cancel returns there
  // instead of dropping the reader out of the event they were only half done reading.
  function calEditModal(ev, presetDate, backToDetail) {
    const types = state.calTypes || [{ key: "reminder", label: "Reminder" }];
    const isEdit = !!ev;
    // A viewer opening an event still sees (and can download) what's attached — the tray that
    // adds and removes files is what managing the calendar buys you.
    const calCanAttach = can("calendar.manage");
    const dateVal = (ev && ev.date) || presetDate || new Date().toISOString().slice(0, 10);
    openModal(`<div class="modal-head"><h3>${isEdit ? "Edit event" : "Add reminder"}</h3><button class="x" onclick="__ent.closeModal()">×</button></div>
      <form id="calForm"><div class="modal-body">
        <div class="field cal-title-field">
          <label>Title</label>
          <div class="cal-title-input-wrap">
            <input name="title" id="calTitleInput" autocomplete="off" required maxlength="200" value="${ev ? esc(ev.title) : ""}" placeholder="e.g. Call Rohan about SOP"/>
            <div id="calMentionMenu" class="cal-mention-menu hidden"></div>
          </div>
          <div class="cal-title-hint">Type <b>@</b> to mention a client</div>
        </div>
        <div class="cal-form-row">
          <div class="field"><label>Type</label><select name="event_type">${types.map((t) => `<option value="${t.key}" ${ev && ev.type === t.key ? "selected" : ""}>${esc(t.label)}</option>`).join("")}</select></div>
          <div class="field"><label>Date</label><input type="date" name="event_date" required value="${esc(dateVal)}"/></div>
          <div class="field"><label>Time (optional)</label><input type="time" name="event_time" value="${ev && ev.time ? esc(ev.time) : ""}"/></div>
        </div>
        <div class="field"><label>Notes (optional)</label><textarea name="notes" maxlength="2000" placeholder="Any details…">${ev && ev.notes ? esc(ev.notes) : ""}</textarea></div>
        <div id="calNotifyRow" class="cal-notify-row hidden">
          <label class="cal-check"><input type="checkbox" id="calNotifyChk"/><span id="calNotifyLabel"></span></label>
          <button type="button" class="cal-mention-clear" id="calMentionClear" title="Remove client link" aria-label="Remove client link">✕</button>
        </div>
        <div class="field cal-att-field" id="calAttField">
          <label>Reference files (optional)</label>
          ${calCanAttach ? `
          <input type="file" id="calAttFile" class="hidden" multiple accept="${CAL_ATT_EXT.join(",")}"/>
          <button type="button" class="cal-att-drop" id="calAttDrop">
            <span class="cal-att-drop-ic">📎</span>
            <span class="cal-att-drop-txt">
              <b>Attach a file</b>
              <span class="cal-att-drop-note" id="calAttNote"></span>
            </span>
          </button>` : ""}
          <div class="cal-att-list hidden" id="calAttList"></div>
        </div>
        <div id="calFormErr" class="auth-error hidden"></div>
      </div>
      <div class="modal-foot">
        ${isEdit ? `<button type="button" class="btn btn-danger btn-sm" onclick="__ent.calDelete(${ev.event_id},this)">Delete</button>
          <button type="button" class="btn btn-ghost btn-sm" onclick="__ent.calToggleDone(${ev.event_id}, ${ev.is_done ? "false" : "true"},this)">${ev.is_done ? "Mark not done" : "✓ Mark done"}</button>` : ""}
        <div class="spacer" style="flex:1"></div>
        <button type="button" class="btn btn-ghost" id="calCancelBtn">Cancel</button>
        <button type="submit" class="btn btn-primary" id="calSaveBtn" disabled>${isEdit ? "Save" : "Add"}</button>
      </div></form>`);

    // ---- @-mention: link a client + optionally notify them ----
    const titleInput = $("#calTitleInput");
    const menu = $("#calMentionMenu");
    const notifyRow = $("#calNotifyRow");
    const notifyChk = $("#calNotifyChk");
    const notifyLabel = $("#calNotifyLabel");
    let modalClient = null;            // {id, name, has_email}
    let mMatches = [], mIdx = 0, mStart = -1, mQuery = "";

    function showNotifyRow(checked) {
      if (!modalClient) { notifyRow.classList.add("hidden"); return; }
      notifyRow.classList.remove("hidden");
      if (modalClient.has_email) {
        notifyLabel.innerHTML = `Notify <b>@${esc(modalClient.name)}</b> by email when this reminder is due`;
        notifyChk.disabled = false;
        notifyChk.checked = checked;
      } else {
        notifyLabel.innerHTML = `<b>@${esc(modalClient.name)}</b> has no email on file — add one on their profile to notify them`;
        notifyChk.disabled = true;
        notifyChk.checked = false;
      }
    }
    function closeMenu() { menu.classList.add("hidden"); mMatches = []; }
    function renderMenu() {
      const all = state.calClients || [];
      const ql = mQuery.toLowerCase();
      mMatches = all.filter((c) => (c.name || "").toLowerCase().includes(ql)).slice(0, 8);
      if (mIdx >= mMatches.length) mIdx = 0;
      if (!mMatches.length) {
        menu.innerHTML = `<div class="cal-mention-empty">${all.length ? "No matching clients" : "No clients yet — add clients first"}</div>`;
        menu.classList.remove("hidden"); return;
      }
      menu.innerHTML = mMatches.map((c, i) => `
        <div class="cal-mention-item ${i === mIdx ? "active" : ""}" data-i="${i}">
          <span class="cal-mention-avatar">${esc((c.name || "?").trim().charAt(0).toUpperCase())}</span>
          <span class="cal-mention-name">${esc(c.name)}</span>
          ${c.has_email ? "" : `<span class="cal-mention-noemail">no email</span>`}
        </div>`).join("");
      menu.classList.remove("hidden");
      $$(".cal-mention-item", menu).forEach((el) => {
        el.onmousedown = (e) => { e.preventDefault(); pickClient(mMatches[parseInt(el.dataset.i, 10)]); };
      });
    }
    function pickClient(c) {
      if (!c) return;
      const val = titleInput.value;
      const after = val.slice(titleInput.selectionStart);
      titleInput.value = (val.slice(0, mStart) + "@" + c.name + " " + after).slice(0, 200);
      modalClient = { id: c.id, name: c.name, has_email: !!c.has_email };
      closeMenu();
      showNotifyRow(true);
      titleInput.focus();
    }
    titleInput.addEventListener("input", () => {
      const pos = titleInput.selectionStart;
      const upto = titleInput.value.slice(0, pos);
      const at = upto.lastIndexOf("@");
      if (at >= 0 && (at === 0 || /\s/.test(upto[at - 1]))) {
        const q = upto.slice(at + 1);
        if (!/\s/.test(q)) { mStart = at; mQuery = q; mIdx = 0; renderMenu(); return; }
      }
      closeMenu();
    });
    titleInput.addEventListener("keydown", (e) => {
      if (menu.classList.contains("hidden") || !mMatches.length) return;
      if (e.key === "ArrowDown") { e.preventDefault(); mIdx = (mIdx + 1) % mMatches.length; renderMenu(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); mIdx = (mIdx - 1 + mMatches.length) % mMatches.length; renderMenu(); }
      else if (e.key === "Enter") { e.preventDefault(); pickClient(mMatches[mIdx]); }
      else if (e.key === "Escape") { closeMenu(); }
    });
    titleInput.addEventListener("blur", () => setTimeout(closeMenu, 150));
    $("#calMentionClear").onclick = () => { modalClient = null; notifyRow.classList.add("hidden"); };

    // ---- reference files ----
    // Uploads fire immediately, never on submit: the body below is JSON, so a file input
    // inside this form would be silently dropped. An event that already exists takes the file
    // straight away; a reminder still being written parks it under this modal's draft token,
    // which the create call then binds.
    const calAttToken = isEdit
      ? null
      : "cd" + Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
    const calAtts = (isEdit && ev.attachments ? ev.attachments : []).map((a, i) => ({
      uid: "a" + i, id: a.id, name: a.filename, size: a.file_size || 0,
      url: a.download_url, status: "done", pct: 100, xhr: null,
    }));
    let calAttSeq = calAtts.length;
    // Assigned once the form is mounted, below; calDrawAtts runs before that on the first
    // paint, hence the no-op default rather than a bare declaration.
    let calSyncSave = () => {};

    function calAttUsed() { return calAtts.reduce((sum, a) => sum + (a.size || 0), 0); }

    function calDrawAtts() {
      const host = $("#calAttList");
      if (!host) return;
      host.innerHTML = calAtts.map((a) => {
        const cls = a.status === "error" ? " is-error" : a.status === "uploading" ? " is-uploading" : "";
        const meta = a.status === "uploading" ? (a.pct || 0) + "%"
          : a.status === "error" ? "Couldn't upload" : fmtSize(a.size);
        const name = a.url
          ? `<a class="cal-att-name" href="${esc(a.url)}" target="_blank" rel="noopener" title="${esc(a.name)}">${esc(a.name)}</a>`
          : `<span class="cal-att-name" title="${esc(a.name)}">${esc(a.name)}</span>`;
        return `<div class="cal-att-chip${cls}">
            <span class="cal-att-ic">${a.status === "error" ? "⚠️" : docIcon(a.name)}</span>${name}
            <span class="cal-att-meta">${esc(meta)}</span>
            ${calCanAttach ? `<button type="button" class="cal-att-x" data-uid="${esc(a.uid)}" aria-label="Remove ${esc(a.name)}">✕</button>` : ""}
            ${a.status === "uploading" ? `<span class="cal-att-bar" style="width:${a.pct || 0}%"></span>` : ""}
          </div>`;
      }).join("");
      host.classList.toggle("hidden", !calAtts.length);
      $$(".cal-att-x", host).forEach((b) => { b.onclick = () => calRemoveAtt(b.dataset.uid); });
      const note = $("#calAttNote");
      if (note) {
        note.textContent = calAtts.length
          ? `${calAtts.length} of ${CAL_ATT_MAX_FILES} · ${fmtSize(calAttUsed())}`
          : `Agenda, appointment letter, checklist — up to ${CAL_ATT_MAX_FILES} files`;
      }
      const drop = $("#calAttDrop");
      if (drop) drop.disabled = calAtts.length >= CAL_ATT_MAX_FILES;
      // Runs on every upload start, progress tick, finish, failure and removal — which is
      // exactly when Save's "no attachment still uploading" term changes.
      calSyncSave();
    }

    async function calRemoveAtt(uid) {
      const index = calAtts.findIndex((a) => a.uid === uid);
      if (index < 0) return;
      const entry = calAtts[index];
      // No confirmModal here: it reuses #modal, which would destroy this open form.
      if (entry.xhr && entry.status === "uploading") { try { entry.xhr.abort(); } catch (e) {} }
      calAtts.splice(index, 1);
      calDrawAtts();
      if (entry.id) {
        try { await api(`/calendar/attachments/${entry.id}`, { method: "DELETE" }); }
        catch (ex) { toast(ex.message, "error"); }
      }
    }

    function calUploadAtt(file) {
      const entry = {
        uid: "u" + (++calAttSeq), name: file.name || "file", size: file.size || 0,
        status: "uploading", pct: 0, id: null, url: null, xhr: null,
      };
      calAtts.push(entry);
      calDrawAtts();

      const form = new FormData();
      form.append("file", file);
      // ev.event_id is the numeric row id — ev.id is the prefixed "manual-42" grid key.
      if (isEdit) form.append("event_id", String(ev.event_id));
      else form.append("draft_token", calAttToken);

      const xhr = new XMLHttpRequest();
      entry.xhr = xhr;
      xhr.open("POST", API + "/calendar/attachments");
      xhr.withCredentials = true;
      xhr.upload.onprogress = (e) => {
        if (!e.lengthComputable) return;
        entry.pct = Math.min(99, Math.round((e.loaded / e.total) * 100));
        calDrawAtts();
      };
      xhr.onload = () => {
        let out = null;
        try { out = JSON.parse(xhr.responseText); } catch (e) {}
        if (xhr.status >= 200 && xhr.status < 300 && out && out.attachment) {
          entry.status = "done";
          entry.pct = 100;
          entry.id = out.attachment.id;
          entry.url = out.attachment.download_url;
          entry.size = out.attachment.file_size || entry.size;
        } else {
          entry.status = "error";
          const detail = out && typeof out.detail === "string" && out.detail.length < 300 ? out.detail : "";
          toast(detail || `Couldn't attach ${entry.name}`, "error");
        }
        entry.xhr = null;
        calDrawAtts();
      };
      xhr.onerror = () => {
        entry.status = "error"; entry.xhr = null; calDrawAtts();
        toast("Upload failed — check your connection and try again", "error");
      };
      // Without this a stalled connection leaves the chip spinning and Save blocked forever.
      xhr.timeout = 180000;
      xhr.ontimeout = () => {
        entry.status = "error"; entry.xhr = null; calDrawAtts();
        toast(`${entry.name} took too long to upload — remove it and try again`, "error");
      };
      xhr.send(form);
    }

    function calAddAttFiles(fileList) {
      const files = Array.prototype.slice.call(fileList || []);
      if (!files.length) return;
      const room = CAL_ATT_MAX_FILES - calAtts.length;
      if (room <= 0) { toast(`An event can hold ${CAL_ATT_MAX_FILES} reference files`, "error"); return; }
      const accepted = [];
      let running = calAttUsed();
      let badType = 0, tooBig = 0, noRoom = 0;
      files.forEach((f) => {
        const dot = (f.name || "").lastIndexOf(".");
        const ext = dot >= 0 ? (f.name || "").slice(dot).toLowerCase() : "";
        if (!CAL_ATT_EXT.includes(ext)) { badType++; return; }
        if ((f.size || 0) > CAL_ATT_MAX_BYTES) { tooBig++; return; }
        // Don't upload what the server is going to refuse anyway.
        if (accepted.length >= room || running + (f.size || 0) > CAL_ATT_MAX_TOTAL_BYTES) { noRoom++; return; }
        running += f.size || 0;
        accepted.push(f);
      });
      accepted.forEach(calUploadAtt);
      if (badType) toast("Attach a PDF, image, Word/Excel file, CSV or text file", "error");
      else if (tooBig) toast(`Each file can be up to ${fmtSize(CAL_ATT_MAX_BYTES)}`, "error");
      else if (noRoom) toast(`Reference files for one event can total ${fmtSize(CAL_ATT_MAX_TOTAL_BYTES)}`, "error");
    }

    if (calCanAttach) {
      $("#calAttDrop").onclick = () => $("#calAttFile").click();
      $("#calAttFile").onchange = () => { calAddAttFiles($("#calAttFile").files); $("#calAttFile").value = ""; };
      // Drag & drop onto the whole field, depth-counted so moving over a child doesn't flicker.
      const attField = $("#calAttField");
      let dragDepth = 0;
      attField.addEventListener("dragenter", (e) => {
        if (!(e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], "Files") >= 0)) return;
        e.preventDefault(); dragDepth++; attField.classList.add("is-dragging");
      });
      attField.addEventListener("dragover", (e) => { e.preventDefault(); });
      attField.addEventListener("dragleave", () => {
        dragDepth = Math.max(0, dragDepth - 1);
        if (!dragDepth) attField.classList.remove("is-dragging");
      });
      attField.addEventListener("drop", (e) => {
        e.preventDefault(); dragDepth = 0; attField.classList.remove("is-dragging");
        calAddAttFiles(e.dataTransfer && e.dataTransfer.files);
      });
    }
    // Title and date are the two genuinely required fields — the submit handler used to just
    // silently return without them. The third term is the attachment state: saving mid-upload
    // would create the event before its files exist to bind, which the handler caught with an
    // error message after the click. calDrawAtts() calls this on every upload tick, so the
    // button follows the upload rather than waiting for the user to try.
    calSyncSave = bindValidity($("#calSaveBtn"), $("#calForm"), () => {
      const t = $("#calTitleInput"), d = $("#calForm").querySelector("[name=event_date]");
      if (!t || !d || !t.value.trim() || !d.value) return false;
      return !calAtts.some((a) => a.status === "uploading");
    }, "Add a title and a date first");
    calDrawAtts();

    // Cancelling a brand-new reminder throws its uploads away now rather than leaving them
    // for the 24h sweep. Only a courtesy — Escape and the overlay close with no hook at all.
    $("#calCancelBtn").onclick = () => {
      if (!isEdit && calAtts.some((a) => a.id)) {
        api(`/calendar/attachments/drafts/${encodeURIComponent(calAttToken)}`, { method: "DELETE" }).catch(() => {});
      }
      // Files upload and unattach the moment they're picked or removed — Cancel can't put them
      // back. Hand the detail card what is actually on the event now, not the list it opened with.
      if (isEdit && backToDetail) {
        ev.attachments = calAtts
          .filter((a) => a.id && a.status === "done")
          .map((a) => ({ id: a.id, filename: a.name, file_size: a.size, download_url: a.url }));
        ev.attachment_count = ev.attachments.length;
        calDetailModal(ev);
        return;
      }
      closeModal();
    };

    // Pre-fill when editing an event that's already linked to a client.
    if (ev && ev.client_id) {
      const known = (state.calClients || []).find((x) => x.id === ev.client_id);
      modalClient = {
        id: ev.client_id,
        name: ev.client_name || (known && known.name) || "Client",
        has_email: known ? known.has_email : true,
      };
      showNotifyRow(!!ev.notify_client);
    }

    $("#calForm").onsubmit = async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const body = {
        title: (fd.get("title") || "").trim(),
        event_type: fd.get("event_type") || "reminder",
        event_date: fd.get("event_date"),
        event_time: fd.get("event_time") || null,
        notes: (fd.get("notes") || "").trim() || null,
      };
      if (modalClient) {
        body.client_id = modalClient.id;
        body.notify_client = !!(notifyChk.checked && !notifyChk.disabled);
      } else if (isEdit && ev && ev.client_id) {
        body.client_id = 0;          // unlink a previously linked client
        body.notify_client = false;
      }
      if (!body.title || !body.event_date) return;
      // Saving mid-upload would create the event before its files exist to bind.
      if (calAtts.some((a) => a.status === "uploading")) {
        const er = $("#calFormErr");
        er.textContent = "Hold on — a file is still uploading.";
        er.classList.remove("hidden");
        return;
      }
      if (!isEdit && calAtts.some((a) => a.id)) body.attachment_draft_token = calAttToken;
      const btn = $("#calSaveBtn"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
      try {
        if (isEdit) await api(`/calendar/events/${ev.event_id}`, { method: "PATCH", body });
        else await api("/calendar/events", { method: "POST", body });
        closeModal(); toast(isEdit ? "Event updated" : "Reminder added", "success"); renderCalendar();
      } catch (ex) {
        const er = $("#calFormErr"); er.textContent = ex.message; er.classList.remove("hidden");
        btn.disabled = false; btn.textContent = isEdit ? "Save" : "Add";
      }
    };
  }

  // `el` is the button itself (passed as `this` from the inline onclick). Both the detail
  // modal and the edit form render one of these and both land here, so locking the node
  // covers both without either knowing about the other.
  async function calToggleDone(eventId, done, el) {
    await withBusy(el, "", async () => {
      try { await api(`/calendar/events/${eventId}`, { method: "PATCH", body: { is_done: done } }); closeModal(); toast(done ? "Marked done" : "Reopened", "success"); renderCalendar(); }
      catch (ex) { toast(ex.message, "error"); }
    });
  }
  async function calDelete(eventId, el) {
    if (el && el.disabled) return;
    if (!(await confirmModal("This reminder will be permanently deleted.", { title: "Delete event?", okText: "Delete" }))) return;
    await withBusy(el, "", async () => {
      try { await api(`/calendar/events/${eventId}`, { method: "DELETE" }); closeModal(); toast("Event deleted", "success"); renderCalendar(); }
      catch (ex) { toast(ex.message, "error"); }
    });
  }

  /* ============================================================
     HELP & SUPPORT + feature requests
     One composer with two modes (help / feature idea) instead of two competing
     forms, quick answers in the rail beside it (matched live against what is
     being typed, so the easy questions never become a ticket), and this org's
     history underneath. Drafts survive a view switch; attachments are picked,
     pasted or dropped and ride along with the POST — nothing is stored.
     ============================================================ */
  // Mirrors ENTERPRISE_DOC_ALLOWED_EXT server-side — the picker only offers what the
  // endpoint will actually accept, so a screenshot never bounces after the upload.
  const SUP_ALLOWED_EXT = [
    ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic",
    ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt",
  ];
  const SUP_ACCEPT = SUP_ALLOWED_EXT.join(",");
  const SUP_THUMB_EXT = [".jpg", ".jpeg", ".png", ".webp", ".gif"];
  const SUP_IC = {
    clip: '<svg viewBox="0 0 20 20" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M14.5 9.2 9.3 14.4a3.3 3.3 0 0 1-4.7-4.7l5.6-5.6a2.2 2.2 0 0 1 3.1 3.1l-5.5 5.6a1.1 1.1 0 0 1-1.6-1.6l5-5"/></svg>',
    mail: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m2 7 10 6 10-6"/></svg>',
    copy: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
    chev: '<svg class="chev" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 5 7 7-7 7"/></svg>',
    arw: '<svg class="arw" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h13M13 6l6 6-6 6"/></svg>',
    bulb: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9.5 18h5"/><path d="M10.5 21.5h3"/><path d="M12 2.5a6.5 6.5 0 0 0-3.8 11.8V16h7.6v-1.7A6.5 6.5 0 0 0 12 2.5z"/></svg>',
    check: '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="m5 13 4.5 4.5L19 7"/></svg>',
    inbox: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M22 12h-5.5l-1.5 2.5h-6L7.5 12H2"/><path d="M5.6 5.2 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.6-6.8A2 2 0 0 0 16.6 4H7.4a2 2 0 0 0-1.8 1.2z"/></svg>',
  };

  /* Quick answers. Static, trusted markup (never interpolate user values into `a`).
     `keys` drive both the rail accordion and the live suggestions under the subject —
     the cheapest ticket is the one the answer above the form already resolved. */
  const SUP_KB = [
    {
      id: "credits",
      q: "How do Rilono Credits work?",
      a: "Every AI action — Deep Scan, Writing Studio drafts, mock-interview links, Course Finder shortlists — spends credits from your organization's shared wallet. Your plan puts credits in that wallet every month (1,000 on Starter, 3,500 on Growth, 10,000 on Scale), and any admin can top up for more. <b>Credits</b> shows the balance, what's left of this month's allowance, what each action costs and where the credits went. Unused plan credits don't carry into the next month; purchased top-ups never expire.",
      view: "credits", cta: "Open Credits",
      keys: ["credit", "credits", "wallet", "balance", "top up", "topup", "recharge", "pricing", "cost", "ran out", "insufficient", "included", "allowance", "monthly"],
    },
    {
      id: "clients",
      q: "Adding and updating a client",
      a: "<b>+ Add Client</b> at the top right opens the intake form — contact details, destination, intake, budget and the rest. Every field stays editable afterwards from the client's profile, and a case moves through the pipeline from the stage picker in its dossier.",
      view: "clients", cta: "Open Clients",
      keys: ["client", "add client", "intake", "profile", "pipeline", "stage", "lead", "student", "applicant", "dossier"],
    },
    {
      id: "portal",
      q: "Can a student see their own case?",
      a: "Yes — open the client and use <b>Share portal</b>. They get a secure link at their email address, confirm a one-time code, then see a view-only copy of the case: stages, recorded details, documents, universities and payments. Internal notes are never shown.",
      view: "clients", cta: "Open Clients",
      keys: ["portal", "share", "view only", "view-only", "one-time", "otp", "student login", "client access", "tracking link"],
    },
    {
      id: "team",
      q: "Inviting your team",
      a: "<b>Team → + Invite member</b> emails an invitation to a colleague. Their role decides who can manage billing, credits and organization settings — everyone else works the pipeline as normal.",
      view: "team", cta: "Open Team",
      keys: ["team", "invite", "member", "colleague", "staff", "role", "permission", "access", "seat", "admin", "counsellor", "counselor"],
    },
    {
      id: "payments",
      q: "Collecting payments from students",
      a: "<b>Finance</b> links your bank account once. After that, each client's <b>Payments</b> tab raises a secure pay link that goes straight to the student, funds settle into your own account, and refunds are issued from the same tab.",
      view: "finance", cta: "Open Finance",
      keys: ["payment", "pay link", "invoice", "fee", "refund", "razorpay", "bank", "settlement", "finance", "collect", "charge", "payout"],
    },
    {
      id: "privacy",
      q: "Documents and data privacy",
      a: "Client documents are stored encrypted and are reachable only by members of your organization. We don't open a client's files to investigate a problem without asking you first — a screenshot of what you're seeing is almost always enough.",
      keys: ["document", "upload", "file", "privacy", "security", "encrypt", "confidential", "gdpr", "data", "delete", "passport"],
    },
    {
      id: "docscan",
      q: "Scanning and validating a document",
      a: "<b>Uploading a document is always free.</b> Ticking <b>Scan &amp; validate with Rilono AI</b> on the upload card is the paid part: Rilono AI reads that one document, checks it is the right type, genuine and still in date, then cross-checks it against the client's profile and their <i>already-validated</i> documents — so a document that was flagged can never quietly become the yardstick for the next one. A passed identity document also auto-fills empty profile fields; anything that differs is flagged for you, never overwritten. You can also scan any stored document later from its card, or re-scan one once more of the dossier has been validated. A scan that fails to return a verdict isn't charged. Documents a student sends through a secure request link are stored unscanned — scan them yourself when you're ready.",
      view: "credits", cta: "See what it costs",
      keys: ["scan", "validate", "validation", "document", "credit", "cost", "charge", "verify", "check", "passport", "fake", "expired", "auto-fill", "autofill", "re-scan"],
    },
    {
      id: "stuck",
      q: "A page is stuck, blank or looks wrong",
      a: "A hard refresh clears a stale copy of the console and fixes most of these. If it survives the refresh, send it below with a screenshot and leave <b>include technical details</b> ticked — it tells us your browser and the exact page, which is usually what pins the bug down.",
      keys: ["stuck", "broken", "error", "bug", "not working", "spinner", "loading", "blank", "crash", "freeze", "fails", "failed", "nothing happens"],
    },
    {
      id: "reply",
      q: "What happens after you send this?",
      a: "Your message reaches the Rilono team with your name and organization already attached, and the reply comes straight back to your email address — usually within one business day. Everything you send is listed under <b>Your requests</b> with its status.",
      keys: ["reply", "response", "how long", "when will", "status", "ticket", "follow up", "chase", "heard back", "waiting"],
    },
  ];

  const supIsMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
  // Thumbnails for picked screenshots; revoked when the chip goes or the view re-renders.
  let supUrls = [];
  function supFreeUrls() {
    supUrls.forEach((u) => { try { URL.revokeObjectURL(u); } catch (e) { /* already revoked */ } });
    supUrls = [];
  }
  function supDraftKey(kind) {
    const org = (state.me && state.me.organization && state.me.organization.id) || "0";
    return "rilono.ent.support.draft." + org + "." + kind;
  }
  function supLoadDraft(kind) {
    try {
      const raw = localStorage.getItem(supDraftKey(kind));
      const d = raw ? JSON.parse(raw) : null;
      if (d && (d.subject || d.message)) return { subject: String(d.subject || ""), message: String(d.message || ""), restored: true };
    } catch (e) { /* private mode / corrupt value — start clean */ }
    return { subject: "", message: "", restored: false };
  }
  function supSaveDraft(kind, subject, message) {
    try {
      if (!subject && !message) localStorage.removeItem(supDraftKey(kind));
      else localStorage.setItem(supDraftKey(kind), JSON.stringify({ subject: subject, message: message }));
    } catch (e) { /* storage full or blocked — the draft is a nicety, not a contract */ }
  }
  function supAgo(iso) {
    const t = new Date(iso).getTime();
    if (!t || isNaN(t)) return "";
    const s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 90) return "just now";
    if (s < 3600) return Math.floor(s / 60) + " min ago";
    if (s < 86400) { const h = Math.floor(s / 3600); return h + (h === 1 ? " hour ago" : " hours ago"); }
    if (s < 604800) { const d = Math.floor(s / 86400); return d + (d === 1 ? " day ago" : " days ago"); }
    return fmtDate(iso);
  }
  function supStatus(raw) {
    const s = String(raw || "").toLowerCase().trim();
    if (s === "closed" || s === "resolved" || s === "done") return { cls: "done", label: "Resolved" };
    if (s === "in_progress" || s === "in progress" || s === "triaged") return { cls: "prog", label: "In progress" };
    if (!s || s === "open" || s === "new") return { cls: "open", label: "Received" };
    return { cls: "gray", label: s.replace(/_/g, " ") };
  }
  /* One line of context appended to a help request when the requester leaves the box
     ticked. Browser, OS, viewport and the page they were on — nothing about clients. */
  function supTechLine() {
    const ua = navigator.userAgent || "";
    const m = /(Edg|OPR|Chrome|Firefox|Version)\/([\d.]+)/.exec(ua);
    const names = { Edg: "Edge", OPR: "Opera", Version: "Safari" };
    const browser = m ? ((names[m[1]] || m[1]) + " " + String(m[2]).split(".")[0]) : "unknown browser";
    const os = /Mac/.test(ua) ? "macOS" : /Windows/.test(ua) ? "Windows" : /Android/.test(ua) ? "Android"
      : /iPhone|iPad/.test(ua) ? "iOS" : /Linux/.test(ua) ? "Linux" : "unknown OS";
    return browser + " · " + os + " · " + window.innerWidth + "×" + window.innerHeight + " · " + location.pathname;
  }
  /* Score the KB against what has been typed so far. Long keys score higher and a single
     short hit isn't enough (threshold 3), which keeps stray words from suggesting nonsense. */
  function supMatch(text) {
    const t = " " + String(text || "").toLowerCase().replace(/[^a-z0-9']+/g, " ").trim() + " ";
    if (t.trim().length < 4) return [];
    return SUP_KB
      .map((k) => {
        let score = 0;
        k.keys.forEach((w) => {
          const needle = w.toLowerCase();
          if (t.indexOf(" " + needle + " ") >= 0) score += needle.length >= 6 ? 4 : 3;
          else if (needle.length >= 5 && t.indexOf(needle) >= 0) score += 2;
        });
        return { k: k, score: score };
      })
      .filter((x) => x.score >= 3)
      .sort((a, b) => b.score - a.score)
      .slice(0, 2)
      .map((x) => x.k);
  }

  async function renderSupport() {
    const c = $("#content");
    supFreeUrls();
    c.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
    let d;
    try { d = await api("/support"); } catch (ex) { c.innerHTML = errBox(ex); return; }
    // Guard the async gap: never paint over a view the user has already moved on to.
    if (state.view !== "support") return;

    const supportEmail = d.support_email || "contact@rilono.com";
    const maxFiles = Number(d.attach_max_files) || 5;
    const maxBytes = Number(d.attach_max_total_bytes) || 10 * 1024 * 1024;
    const meUser = (state.me && state.me.user) || {};
    const org = (state.me && state.me.organization) || {};
    const myEmail = meUser.email || "";

    let kind = "support";
    // Switching the support/feature tab re-mounts the whole composer, which would hand back
    // a brand-new, enabled submit button while the previous send is still uploading its
    // files. So the lock lives in the closure, and the markup reads it on every mount.
    let supSending = false;
    const trays = { support: [], feature_request: [] };
    const drafts = { support: supLoadDraft("support"), feature_request: supLoadDraft("feature_request") };
    let traySeq = 0;
    let draftTimer = null, suggestTimer = null;

    /* ---------------- markup ---------------- */
    const kbHtml = () => SUP_KB.map((k) => `
      <div class="sup-kb-item" data-kb="${k.id}">
        <button type="button" class="sup-kb-q" aria-expanded="false">${esc(k.q)}${SUP_IC.chev}</button>
        <div class="sup-kb-a hidden">${k.a}${k.view ? `<button type="button" class="btn btn-soft btn-sm sup-kb-cta" data-goto="${k.view}">${esc(k.cta)} →</button>` : ""}</div>
      </div>`).join("");

    const histRow = (r) => {
      const isF = r.request_type === "feature_request";
      const st = supStatus(r.status);
      const atts = r.attachments || [];
      const files = atts.length
        ? `<div class="sup-hist-files">${atts.map((a) => `<span class="sup-hist-file">${docIcon(a.filename)} ${esc(a.filename)}${a.size ? " · " + fmtSize(a.size) : ""}</span>`).join("")}</div>`
        : "";
      return `
      <div class="sup-hist-item">
        <button type="button" class="sup-hist-row" aria-expanded="false" aria-label="${esc(r.subject)} — ${esc(st.label)}, ${esc(supAgo(r.created_at))}. Show the message you sent">
          <span class="sup-hist-ic ${isF ? "feature" : "help"}">${isF ? "💡" : "🛟"}</span>
          <span class="sup-hist-main">
            <b>${esc(r.subject)}</b>
            <span class="sup-hist-sub" title="${esc(fmtDateTime(r.created_at))}">${esc(isF ? "Feature idea" : "Help request")} · ${esc(supAgo(r.created_at))}${atts.length ? " · 📎 " + atts.length : ""}</span>
          </span>
          <span class="sup-pill ${st.cls}">${esc(st.label)}</span>
          ${SUP_IC.chev}
        </button>
        <div class="sup-hist-body hidden">${esc(r.message || "")}${files}</div>
      </div>`;
    };
    const historyHtml = (reqs) => `
      <div class="card-head"><h3>Your requests</h3>${reqs.length ? `<span class="sup-hcount">${reqs.length} most recent</span>` : ""}</div>
      <div class="sup-hist">${reqs.length ? reqs.map(histRow).join("") : `
        <div class="sup-empty">
          <div class="sup-empty-ic">${SUP_IC.inbox}</div>
          <b>Nothing sent yet</b>
          <span>Messages from anyone on your team show up here with their status.</span>
        </div>`}</div>`;

    const composerHtml = () => {
      const isF = kind === "feature_request";
      return `
      <div class="sup-tabs" role="tablist" aria-label="What would you like to send?">
        <button type="button" class="sup-tab" role="tab" data-kind="support" aria-selected="${!isF}"><span class="ic">🛟</span> Get help</button>
        <button type="button" class="sup-tab" role="tab" data-kind="feature_request" aria-selected="${isF}"><span class="ic">💡</span> Feature idea</button>
      </div>
      <div class="sup-body" role="tabpanel">
        <p class="sup-lead">${isF
          ? "Have an idea that would make Rilono better for your team? We read every one — and we ship a lot of them."
          : "Something not behaving? The steps you took and a screenshot get it fixed fastest."}</p>
        <form class="sup-form" id="supForm" novalidate>
          <div class="sup-field">
            <div class="sup-flabel">
              <label for="supSubject">${isF ? "What would you like to see?" : "Subject"}</label>
              <span class="sup-count" id="supSubjCount"></span>
            </div>
            <input id="supSubject" maxlength="160" autocomplete="off"
              placeholder="${isF ? "e.g. Bulk import clients from a CSV" : "e.g. A client document won't upload"}"/>
            <div class="sup-err hidden" id="supSubjErr"></div>
          </div>
          <div class="sup-sugg hidden" id="supSugg"></div>
          <div class="sup-field">
            <div class="sup-flabel">
              <label for="supMessage">${isF ? "Tell us more" : "What happened?"}</label>
              <span class="sup-count" id="supMsgCount"></span>
            </div>
            <textarea id="supMessage" maxlength="4000"
              placeholder="${isF ? "How would your team use it, and what does it save them doing by hand?" : "What you were doing, what you expected, and what happened instead. You can paste a screenshot straight into this box."}"></textarea>
            <div class="sup-err hidden" id="supMsgErr"></div>
          </div>
          <input type="file" id="supFile" class="hidden" multiple accept="${SUP_ACCEPT}"/>
          <button type="button" class="sup-drop" id="supDrop" aria-label="${isF ? "Attach a mockup or file" : "Attach a screenshot or file"} — optional, up to ${maxFiles} files">
            <span class="sup-drop-ic">${SUP_IC.clip}</span>
            <span class="sup-drop-txt">
              <b>${isF ? "Attach a mockup or file" : "Attach a screenshot or file"}</b>
              <span class="sup-drop-note" id="supDropNote"></span>
            </span>
          </button>
          <div class="sup-atts hidden" id="supAtts"></div>
          ${isF ? "" : `<label class="sup-tech">
            <input type="checkbox" id="supTech" checked/>
            <span>Include technical details</span>
            ${infoTip("Adds one line to your message: your browser and version, operating system, window size and the page you are on. Nothing about your clients.", "What gets included")}
          </label>`}
          <div class="sup-alert hidden" id="supErr" role="alert"></div>
          <div class="sup-foot">
            <span class="sup-draft" id="supDraft"></span>
            <span class="sup-foot-note"><span class="sup-kbd">${supIsMac ? "⌘" : "Ctrl"}</span><span class="sup-kbd">↵</span> to send</span>
            <button type="submit" class="btn btn-primary sup-send${isF ? " feature" : ""}" ${supSending ? "disabled" : ""}>${supSending ? '<span class="spinner"></span> Sending…' : (isF ? "Send feature idea" : "Send to support")}</button>
          </div>
        </form>
      </div>`;
    };

    c.innerHTML = `
      <div class="card sup-hero">
        <div>
          <h2>How can we help?</h2>
          <p>Tell us what's going on and we'll reply${myEmail ? ` to <b>${esc(myEmail)}</b>` : ""} — usually within one business day.</p>
        </div>
        <div class="sup-hero-side">
          <a class="sup-mail" href="mailto:${esc(supportEmail)}">${SUP_IC.mail}${esc(supportEmail)}</a>
          <button type="button" class="sup-copy" id="supCopy" title="Copy email address" aria-label="Copy support email address">${SUP_IC.copy}</button>
        </div>
      </div>
      <div class="sup-layout">
        <div class="sup-main">
          <div class="card sup-card" id="supCard">${composerHtml()}</div>
          <div class="card" id="supHistory">${historyHtml(d.requests || [])}</div>
        </div>
        <aside class="sup-rail">
          <div class="card sup-kb">
            <div class="sup-kb-head">${SUP_IC.bulb} Quick answers</div>
            ${kbHtml()}
          </div>
          <div class="card sup-side">
            <div class="sup-side-head">Writing as</div>
            <div class="sup-side-row"><span>You</span><b>${esc(meUser.full_name || myEmail || "—")}</b></div>
            ${myEmail && meUser.full_name ? `<div class="sup-side-row"><span>Email</span><b>${esc(myEmail)}</b></div>` : ""}
            <div class="sup-side-row"><span>Organization</span><b>${esc(org.company_name || org.name || "—")}</b></div>
            <p class="sup-side-note">These travel with every message, so you never have to repeat them — and the reply comes back to that address.</p>
          </div>
        </aside>
      </div>`;

    /* ---------------- attachments ---------------- */
    function freeChip(a) {
      if (!a.url) return;
      const i = supUrls.indexOf(a.url);
      if (i >= 0) supUrls.splice(i, 1);
      try { URL.revokeObjectURL(a.url); } catch (e) { /* already revoked */ }
      a.url = "";
    }
    function drawTray() {
      const tray = trays[kind];
      const host = $("#supAtts");
      const note = $("#supDropNote");
      if (!host) return;
      host.innerHTML = tray.map((a) => `
        <div class="sup-chip">
          ${a.url ? `<img class="sup-chip-th" src="${a.url}" alt=""/>` : `<span class="sup-chip-ic">${docIcon(a.file.name)}</span>`}
          <span class="sup-chip-name" title="${esc(a.file.name)}">${esc(a.file.name)}</span>
          <span class="sup-chip-meta">${fmtSize(a.file.size)}</span>
          <button type="button" class="sup-chip-x" data-uid="${esc(a.uid)}" aria-label="Remove ${esc(a.file.name)}">✕</button>
        </div>`).join("");
      host.classList.toggle("hidden", !tray.length);
      $$(".sup-chip-x", host).forEach((b) => b.onclick = () => {
        const i = tray.findIndex((a) => a.uid === b.dataset.uid);
        if (i >= 0) { freeChip(tray[i]); tray.splice(i, 1); }
        drawTray();
      });
      if (!note) return;
      const total = tray.reduce((sum, a) => sum + (a.file.size || 0), 0);
      note.textContent = tray.length
        ? `${tray.length} of ${maxFiles} attached · ${fmtSize(total)} of ${fmtSize(maxBytes)}`
        : `Optional · drag files here or paste a screenshot · up to ${maxFiles} files, ${fmtSize(maxBytes)}`;
    }
    function addFiles(fileList) {
      const tray = trays[kind];
      const files = Array.prototype.slice.call(fileList || []);
      if (!files.length) return;
      let running = tray.reduce((sum, a) => sum + (a.file.size || 0), 0);
      const rejected = [];
      files.forEach((raw) => {
        // Clipboard images arrive unnamed on some browsers — give them one we accept.
        let f = raw;
        if (!f.name || f.name.indexOf(".") < 0) {
          const ext = (String(f.type || "").split("/")[1] || "png").replace("jpeg", "jpg");
          try { f = new File([raw], `screenshot-${Date.now()}.${ext}`, { type: raw.type || "image/png" }); }
          catch (e) { rejected.push("That file has no name we can send"); return; }
        }
        const ext = "." + String(f.name).split(".").pop().toLowerCase();
        if (!SUP_ALLOWED_EXT.includes(ext)) { rejected.push(`${f.name} — file type not supported`); return; }
        if (tray.length >= maxFiles) { rejected.push(`${f.name} — limit is ${maxFiles} files`); return; }
        if (running + (f.size || 0) > maxBytes) { rejected.push(`${f.name} — over the ${fmtSize(maxBytes)} total`); return; }
        running += f.size || 0;
        let url = "";
        if (SUP_THUMB_EXT.includes(ext)) {
          try { url = URL.createObjectURL(f); supUrls.push(url); } catch (e) { url = ""; }
        }
        tray.push({ uid: "s" + (++traySeq), file: f, url: url });
      });
      drawTray();
      if (rejected.length) toast(rejected[0], "error");
    }

    /* ---------------- composer ---------------- */
    function fieldErr(which, msg) {
      const box = $(which === "subject" ? "#supSubjErr" : "#supMsgErr");
      const input = $(which === "subject" ? "#supSubject" : "#supMessage");
      if (!box || !input) return;
      if (msg) { box.textContent = msg; box.classList.remove("hidden"); input.setAttribute("aria-invalid", "true"); }
      else { box.classList.add("hidden"); input.removeAttribute("aria-invalid"); }
    }
    function counts() {
      const subj = $("#supSubject"), msg = $("#supMessage");
      [[subj, $("#supSubjCount"), 160], [msg, $("#supMsgCount"), 4000]].forEach(([el, out, max]) => {
        if (!el || !out) return;
        const n = el.value.length;
        // Quiet until it starts to matter — a counter on an empty field is just noise.
        out.textContent = n >= max * 0.6 ? `${n} / ${max}` : "";
        out.classList.toggle("warn", n >= max * 0.9 && n < max);
        out.classList.toggle("over", n >= max);
      });
    }
    function autoGrow() {
      const el = $("#supMessage");
      if (!el) return;
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight + 2, 380) + "px";
    }
    function noteDraft(text, withDiscard) {
      const el = $("#supDraft");
      if (!el) return;
      el.innerHTML = esc(text) + (withDiscard ? ' <button type="button" id="supDiscard">Discard</button>' : "");
      el.classList.toggle("on", !!text);
      const dis = $("#supDiscard");
      if (dis) dis.onclick = () => {
        supSaveDraft(kind, "", "");
        drafts[kind] = { subject: "", message: "", restored: false };
        const s = $("#supSubject"), m = $("#supMessage");
        if (s) s.value = ""; if (m) m.value = "";
        counts(); autoGrow(); showSuggestions(); noteDraft("", false);
        if (s) s.focus();
      };
    }
    function showSuggestions() {
      const box = $("#supSugg");
      if (!box) return;
      const subj = $("#supSubject"), msg = $("#supMessage");
      // Only on the help side: a feature idea has no answer to deflect it with.
      const hits = kind === "support" ? supMatch((subj ? subj.value : "") + " " + (msg ? msg.value : "")) : [];
      if (!hits.length) { box.classList.add("hidden"); box.innerHTML = ""; return; }
      box.innerHTML = `<div class="sup-sugg-head">Might this answer it?</div>` + hits.map((k) =>
        `<button type="button" class="sup-sugg-item" data-kb="${k.id}">${esc(k.q)}${SUP_IC.arw}</button>`).join("");
      box.classList.remove("hidden");
      $$(".sup-sugg-item", box).forEach((b) => b.onclick = () => openKb(b.dataset.kb, true));
    }
    function saveDraftSoon() {
      clearTimeout(draftTimer);
      draftTimer = setTimeout(() => {
        const s = $("#supSubject"), m = $("#supMessage");
        if (!s || !m) return;
        const subject = s.value.trim(), message = m.value.trim();
        drafts[kind] = { subject: subject, message: message, restored: false };
        supSaveDraft(kind, subject, message);
        noteDraft(subject || message ? "Draft saved" : "", !!(subject || message));
      }, 500);
    }

    function mountComposer(focus) {
      // Raising a ticket is an outbound email channel that can carry attachments, so it is
      // its own revocable capability rather than something every member always has.
      if (!can("support.request")) {
        $("#supCard").innerHTML = deniedCard("You don't have permission to contact Rilono support. Ask a workspace admin to raise this for you.");
        return;
      }
      $("#supCard").innerHTML = composerHtml();
      const form = $("#supForm"), subj = $("#supSubject"), msg = $("#supMessage"), file = $("#supFile");
      const isF = kind === "feature_request";

      subj.value = drafts[kind].subject || "";
      msg.value = drafts[kind].message || "";
      counts(); autoGrow(); drawTray(); showSuggestions();
      const hasDraft = !!(subj.value || msg.value);
      noteDraft(hasDraft ? (drafts[kind].restored ? "Draft restored" : "Draft saved") : "", hasDraft);

      $$(".sup-tab").forEach((t) => {
        t.onclick = () => {
          if (t.dataset.kind === kind) return;
          drafts[kind] = { subject: subj.value.trim(), message: msg.value.trim(), restored: false };
          supSaveDraft(kind, drafts[kind].subject, drafts[kind].message);
          kind = t.dataset.kind;
          mountComposer(true);
        };
        t.onkeydown = (e) => {
          if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
          e.preventDefault();
          const other = $$(".sup-tab").find((x) => x !== t);
          if (other) other.click();
        };
      });

      [subj, msg].forEach((el) => el.addEventListener("input", () => {
        counts(); saveDraftSoon();
        if (el === msg) autoGrow();
        fieldErr(el === subj ? "subject" : "message", "");
        clearTimeout(suggestTimer);
        suggestTimer = setTimeout(showSuggestions, 240);
      }));
      // Paste a screenshot straight into the message — the shortest path from ⌘⇧4 to us.
      msg.addEventListener("paste", (e) => {
        const dt = e.clipboardData;
        if (!dt || !dt.files || !dt.files.length) return;
        const files = Array.prototype.filter.call(dt.files, (f) => f && f.size);
        if (!files.length) return;
        if (!dt.getData("text/plain")) e.preventDefault();
        addFiles(files);
      });
      form.addEventListener("keydown", (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event("submit", { cancelable: true })); }
      });

      $("#supDrop").onclick = () => file.click();
      file.onchange = () => { addFiles(file.files); file.value = ""; };

      form.onsubmit = async (e) => {
        e.preventDefault();
        if (supSending) return;   // also covers the ⌘↵ path, which bypasses the button
        const subject = subj.value.trim(), message = msg.value.trim();
        let bad = null;
        if (subject.length < 3) {
          fieldErr("subject", isF ? "Give the idea a short title so we can file it." : "Add a short subject so we know what this is about.");
          bad = subj;
        } else fieldErr("subject", "");
        if (message.length < 5) {
          fieldErr("message", isF ? "Tell us a little about the idea — a sentence is fine." : "Describe what happened — even one line helps.");
          bad = bad || msg;
        } else fieldErr("message", "");
        if (bad) { bad.focus(); return; }

        const tech = $("#supTech");
        const body = new FormData();
        body.append("request_type", kind);
        body.append("subject", subject);
        body.append("message", !isF && tech && tech.checked ? `${message}\n\n— Technical details: ${supTechLine()}` : message);
        trays[kind].forEach((a) => body.append("files", a.file, a.file.name));

        const btn = form.querySelector("button[type=submit]");
        const orig = btn.textContent;
        supSending = true;
        btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Sending…';
        $("#supErr").classList.add("hidden");
        try {
          // Uploads are slower than a plain JSON post — give the files room to finish.
          const r = await api("/support", { method: "POST", body: body, timeout: 180000 });
          clearTimeout(draftTimer);
          supSaveDraft(kind, "", "");
          drafts[kind] = { subject: "", message: "", restored: false };
          trays[kind].forEach(freeChip);
          trays[kind] = [];
          toast(r.message || "Sent — thank you!", "success");
          showSent(subject);
          refreshHistory();
        } catch (ex) {
          const er = $("#supErr");
          er.textContent = ex.message; er.classList.remove("hidden");
          if (btn.isConnected) { btn.disabled = false; btn.textContent = orig; }
        } finally { supSending = false; }
      };

      if (focus) subj.focus();
    }

    function showSent(subject) {
      const isF = kind === "feature_request";
      $("#supCard").innerHTML = `
        <div class="sup-sent">
          <div class="sup-sent-ic">${SUP_IC.check}</div>
          <h3>${isF ? "Idea sent" : "Message sent"}</h3>
          <p>We've got <b>${esc(subject)}</b>${myEmail ? ` and we'll reply to <b>${esc(myEmail)}</b>` : ""} — usually within one business day. It's listed below with its status.</p>
          <button type="button" class="btn btn-ghost" id="supAgain">Write another message</button>
        </div>`;
      $("#supAgain").onclick = () => mountComposer(true);
    }

    async function refreshHistory() {
      try {
        const fresh = await api("/support");
        if (state.view !== "support") return;
        const host = $("#supHistory");
        if (!host) return;
        host.innerHTML = historyHtml(fresh.requests || []);
        wireHistory();
      } catch (ex) { /* the send succeeded; a stale list is not worth an error box */ }
    }

    /* ---------------- history + quick answers ---------------- */
    function wireHistory() {
      $$("#supHistory .sup-hist-row").forEach((row) => row.onclick = () => {
        const item = row.closest(".sup-hist-item");
        const open = item.classList.toggle("open");
        $(".sup-hist-body", item).classList.toggle("hidden", !open);
        row.setAttribute("aria-expanded", open ? "true" : "false");
      });
    }
    function openKb(id, scroll) {
      const item = $$(".sup-kb-item").find((x) => x.dataset.kb === id);
      if (!item) return;
      if (!item.classList.contains("open")) $(".sup-kb-q", item).click();
      if (!scroll) return;
      item.scrollIntoView({ behavior: "smooth", block: "center" });
      item.classList.remove("flash");
      void item.offsetWidth; // restart the highlight if it is already the open one
      item.classList.add("flash");
    }
    $$(".sup-kb-q").forEach((q) => q.onclick = () => {
      const item = q.closest(".sup-kb-item");
      const open = item.classList.toggle("open");
      $(".sup-kb-a", item).classList.toggle("hidden", !open);
      q.setAttribute("aria-expanded", open ? "true" : "false");
    });
    $$(".sup-kb-cta").forEach((b) => b.onclick = (e) => { e.stopPropagation(); navigate(b.dataset.goto); });

    $("#supCopy").onclick = async () => {
      try { await navigator.clipboard.writeText(supportEmail); toast("Email address copied", "success"); }
      catch (ex) { toast("Copy failed — the address is " + supportEmail, "error"); }
    };

    // Drag-and-drop lives on the card, not the form, so it survives every composer swap.
    const card = $("#supCard");
    ["dragenter", "dragover"].forEach((evt) => card.addEventListener(evt, (e) => {
      if (!$("#supForm")) return;
      if (!(e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], "Files") >= 0)) return;
      e.preventDefault(); card.classList.add("is-dragging");
    }));
    ["dragleave", "dragend"].forEach((evt) => card.addEventListener(evt, (e) => {
      if (e.relatedTarget && card.contains(e.relatedTarget)) return;
      card.classList.remove("is-dragging");
    }));
    card.addEventListener("drop", (e) => {
      if (!$("#supForm")) return;
      if (!(e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length)) return;
      e.preventDefault(); card.classList.remove("is-dragging");
      addFiles(e.dataTransfer.files);
    });

    wireHistory();
    mountComposer(false);
  }

  /* ============================================================
     COURSE FINDER — Rilono's verified universities & courses catalog
     (free browse) + billed AI shortlists, optionally per-client.
     Catalog data is maintained by the background catalog agent and
     every row carries a "verified N days ago" stamp.
     ============================================================ */
  const cf = {
    meta: null,
    country: "", level: "", discipline: "", q: "", maxTuition: "",
    adv: null, advOpen: false, // deep filters — set below from cfEmptyAdv()
    browse: null, browseSeq: 0,
    clients: null, clientId: "", clientName: "",
    recs: null, activeRec: null, aiBusy: false, saveBusy: false,
    aiField: "", aiBudget: "", aiNotes: "", // survive tab switches/re-renders
    saved: {}, // "recId:index" → true once added to a client (idempotent UI)
    tab: "browse",
  };
  // The recommend endpoint can fall back to grounded live search on a thin catalog —
  // slower than plain AI calls, and (like Deep Scan) a completed run bills even if
  // the client gave up, so give it a longer leash than AI_API_TIMEOUT_MS.
  const CF_AI_TIMEOUT_MS = 150000;
  const CF_LEVEL_LABELS = { bachelors: "Bachelor's", masters: "Master's", phd: "PhD", diploma: "Diploma", other: "Other" };
  const CF_FIT_META = {
    reach: { label: "Reach", color: "#f59e0b" },
    match: { label: "Match", color: "#10b981" },
    safety: { label: "Safety", color: "#0ea5e9" },
  };
  // Local URL guard — model/API data rendered as hrefs must be http(s) only.
  function cfSafeUrl(u) {
    const s = String(u || "").trim();
    return /^https?:\/\//i.test(s) ? s : "";
  }
  function cfAgo(iso) {
    if (!iso) return "";
    const days = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86400000));
    if (days === 0) return "today";
    if (days === 1) return "yesterday";
    return `${days}d ago`;
  }
  function cfCost() {
    if (cf.meta && cf.meta.cost_credits != null) return cf.meta.cost_credits;
    return ((state.credits && state.credits.actions || []).find((a) => a.key === "course_finder") || {}).credits || 5;
  }

  /* ---------------- Advanced browse filters ----------------
     Deep filters for consultants working a specific brief ("6.0 IELTS, no GRE, under
     CAD 30k, finishes in a year"). Held in ONE object so the panel inputs, the removable
     chip row, the reset and the query string can never drift apart. Enum option lists
     come from /course-catalog/meta (the same vocabulary the server validates against);
     the constants below are only the fallback if that payload is missing a list. */
  function cfEmptyAdv() {
    return {
      min_tuition: "", require_tuition: false, no_app_fee: false, scholarships_only: false,
      max_ielts: "", max_toefl: "", tests_include_unknown: false, gre: "",
      intake: "", max_duration: "", has_deadline: false,
      max_qs_rank: "", uni_type: "", city: "", verified_only: false,
      sort: "rank",
    };
  }
  cf.adv = cfEmptyAdv();
  const CF_IELTS_BANDS = ["5.0", "5.5", "6.0", "6.5", "7.0", "7.5", "8.0"];
  const CF_DURATIONS = [
    { v: 12, l: "1 year or less" },
    { v: 18, l: "18 months or less" },
    { v: 24, l: "2 years or less" },
    { v: 36, l: "3 years or less" },
  ];
  const CF_QS_BANDS = [50, 100, 200, 300, 500, 1000];
  const CF_INTAKES = [
    { key: "fall", label: "Fall / Autumn" }, { key: "spring", label: "Spring" },
    { key: "summer", label: "Summer" }, { key: "winter", label: "Winter" },
  ];
  const CF_SORTS = [
    { key: "rank", label: "Best ranked first" }, { key: "qs", label: "QS world rank" },
    { key: "tuition_asc", label: "Tuition: low → high" }, { key: "tuition_desc", label: "Tuition: high → low" },
    { key: "name", label: "University name (A–Z)" }, { key: "verified", label: "Recently verified" },
  ];
  const CF_UNI_TYPES = [{ key: "public", label: "Public" }, { key: "private", label: "Private" }];
  const CF_GRE_FILTERS = [
    { key: "not_required", label: "Not required / optional" }, { key: "required", label: "Required" },
  ];
  function cfOptions(metaKey, fallback) {
    const list = cf.meta && cf.meta[metaKey];
    return list && list.length ? list : fallback;
  }
  function cfOptLabel(metaKey, fallback, key) {
    return (cfOptions(metaKey, fallback).find((x) => x.key === key) || {}).label || key;
  }
  function cfInt(v) {
    const n = Number(v);
    return v !== "" && v != null && isFinite(n) && n > 0 ? Math.floor(n) : 0;
  }
  // Thousands separators only — the amount is in the destination's own currency, which
  // varies per country, so no symbol is safe to prepend.
  function cfAmount(v) {
    return cfInt(v).toLocaleString();
  }

  /* One descriptor per active filter, driving the chip row AND the count badge. Sort
     rides along as a chip (the panel it lives in is usually collapsed) but never counts
     as a filter — it changes the order, not the result set. */
  function cfAdvChips() {
    const a = cf.adv || {};
    const out = [];
    const push = (key, text) => out.push({ key, text });
    if (cfInt(a.min_tuition)) push("min_tuition", `Tuition ≥ ${cfAmount(a.min_tuition)}`);
    if (a.require_tuition) push("require_tuition", "Fee published");
    if (a.no_app_fee) push("no_app_fee", "No application fee");
    if (a.scholarships_only) push("scholarships_only", "Lists scholarships");
    if (a.max_ielts) push("max_ielts", `IELTS ≤ ${a.max_ielts}`);
    if (cfInt(a.max_toefl)) push("max_toefl", `TOEFL ≤ ${cfInt(a.max_toefl)}`);
    if (a.tests_include_unknown) push("tests_include_unknown", "Incl. no published score");
    if (a.gre) push("gre", `GRE/GMAT: ${cfOptLabel("gre_filters", CF_GRE_FILTERS, a.gre)}`);
    if (a.intake) push("intake", `${cfOptLabel("intakes", CF_INTAKES, a.intake)} intake`);
    if (cfInt(a.max_duration)) push("max_duration", (CF_DURATIONS.find((d) => d.v === cfInt(a.max_duration)) || {}).l || `≤ ${cfInt(a.max_duration)} months`);
    if (a.has_deadline) push("has_deadline", "Deadline published");
    if (cfInt(a.max_qs_rank)) push("max_qs_rank", `QS top ${cfInt(a.max_qs_rank)}`);
    if (a.uni_type) push("uni_type", cfOptLabel("university_types", CF_UNI_TYPES, a.uni_type));
    if (a.city) push("city", `City: ${a.city}`);
    if (a.verified_only) push("verified_only", "Verified data only");
    if (a.sort && a.sort !== "rank") push("sort", `Sorted: ${cfOptLabel("sorts", CF_SORTS, a.sort)}`);
    return out;
  }
  function cfAdvCount() {
    return cfAdvChips().filter((c) => c.key !== "sort").length;
  }
  // Any narrowing at all (basic row included) — decides whether the empty state offers a
  // "clear filters" way out instead of implying the catalog itself is empty.
  function cfAnyFilters() {
    return !!(cf.level || cf.discipline || cf.q || cfInt(cf.maxTuition) || cfAdvCount());
  }

  async function renderCourseFinder() {
    const c = $("#content");
    if (!cf.meta) c.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
    try {
      cf.meta = await api("/course-catalog/meta");
    } catch (ex) {
      // Guard the async gap: never paint an error over a view the user moved on to.
      if (state.view !== "coursefinder") return;
      if (!cf.meta) { c.innerHTML = errBox(ex); return; }
    }
    if (state.view !== "coursefinder") return;
    if (!cf.country) {
      const withData = (cf.meta.countries || []).find((x) => x.universities > 0);
      cf.country = (withData || (cf.meta.countries || [])[0] || {}).code || "US";
    }
    cfDraw();
  }

  function cfDraw() {
    if (state.view !== "coursefinder") return;
    const c = $("#content");
    const m = cf.meta || {};
    const totalUnis = (m.countries || []).reduce((s, x) => s + (x.universities || 0), 0);
    const totalCourses = (m.countries || []).reduce((s, x) => s + (x.courses || 0), 0);
    // Most of the roster is seeded-but-not-yet-researched, so show what is actually
    // verified rather than implying every listed university has verified course data.
    const totalEnriched = (m.countries || []).reduce((s, x) => s + (x.universities_enriched || 0), 0);
    const latest = (m.countries || []).map((x) => x.last_verified_at).filter(Boolean).sort().pop();
    c.innerHTML = `
      <div class="cf-hero">
        <div class="cf-hero-main">
          <h2>🎓 Course Finder</h2>
          <p>Universities, courses, fees, intakes &amp; entry requirements across your destinations — researched and kept current by Rilono AI. Browsing is free; personalized AI shortlists cost <b>${esc(String(cfCost()))} credits</b>.</p>
          <div class="cf-hero-chips">
            ${(m.countries || []).map((x) => `<span class="cf-chip" title="${esc(x.name)}: ${x.universities} universities · ${x.courses} courses">${esc(x.flag_emoji || "")} ${esc(x.code)} · ${x.universities}</span>`).join("")}
          </div>
        </div>
        <div class="cf-hero-stats">
          <div class="cf-stat"><b>${totalUnis}</b><span>Universities</span></div>
          <div class="cf-stat" title="Universities whose courses &amp; fees Rilono AI has verified from official sources"><b>${totalEnriched}</b><span>Verified</span></div>
          <div class="cf-stat"><b>${totalCourses}</b><span>Courses</span></div>
          <div class="cf-stat"><b>${latest ? esc(cfAgo(latest)) : "—"}</b><span>Data refreshed</span></div>
        </div>
      </div>
      <div class="cf-tabs">
        <button class="cf-tab ${cf.tab === "browse" ? "active" : ""}" data-cftab="browse">📚 Browse Catalog</button>
        <button class="cf-tab ${cf.tab === "ai" ? "active" : ""}" data-cftab="ai">✨ AI Shortlists</button>
      </div>
      <div id="cfPanel"></div>`;
    $$(".cf-tab", c).forEach((b) => b.onclick = () => { cf.tab = b.dataset.cftab; cfDraw(); });
    if (cf.tab === "browse") { cfDrawBrowseShell(); } else { cfDrawAI(); }
  }

  /* ---------------- Browse (free) ---------------- */
  function cfDrawBrowseShell() {
    const panel = $("#cfPanel");
    if (!panel) return;
    const m = cf.meta || {};
    panel.innerHTML = `
      <div class="card cf-filters-card"><div class="card-body">
        <div class="cf-filters">
          <label class="cf-f"><span>Destination</span>
            <select id="cfCountry">${(m.countries || []).map((x) => `<option value="${esc(x.code)}" ${x.code === cf.country ? "selected" : ""}>${esc(x.flag_emoji || "")} ${esc(x.name)}</option>`).join("")}</select>
          </label>
          <label class="cf-f"><span>Level</span>
            <select id="cfLevel"><option value="">Any level</option>${(m.degree_levels || []).map((l) => `<option value="${esc(l.key)}" ${l.key === cf.level ? "selected" : ""}>${esc(l.label)}</option>`).join("")}</select>
          </label>
          <label class="cf-f"><span>Discipline</span>
            <select id="cfDiscipline"><option value="">Any discipline</option>${(m.disciplines || []).map((d) => `<option value="${esc(d)}" ${d === cf.discipline ? "selected" : ""}>${esc(d)}</option>`).join("")}</select>
          </label>
          <label class="cf-f cf-f-grow"><span>Search</span>
            <input id="cfQ" type="search" placeholder="Course or university, e.g. Data Science…" value="${esc(cf.q)}" />
          </label>
          <label class="cf-f"><span>Max tuition/yr</span>
            <input id="cfMaxTuition" type="number" min="0" step="1000" placeholder="Local currency" value="${esc(cf.maxTuition)}" />
          </label>
          <button class="btn btn-primary btn-sm" id="cfApply">Search</button>
        </div>
        ${cfAdvBarHtml()}
        ${cfAdvPanelHtml()}
      </div></div>
      <div id="cfBrowseBody"><div class="center-load"><div class="spinner dark"></div></div></div>`;
    // One read-everything-then-load path: the advanced panel stays in the DOM when
    // collapsed, so a filter set and then hidden is still the filter that gets applied.
    const apply = () => { cfReadFilters(); cfSyncFilterBar(); cfLoadBrowse(); };
    $("#cfApply").onclick = apply;
    $("#cfQ").onkeydown = (e) => { if (e.key === "Enter") apply(); };
    ["cfCountry", "cfLevel", "cfDiscipline"].forEach((id) => { $("#" + id).onchange = apply; });
    // The deep filters are set several at a time, so they wait for Apply (or Enter) rather
    // than firing a request per change — Sort is the one control that decides on its own.
    $("#cfAdvApply").onclick = apply;
    $("#cfSort").onchange = apply;
    $$("#cfAdvPanel input", panel).forEach((el) => {
      el.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); apply(); } };
    });
    $("#cfAdvToggle").onclick = () => {
      cf.advOpen = !cf.advOpen;
      $("#cfAdvPanel").classList.toggle("open", cf.advOpen);
      $("#cfAdvToggle").classList.toggle("open", cf.advOpen);
      $("#cfAdvToggle").setAttribute("aria-expanded", cf.advOpen ? "true" : "false");
    };
    // Read first, then reset: a re-render paints from state, so anything typed into the
    // basic row but not yet applied would otherwise be thrown away with the deep filters.
    $("#cfAdvReset").onclick = () => { cfReadFilters(); cf.adv = cfEmptyAdv(); cfDrawBrowseShell(); };
    cfWireFilterBar();
    cfLoadBrowse();
  }

  function cfAdvBarHtml() {
    const n = cfAdvCount();
    return `
      <div class="cf-adv-bar">
        <button type="button" class="cf-adv-toggle ${cf.advOpen ? "open" : ""}" id="cfAdvToggle" aria-expanded="${cf.advOpen ? "true" : "false"}" aria-controls="cfAdvPanel">
          <span class="cf-adv-caret">▸</span> Advanced filters${n ? ` <span class="cf-adv-count">${n}</span>` : ""}
        </button>
        ${infoTip(
          "Deep filters read the figures Rilono AI has <b>verified from the university's own pages</b> — tuition, test scores, program length, intakes, deadlines and rank."
          + "<br><br>A program that publishes nothing for a filter you set is left out, so results get smaller but each match is defensible. Test scores are the exception: tick <b>Also show programs that publish no score</b> to keep those in."
          + "<br><br>IELTS and TOEFL work as “my student has this score” — a program matches when it accepts either one.",
          "How advanced filters work",
        )}
        <div class="cf-fchips" id="cfChips">${cfChipsHtml()}</div>
      </div>`;
  }

  function cfChipsHtml() {
    const chips = cfAdvChips();
    if (!chips.length) return "";
    return chips.map((c) => `
      <span class="cf-fchip ${c.key === "sort" ? "cf-fchip-sort" : ""}">${esc(c.text)}
        <button type="button" class="cf-fchip-x" data-cfchip="${esc(c.key)}" aria-label="Remove filter ${esc(c.text)}">×</button>
      </span>`).join("")
      + `<button type="button" class="cf-clear-all" id="cfClearFilters">Clear all</button>`;
  }

  function cfAdvPanelHtml() {
    const a = cf.adv;
    const sel = (v, cur) => (String(v) === String(cur) ? "selected" : "");
    const chk = (v) => (v ? "checked" : "");
    const opts = (list, cur) => list.map((x) => `<option value="${esc(x.key)}" ${sel(x.key, cur)}>${esc(x.label)}</option>`).join("");
    return `
      <div class="cf-adv ${cf.advOpen ? "open" : ""}" id="cfAdvPanel">
        <div class="cf-adv-grid">
          <div class="cf-adv-group">
            <h4>💰 Fees &amp; funding</h4>
            <label class="cf-f"><span>Min tuition/yr</span>
              <input id="cfMinTuition" type="number" min="0" step="1000" placeholder="Local currency" value="${esc(a.min_tuition)}" />
            </label>
            <label class="cf-check"><input type="checkbox" id="cfRequireTuition" ${chk(a.require_tuition)} /><span>Only programs with a published fee</span></label>
            <label class="cf-check"><input type="checkbox" id="cfNoAppFee" ${chk(a.no_app_fee)} /><span>No application fee</span></label>
            <label class="cf-check"><input type="checkbox" id="cfScholarships" ${chk(a.scholarships_only)} /><span>University lists scholarships</span></label>
          </div>
          <div class="cf-adv-group">
            <h4>📝 Tests &amp; entry</h4>
            <label class="cf-f"><span>Student's IELTS band</span>
              <select id="cfIelts"><option value="">Any requirement</option>${CF_IELTS_BANDS.map((b) => `<option value="${b}" ${sel(b, a.max_ielts)}>${b} or lower</option>`).join("")}</select>
            </label>
            <label class="cf-f"><span>Student's TOEFL (iBT)</span>
              <input id="cfToefl" type="number" min="40" max="120" placeholder="e.g. 95" value="${esc(a.max_toefl)}" />
            </label>
            <label class="cf-f"><span>GRE / GMAT</span>
              <select id="cfGre"><option value="">Any</option>${opts(cfOptions("gre_filters", CF_GRE_FILTERS), a.gre)}</select>
            </label>
            <label class="cf-check"><input type="checkbox" id="cfTestsUnknown" ${chk(a.tests_include_unknown)} /><span>Also show programs that publish no score</span></label>
          </div>
          <div class="cf-adv-group">
            <h4>🎓 Program</h4>
            <label class="cf-f"><span>Intake</span>
              <select id="cfIntake"><option value="">Any intake</option>${opts(cfOptions("intakes", CF_INTAKES), a.intake)}</select>
            </label>
            <label class="cf-f"><span>Finishes within</span>
              <select id="cfDuration"><option value="">Any length</option>${CF_DURATIONS.map((d) => `<option value="${d.v}" ${sel(d.v, a.max_duration)}>${esc(d.l)}</option>`).join("")}</select>
            </label>
            <label class="cf-check"><input type="checkbox" id="cfHasDeadline" ${chk(a.has_deadline)} /><span>Application deadline published</span></label>
          </div>
          <div class="cf-adv-group">
            <h4>🏛️ University</h4>
            <label class="cf-f"><span>QS world rank</span>
              <select id="cfQsRank"><option value="">Any rank</option>${CF_QS_BANDS.map((n) => `<option value="${n}" ${sel(n, a.max_qs_rank)}>Top ${n}</option>`).join("")}</select>
            </label>
            <label class="cf-f"><span>Type</span>
              <select id="cfUniType"><option value="">Any type</option>${opts(cfOptions("university_types", CF_UNI_TYPES), a.uni_type)}</select>
            </label>
            <label class="cf-f"><span>City</span>
              <input id="cfCity" type="search" placeholder="e.g. Toronto" value="${esc(a.city)}" />
            </label>
            <label class="cf-check"><input type="checkbox" id="cfVerifiedOnly" ${chk(a.verified_only)} /><span>Verified data only</span></label>
          </div>
        </div>
        <div class="cf-adv-foot">
          <label class="cf-f cf-adv-sort"><span>Sort by</span>
            <select id="cfSort">${opts(cfOptions("sorts", CF_SORTS), a.sort)}</select>
          </label>
          <div class="cf-adv-foot-actions">
            <button type="button" class="btn btn-soft btn-sm" id="cfAdvReset">Reset advanced</button>
            <button type="button" class="btn btn-primary btn-sm" id="cfAdvApply">Apply filters</button>
          </div>
        </div>
      </div>`;
  }

  // Pull every control (basic row + advanced panel) into state before a load, so the
  // request, the chips and the inputs always describe the same search.
  function cfReadFilters() {
    const val = (id) => { const el = $("#" + id); return el ? String(el.value || "").trim() : ""; };
    const on = (id) => { const el = $("#" + id); return !!(el && el.checked); };
    cf.country = val("cfCountry") || cf.country;
    cf.level = val("cfLevel");
    cf.discipline = val("cfDiscipline");
    cf.q = val("cfQ");
    cf.maxTuition = val("cfMaxTuition");
    cf.adv = {
      min_tuition: val("cfMinTuition"),
      require_tuition: on("cfRequireTuition"),
      no_app_fee: on("cfNoAppFee"),
      scholarships_only: on("cfScholarships"),
      max_ielts: val("cfIelts"),
      max_toefl: val("cfToefl"),
      tests_include_unknown: on("cfTestsUnknown"),
      gre: val("cfGre"),
      intake: val("cfIntake"),
      max_duration: val("cfDuration"),
      has_deadline: on("cfHasDeadline"),
      max_qs_rank: val("cfQsRank"),
      uni_type: val("cfUniType"),
      city: val("cfCity"),
      verified_only: on("cfVerifiedOnly"),
      sort: val("cfSort") || "rank",
    };
  }

  // Repaint just the chips + count badge. A full shell re-render would throw away the
  // panel's scroll position and focus while the consultant is still adjusting filters.
  function cfSyncFilterBar() {
    const chips = $("#cfChips");
    if (chips) { chips.innerHTML = cfChipsHtml(); cfWireFilterBar(); }
    const toggle = $("#cfAdvToggle");
    if (toggle) {
      const n = cfAdvCount();
      toggle.innerHTML = `<span class="cf-adv-caret">▸</span> Advanced filters${n ? ` <span class="cf-adv-count">${n}</span>` : ""}`;
    }
  }

  function cfWireFilterBar() {
    $$("[data-cfchip]").forEach((b) => {
      b.onclick = () => {
        // Reset the one key to its default (false/""/"rank") and re-render the shell so
        // the panel control that set it visibly clears too. Reading the panel first keeps
        // any other pending edit the consultant has already made on screen.
        cfReadFilters();
        cf.adv[b.dataset.cfchip] = cfEmptyAdv()[b.dataset.cfchip];
        cfDrawBrowseShell();
      };
    });
    const clear = $("#cfClearFilters");
    if (clear) clear.onclick = cfClearFilters;
  }

  function cfClearFilters() {
    cf.level = ""; cf.discipline = ""; cf.q = ""; cf.maxTuition = "";
    cf.adv = cfEmptyAdv();
    cfDrawBrowseShell();
  }

  async function cfLoadBrowse(offset) {
    const body = $("#cfBrowseBody");
    if (!body) return;
    const append = Number(offset) > 0;
    if (!append) body.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
    const seq = ++cf.browseSeq;
    const p = new URLSearchParams({ country: cf.country });
    if (cf.level) p.set("level", cf.level);
    if (cf.discipline) p.set("discipline", cf.discipline);
    if (cf.q) p.set("q", cf.q);
    if (cf.maxTuition && Number(cf.maxTuition) > 0) p.set("max_tuition", String(Math.floor(Number(cf.maxTuition))));
    // Advanced filters. Only non-empty values are sent, so the URL stays readable and the
    // server never has to tell "unset" from "cleared".
    const a = cf.adv || {};
    [["min_tuition", a.min_tuition], ["max_toefl", a.max_toefl], ["max_duration", a.max_duration],
      ["max_qs_rank", a.max_qs_rank]].forEach(([k, v]) => { if (cfInt(v)) p.set(k, String(cfInt(v))); });
    if (a.max_ielts) p.set("max_ielts", String(a.max_ielts));
    [["gre", a.gre], ["intake", a.intake], ["uni_type", a.uni_type], ["city", a.city]]
      .forEach(([k, v]) => { if (v) p.set(k, String(v)); });
    ["require_tuition", "tests_include_unknown", "no_app_fee", "has_deadline", "verified_only", "scholarships_only"]
      .forEach((k) => { if (a[k]) p.set(k, "1"); });
    if (a.sort && a.sort !== "rank") p.set("sort", a.sort);
    if (append) p.set("offset", String(offset));
    try {
      const d = await api("/course-catalog?" + p.toString());
      if (seq !== cf.browseSeq || state.view !== "coursefinder") return; // stale response
      // The catalog runs to ~1.5k universities per country, so browse is paged.
      // Append the new page in place — a full re-render would collapse every
      // university card the consultant had expanded and jump the scroll position.
      if (append && cf.browse) {
        const prev = (cf.browse.universities || []).length;
        d.universities = (cf.browse.universities || []).concat(d.universities || []);
        cf.browse = d;
        cfAppendBrowse(prev);
      } else {
        cf.browse = d;
        cfDrawBrowse();
      }
    } catch (ex) {
      if (seq !== cf.browseSeq) return;
      if (append) { const b = $("#cfMoreBtn"); if (b) { b.disabled = false; b.textContent = "Load more"; } toast(ex.message, "error"); }
      else body.innerHTML = errBox(ex);
    }
  }

  function cfDrawBrowse() {
    const body = $("#cfBrowseBody");
    if (!body || !cf.browse) return;
    const unis = cf.browse.universities || [];
    if (!unis.length) {
      // With deep filters on, "nothing matched" is usually one filter too many rather than
      // a thin catalog — so say which way out applies.
      const filtered = cfAnyFilters();
      body.innerHTML = `
        <div class="empty"><div class="emoji">🛰️</div>
          <h3>${filtered ? "No matches for these filters" : "Nothing here yet"}</h3>
          <p>${filtered
            ? "Nothing in the verified catalog meets every filter at once. Loosen the strictest one — tuition, test scores or QS rank are the usual culprits — or try the <b>AI Shortlists</b> tab, which can also search live data."
            : "Rilono's research agent adds &amp; re-verifies universities every day — or try the <b>AI Shortlists</b> tab, which can also search live data."}</p>
          ${filtered ? '<button type="button" class="btn btn-secondary btn-sm" id="cfEmptyClear">Clear all filters</button>' : ""}
        </div>`;
      const clear = $("#cfEmptyClear");
      if (clear) clear.onclick = cfClearFilters;
      return;
    }
    const total = Number(cf.browse.total_universities || unis.length);
    const more = !!cf.browse.has_more;
    const counter = total > unis.length || more
      ? `<div class="cf-count">Showing <b>${unis.length}</b> of <b>${total}</b> universities</div>` : "";
    const moreBtn = more
      ? `<div class="cf-more"><button class="btn btn-secondary" id="cfMoreBtn">Load more</button></div>` : "";
    body.innerHTML = counter + unis.map((u, i) => cfUniCard(u, i)).join("") + moreBtn;
    $$(".cf-uni-toggle", body).forEach((btn) => {
      btn.onclick = () => {
        const card = btn.closest(".cf-uni");
        if (card) card.classList.toggle("cf-uni-open");
        const tbl = card && card.querySelector(".cf-courses");
        btn.textContent = tbl && card.classList.contains("cf-uni-open") ? "Hide courses" : `View courses (${btn.dataset.n})`;
      };
    });
    cfWireMore(body);
  }

  // Wire the toggle handlers for a set of cards + the "Load more" button. Kept
  // separate from cfDrawBrowse so appending a page doesn't re-render (and collapse)
  // the cards already on screen.
  function cfWireCards(scope) {
    $$(".cf-uni-toggle", scope).forEach((btn) => {
      if (btn.dataset.wired) return;
      btn.dataset.wired = "1";
      btn.onclick = () => {
        const card = btn.closest(".cf-uni");
        if (card) card.classList.toggle("cf-uni-open");
        const tbl = card && card.querySelector(".cf-courses");
        btn.textContent = tbl && card.classList.contains("cf-uni-open") ? "Hide courses" : `View courses (${btn.dataset.n})`;
      };
    });
  }

  function cfWireMore(body) {
    cfWireCards(body);
    const mb = $("#cfMoreBtn");
    if (mb) mb.onclick = () => {
      mb.disabled = true; mb.innerHTML = '<span class="spinner"></span> Loading…';
      cfLoadBrowse((cf.browse && (cf.browse.universities || []).length) || 0);
    };
  }

  // Append only the newly-fetched universities, leaving existing cards (and any the
  // consultant expanded) untouched.
  function cfAppendBrowse(prevCount) {
    const body = $("#cfBrowseBody");
    if (!body || !cf.browse) return;
    const unis = cf.browse.universities || [];
    const fresh = unis.slice(prevCount);
    const oldMore = $("#cfMoreBtn");
    const moreWrap = oldMore && oldMore.closest(".cf-more");
    if (moreWrap) moreWrap.remove();
    const frag = document.createElement("div");
    frag.innerHTML = fresh.map((u, i) => cfUniCard(u, prevCount + i)).join("");
    while (frag.firstChild) body.appendChild(frag.firstChild);
    const counter = body.querySelector(".cf-count");
    const total = Number(cf.browse.total_universities || unis.length);
    if (counter) counter.innerHTML = `Showing <b>${unis.length}</b> of <b>${total}</b> universities`;
    if (cf.browse.has_more) {
      const wrap = document.createElement("div");
      wrap.className = "cf-more";
      wrap.innerHTML = '<button class="btn btn-secondary" id="cfMoreBtn">Load more</button>';
      body.appendChild(wrap);
    }
    cfWireMore(body);
  }

  function cfUniCard(u, idx) {
    const verified = u.last_verified_at
      ? `<span class="cf-verified" title="Last verified by Rilono AI">✓ Verified ${esc(cfAgo(u.last_verified_at))}</span>`
      : '<span class="cf-verified cf-pending" title="Queued for the research agent">⏳ Enriching soon</span>';
    const site = cfSafeUrl(u.website_url);
    const courses = u.courses || [];
    const open = idx < 3 && courses.length; // first few expanded so the page never looks empty
    return `
    <div class="card cf-uni ${open ? "cf-uni-open" : ""}">
      <div class="card-body">
        <div class="cf-uni-head">
          <div class="cf-uni-title">
            <h3>${esc(u.name)}</h3>
            <div class="cf-uni-sub">${esc(u.city || "")}${u.university_type ? ` · ${esc(u.university_type)}` : ""}</div>
          </div>
          <div class="cf-uni-meta">
            ${u.qs_world_rank ? `<span class="cf-rank" title="QS World University Ranking">QS #${esc(u.qs_world_rank)}</span>` : ""}
            ${u.national_rank ? `<span class="cf-rank cf-rank-nat" title="National rank">Nat. #${esc(u.national_rank)}</span>` : ""}
            ${verified}
          </div>
        </div>
        ${u.summary ? `<p class="cf-uni-summary">${esc(u.summary)}</p>` : ""}
        <div class="cf-uni-facts">
          ${u.tuition_note ? `<span title="Typical international tuition">💰 ${esc(u.tuition_note)}</span>` : ""}
          ${u.scholarships_note ? `<span title="Scholarships">🎁 ${esc(u.scholarships_note)}</span>` : ""}
          ${site ? `<a href="${esc(site)}" target="_blank" rel="noopener noreferrer">🔗 Official website</a>` : ""}
        </div>
        ${courses.length ? `
          <button class="btn btn-soft btn-sm cf-uni-toggle" data-n="${courses.length}">${open ? "Hide courses" : `View courses (${courses.length})`}</button>
          <div class="cf-courses-wrap"><table class="client-table cf-courses">
            <thead><tr><th>Course</th><th>Level</th><th>Tuition / yr</th><th>Intakes</th><th>IELTS / TOEFL</th><th>Deadline</th><th>App. fee</th><th></th></tr></thead>
            <tbody>${courses.map((cr) => cfCourseRow(cr)).join("")}</tbody>
          </table></div>` : `<div class="hint" style="margin-top:8px">${u.last_verified_at ? "No courses here match the current filters — clear them to see this university's full course list." : "Course list coming with this university's next agent refresh."}</div>`}
      </div>
    </div>`;
  }

  function cfCourseRow(cr) {
    const link = cfSafeUrl(cr.course_url);
    const scores = [cr.ielts_requirement ? `IELTS ${cr.ielts_requirement}` : "", cr.toefl_requirement ? `TOEFL ${cr.toefl_requirement}` : ""].filter(Boolean).join(" · ");
    return `<tr>
      <td><b>${esc(cr.course_name)}</b>${cr.discipline ? `<div class="cf-td-sub">${esc(cr.discipline)}${cr.duration ? ` · ${esc(cr.duration)}` : ""}</div>` : ""}</td>
      <td>${esc(CF_LEVEL_LABELS[cr.degree_level] || cr.degree_level || "—")}</td>
      <td>${esc(cr.annual_tuition || "—")}</td>
      <td>${esc((cr.intakes || []).join(", ") || "—")}</td>
      <td>${esc(scores || "—")}</td>
      <td>${esc(cr.application_deadline || "—")}</td>
      <td>${esc(cr.application_fee || "—")}</td>
      <td>${link ? `<a class="cf-course-link" href="${esc(link)}" target="_blank" rel="noopener noreferrer">Page ↗</a>` : ""}</td>
    </tr>`;
  }

  /* ---------------- AI shortlists (billed) ---------------- */
  async function cfEnsureClients() {
    if (cf.clients) return cf.clients;
    try {
      const d = await api("/clients?limit=500");
      cf.clients = d.clients || [];
      return cf.clients;
    } catch (ex) {
      // Don't cache the failure (an empty [] is truthy) — surface it and let the
      // next focus retry, matching the send-interview picker's behavior.
      toast(ex.message, "error");
      return [];
    }
  }

  function cfDrawAI() {
    const panel = $("#cfPanel");
    if (!panel) return;
    const m = cf.meta || {};
    const canEdit = can("ai.coursefinder");
    const cost = cfCost();
    panel.innerHTML = `
      <div class="card"><div class="card-head"><h3>✨ New AI shortlist <span class="uni-cost">${esc(String(cost))} credits</span></h3></div>
      <div class="card-body">
        ${!m.ai_available ? '<div class="hint" style="margin-bottom:10px">AI is not configured on this server right now.</div>' : ""}
        <div class="cf-ai-grid">
          <label class="cf-f"><span>Client</span>
            <div class="docsel">
              <input id="cfClientSearch" class="docsel-input" placeholder="Search your clients…" autocomplete="off" value="${esc(cf.clientName)}" />
              <div class="docsel-menu hidden" id="cfClientMenu"></div>
            </div>
            <span class="cf-f-hint">Optional — tailors picks to their profile</span>
          </label>
          <label class="cf-f"><span>Destination</span>
            <select id="cfAiCountry">${(m.countries || []).map((x) => `<option value="${esc(x.code)}" ${x.code === cf.country ? "selected" : ""}>${esc(x.flag_emoji || "")} ${esc(x.name)}</option>`).join("")}</select>
          </label>
          <label class="cf-f"><span>Field of study</span>
            <input id="cfAiField" placeholder="e.g. Machine Learning, MBA…" value="${esc(cf.aiField || cf.q)}" maxlength="120" />
          </label>
          <label class="cf-f"><span>Level</span>
            <select id="cfAiLevel"><option value="">Any</option>${(m.degree_levels || []).map((l) => `<option value="${esc(l.key)}" ${l.key === cf.level ? "selected" : ""}>${esc(l.label)}</option>`).join("")}</select>
          </label>
          <label class="cf-f"><span>Discipline</span>
            <select id="cfAiDiscipline"><option value="">Any</option>${(m.disciplines || []).map((d) => `<option value="${esc(d)}" ${d === cf.discipline ? "selected" : ""}>${esc(d)}</option>`).join("")}</select>
          </label>
          <label class="cf-f"><span>Annual budget</span>
            <input id="cfAiBudget" placeholder="e.g. USD 40,000" value="${esc(cf.aiBudget)}" maxlength="60" />
          </label>
          <label class="cf-f cf-f-full"><span>Notes for Rilono AI</span>
            <input id="cfAiNotes" placeholder="e.g. prefers co-op programs, needs scholarships, open to smaller cities" value="${esc(cf.aiNotes)}" maxlength="300" />
          </label>
        </div>
        <div class="cf-ai-actions">
          <button class="btn btn-primary" id="cfAiRun" ${(!canEdit || !m.ai_available || cf.aiBusy || !cfAiHasTarget()) ? "disabled" : ""} title="${cfAiHasTarget() ? "" : "Enter a field of study or pick a discipline first"}">${cf.aiBusy ? '<span class="spinner"></span> Rilono AI is researching…' : `Generate shortlist · ${esc(String(cost))} cr`}</button>
          ${!canEdit ? '<span class="hint">Viewers can browse, but only editors can run AI actions.</span>' : ""}
        </div>
      </div></div>
      <div id="cfAiResult"></div>
      <div class="card"><div class="card-head"><h3>Past shortlists</h3></div><div class="card-body" id="cfRecsList"><div class="center-load"><div class="spinner dark"></div></div></div></div>`;

    cfWireClientPicker();
    // Persist form state so tab switches / re-renders never wipe what was typed.
    $("#cfAiField").oninput = (e) => { cf.aiField = e.target.value; cfSyncAiRun(); };
    $("#cfAiBudget").oninput = (e) => { cf.aiBudget = e.target.value; };
    $("#cfAiNotes").oninput = (e) => { cf.aiNotes = e.target.value; };
    $("#cfAiCountry").onchange = (e) => { cf.country = e.target.value; };
    $("#cfAiLevel").onchange = (e) => { cf.level = e.target.value; };
    $("#cfAiDiscipline").onchange = (e) => { cf.discipline = e.target.value; cfSyncAiRun(); };
    $("#cfAiRun").onclick = cfRunRecommend;
    if (cf.activeRec) cfDrawActiveRec();
    cfLoadRecs();
  }

  function cfWireClientPicker() {
    const input = $("#cfClientSearch");
    const menu = $("#cfClientMenu");
    if (!input || !menu) return;
    let items = [];
    const paint = (list) => {
      items = list;
      menu.innerHTML = list.length
        ? list.map((cl, i) => `<div class="docsel-item" data-i="${i}"><b>${esc(cl.full_name)}</b> <span class="cf-td-sub">${esc(cl.destination_country_name || cl.destination_country_code || "")}</span></div>`).join("")
        : '<div class="docsel-empty">No matching clients</div>';
      $$(".docsel-item", menu).forEach((el) => {
        el.onmousedown = (e) => { e.preventDefault(); pick(items[Number(el.dataset.i)]); };
      });
    };
    const pick = (cl) => {
      if (!cl) return;
      cf.clientId = String(cl.id);
      cf.clientName = cl.full_name;
      input.value = cl.full_name;
      menu.classList.add("hidden");
      // Personalizing for a client → default the destination to THEIR country when we cover it.
      const dest = (cl.destination_country_code || "").toUpperCase();
      const sel = $("#cfAiCountry");
      if (sel && dest && (cf.meta.countries || []).some((x) => x.code === dest)) sel.value = dest;
    };
    const openMenu = async () => {
      const all = await cfEnsureClients();
      const needle = input.value.trim().toLowerCase();
      const list = all.filter((cl) => !needle || (cl.full_name || "").toLowerCase().includes(needle) || (cl.email || "").toLowerCase().includes(needle)).slice(0, 30);
      paint(list);
      menu.classList.remove("hidden");
    };
    input.onfocus = openMenu;
    input.oninput = () => { cf.clientId = ""; cf.clientName = ""; openMenu(); };
    input.onblur = () => setTimeout(() => menu.classList.add("hidden"), 150);
    input.onkeydown = (e) => {
      if (e.key === "Escape") { menu.classList.add("hidden"); input.blur(); }
      if (e.key === "Enter" && items.length) { e.preventDefault(); pick(items[0]); }
    };
  }

  /* A shortlist needs SOMETHING to search for. Either box will do — a free-text field of
     study or a picked discipline — which is why this is one predicate over both rather than
     a required-field check on each. */
  function cfAiHasTarget() {
    const f = $("#cfAiField"), d = $("#cfAiDiscipline");
    const field = f ? f.value : (cf.aiField || "");
    const disc = d ? d.value : (cf.discipline || "");
    return String(field || "").trim() !== "" || String(disc || "") !== "";
  }
  function cfSyncAiRun() {
    const b = $("#cfAiRun");
    if (!b || cf.aiBusy) return;
    const ok = cfAiHasTarget() && can("ai.coursefinder");
    b.disabled = !ok;
    b.title = cfAiHasTarget() ? "" : "Enter a field of study or pick a discipline first";
  }

  async function cfRunRecommend() {
    if (cf.aiBusy) return;
    const btn = $("#cfAiRun");
    const body = {
      client_id: cf.clientId ? Number(cf.clientId) : null,
      country_code: $("#cfAiCountry") ? $("#cfAiCountry").value : cf.country,
      degree_level: $("#cfAiLevel") ? $("#cfAiLevel").value || null : null,
      discipline: $("#cfAiDiscipline") ? $("#cfAiDiscipline").value || null : null,
      field_of_study: $("#cfAiField") ? $("#cfAiField").value.trim() || null : null,
      budget: $("#cfAiBudget") ? $("#cfAiBudget").value.trim() || null : null,
      notes: $("#cfAiNotes") ? $("#cfAiNotes").value.trim() || null : null,
      max_results: 6,
    };
    if (!body.field_of_study && !body.discipline) { toast("Add a field of study (or pick a discipline) first.", "error"); return; }
    cf.aiBusy = true;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Rilono AI is researching…';
    try {
      const r = await api("/course-finder/recommend", { method: "POST", body, timeout: CF_AI_TIMEOUT_MS });
      if (r.wallet) { state.credits = r.wallet; updatePlanChip(); }
      cf.activeRec = r.rec;
      cf.recs = null; // refresh history below
      toast(r.credits_charged ? `Shortlist ready — ${r.credits_charged} credits used` : "Shortlist ready", "success");
      cfDrawActiveRec();
      cfLoadRecs();
    } catch (ex) {
      if (ex && ex.status === 402) {
        toast(ex.message, "error");
        navigate("credits");
        return;
      }
      toast(ex.message || "Couldn't generate the shortlist.", "error");
      // A client-side timeout doesn't guarantee the server didn't complete AND bill —
      // refresh history so a stored (paid) result is never invisible. (Deep Scan pattern.)
      cf.recs = null;
      cfLoadRecs();
    } finally {
      cf.aiBusy = false;
      // Rebuild the label explicitly — the button may have been re-rendered (in its
      // busy state) by a tab switch mid-run, so a captured snapshot can't be trusted.
      const runBtn = $("#cfAiRun");
      if (runBtn) {
        runBtn.innerHTML = `Generate shortlist · ${esc(String(cfCost()))} cr`;
        cfSyncAiRun();   // carries the "needs a target" term, not just the permission one
      }
    }
  }

  function cfDrawActiveRec() {
    const mount = $("#cfAiResult");
    if (!mount) return;
    const rec = cf.activeRec;
    if (!rec) { mount.innerHTML = ""; return; }
    const items = rec.recommendations || [];
    // Saving a catalog match onto a client writes to their shortlist.
    const canEdit = can("universities.manage");
    const target = rec.client_name ? `for <b>${esc(rec.client_name)}</b>` : (cf.clientName ? `→ can save to <b>${esc(cf.clientName)}</b>` : "");
    mount.innerHTML = `
      <div class="card cf-rec-card"><div class="card-head">
        <h3>🎯 Shortlist ${target} <span class="cf-td-sub">${esc(fmtDateTime(rec.created_at))}</span></h3>
        <div>
          ${rec.catalog_based ? '<span class="cf-verified" title="Built from Rilono\'s verified catalog">✓ Catalog data</span>' : '<span class="cf-verified cf-pending" title="Generated with live search while this destination is still being seeded">🌐 Live research</span>'}
        </div>
      </div>
      <div class="card-body">
        ${rec.summary ? `<p class="cf-rec-summary">${esc(rec.summary)}</p>` : ""}
        <div class="cf-rec-grid">${items.map((it, i) => cfRecItem(it, i, rec, canEdit)).join("")}</div>
      </div></div>`;
    $$(".cf-rec-save", mount).forEach((b) => { b.onclick = () => cfSaveRec(Number(b.dataset.i)); });
  }

  function cfRecItem(it, i, rec, canEdit) {
    const fit = CF_FIT_META[it.fit_level] || CF_FIT_META.match;
    const site = cfSafeUrl(it.website_url);
    const page = cfSafeUrl(it.course_url);
    const canSave = canEdit && (rec.client_id || cf.clientId);
    const savedAlready = !!cf.saved[`${rec.id}:${i}`];
    return `
    <div class="cf-rec-item">
      <div class="cf-rec-top">
        <span class="status-pill" style="background:${fit.color}1a;color:${fit.color}"><span class="sd" style="background:${fit.color}"></span>${fit.label}</span>
        ${it.qs_world_rank ? `<span class="cf-rank">QS #${esc(it.qs_world_rank)}</span>` : ""}
        ${it.in_catalog ? '<span class="cf-verified" title="From Rilono\'s verified catalog">✓ Verified</span>' : '<span class="cf-verified cf-pending" title="Not yet in our catalog — double-check on the official page">Verify</span>'}
      </div>
      <h4>${esc(it.course_name)}</h4>
      <div class="cf-rec-uni">${esc(it.university_name)}${it.location ? ` · ${esc(it.location)}` : ""}</div>
      ${it.why_recommended ? `<p>${esc(it.why_recommended)}</p>` : ""}
      <div class="cf-rec-facts">
        ${it.annual_tuition ? `<span>💰 ${esc(it.annual_tuition)}</span>` : ""}
        ${it.intakes ? `<span>📅 ${esc(it.intakes)}</span>` : ""}
        ${it.application_deadline ? `<span>⏰ ${esc(it.application_deadline)}</span>` : ""}
        ${it.application_fee ? `<span>🧾 ${esc(it.application_fee)}</span>` : ""}
      </div>
      ${(it.key_requirements || []).length ? `<div class="cf-rec-reqs">${it.key_requirements.map((r) => `<span>${esc(r)}</span>`).join("")}</div>` : ""}
      <div class="cf-rec-actions">
        ${page ? `<a class="btn btn-ghost btn-sm" href="${esc(page)}" target="_blank" rel="noopener noreferrer">Course page ↗</a>` : (site ? `<a class="btn btn-ghost btn-sm" href="${esc(site)}" target="_blank" rel="noopener noreferrer">Website ↗</a>` : "")}
        ${canSave ? (savedAlready
          ? '<button class="btn btn-soft btn-sm" disabled>✓ Added</button>'
          : `<button class="btn btn-soft btn-sm cf-rec-save" data-i="${i}">➕ Add to client's universities</button>`) : ""}
      </div>
    </div>`;
  }

  async function cfSaveRec(index) {
    if (cf.saveBusy || !cf.activeRec) return;
    const clientId = cf.activeRec.client_id || (cf.clientId ? Number(cf.clientId) : null);
    if (!clientId) { toast("Pick a client above first.", "error"); return; }
    cf.saveBusy = true;
    try {
      const r = await api(`/course-finder/recs/${cf.activeRec.id}/save-to-client`, { method: "POST", body: { index, client_id: clientId } });
      cf.saved[`${cf.activeRec.id}:${index}`] = true;
      toast(r.already_saved
        ? "Already on that client's Universities tab"
        : `Added to ${cf.activeRec.client_name || cf.clientName || "the client"}'s Universities tab`, "success");
      cfDrawActiveRec(); // re-render so the button flips to "✓ Added"
    } catch (ex) {
      toast(ex.message || "Couldn't save.", "error");
    } finally {
      cf.saveBusy = false;
    }
  }

  async function cfLoadRecs() {
    const mount = $("#cfRecsList");
    if (!mount) return;
    try {
      const d = await api("/course-finder/recs?limit=20");
      cf.recs = d.recs || [];
    } catch (ex) {
      mount.innerHTML = errBox(ex);
      return;
    }
    if (!$("#cfRecsList")) return; // user navigated away mid-fetch
    if (!cf.recs.length) {
      mount.innerHTML = '<div class="hint">No AI shortlists yet. Your team\'s past shortlists will appear here — results are stored, so a paid shortlist is never lost.</div>';
      return;
    }
    mount.innerHTML = cf.recs.map((r) => `
      <button class="cf-hist-row" data-id="${r.id}">
        <div class="cf-hist-main">
          <b>${esc(r.client_name || "General")}</b>
          <span>${esc(r.country_code || "")}${r.degree_level ? ` · ${esc(CF_LEVEL_LABELS[r.degree_level] || r.degree_level)}` : ""}${r.discipline ? ` · ${esc(r.discipline)}` : ""}${(r.query && r.query.field_of_study) ? ` · ${esc(r.query.field_of_study)}` : ""}</span>
        </div>
        <div class="cf-hist-side">
          <span>${r.count} picks</span>
          <span>${r.credits_charged ? `${r.credits_charged} cr` : "—"}</span>
          <span>${esc(fmtDateTime(r.created_at))}</span>
        </div>
      </button>`).join("");
    $$(".cf-hist-row", mount).forEach((b) => { b.onclick = () => cfOpenRec(Number(b.dataset.id)); });
  }

  async function cfOpenRec(id) {
    try {
      const d = await api(`/course-finder/recs/${id}`);
      cf.activeRec = d.rec;
      cfDrawActiveRec();
      const mount = $("#cfAiResult");
      if (mount) mount.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (ex) {
      toast(ex.message || "Couldn't open that shortlist.", "error");
    }
  }

  /* ============================================================
     LEADS — branded lead-collection forms + inbox
     Forms are built here, shared as /f/{token} links (public page:
     static/lead_form.html), and every submission lands in the inbox
     below, one click away from becoming a client.
     ============================================================ */
  const ld = { tab: "inbox", forms: null, leads: [], counts: {}, total: 0, status: "", formFilter: "", q: "", seq: 0, limit: 100 };
  const LD_PAGE_SIZE = 100;
  const LD_SCOPE_DENIED = "Leads are workspace-wide enquiries that aren't assigned to an office or counselor yet, so they're only visible to members whose access scope is the entire workspace. Ask a workspace admin.";
  // Leads are unassigned enquiries with no branch or counselor, so there is nothing to
  // scope them by — the backend restricts the inbox to workspace-scope members and the
  // UI must agree, or the nav item leads straight to a 403.
  function canSeeLeads() {
    const a = state.access;
    if (!a) return true;                              // pre-access-control server
    const scope = String(a.data_scope || "all");
    return scope === "all" || !!a.is_admin_like || !state.caps;
  }
  const LD_STATUSES = ["new", "contacted", "converted", "closed"];
  const LD_TYPE_LABELS = { text: "Text", email: "Email", phone: "Phone", textarea: "Paragraph", select: "Dropdown", date: "Date", number: "Number", checkbox: "Checkbox", file: "File upload" };
  // Mirrors _LEAD_FORM_MAX_FILE_FIELDS / _LEAD_UPLOAD_MAX_PER_FIELD on the server.
  // The server is the authority — this only keeps the builder from offering a
  // shape it would reject.
  const LD_MAX_FILE_FIELDS = 5;
  const LD_MAX_FILES_PER_FIELD = 5;
  const LD_DEFAULT_FIELDS = [
    { label: "Full name", type: "text", required: true },
    { label: "Email", type: "email", required: true },
    { label: "Phone / WhatsApp", type: "phone", required: false },
    { label: "Which country are you interested in?", type: "select", required: false, options: ["USA", "UK", "Canada", "Australia", "Germany", "Other"] },
    { label: "Anything you'd like to tell us?", type: "textarea", required: false },
  ];

  function ldStatusLabel(s) { return { new: "New", contacted: "Contacted", converted: "Converted", closed: "Closed" }[s] || s; }

  async function renderLeads() {
    const c = $("#content");
    if (!canSeeLeads()) { c.innerHTML = deniedCard(LD_SCOPE_DENIED); return; }
    c.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
    try {
      const d = await api("/lead-forms");
      if (state.view !== "leads") return;
      applyAccessPayload(d);
      ld.forms = d.forms || [];
    } catch (ex) {
      if (state.view !== "leads") return;
      c.innerHTML = errBox(ex);
      return;
    }
    ldDraw();
  }

  async function ldRefreshForms() {
    try {
      const d = await api("/lead-forms");
      if (state.view !== "leads") return;
      applyAccessPayload(d);
      ld.forms = d.forms || [];
      ldDraw();
    } catch (e) { /* next full render reloads */ }
  }

  function ldDraw() {
    if (state.view !== "leads") return;
    const c = $("#content");
    const forms = ld.forms || [];
    const totalLeads = forms.reduce((s, f) => s + (f.total_leads || 0), 0);
    const newLeads = forms.reduce((s, f) => s + (f.new_leads || 0), 0);
    c.innerHTML = `
      <div class="ld-hero">
        <div>
          <h2><i>🎯</i>Leads</h2>
          <p>Build branded enquiry forms, share the link anywhere — email, WhatsApp, Instagram bio, a QR on a flyer — and every submission lands here, one click away from becoming a client. ${infoTip("The public form page carries <b>your</b> company name and logo (set them in Settings → Branding), with only a small “Powered by Rilono” line at the bottom. Each form's link keeps working until you pause the form or generate a new link.", "About lead forms")}</p>
        </div>
        <div class="ld-hero-stats">
          <div class="ld-stat"><b>${forms.length}</b><span>Forms</span></div>
          <div class="ld-stat"><b>${totalLeads}</b><span>Leads collected</span></div>
          <div class="ld-stat"><b>${newLeads}</b><span>New</span></div>
        </div>
      </div>
      <div class="ld-tabs">
        <button class="ld-tab ${ld.tab === "inbox" ? "active" : ""}" data-ldtab="inbox"><i>📥</i>Lead Inbox</button>
        <button class="ld-tab ${ld.tab === "forms" ? "active" : ""}" data-ldtab="forms"><i>🧾</i>Forms</button>
      </div>
      <div id="ldPanel"></div>`;
    $$(".ld-tab", c).forEach((b) => b.onclick = () => { ld.tab = b.dataset.ldtab; ldDraw(); });
    if (ld.tab === "inbox") ldDrawInbox(); else ldDrawForms();
  }

  /* ---------------- inbox ---------------- */
  function ldChipsHtml() {
    const cts = ld.counts || {};
    const all = LD_STATUSES.reduce((s, k) => s + (cts[k] || 0), 0);
    const defs = [["", "All", all]].concat(LD_STATUSES.map((k) => [k, ldStatusLabel(k), cts[k] || 0]));
    return defs.map(([k, label, n]) => `<button class="chip ${ld.status === k ? "active" : ""}" data-ldst="${k}">${label} <span class="c-count">${n}</span></button>`).join("");
  }

  function ldDrawInbox() {
    const panel = $("#ldPanel");
    if (!panel) return;
    const forms = ld.forms || [];
    // A filter pointing at a deleted form renders as "All forms" while still filtering —
    // clear it so the empty state can't lie about which filters are active.
    if (ld.formFilter && !forms.some((f) => String(f.id) === String(ld.formFilter))) ld.formFilter = "";
    panel.innerHTML = `
      <div class="toolbar">
        <div id="ldChips" style="display:flex;gap:8px;flex-wrap:wrap"></div>
        <select class="select-mini" id="ldFormFilter">
          <option value="">All forms</option>
          ${forms.map((f) => `<option value="${f.id}" ${String(ld.formFilter) === String(f.id) ? "selected" : ""}>${esc(f.name)}</option>`).join("")}
        </select>
        <input class="select-mini ld-search" id="ldSearch" type="search" placeholder="Search name, email, phone…" value="${esc(ld.q)}"/>
      </div>
      <div id="ldListWrap"><div class="center-load"><div class="spinner dark"></div></div></div>`;
    $("#ldFormFilter").onchange = () => { ld.formFilter = $("#ldFormFilter").value; ld.limit = LD_PAGE_SIZE; ldLoadLeads(); };
    let debounce = null;
    $("#ldSearch").oninput = () => {
      clearTimeout(debounce);
      debounce = setTimeout(() => { ld.q = $("#ldSearch").value.trim(); ld.limit = LD_PAGE_SIZE; ldLoadLeads(); }, 350);
    };
    ldLoadLeads();
  }

  async function ldLoadLeads() {
    const wrap = $("#ldListWrap");
    if (!wrap) return;
    const seq = ++ld.seq;
    const params = new URLSearchParams();
    if (ld.status) params.set("status_filter", ld.status);
    if (ld.formFilter) params.set("form_id", ld.formFilter);
    if (ld.q) params.set("q", ld.q);
    params.set("limit", String(Math.min(ld.limit || LD_PAGE_SIZE, 200)));
    let d;
    try {
      d = await api("/leads?" + params.toString());
    } catch (ex) {
      if (seq === ld.seq && state.view === "leads" && $("#ldListWrap")) $("#ldListWrap").innerHTML = errBox(ex);
      return;
    }
    if (seq !== ld.seq || state.view !== "leads" || !$("#ldListWrap")) return;
    applyAccessPayload(d);
    ld.leads = d.leads || []; ld.counts = d.counts || {}; ld.total = d.total || 0;
    const chips = $("#ldChips");
    if (chips) {
      chips.innerHTML = ldChipsHtml();
      $$(".chip", chips).forEach((b) => b.onclick = () => { ld.status = b.dataset.ldst; ld.limit = LD_PAGE_SIZE; ldLoadLeads(); });
    }
    const listWrap = $("#ldListWrap");
    if (!ld.leads.length) {
      const filtered = !!(ld.status || ld.q || ld.formFilter);
      const hasForms = (ld.forms || []).length > 0;
      listWrap.innerHTML = `<div class="empty"><div class="emoji">📥</div>
        <h3>${filtered ? "No leads match" : "No leads yet"}</h3>
        <p>${filtered ? "No lead matches the filters you've set." : (hasForms ? "Share a form link to start collecting enquiries." : "Create your first lead form and share the link to start collecting enquiries.")}</p>
        ${filtered ? '<button class="btn btn-soft btn-sm" id="ldEmptyClear">Clear filters</button>' : ""}
        ${!filtered && !hasForms && can("clients.edit") ? '<button class="btn btn-primary btn-sm" id="ldEmptyCreate">+ Create a form</button>' : ""}
        ${!filtered && hasForms ? '<button class="btn btn-soft btn-sm" id="ldEmptyForms">See my forms</button>' : ""}</div>`;
      const b = $("#ldEmptyCreate");
      if (b) b.onclick = () => { ld.tab = "forms"; ldDraw(); ldOpenBuilder(null); };
      const sf = $("#ldEmptyForms");
      if (sf) sf.onclick = () => { ld.tab = "forms"; ldDraw(); };
      // "Try clearing the filters" with nothing to click is a dead end — make it an action.
      const cf = $("#ldEmptyClear");
      if (cf) cf.onclick = () => { ld.status = ""; ld.q = ""; ld.formFilter = ""; ld.limit = LD_PAGE_SIZE; ldDrawInbox(); };
      return;
    }
    listWrap.innerHTML = `<div class="card"><table class="client-table">
      <thead><tr><th>Lead</th><th>Form</th><th>Received</th><th>Status</th></tr></thead>
      <tbody>${ld.leads.map((l, i) => `
        <tr class="ld-row" data-ldi="${i}">
          <td><div class="ld-cell-name">${esc(l.full_name || "—")}${
            (l.files || []).length ? `<span class="ld-clip" title="${l.files.length} attached file${l.files.length === 1 ? "" : "s"}">📎${l.files.length > 1 ? ` ${l.files.length}` : ""}</span>` : ""
          }</div><div class="ld-cell-sub">${esc([l.email, l.phone].filter(Boolean).join(" · ") || "no contact details")}</div></td>
          <td>${esc(l.form_name || "—")}</td>
          <td>${esc(fmtDateTime(l.created_at) || "")}</td>
          <td><span class="ld-pill ${esc(l.status)}">${esc(ldStatusLabel(l.status))}</span></td>
        </tr>`).join("")}</tbody></table></div>`
      + (ld.leads.length < ld.total
        ? `<div class="ld-more">Showing ${ld.leads.length} of ${ld.total} leads <button class="btn btn-ghost btn-sm" id="ldMore">Load more</button></div>`
        : "");
    $$(".ld-row", listWrap).forEach((tr) => tr.onclick = () => ldOpenLead(ld.leads[Number(tr.dataset.ldi)]));
    const more = $("#ldMore");
    // The server clamps at 200, so past that the window slides instead of growing.
    if (more) more.onclick = () => { ld.limit = Math.min((ld.limit || LD_PAGE_SIZE) + LD_PAGE_SIZE, 200); ldLoadLeads(); };
  }

  function ldOpenLead(lead) {
    if (!lead) return;
    const canEdit = can("clients.edit");
    const canConvert = can("clients.create");
    // Raw files are gated on documents.download, not the inbox's clients.view —
    // an enquiry attachment is a passport page like any other.
    const canDownload = can("documents.download");
    const files = lead.files || [];
    const name = lead.full_name || "Lead";
    // #drawer is a bare flex column — content must bring the app's hero/body/footer
    // structure with it, or every child stretches edge-to-edge with no padding.
    openDrawer(`
      <div class="drawer-hero ld-dh">
        <button class="x" id="ldDetailClose" aria-label="Close">×</button>
        <div class="dh-top">
          <div class="dh-avatar" style="background:${avatarColor(name)}">${esc(initials(name))}</div>
          <div style="min-width:0">
            <h2>${esc(name)}</h2>
            <div class="dh-sub">via ${esc(lead.form_name || "a deleted form")} · ${esc(fmtDateTime(lead.created_at) || "")}</div>
          </div>
        </div>
        <div class="ld-dh-chips">
          <span class="ld-pill ${esc(lead.status)}">${esc(ldStatusLabel(lead.status))}</span>
          ${lead.email ? `<a class="ld-dh-chip" href="mailto:${encodeURIComponent(lead.email)}" title="Email this lead"><i>✉️</i>${esc(lead.email)}</a>` : ""}
          ${lead.phone ? `<a class="ld-dh-chip" href="tel:${encodeURIComponent(lead.phone.replace(/[^\d+]/g, ""))}" title="Call this lead"><i>📞</i>${esc(lead.phone)}</a>` : ""}
        </div>
      </div>
      <div class="drawer-body">
        <div class="cp-sub-label">What they told you</div>
        <div class="ld-detail-kv">
          ${(lead.answers || []).filter((a) => a.type !== "file").map((a) => `<div class="it${a.type === "textarea" || String(a.value || "").length > 80 ? " wide" : ""}"><label>${esc(a.label)}</label><div>${esc(a.value)}</div></div>`).join("")
            || '<div class="ld-detail-empty">No answers recorded.</div>'}
        </div>
        ${files.length ? `
          <div class="cp-sub-label" style="margin-top:18px">Files they attached</div>
          <div class="ld-files">
            ${files.map((f) => `
              <div class="ld-file">
                <span class="ld-file-i">📄</span>
                <span class="ld-file-n">${esc(f.filename)}<span>${esc(f.field_label || "Attachment")}${f.file_size ? ` · ${fmtSize(f.file_size)}` : ""}</span></span>
                ${canDownload ? `<button class="btn btn-soft btn-sm" data-ldfile="${f.id}">Download</button>`
                  : '<span class="ld-file-lock" title="Your role can\'t download files">🔒</span>'}
              </div>`).join("")}
          </div>
          ${lead.status === "converted" ? "" : '<div class="ld-detail-meta"><i>📥</i> These move into the client\'s documents when you convert this lead.</div>'}` : ""}
        ${lead.source ? `<div class="ld-detail-meta"><i>🌐</i> Came from <b>${esc(lead.source)}</b></div>` : ""}
        ${lead.converted_client_id ? '<div class="ld-detail-meta"><i>✅</i> Already converted into a client.</div>' : ""}
      </div>
      <div class="ld-detail-actions">
        ${canConvert && lead.status !== "converted" ? '<button class="btn btn-primary btn-sm" id="ldConvertBtn">Convert to client →</button>' : ""}
        ${lead.converted_client_id ? '<button class="btn btn-soft btn-sm" id="ldOpenClientBtn">Open client</button>' : ""}
        ${canEdit ? `<label class="ld-status-pick">Status
          <select class="select-mini" id="ldStatusSel" title="Lead status">${LD_STATUSES.map((s) => `<option value="${s}" ${lead.status === s ? "selected" : ""}>${ldStatusLabel(s)}</option>`).join("")}</select></label>` : ""}
        ${canEdit ? '<button class="btn btn-danger btn-sm" id="ldDeleteBtn" style="margin-left:auto">Delete</button>' : ""}
      </div>`);
    $("#ldDetailClose").onclick = closeDrawer;
    $$("[data-ldfile]").forEach((btn) => {
      btn.onclick = async () => {
        const old = btn.textContent;
        btn.disabled = true; btn.textContent = "…";
        try { await downloadFile(`${API}/leads/${lead.id}/files/${btn.dataset.ldfile}/download`); }
        catch (ex) { toast(ex.message, "error"); }
        finally { btn.disabled = false; btn.textContent = old; }
      };
    });
    const conv = $("#ldConvertBtn");
    if (conv) conv.onclick = () => ldConvert(lead);
    const oc = $("#ldOpenClientBtn");
    if (oc) oc.onclick = () => { closeDrawer(); openClient(lead.converted_client_id); };
    const sel = $("#ldStatusSel");
    // A sequence guard rather than a disable: this is a <select>, and greying it out
    // mid-change would fight the user's own next pick. Changing it three times quickly
    // fires three PATCHes that can land out of order, so only the newest one is allowed to
    // write back — an older reply arriving late would otherwise re-label the lead with a
    // status the user has already moved on from.
    ld.statusSeq = ld.statusSeq || 0;
    if (sel) sel.onchange = async () => {
      const want = sel.value;
      const seq = ++ld.statusSeq;
      sel.setAttribute("aria-busy", "true");
      try {
        const r = await api(`/leads/${lead.id}/status`, { method: "PATCH", body: { status: want } });
        if (seq !== ld.statusSeq) return;   // superseded by a newer pick
        lead.status = (r.lead && r.lead.status) || want;
        toast("Lead updated", "success");
        ldLoadLeads(); ldRefreshFormCounters();
      } catch (ex) { if (seq === ld.statusSeq) toast(ex.message, "error"); }
      finally { if (seq === ld.statusSeq && sel.isConnected) sel.removeAttribute("aria-busy"); }
    };
    const del = $("#ldDeleteBtn");
    if (del) del.onclick = async () => {
      closeDrawer();
      if (!(await confirmModal("This lead and their submitted details will be permanently removed.", { title: "Delete lead?", okText: "Delete" }))) return;
      try {
        await api(`/leads/${lead.id}`, { method: "DELETE" });
        toast("Lead deleted", "success");
        ldLoadLeads(); ldRefreshFormCounters();
      } catch (ex) { toast(ex.message, "error"); }
    };
  }

  // Refresh the per-form counters (and hero stats) without repainting the inbox list.
  async function ldRefreshFormCounters() {
    try {
      const d = await api("/lead-forms");
      if (state.view !== "leads") return;
      ld.forms = d.forms || ld.forms;
    } catch (e) { /* cosmetic only */ }
  }

  async function ldConvert(lead) {
    closeDrawer();
    await ensureTeam();   // the intake form reads teamMembersCache for the counselor picker
    const pseudo = {
      full_name: lead.full_name || "",
      email: lead.email || "",
      phone: lead.phone || "",
      lead_source: "website",
      lead_source_detail: String(lead.form_name || "Lead form").slice(0, 120),
    };
    // Soft destination match: a "country"/"destination" answer that names a catalog
    // country pre-picks it; anything fuzzier stays with the counselor.
    const countries = (state.catalog && state.catalog.countries) || [];
    for (const a of (lead.answers || [])) {
      const hay = (String(a.label || "") + " " + String(a.key || "")).toLowerCase();
      if (!/countr|destination/.test(hay)) continue;
      const val = String(a.value || "").trim().toLowerCase();
      const hit = countries.find((ct) => val && (String(ct.name || "").toLowerCase() === val || String(ct.code || "").toLowerCase() === val));
      if (hit) { pseudo.destination_country_code = hit.code; break; }
    }
    openClientForm(pseudo, {
      forceCreate: true,
      heading: "Convert lead to client",
      onCreated: async (client) => {
        let copied = 0;
        try {
          const r = await api(`/leads/${lead.id}/mark-converted`, { method: "POST", body: { client_id: client.id } });
          copied = r.documents_copied || 0;
        } catch (e) { /* the client exists either way — linking back is best-effort */ }
        toast(copied
          ? `Lead converted — ${copied} attached file${copied === 1 ? "" : "s"} filed under Documents`
          : "Lead converted to client", "success");
        openClient(client.id);
        return true;
      },
    });
    // Carry the full submission into the first note so nothing is lost in translation.
    const noteEl = document.querySelector("#clientForm [name=initial_note]");
    if (noteEl && !noteEl.value) {
      noteEl.value = `From lead form "${lead.form_name || ""}" (${fmtDateTime(lead.created_at) || ""}):\n` +
        (lead.answers || []).map((a) => `${a.label}: ${a.value}`).join("\n");
    }
  }

  /* Inline SVG rather than emoji: at 30px an emoji ⏸/🗑 renders washed-out and
     can't pick up the button's hover colour (or the red danger state). */
  const LD_ICON = {
    pause: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M9 5v14M15 5v14"/></svg>',
    play: '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l13-7.5z"/></svg>',
    rotate: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1"/><path d="M20.5 4.5V10H15"/></svg>',
    trash: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M10 4h4M9 7v12M15 7v12M6 7l1 13h10l1-13"/></svg>',
  };

  /* ---------------- forms ---------------- */
  function ldDrawForms() {
    const panel = $("#ldPanel");
    if (!panel) return;
    const forms = ld.forms || [];
    const canEdit = can("clients.edit");
    panel.innerHTML = `
      <div class="toolbar">
        <div style="font-weight:800">${forms.length ? `${forms.length} form${forms.length === 1 ? "" : "s"}` : ""}</div>
        ${canEdit ? '<button class="btn btn-primary btn-sm" id="ldNewForm" style="margin-left:auto">+ New form</button>' : ""}
      </div>
      ${forms.length
        ? `<div class="ld-form-grid">${forms.map((f, i) => ldFormCardHtml(f, i, canEdit)).join("")}</div>`
        : `<div class="empty"><div class="emoji">🧾</div><h3>No forms yet</h3><p>Create a branded form, then share its link over email, WhatsApp or social media to collect enquiries.</p>${canEdit ? '<button class="btn btn-primary btn-sm" id="ldEmptyForm">+ Create your first form</button>' : ""}</div>`}`;
    const nb = $("#ldNewForm"); if (nb) nb.onclick = () => ldOpenBuilder(null);
    const eb = $("#ldEmptyForm"); if (eb) eb.onclick = () => ldOpenBuilder(null);
    $$("[data-ldact]", panel).forEach((b) => {
      b.onclick = async (e) => {
        e.stopPropagation();
        if (b.disabled) return;
        const f = (ld.forms || [])[Number(b.dataset.ldfi)];
        if (!f) return;
        const act = b.dataset.ldact;
        // pause/rotate/del write; the rest are copy, open, and modal-openers. Held for the
        // duration because these mini-buttons are the same size as their icon and give no
        // other feedback — a second Pause click just fires a second PATCH.
        const writes = act === "pause" || act === "rotate" || act === "del";
        if (writes) b.disabled = true;
        try {
          if (act === "copy") ldCopyLink(f);
          else if (act === "open") window.open(f.link, "_blank", "noopener");
          else if (act === "share") ldOpenShare(f);
          else if (act === "edit") ldOpenBuilder(f);
          else if (act === "pause") await ldTogglePause(f);
          else if (act === "rotate") await ldRotate(f);
          else if (act === "del") await ldDeleteForm(f);
        } finally {
          if (writes && b.isConnected) b.disabled = false;
        }
      };
    });
  }

  function ldFormCardHtml(f, i, canEdit) {
    const fieldCount = (f.fields || []).length;
    return `<div class="card ${f.is_active ? "" : "ld-paused"}"><div class="card-body ld-form-card">
      <div class="ld-form-top">
        <div style="min-width:0">
          <h4>${esc(f.name)}</h4>
          <div class="ld-form-meta">${f.total_leads || 0} lead${(f.total_leads || 0) === 1 ? "" : "s"}${f.new_leads ? ` · <b>${f.new_leads} new</b>` : ""} · ${fieldCount} field${fieldCount === 1 ? "" : "s"}</div>
        </div>
        <span class="ld-form-badges">
          <span class="ld-pill ${f.is_active ? "converted" : "closed"}">${f.is_active ? "Live" : "Paused"}</span>
          ${canEdit ? `<span class="ld-act-quiet">
            <button class="lf-b-mini" data-ldact="pause" data-ldfi="${i}" title="${f.is_active ? "Pause this form" : "Resume this form"}" aria-label="${f.is_active ? "Pause form" : "Resume form"}">${f.is_active ? LD_ICON.pause : LD_ICON.play}</button>
            <button class="lf-b-mini" data-ldact="rotate" data-ldfi="${i}" title="Generate a new link — the current one stops working" aria-label="New link">${LD_ICON.rotate}</button>
            <button class="lf-b-mini danger" data-ldact="del" data-ldfi="${i}" title="Delete this form (collected leads are kept)" aria-label="Delete form">${LD_ICON.trash}</button>
          </span>` : ""}
        </span>
      </div>
      <div class="ld-link-row">
        <input type="text" readonly value="${esc(f.link)}" onclick="this.select()" aria-label="Shareable form link"/>
        <button class="btn btn-soft btn-sm" data-ldact="copy" data-ldfi="${i}">Copy</button>
      </div>
      <div class="ld-form-actions">
        <button class="btn btn-ghost btn-sm" data-ldact="open" data-ldfi="${i}">Preview</button>
        ${canEdit && can("emails.send") ? `<button class="btn btn-ghost btn-sm" data-ldact="share" data-ldfi="${i}"><i>✉️</i>Email link</button>` : ""}
        ${canEdit ? `<button class="btn btn-ghost btn-sm" data-ldact="edit" data-ldfi="${i}">Edit fields</button>` : ""}
      </div>
    </div></div>`;
  }

  async function ldCopyLink(f) {
    try {
      await navigator.clipboard.writeText(f.link);
      toast("Link copied", "success");
    } catch (e) {
      promptModal("Copy this link:", { title: "Form link", value: f.link, okText: "Done" });
    }
  }

  function ldPatchForm(updated) {
    if (!updated) return;
    const idx = (ld.forms || []).findIndex((x) => x.id === updated.id);
    if (idx >= 0) {
      // Mutation responses don't recount leads — keep the counters we had.
      updated.total_leads = ld.forms[idx].total_leads;
      updated.new_leads = ld.forms[idx].new_leads;
      ld.forms[idx] = updated;
    } else {
      ld.forms = [updated].concat(ld.forms || []);
    }
    ldDraw();
  }

  async function ldTogglePause(f) {
    try {
      const r = await api(`/lead-forms/${f.id}`, { method: "PATCH", body: { is_active: !f.is_active } });
      ldPatchForm(r.form);
      toast(r.form && r.form.is_active ? "Form is live again" : "Form paused — its link now shows a “not accepting responses” notice", "success");
    } catch (ex) { toast(ex.message, "error"); }
  }

  async function ldRotate(f) {
    if (!(await confirmModal("Anyone holding the current link will see “link invalid”. You'll get a fresh link to share.", { title: "Generate a new link?", okText: "New link" }))) return;
    try {
      const r = await api(`/lead-forms/${f.id}/rotate-link`, { method: "POST" });
      ldPatchForm(r.form);
      if (r.form) ldCopyLink(r.form);
    } catch (ex) { toast(ex.message, "error"); }
  }

  async function ldDeleteForm(f) {
    if (!(await confirmModal(`"${f.name}" will stop accepting responses and its link will die. Leads already collected stay in the inbox.`, { title: "Delete this form?", okText: "Delete" }))) return;
    try {
      await api(`/lead-forms/${f.id}`, { method: "DELETE" });
      toast("Form deleted", "success");
      await ldRefreshForms();
    } catch (ex) { toast(ex.message, "error"); }
  }

  function ldOpenShare(f) {
    openModal(`
      <div class="modal-head"><h3>Email this form link</h3><button class="x" onclick="__ent.closeModal()">×</button></div>
      <form id="ldShareForm">
      <div class="modal-body">
        <div class="ld-share-what">
          <span class="ld-share-label">Sending</span>
          <b>${esc(f.title || f.name)}</b>
          <span class="ld-share-url">${esc(f.link)}</span>
        </div>
        <div class="field"><label>Send to</label><input type="email" name="to_email" required placeholder="prospect@email.com"/></div>
        <div class="field"><label>Add a note (optional)</label><textarea name="note" maxlength="400" style="min-height:70px" placeholder="Hi! Fill this in and we'll get back to you within a day."></textarea></div>
        <p class="mw-hint">The email carries your company name and logo, and replies come straight to your inbox.</p>
        <div id="ldShareErr" class="auth-error hidden"></div>
      </div>
      <div class="modal-foot">
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary" id="ldShareBtn">Send</button>
      </div></form>`);
    $("#ldShareForm").onsubmit = async (e) => {
      e.preventDefault();
      const fEl = e.target; const btn = $("#ldShareBtn"); const err = $("#ldShareErr");
      err.classList.add("hidden");
      btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
      try {
        const r = await api(`/lead-forms/${f.id}/share-email`, {
          method: "POST",
          body: { to_email: fEl.elements.to_email.value.trim(), note: fEl.elements.note.value.trim() || null },
        });
        closeModal();
        toast(r.message || "Sent", r.email_sent === false ? "error" : "success");
      } catch (ex) {
        err.textContent = ex.message; err.classList.remove("hidden");
      } finally { btn.disabled = false; btn.textContent = "Send"; }
    };
  }

  /* ---------------- form builder ---------------- */
  function ldOpenBuilder(form) {
    const isEdit = !!form;
    // Work on a deep copy — cancel must leave the card untouched.
    const draft = JSON.parse(JSON.stringify(isEdit ? (form.fields || []) : LD_DEFAULT_FIELDS));
    const myEmail = (state.me && state.me.user && state.me.user.email) || "";
    openModal(`
      <div class="modal-head"><h3>${isEdit ? "Edit form" : "New lead form"}</h3><button class="x" onclick="__ent.closeModal()">×</button></div>
      <form id="ldBuildForm">
      <div class="modal-body">
        <div class="lf-b-sec"><span class="cp-sub-label">The basics</span></div>
        <div class="lf-b-grid">
          <div class="field"><label>Form name (internal) *</label><input name="name" required maxlength="80" value="${esc(isEdit ? form.name : "")}" placeholder="e.g. Website enquiries"/><div class="hint">Only your team sees this.</div></div>
          <div class="field"><label>Public title</label><input name="title" maxlength="120" value="${esc(isEdit ? form.title || "" : "")}" placeholder="e.g. Start your study-abroad journey"/><div class="hint">The heading on the shared page. Defaults to “Get in touch”.</div></div>
          <div class="field span2"><label>Intro text (shown under the title)</label><textarea name="intro_text" maxlength="600" style="min-height:70px" placeholder="Tell us a little about your plans and we'll get back to you within 24 hours.">${esc(isEdit ? form.intro_text || "" : "")}</textarea></div>
        </div>
        <div class="lf-b-sec"><span class="cp-sub-label">What you're asking for</span><span class="lf-b-count" id="ldFieldCount"></span></div>
        <div id="ldFieldList" class="lf-b-list"></div>
        <button type="button" class="lf-b-add" id="ldAddField">+ Add a field</button>
        <div class="lf-b-sec"><span class="cp-sub-label">After they submit</span></div>
        <div class="lf-b-grid">
          <div class="field"><label>Submit button label</label><input name="submit_label" maxlength="40" value="${esc(isEdit ? form.submit_label || "" : "")}" placeholder="Submit"/></div>
          <div class="field"><label>Email me each new lead at</label><input type="email" name="notify_email" maxlength="200" value="${esc(isEdit ? form.notify_email || "" : myEmail)}" placeholder="Leave empty for no email alerts"/></div>
          <div class="field span2"><label>Thank-you message</label><input name="success_message" maxlength="400" value="${esc(isEdit ? form.success_message || "" : "")}" placeholder="Thanks! Your details were sent — the team will get back to you shortly."/></div>
        </div>
        <div id="ldBuildErr" class="auth-error hidden"></div>
      </div>
      <div class="modal-foot">
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary" id="ldBuildSave">${isEdit ? "Save changes" : "Create form"}</button>
      </div></form>`, { wide: true });

    function drawFields() {
      const count = $("#ldFieldCount");
      if (count) count.textContent = draft.length + (draft.length === 1 ? " field" : " fields") + " · max 20";
      $("#ldFieldList").innerHTML = draft.map((f, i) => `
        <div class="lf-b-field">
          <div class="lf-b-row">
            <span class="lf-b-num">${i + 1}</span>
            <input class="lf-b-label" type="text" data-lf="label" data-i="${i}" maxlength="120" value="${esc(f.label)}" placeholder="Field label — e.g. Full name"/>
            <select class="lf-b-type" data-lf="type" data-i="${i}">${Object.keys(LD_TYPE_LABELS).map((t) => `<option value="${t}" ${f.type === t ? "selected" : ""}>${LD_TYPE_LABELS[t]}</option>`).join("")}</select>
            <label class="lf-b-req" title="Make this field mandatory"><input type="checkbox" data-lf="required" data-i="${i}" ${f.required ? "checked" : ""}/><span>Required</span></label>
            <span class="lf-b-tools">
              <button type="button" class="lf-b-mini" data-lf="up" data-i="${i}" title="Move up" aria-label="Move up" ${i === 0 ? "disabled" : ""}>↑</button>
              <button type="button" class="lf-b-mini" data-lf="down" data-i="${i}" title="Move down" aria-label="Move down" ${i === draft.length - 1 ? "disabled" : ""}>↓</button>
              <button type="button" class="lf-b-mini danger" data-lf="del" data-i="${i}" title="Remove field" aria-label="Remove field">✕</button>
            </span>
          </div>
          ${f.type === "select" ? `<div class="lf-b-opts"><label>Dropdown choices <span>(comma-separated)</span></label><input type="text" data-lf="options" data-i="${i}" value="${esc((f.options || []).join(", "))}" placeholder="USA, UK, Canada"/></div>` : ""}
          ${f.type === "file" ? `<div class="lf-b-opts"><label>How many files <span>(they can attach up to this many)</span></label>
            <select class="lf-b-maxfiles" data-lf="max_files" data-i="${i}">${
              Array.from({ length: LD_MAX_FILES_PER_FIELD }, (_, n) => n + 1).map((n) =>
                `<option value="${n}" ${Number(f.max_files || 1) === n ? "selected" : ""}>${n} file${n === 1 ? "" : "s"}</option>`).join("")
            }</select>
            <div class="hint">PDF, images, Word/Excel, CSV or text · max 10 MB each. Files land on the lead and move into the client's documents when you convert them.</div></div>` : ""}
        </div>`).join("");
      $$("#ldFieldList [data-lf]").forEach((el) => {
        const i = Number(el.dataset.i);
        const kind = el.dataset.lf;
        if (el.tagName === "INPUT" && el.type === "text") {
          // The field rows live inside the builder <form>; Enter would implicitly submit
          // and publish a half-built form. Add a field instead.
          el.onkeydown = (ev) => { if (ev.key === "Enter") { ev.preventDefault(); if (kind === "label") $("#ldAddField").click(); } };
        }
        if (kind === "label") el.oninput = () => { draft[i].label = el.value; };
        else if (kind === "type") el.onchange = () => {
          // Guard the file-field cap here rather than letting the save 400 —
          // switching a field back is a click, re-reading an error is not.
          if (el.value === "file" && draft[i].type !== "file"
              && draft.filter((d) => d.type === "file").length >= LD_MAX_FILE_FIELDS) {
            toast(`A form can ask for at most ${LD_MAX_FILE_FIELDS} file uploads`, "error");
            el.value = draft[i].type;
            return;
          }
          draft[i].type = el.value;
          if (el.value === "select" && !draft[i].options) draft[i].options = [];
          if (el.value === "file" && !draft[i].max_files) draft[i].max_files = 1;
          drawFields();
        };
        else if (kind === "required") el.onchange = () => { draft[i].required = el.checked; };
        else if (kind === "options") el.oninput = () => { draft[i].options = el.value.split(",").map((s) => s.trim()).filter(Boolean); };
        else if (kind === "max_files") el.onchange = () => { draft[i].max_files = Number(el.value) || 1; };
        else if (kind === "up") el.onclick = () => { if (i > 0) { const t = draft[i - 1]; draft[i - 1] = draft[i]; draft[i] = t; drawFields(); } };
        else if (kind === "down") el.onclick = () => { if (i < draft.length - 1) { const t = draft[i + 1]; draft[i + 1] = draft[i]; draft[i] = t; drawFields(); } };
        else if (kind === "del") el.onclick = () => { draft.splice(i, 1); drawFields(); };
      });
    }
    drawFields();
    $("#ldAddField").onclick = () => {
      if (draft.length >= 20) { toast("A form can have at most 20 fields", "error"); return; }
      draft.push({ label: "", type: "text", required: false });
      drawFields();
      const inputs = $$('#ldFieldList [data-lf="label"]');
      const last = inputs[inputs.length - 1];
      if (last) last.focus();
    };

    $("#ldBuildForm").onsubmit = async (e) => {
      e.preventDefault();
      const fEl = e.target; const btn = $("#ldBuildSave"); const err = $("#ldBuildErr");
      err.classList.add("hidden");
      // fEl.elements[...] rather than fEl.name — "name" collides with the form's own
      // built-in name property and would read "" instead of the input.
      const gv = (n) => (fEl.elements[n] ? String(fEl.elements[n].value || "").trim() : "");
      const body = {
        name: gv("name"),
        title: gv("title") || null,
        intro_text: gv("intro_text") || null,
        fields: draft
          .map((f) => ({
            label: String(f.label || "").trim(),
            type: f.type,
            required: !!f.required,
            options: f.type === "select" ? (f.options || []) : undefined,
            max_files: f.type === "file" ? (Number(f.max_files) || 1) : undefined,
          }))
          .filter((f) => f.label),
        submit_label: gv("submit_label") || null,
        success_message: gv("success_message") || null,
        notify_email: gv("notify_email") || null,
      };
      if (!body.fields.length) {
        err.textContent = "Add at least one field (labels can't be empty).";
        err.classList.remove("hidden");
        return;
      }
      btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
      try {
        const r = isEdit
          ? await api(`/lead-forms/${form.id}`, { method: "PATCH", body })
          : await api("/lead-forms", { method: "POST", body });
        closeModal();
        toast(isEdit ? "Form updated" : "Form created — the link is ready to share", "success");
        if (isEdit) ldPatchForm(r.form);
        else { ld.tab = "forms"; await ldRefreshForms(); if (r.form) ldCopyLink(r.form); }
      } catch (ex) {
        err.textContent = ex.message; err.classList.remove("hidden");
      } finally { btn.disabled = false; btn.textContent = isEdit ? "Save changes" : "Create form"; }
    };
  }

  window.__ent = {
    go: navigate, openClient, openClientForm: () => openClientForm(null), editClient, deleteClient, setStatus,
    closeModal, closeDrawer, removeMember, checkout,
    // Team sub-tabs. `changeRole` is gone on purpose: the legacy 3-option role <select>
    // it backed would silently convert a branch manager or a custom role into "editor".
    // Role changes now go through Edit access (PATCH /team/users/{id}/access).
    teamTab: teamGoTab,
    applyCreditCoupon, removeCreditCoupon, applyBillingCoupon, removeBillingCoupon, syncCouponApply,
    cancelPlanRenewal,
    topup: openCreditCheckout,
    saveBank: saveLinkedAccount, refreshBank: refreshLinkedAccount,
    finAdd: finAddEntry, finTab: finGoTab,
    viewClients: openClientsFiltered, viewVisaType, clearSearch: clearClientSearch,
    viewInterview: viewInterviewSession, sendInterview: openSendInterviewPicker,
    setUniStatus, removeUni,
    calPrev, calNext, calToday, calSetMonth, calSetYear, calEvent, calAdd, calDelete, calToggleDone,
    calEditEvent, calOpenClient,
    dashEvent,
  };

  /* ============================================================
     INIT
     ============================================================ */
  setupAuth();
  wireInfoTips();
  boot().then(() => {
    // Signed in on another origin and got redirected here — confirm it now that we're in.
    if (consumeSignedInFlag() && $("#appView").classList.contains("active")) {
      toast("Login successful — welcome back!", "success");
    }
  });
})();
