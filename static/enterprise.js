/* ===========================================================================
   Rilono Enterprise — Visa Consultancy CRM frontend
   =========================================================================== */
(function () {
  "use strict";

  const API = "/api/enterprise";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  const state = {
    me: null,
    perms: { can_view_data: true, can_edit_data: false, can_manage_users: false },
    subscription: null,
    credits: null,
    catalog: null,
    view: "dashboard",
    clients: [],
    statusCounts: {},
    filters: { status: "", category: "", country: "", q: "" },
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
  });
  function clientHeroTheme(client) {
    let code = String(client.destination_country_code || client.country?.code || "").trim().toUpperCase();
    if (code === "GB") code = "UK";
    return CLIENT_HERO_THEMES[code] || { key: "intl", code: code || "INTL" };
  }
  // How prominently to surface the mock-interview feature, by destination. Whether a real
  // visa interview happens drives the emphasis — the feature is ALWAYS available (tab +
  // send flow), we only change how hard we push it:
  //   standard — US F-1: mandatory consular interview → push it ("Recommended", Overview CTA).
  //   possible — UK: occasional credibility interview → available, not badged.
  //   rare     — CA study permit (SOP is the "interview"), AU subclass 500 (Genuine Student is
  //              written), DE Type-D (embassy intake, not an adjudicating interview), IE →
  //              available but shown as "Optional", no highlight.
  // Unknown/blank codes default to "standard" (fail open — never hide the feature for a
  // destination we haven't classified). Mirrors the per-country gating already used for the
  // UK maintenance-funds card.
  const INTERVIEW_RELEVANCE = Object.freeze({
    US: "standard", UK: "possible", CA: "rare", AU: "rare", DE: "rare", IE: "rare",
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
  // ---- Display currency (from Settings → company country; live FX, billing stays INR) ----
  function orgCur() {
    const c = state.me && state.me.organization && state.me.organization.display_currency;
    return (c && c.code && c.code !== "INR" && Number(c.rate_from_inr) > 0) ? c : null;
  }
  function fmtInr(amountInr) {
    const n = Number(amountInr || 0);
    const cur = orgCur();
    if (!cur) return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
    const v = n * Number(cur.rate_from_inr);
    return cur.symbol + v.toLocaleString("en-US", { maximumFractionDigits: v >= 1000 ? 0 : 2 });
  }
  function fmtPaise(p) {
    return fmtInr(Number(p || 0) / 100);
  }
  // Razorpay charges in INR — show the real billed amount wherever a payment starts.
  function inrBilledNote(paise) {
    if (!orgCur()) return "";
    const inr = "₹" + (Number(paise || 0) / 100).toLocaleString("en-IN", { maximumFractionDigits: 2 });
    return `<div style="font-size:11.5px;color:var(--muted);margin-top:2px">Billed in INR: ${inr} · shown in ${orgCur().code} at today's rate</div>`;
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
    return `<div class="coupon-bar">
      <input id="${inputId}" class="coupon-input" placeholder="Have a discount code?" maxlength="40"
        onkeydown="if(event.key==='Enter'){event.preventDefault();__ent.${applyFn}();}" />
      <button class="btn btn-primary btn-sm" onclick="__ent.${applyFn}()">Apply</button>
    </div>`;
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

  async function api(path, opts) {
    opts = opts || {};
    const controller = new AbortController();
    const timeoutMs = opts.timeout || DEFAULT_API_TIMEOUT_MS;
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let res;
    try {
      res = await fetch(API + path, {
        method: opts.method || "GET",
        credentials: "include",
        headers: opts.body ? { "Content-Type": "application/json" } : {},
        body: opts.body ? JSON.stringify(opts.body) : undefined,
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

  /* ---------------- overlay / modal / drawer ---------------- */
  function openModal(html) {
    const m = $("#modal"); m.innerHTML = html;
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

  /* ---------------- landmark photo ---------------- */
  // Real bundled landmark photo per country. The parent .country-art carries a
  // gradient background, so if an image is ever missing it degrades gracefully.
  function landmarkArt(country) {
    const code = String(country.code || "").toLowerCase();
    return `<img class="lk-img" src="/static/destinations/${esc(code)}.jpg" alt="${esc(country.landmark || country.name || "")}" loading="lazy" onerror="this.style.display='none'">`;
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
        const turnstileToken = await getEnterpriseTurnstileToken("forgot");
        btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Sending…';
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
      errEl.classList.add("hidden");
      try {
        const body = { email };
        const turnstileToken = await getEnterpriseTurnstileToken("signup");
        if (turnstileToken) body.cf_turnstile_token = turnstileToken;
        btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> ' + busyLabel;
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
      try {
        const body = { email: f.email.value.trim(), password: f.password.value };
        const turnstileToken = await getEnterpriseTurnstileToken("login");
        if (turnstileToken) body.cf_turnstile_token = turnstileToken;
        btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Signing in…';
        const data = await api("/login", { method: "POST", body });
        if (data.onboarding_required) { showOnboard(); return; }
        if (redirectToPortalIfNeeded(data)) return;
        await boot({ fromAuthAction: true });
      } catch (ex) {
        showLoginError(ex.message);
        resetEnterpriseTurnstile("login");
      } finally { btn.disabled = false; btn.textContent = "Sign in"; }
    };

    $("#onboardForm").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target; const btn = $("#onboardBtn");
      const err = $("#onboardError"); err.classList.add("hidden");
      btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Finishing…';
      try {
        await api("/onboarding", { method: "POST", body: { company_name: f.company_name.value.trim(), subdomain_slug: f.subdomain_slug.value.trim().toLowerCase() } });
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
    window.location.assign(target.toString());
    return true;
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
    state.me = me;
    state.perms = me.permissions || state.perms;
    state.subscription = me.subscription || null;
    state.credits = me.credits || null;

    // brand + user chip
    const org = me.organization || {};
    $("#brandName").textContent = org.company_name || "Your Consultancy";
    if (org.logo_url) { const l = $("#brandLogo"); l.src = org.logo_url; l.style.display = ""; }
    const u = me.user || {};
    $("#userName").textContent = u.full_name || u.email || "User";
    $("#userRole").textContent = ((me.membership && me.membership.role) || "member").replace(/^\w/, (c) => c.toUpperCase());
    const [c1] = avatarColor(u.email);
    $("#userAvatar").textContent = (initials(u.full_name || u.email) || "U").toUpperCase();
    $("#userAvatar").style.background = `linear-gradient(135deg, ${c1}, ${avatarColor(u.email)[1]})`;
    updatePlanChip();
    renderDpaBanner();
    maybeShowEntHeardAbout(me);

    if (!state.perms.can_edit_data) $("#topAddClient").classList.add("hidden");

    try { state.catalog = await api("/catalog"); } catch (e) { state.catalog = { countries: [], categories: [], stages: [], priorities: [] }; }

    // Restore the view from the URL (deep-link / refresh / bookmark), replacing the
    // history entry so we don't add a spurious one on first load.
    applyRoute(location.pathname, { replace: true });
    refreshCalendarBadge();  // keep the overdue-reminder badge correct without needing to open Calendar
    wireNotifications();
    refreshNotifications();  // bell badge correct from first paint
  }

  function updatePlanChip() {
    const s = state.subscription;
    const cr = state.credits;
    if (cr && cr.balance_credits != null) {
      $("#brandPlan").textContent = cr.balance_credits + " credits";
    } else {
      // No plan tiers exist — the platform is free CRM + pay-as-you-go credits.
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
        else if (rt === "credits") navigate("credits");
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
  // "billing" removed: the plan-tier system is dormant (free CRM + credits is the model),
  // so the dead Plans page must not be reachable even by deep link. Code kept for reversibility.
  const ROUTE_VIEWS = ["dashboard", "clients", "calendar", "coursefinder", "ai", "team", "credits", "finance", "support", "settings"];
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
    const titles = { dashboard: "Dashboard", clients: "Clients", calendar: "Calendar", coursefinder: "Course Finder", ai: "Rilono AI Assistant", team: "Team", credits: "Credits & Billing", finance: "Finance", support: "Help & Support", billing: "Plans & Billing", settings: "Settings" };
    $("#viewTitle").textContent = titles[view] || "";
    $("#globalSearchBox").style.display = view === "clients" || view === "dashboard" ? "" : "none";
    syncUrl(viewToPath(view), opts);
    if (view === "dashboard") renderDashboard();
    else if (view === "clients") renderClients();
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

  function trialBanner() {
    // Rilono Enterprise is free — no trial countdown or upgrade prompts.
    return "";
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
    const canAccept = !!(state.perms && state.perms.can_manage_users);
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
    try { d = await api("/dashboard"); } catch (ex) { c.innerHTML = errBox(ex); return; }
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

    const countryCards = (d.top_countries.length ? d.top_countries : []).map((ct) =>
      `<div class="country-card clickable" role="button" tabindex="0" onclick="__ent.viewClients({country:'${ct.code}'})">
        <div class="country-art" style="background:linear-gradient(135deg,${ct.gradient_from || "#6366f1"},${ct.gradient_to || "#8b5cf6"})">${landmarkArt(ct)}
        <span class="flag">${ct.flag_emoji || "🌐"}</span><span class="cnt">${ct.count}</span></div>
        <div class="country-meta"><b>${esc(ct.name)}</b><span>${esc(ct.landmark || "")}</span></div></div>`).join("");

    const deadlines = d.upcoming_deadlines.length ? d.upcoming_deadlines.map((cl) => {
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

    c.innerHTML = `
      ${trialBanner()}
      <div class="kpi-grid">
        ${kpiCard("linear-gradient(135deg,#6366f1,#8b5cf6)", "👥", "Total clients", k.total_clients, "View all clients", "__ent.viewClients({})")}
        ${kpiCard("linear-gradient(135deg,#0ea5e9,#22d3ee)", "📂", "Active cases", k.active_clients, "in progress", "__ent.viewClients({scope:'active',label:'Active cases'})")}
        ${kpiCard("linear-gradient(135deg,#10b981,#34d399)", "✅", "Approved", k.approved, k.approval_rate != null ? k.approval_rate + "% approval rate" : "View approved", "__ent.viewClients({status:'approved'})")}
        ${kpiCard("linear-gradient(135deg,#f59e0b,#f97316)", "🆕", "New this month", k.new_this_month, "this month", "__ent.viewClients({scope:'month',label:'New this month'})")}
      </div>
      ${state.perms && state.perms.can_edit_data ? `
      <div class="dash-cta">
        <div class="dash-cta-ic">🎤</div>
        <div class="dash-cta-txt"><b>Send a mock visa interview</b><span>Email a student a secure link so they can practise on their own — Rilono AI plays the visa officer and you see every result here.</span></div>
        <button class="btn btn-primary dash-cta-btn" onclick="__ent.sendInterview()">✉ Send mock interview</button>
      </div>` : ""}
      <div class="grid-2">
        <div class="card"><div class="card-head"><h3>Visa pipeline</h3><button class="link" onclick="__ent.go('clients')">View all →</button></div>
          <div class="card-body">${pipeRows}</div></div>
        <div class="card"><div class="card-head"><h3>By visa type</h3></div>
          <div class="card-body"><div class="cat-grid">${vtCells}</div></div></div>
      </div>
      <div class="card" style="margin-top:20px"><div class="card-head"><h3>Destinations</h3></div>
        <div class="card-body">${countryCards ? `<div class="country-grid">${countryCards}</div>` : `<div class="empty" style="padding:24px"><p>Add clients to see destination insights.</p></div>`}</div></div>
      <div class="grid-2 even" style="margin-top:20px">
        <div class="card"><div class="card-head"><h3>Upcoming deadlines</h3></div><div class="card-body">${deadlines}</div></div>
        <div class="card"><div class="card-head"><h3>Recent clients</h3><button class="link" onclick="__ent.go('clients')">All →</button></div><div class="card-body">${recent}</div></div>
      </div>`;
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
    if (!state.perms || !state.perms.can_edit_data) { toast("Only editors and admins can send mock interviews.", "error"); return; }
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
      const sb = $("#sendIvSave"); if (sb) { sb.disabled = blocked; sb.title = blocked ? "Top up your wallet to send this link" : ""; }
    }
    const ic = $("#sendIvCount"); if (ic) ic.addEventListener("input", updateCost);
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
      const btn = $("#sendIvSave"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Sending…';
      try {
        const r = await api(`/clients/${id}/interview/invite`, { method: "POST", body: { allowed_count: n } });
        closeModal();
        toast(r.message || "Mock interview link sent", r.email_sent ? "success" : "error");
        if (state.activeClient === id) openClient(id);  // refresh the open profile
      } catch (ex) {
        const er = $("#sendIvErr"); er.textContent = ex.message; er.classList.remove("hidden");
        btn.disabled = false; btn.innerHTML = "✉ Send link";
      }
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
      <select class="select-mini" id="filterCountry">${countryOpts}</select>
      ${state.perms.can_edit_data ? `<button class="btn btn-primary btn-sm" id="addClientBtn">+ Add Client</button>` : ""}`;

    function clearScope() { state.dashScope = null; state.dashScopeLabel = ""; }
    $$(".chip[data-st]", tb).forEach((ch) => ch.onclick = () => { state.filters.status = ch.dataset.st; clearScope(); loadAndRenderClientList(); renderClientToolbar(); });
    const searchEl = $("#searchChip", tb); if (searchEl) searchEl.onclick = () => clearClientSearch();
    const scEl = $("#scopeChip", tb); if (scEl) scEl.onclick = () => { clearScope(); loadAndRenderClientList(); renderClientToolbar(); };
    $("#filterCountry").onchange = (e) => { state.filters.country = e.target.value; clearScope(); loadAndRenderClientList(); };
    const ab = $("#addClientBtn"); if (ab) ab.onclick = () => openClientForm(null);
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

    const hasFilter = q || state.filters.status || state.filters.country || state.dashScope;
    if (!clients.length) {
      const emptyTitle = q ? `No clients found for “${esc(q)}”` : (hasFilter ? "No matching clients" : "No clients yet");
      const emptyHelp = q ? "Try another name, email, phone, passport, visa type, country, intake, or counselor." : (hasFilter ? "Try clearing your filters." : "Add your first visa client to get started.");
      wrap.innerHTML = `<div class="empty"><div class="emoji">🗂️</div><h3>${emptyTitle}</h3>
        <p>${emptyHelp}</p>
        ${q ? `<button class="btn btn-ghost" onclick="__ent.clearSearch()">Clear search</button>` : ""}
        ${!hasFilter && state.perms.can_edit_data ? `<button class="btn btn-primary" onclick="__ent.openClientForm()">+ Add your first client</button>` : ""}</div>`;
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

  /* ---------------- add / edit client form ---------------- */
  function openClientForm(client) {
    const isEdit = !!client;
    const members = teamMembersCache || [];
    const c = client || {};

    openModal(`
      <div class="modal-head"><h3>${isEdit ? "Edit client" : "Add new client"}</h3><button class="x" onclick="__ent.closeModal()">×</button></div>
      <form id="clientForm">
      <div class="modal-body">
        <div class="field"><label>Full name *</label><input name="full_name" required value="${esc(c.full_name || "")}" placeholder="Client's full name"/></div>
        <div class="field-row">
          <div class="field"><label>Email</label><input type="email" name="email" value="${esc(c.email || "")}" placeholder="client@email.com"/></div>
          <div class="field"><label>Phone</label><div class="phone-input-group"><select name="phone_cc" id="cfPhoneCc" aria-label="Phone country code"></select><input name="phone" id="cfPhone" inputmode="tel" placeholder="98765 43210"/></div></div>
        </div>
        <div class="field-row">
          <div class="field"><label>Destination country *</label><select name="destination_country_code" id="cfCountry" required></select></div>
          <div class="field"><label>Visa type *</label><select name="visa_type" id="cfVisa" required></select></div>
        </div>
        <div class="field" id="cfIntakeWrap"><label>Intake</label><select name="intake" id="cfIntake"><option value="">—</option></select></div>
        <div class="field-row">
          <div class="field"><label>Status</label><select name="status" id="cfStatus"></select></div>
          <div class="field"><label>Priority</label><select name="priority" id="cfPriority"></select></div>
        </div>
        <div class="field-row">
          <div class="field"><label>Assigned counselor</label><select name="assigned_to_user_id" id="cfAssign"><option value="">Unassigned</option>${members.map((m) => `<option value="${m.user_id}" ${c.assigned_to_user_id === m.user_id ? "selected" : ""}>${esc(m.full_name || m.email)}</option>`).join("")}</select></div>
          <div class="field"><label>Key date (interview / travel)</label><input type="date" name="target_date" value="${esc((c.target_date || "").slice(0, 10))}"/></div>
        </div>
        <details style="margin-bottom:6px"><summary style="cursor:pointer;font-size:13px;color:var(--primary-600);font-weight:600">More details (passport, nationality…)</summary>
          <div class="field-row" style="margin-top:12px">
            <div class="field"><label>Nationality</label><input name="nationality" value="${esc(c.nationality || "")}"/></div>
            <div class="field"><label>Date of birth</label><input type="date" name="date_of_birth" value="${esc((c.date_of_birth || "").slice(0, 10))}"/></div>
          </div>
          <div class="field-row">
            <div class="field"><label>Passport number</label><input name="passport_number" value="${esc(c.passport_number || "")}"/></div>
            <div class="field"><label>Passport expiry</label><input type="date" name="passport_expiry" value="${esc((c.passport_expiry || "").slice(0, 10))}"/></div>
          </div>
          <div class="field"><label>Application reference</label><input name="application_reference" value="${esc(c.application_reference || "")}"/></div>
        </details>
        ${isEdit ? "" : `<div class="field"><label>First note (optional)</label><textarea name="initial_note" placeholder="e.g. Walk-in enquiry, interested in Fall intake…"></textarea></div>`}
        ${isEdit ? "" : `<div class="consent-field" style="display:flex;gap:8px;align-items:flex-start;margin-top:2px"><input type="checkbox" id="clientConsent" name="client_consent_confirmed" style="width:auto;margin-top:3px"/><label for="clientConsent" style="font-size:13px;font-weight:500;line-height:1.4">This client has consented to their personal data being collected and processed through Rilono (see <a href="/dpa" target="_blank" rel="noopener">Data Processing Agreement</a>).</label></div>`}
        <div id="clientFormError" class="auth-error hidden"></div>
      </div>
      <div class="modal-foot">
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary" id="clientSaveBtn">${isEdit ? "Save changes" : "Add client"}</button>
      </div></form>`);

    const countrySel = $("#cfCountry"), visaSel = $("#cfVisa"),
      intakeSel = $("#cfIntake"), intakeWrap = $("#cfIntakeWrap"), statusSel = $("#cfStatus"), prioSel = $("#cfPriority");
    const CAT = "student";

    statusSel.innerHTML = state.catalog.stages.map((s) => `<option value="${s.key}" ${(c.status || "new_lead") === s.key ? "selected" : ""}>${esc(s.label)}</option>`).join("");
    prioSel.innerHTML = state.catalog.priorities.map((p) => `<option value="${p.key}" ${(c.priority || "normal") === p.key ? "selected" : ""}>${esc(p.label)}</option>`).join("");

    function fillCountries() {
      const list = state.catalog.countries.filter((ct) => (ct.visa_types[CAT] || []).length);
      countrySel.innerHTML = list.map((ct) => `<option value="${ct.code}" ${c.destination_country_code === ct.code ? "selected" : ""}>${ct.flag_emoji} ${esc(ct.name)}</option>`).join("");
      fillVisas();
    }
    function fillVisas() {
      const ct = countryByCode(countrySel.value);
      const visas = ct ? (ct.visa_types[CAT] || []) : [];
      visaSel.innerHTML = visas.map((v) => `<option value="${esc(v)}" ${c.visa_type === v ? "selected" : ""}>${esc(v)}</option>`).join("");
      if (ct) {
        intakeWrap.style.display = "";
        intakeSel.innerHTML = `<option value="">—</option>` + (ct.student_intakes || []).map((i) => `<option value="${esc(i)}" ${c.intake === i ? "selected" : ""}>${esc(i)}</option>`).join("");
      } else { intakeWrap.style.display = "none"; intakeSel.innerHTML = `<option value="">—</option>`; }
    }
    countrySel.onchange = fillVisas;
    fillCountries();

    const phoneParts = splitPhone(c.phone || "");
    $("#cfPhoneCc").innerHTML = phoneCcOptions(phoneParts.dial);
    $("#cfPhone").value = phoneParts.local;

    $("#clientForm").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target; const btn = $("#clientSaveBtn"); const err = $("#clientFormError");
      err.classList.add("hidden");
      const body = {};
      ["full_name", "destination_country_code", "visa_type", "intake", "email",
        "nationality", "date_of_birth", "passport_number", "passport_expiry", "priority", "status",
        "target_date", "application_reference"].forEach((k) => {
        const el = f[k]; if (!el) return; const v = (el.value || "").trim(); if (v !== "") body[k] = v;
      });
      const phoneLocal = (f.phone.value || "").trim();
      if (phoneLocal) {
        const dial = (f.phone_cc && f.phone_cc.value) || DEFAULT_DIAL;
        body.phone = phoneLocal[0] === "+" ? phoneLocal : (dial + " " + phoneLocal);
      }
      if (!isEdit) body.visa_category = "student";
      const assign = f.assigned_to_user_id.value;
      body.assigned_to_user_id = assign ? parseInt(assign, 10) : null;
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
        }
        closeModal();
        if (isEdit && state.view === "clientPage" && state.activeClient === client.id) { openClient(client.id); }
        else if (state.view === "clients") loadAndRenderClientList();
        else navigate("clients");
      } catch (ex) {
        if (ex.status === 402) { closeModal(); toast(ex.message, "error"); navigate("credits"); return; }
        err.textContent = ex.message; err.classList.remove("hidden");
      } finally { btn.disabled = false; btn.innerHTML = isEdit ? "Save changes" : "Add client"; }
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
      subject: "Documents needed for your {{destination}} visa application",
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
    c.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
    await ensureTeam();
    let data;
    try { data = await api("/clients/" + id); } catch (ex) { c.innerHTML = errBox(ex); return; }
    renderClientPage(data);
  }

  function renderClientPage(data) {
    const cl = data.client;
    const canEdit = state.perms.can_edit_data;
    const members = teamMembersCache || [];
    const grad = `linear-gradient(135deg,${cl.country.gradient_from},${cl.country.gradient_to})`;
    const hero = clientHeroTheme(cl);
    const docs = data.documents || [];
    const pendingDocIds = new Set();  // docs uploaded this session, awaiting AI validation (for the "scanning…" badge)
    const iv = { started: false, history: [], finished: false, feedback: null, busy: false, voiceOn: false, sessions: null, spoken: 0 };
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
    let overviewEditing = false;  // inline "Edit details" mode on the Overview tab
    let openStageKey = null;      // stage whose case-record panel is expanded under the tracker
    $("#viewTitle").textContent = cl.full_name;

    const detail = (label, val) => `<div class="detail-item"><label>${label}</label><div>${val || "—"}</div></div>`;

    $("#content").innerHTML = `
      <div class="client-page">
        <div class="cp-actionbar">
          <button class="cp-back" id="cpBack"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M19 12H5M11 6l-6 6 6 6" stroke-linecap="round" stroke-linejoin="round"/></svg> Back</button>
          <div style="flex:1"></div>
          ${canEdit ? `<button class="btn btn-soft btn-sm" id="cpShare">🔗 Share with client</button>
            <button class="btn btn-soft btn-sm" id="cpEdit">Edit details</button>` : ""}
        </div>
        <div class="cp-hero cp-hero--${hero.key}" style="--cp-hero-fallback:${grad}"
          aria-label="${esc(cl.destination_country_name)} visa case for ${esc(cl.full_name)}">
          <div class="cp-destination-seal" aria-hidden="true">
            <span>Destination</span>
            <div class="cp-seal-code"><strong>${esc(hero.code)}</strong><small>${esc(cl.country.flag_emoji || "🌐")}</small></div>
          </div>
          <div class="cp-hmeta">
            <div class="cp-kicker">Student visa dossier</div>
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
          <button class="cp-tab" data-tab="interview">🎤 Mock Interview</button>
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
      $("#cpShare").onclick = openPortalShareModal;
    }
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
      const stages = state.catalog.stages.filter((s) => s.key !== "on_hold");
      const onHold = state.catalog.stages.find((s) => s.key === "on_hold");
      const cur = current != null ? current : cl.status;
      const btn = (s) => {
        const active = cur === s.key;
        const style = active ? ` style="background:${s.color}"` : "";
        const attrs = interactive ? ` data-key="${s.key}"` : " disabled";
        return `<button type="button" class="stage-step ${active ? "done" : ""}"${style}${attrs}>${esc(s.label)}</button>`;
      };
      return stages.map(btn).join("") + (onHold ? btn(onHold) : "");
    }

    // Visual journey tracker (mirrors the B2C stage stepper): the linear visa pipeline as
    // connected nodes with done / current / upcoming states, off-path Rejected & On-Hold
    // pills, and a document-readiness line built from the client's uploaded documents.
    function journeyTrackHtml(interactive, current, docs) {
      const stages = (state.catalog && state.catalog.stages) || [];
      if (!stages.length) return "";
      const ordered = stages
        .map((s, i) => Object.assign({}, s, { _o: s.order != null ? s.order : i + 1 }))
        .sort((a, b) => a._o - b._o);
      const linear = ordered.filter((s) => s._o <= 6);          // New Lead → Approved
      const rejected = ordered.find((s) => s._o === 7);
      const onHold = ordered.find((s) => s._o === 8);
      const curStage = ordered.find((s) => s.key === current) || {};
      const curOrder = curStage._o || 0;
      const isRejected = rejected && current === rejected.key;
      const isOnHold = onHold && current === onHold.key;
      // On Hold keeps the client's real position (held_from_status, remembered by the
      // backend) so the tracker shows WHERE the case is paused — and Resume restores it.
      const heldStage = isOnHold && cl.held_from_status
        ? ordered.find((s) => s.key === cl.held_from_status) : null;
      const heldOrder = heldStage ? heldStage._o : 0;

      const nodes = linear.map((s) => {
        let cls;
        if (isRejected) cls = s._o <= 5 ? "done" : "upcoming";  // reached decision, then refused
        else if (isOnHold) {
          if (heldOrder > 0) {
            cls = s._o < heldOrder ? "done" : (s._o === heldOrder ? "current paused" : "upcoming");
          } else cls = "upcoming";                              // legacy hold — position unknown
        }
        else if (s._o < curOrder) cls = "done";
        else if (s._o === curOrder) cls = "current";
        else cls = "upcoming";
        if (s._o === 6 && cls !== "upcoming" && !isOnHold) cls += " approved"; // success node
        const inner = cls.indexOf("paused") >= 0 ? "⏸"
          : cls.indexOf("done") >= 0 ? "✓"
          : (cls.indexOf("current") >= 0 && s._o === 6 ? "✓" : String(s._o));
        const jk = interactive ? ` data-jkey="${s.key}"` : "";
        // Amber dot on a reached stage whose required case-record fields are still empty.
        const gaps = (interactive && s._o <= (curOrder || heldOrder)) ? stageMissingRequired(s.key).length : 0;
        const openCls = (openStageKey === s.key) ? " panel-open" : "";
        const tip = gaps ? `${s.label} — ${gaps} required field${gaps === 1 ? "" : "s"} still empty` : s.label;
        return `<div class="jtrack-step ${cls}${gaps ? " has-gap" : ""}${openCls}"${jk} title="${esc(tip)}">
            <div class="jtrack-node">${inner}${gaps ? '<span class="jtrack-gap" aria-hidden="true"></span>' : ""}</div>
            <div class="jtrack-label">${esc(s.label)}</div>
          </div>`;
      }).join("");

      const altPill = (s, active) => {
        if (!s) return "";
        const jk = interactive ? ` data-jkey="${s.key}"` : "";
        const tone = s._o === 7 ? "jtrack-alt-rej" : "jtrack-alt-hold";
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

      return `<div class="jtrack${isOnHold ? " jtrack-held" : ""}">${nodes}</div>
        <div class="jtrack-alt">${altPill(rejected, isRejected)}${altPill(onHold, isOnHold)}${resumeBtn}</div>
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
      const stages = (state.catalog && state.catalog.stages) || [];
      const s = stages.find((x) => x.key === openStageKey);
      if (!s) return "";
      const fields = stageFieldsFor(openStageKey);
      const vals = stageValuesFor(openStageKey);
      const isCurrent = cl.status === openStageKey;

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
            ${isCurrent ? "" : `<span class="stage-panel-tag">Not the current stage</span>`}
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
      // run an interview (US). For UK/CA/AU/DE the feature stays reachable in the Mock
      // Interview tab, just not pushed here — see interviewRelevance().
      const pushInterview = interviewRelevance(cl) === "standard";
      body.innerHTML = `
        ${canEdit && pushInterview ? `<button class="btn btn-primary btn-block cp-iv-cta" id="ovSendIv">🎤 Send ${esc(ovFirst)} a mock interview</button>` : ""}
        <div class="cp-card">
          <div class="cp-card-head"><h3>Visa journey</h3>${statusPill(cl.stage)}</div>
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
            ${detail("Priority", `<span class="prio" style="background:${priorityColor(cl.priority)}1f;color:${priorityColor(cl.priority)}">${esc(cl.priority)}</span>`)}
            ${detail("Key date", cl.target_date ? fmtDate(cl.target_date) : "")}
            ${detail("Intake", cl.intake ? esc(cl.intake) : "")}
            ${assignField}
            ${detail("Nationality", cl.nationality ? esc(cl.nationality) : "")}
            ${detail("Date of birth", cl.date_of_birth ? fmtDate(cl.date_of_birth) : "")}
            ${detail("Passport no.", cl.passport_number ? esc(cl.passport_number) : "")}
            ${detail("Passport expiry", cl.passport_expiry ? fmtDate(cl.passport_expiry) : "")}
            ${detail("Application ref.", cl.application_reference ? esc(cl.application_reference) : "")}
            ${detail("Added", fmtDate(cl.created_at))}
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
      // Clicking a stage OPENS that stage's case-record panel underneath the tracker.
      // Moving the case is a deliberate button inside the panel, so a stray click on the
      // journey can never silently change the client's status.
      if (canEdit) {
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
        wireStagePanel();
      }
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
        const stages = (state.catalog && state.catalog.stages) || [];
        const stageOf = (k) => stages.find((x) => x.key === k) || {};
        const labelOf = (k) => stageOf(k).label || (k || "").replace(/_/g, " ");
        const orderOf = (k) => (stageOf(k).order != null ? stageOf(k).order : 0);
        const first = (cl.full_name || "the client").split(" ")[0];
        const toLabel = labelOf(key), fromLabel = labelOf(cl.status);
        const isReject = /reject/i.test(key), isHold = /hold/i.test(key);

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
      const CAT = "student";
      const ph = splitPhone(cl.phone || "");
      const dval = (v) => esc((v || "").slice(0, 10));
      const prioOpts = state.catalog.priorities.map((p) => `<option value="${p.key}" ${(cl.priority || "normal") === p.key ? "selected" : ""}>${esc(p.label)}</option>`).join("");
      const assignOpts = `<option value="">Unassigned</option>` + members.map((m) => `<option value="${m.user_id}" ${cl.assigned_to_user_id === m.user_id ? "selected" : ""}>${esc(m.full_name || m.email)}</option>`).join("");
      let pending = cl.status;  // selected-but-unsaved visa status — only applied on Save
      body.innerHTML = `
        <div class="cp-card">
          <div class="cp-card-head"><h3>Visa status</h3><span class="cpe-hint">Pick a stage — saved with the form</span></div>
          <div class="stage-flow" id="cpeStageFlow">${stageStepsHtml(true, pending)}</div>
        </div>
        <div class="cp-card">
          <div class="cp-card-head"><h3>Edit client details</h3></div>
          <form id="cpEditForm" class="cp-edit-form">
            <div class="detail-grid">
              <div class="field cpe-full"><label>Full name</label><input name="full_name" value="${esc(cl.full_name || "")}" required></div>
              <div class="field"><label>Email</label><input type="email" name="email" value="${esc(cl.email || "")}"></div>
              <div class="field"><label>Phone</label><div class="phone-input-group"><select name="phone_cc" id="cpePhoneCc" aria-label="Phone country code"></select><input name="phone" id="cpePhone" inputmode="tel" placeholder="98765 43210"></div></div>
              <div class="field"><label>Destination country</label><select name="destination_country_code" id="cpeCountry"></select></div>
              <div class="field"><label>Visa type</label><select name="visa_type" id="cpeVisa"></select></div>
              <div class="field"><label>Intake</label><select name="intake" id="cpeIntake"><option value="">—</option></select></div>
              <div class="field"><label>Priority</label><select name="priority">${prioOpts}</select></div>
              <div class="field"><label>Assigned counselor</label><select name="assigned_to_user_id">${assignOpts}</select></div>
              <div class="field"><label>Key date (interview / travel)</label><input type="date" name="target_date" value="${dval(cl.target_date)}"></div>
              <div class="field"><label>Nationality</label><input name="nationality" value="${esc(cl.nationality || "")}"></div>
              <div class="field"><label>Date of birth</label><input type="date" name="date_of_birth" value="${dval(cl.date_of_birth)}"></div>
              <div class="field"><label>Passport number</label><input name="passport_number" value="${esc(cl.passport_number || "")}"></div>
              <div class="field"><label>Passport expiry</label><input type="date" name="passport_expiry" value="${dval(cl.passport_expiry)}"></div>
              <div class="field cpe-full"><label>Application reference</label><input name="application_reference" value="${esc(cl.application_reference || "")}"></div>
            </div>
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

      // Country → visa → intake cascade (same catalog as the add-client form).
      const countrySel = $("#cpeCountry"), visaSel = $("#cpeVisa"), intakeSel = $("#cpeIntake");
      function fillVisas() {
        const ct = countryByCode(countrySel.value);
        const visas = ct ? (ct.visa_types[CAT] || []) : [];
        visaSel.innerHTML = visas.map((v) => `<option value="${esc(v)}" ${cl.visa_type === v ? "selected" : ""}>${esc(v)}</option>`).join("");
        intakeSel.innerHTML = `<option value="">—</option>` + (ct ? (ct.student_intakes || []) : []).map((i) => `<option value="${esc(i)}" ${cl.intake === i ? "selected" : ""}>${esc(i)}</option>`).join("");
      }
      const clist = state.catalog.countries.filter((ct) => (ct.visa_types[CAT] || []).length);
      countrySel.innerHTML = clist.map((ct) => `<option value="${ct.code}" ${cl.destination_country_code === ct.code ? "selected" : ""}>${ct.flag_emoji} ${esc(ct.name)}</option>`).join("");
      countrySel.onchange = fillVisas;
      fillVisas();
      $("#cpePhoneCc").innerHTML = phoneCcOptions(ph.dial);
      $("#cpePhone").value = ph.local;

      $("#cpEditCancel").onclick = () => { overviewEditing = false; renderOverview(); };
      $("#cpEditForm").onsubmit = async (e) => {
        e.preventDefault();
        const f = e.target, btn = $("#cpEditSave"), err = $("#cpEditError");
        err.classList.add("hidden");
        const patch = {};
        ["full_name", "destination_country_code", "visa_type", "intake", "email", "nationality",
          "date_of_birth", "passport_number", "passport_expiry", "priority", "target_date",
          "application_reference"].forEach((k) => {
          const el = f[k]; if (!el) return; const v = (el.value || "").trim(); if (v !== "") patch[k] = v;
        });
        const phoneLocal = (f.phone.value || "").trim();
        if (phoneLocal) {
          const dial = (f.phone_cc && f.phone_cc.value) || DEFAULT_DIAL;
          patch.phone = phoneLocal[0] === "+" ? phoneLocal : (dial + " " + phoneLocal);
        }
        // Visa status + counselor now save with the form (no live auto-save on click).
        patch.status = pending;
        const assignEl = f.assigned_to_user_id;
        patch.assigned_to_user_id = (assignEl && assignEl.value) ? parseInt(assignEl.value, 10) : null;
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

    // Destination-personalized document list for THIS client (US/UK/CA/AU/DE/IE each
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
          }
          return;
        }
      }
      pendingDocIds.delete(docId);                     // stop showing "validating…" after the timeout
      if (state.activeClient === cl.id && body.isConnected && onDocsTab()) renderDocs();
    }

    function renderDocs() {
      const uploader = canEdit ? `
        <div class="cp-card doc-upload">
          <div class="cp-sub-label">Upload a document</div>
          <div class="doc-up-row">
            <div class="docsel" id="docSel">
              <input type="text" id="docTypeInput" class="docsel-input" autocomplete="off"
                placeholder="Search ${esc(cl.destination_country_name || "")} document types…" />
              <div class="docsel-menu hidden" id="docTypeMenu"></div>
            </div>
            <input type="file" id="docFile" class="doc-file" />
            <button class="btn btn-primary btn-sm" id="docUploadBtn">Upload document</button>
            <div id="docOtherWrap" class="docsel-other-wrap" style="display:none">
              <input type="text" id="docOtherDetail" class="docsel-input" maxlength="70" autocomplete="off"
                placeholder="What is this document? e.g. Police clearance certificate, Name-change affidavit…" />
            </div>
          </div>
          <div class="doc-hint">🔒 Encrypted at rest · PDF, images, Word/Excel, CSV or text · up to 25 MB</div>
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
        if (s === "error") return { cls: "muted", txt: "Not auto-scanned", msg: d.validation_message || "" };
        if (!s && pendingDocIds.has(d.id)) return { cls: "pending", txt: "◌ Rilono AI is validating…", msg: "" };
        return null;  // pre-existing document with no validation record
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
        const acceptRow = (canEdit && (d.validation_status === "invalid" || d.validation_status === "error"))
          ? `<div class="doc-accept-row"><button class="btn btn-soft btn-sm doc-accept" data-id="${d.id}">✓ Checked it myself — accept anyway</button></div>` : "";
        return `
        <div class="doc-card">
          <div class="doc-ic">${docIcon(d.original_filename)}</div>
          <div class="doc-meta">
            <a href="${d.download_url}" target="_blank" rel="noopener" class="doc-name">${esc(d.original_filename)}</a>
            <div class="doc-sub">${esc(d.document_type)} · ${fmtSize(d.file_size)} · ${esc(d.uploaded_by_name || "")} · ${fmtDate(d.created_at)}</div>
            ${valRow}${afRow}${cfRow}${cvfRow}${acceptRow}
          </div>
          <a class="doc-act" href="${d.download_url}" target="_blank" rel="noopener" title="View / download">⬇</a>
          ${canEdit ? `<button class="doc-act doc-del" data-id="${d.id}" title="Delete">✕</button>` : ""}
        </div>`;
      }).join("")}</div>`
        : `<div class="empty" style="padding:34px"><div class="emoji">📁</div><h3>No documents yet</h3><p>${canEdit ? "Upload this student's passport, offer letter, financials, test scores and more — securely." : "No documents have been uploaded for this client."}</p></div>`;
      // The full audit lives in its own Deep Scan tab now — this card is a pointer.
      const deepScanBar = docs.length ? `
        <div class="cp-card deep-scan-card" id="deepScanCard">
          <div class="deep-scan-head">
            <div class="deep-scan-copy">
              <div class="deep-scan-title"><span class="deep-scan-title-icon" aria-hidden="true">🛡️</span> Deep Scan client audit</div>
              <div class="deep-scan-description">Rilono AI strictly audits the <b>entire dossier</b> — these documents' contents plus profile, case records, notes, emails and payments — and flags anything irregular.</div>
            </div>
            <button class="btn btn-primary btn-sm deep-scan-btn" id="deepScanOpenBtn">Open Deep Scan</button>
          </div>
        </div>` : "";
      const docReqHolder = canEdit ? `<div id="docReqCard" class="cp-card doc-req-card" style="margin-bottom:14px"></div>` : "";
      body.innerHTML = uploader + docReqHolder + deepScanBar + list;
      const dsb = $("#deepScanOpenBtn");
      if (dsb) dsb.onclick = () => showTab("deepscan");
      if (canEdit) { drawDocReq(); if (dr.request === undefined) loadDocReq(); }

      if (canEdit) {
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

        $("#docUploadBtn").onclick = async () => {
          const fileEl = $("#docFile");
          if (!fileEl.files || !fileEl.files[0]) { toast("Choose a file first", "error"); return; }
          let chosenType = (dtInput && dtInput.value.trim()) || "Other";
          if (/^other$/i.test(chosenType)) {
            const detail = ($("#docOtherDetail")?.value || "").trim();
            if (detail) chosenType = "Other — " + detail;   // stored & shown everywhere
          }
          const fd = new FormData();
          fd.append("file", fileEl.files[0]);
          fd.append("document_type", chosenType);
          const btn = $("#docUploadBtn"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Uploading…';
          try {
            const res = await fetch(API + "/clients/" + cl.id + "/documents", { method: "POST", credentials: "include", body: fd });
            const out = await res.json().catch(() => null);
            if (!res.ok) throw makePublicApiError(res, out, "We couldn't upload this document. Please try again.");
            docs.unshift(out.document);
            if (out.document && out.document.id) pendingDocIds.add(out.document.id);
            tabCount("documents", docs.length);
            toast("Document uploaded — Rilono AI is validating…", "success");
            renderDocs();
            if (out.document && out.document.id) pollDocValidation(out.document.id);
          } catch (ex) { toast(ex.message, "error"); btn.disabled = false; btn.textContent = "Upload document"; }
        };
        $$(".doc-del", body).forEach((b) => b.onclick = async () => {
          const id = parseInt(b.dataset.id, 10);
          if (!(await confirmModal("This document will be permanently deleted. This cannot be undone.", { title: "Delete document?", okText: "Delete" }))) return;
          try {
            await api("/clients/" + cl.id + "/documents/" + id, { method: "DELETE" });
            const i = docs.findIndex((x) => x.id === id); if (i >= 0) docs.splice(i, 1);
            tabCount("documents", docs.length); toast("Document deleted", "success"); renderDocs();
          } catch (ex) { toast(ex.message, "error"); }
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
      const rv = $("#docReqRevoke"); if (rv) rv.onclick = revokeDocReq;
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
        <button type="submit" class="btn btn-primary" id="docReqSave">✉ Send request</button></div></form>`);
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
        const btn = $("#docReqSave"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Sending…';
        try {
          const r = await api(`/clients/${cl.id}/document-requests`, { method: "POST", body: { document_types: picked, message: ($("#docReqMsg").value || "").trim() || null } });
          dr.request = r.request; closeModal(); toast(r.message || "Document request sent", r.email_sent ? "success" : "error"); drawDocReq();
        } catch (ex) { er.textContent = ex.message; er.classList.remove("hidden"); btn.disabled = false; btn.innerHTML = "✉ Send request"; }
      };
    }
    async function revokeDocReq() {
      if (!(await confirmModal("The student's upload link will stop working.", { title: "Revoke document request?", okText: "Revoke" }))) return;
      try { await api(`/clients/${cl.id}/document-requests/revoke`, { method: "POST" }); dr.request = null; toast("Request revoked", "success"); drawDocReq(); }
      catch (ex) { toast(ex.message, "error"); }
    }

    function renderNotes() {
      const add = canEdit ? `<div class="cp-card note-add">
        <div class="cp-sub-label">Add a note</div>
        <textarea id="noteInput" placeholder="Log a call, a follow-up or a decision about ${esc(cl.full_name)}…"></textarea>
        <button class="btn btn-primary btn-sm" id="noteSaveBtn">Add note</button></div>` : "";
      // Admins can delete any note (incl. AI-generated); editors only their own.
      const myId = state.me && state.me.user ? state.me.user.id : null;
      const isAdmin = !!(state.perms && state.perms.can_manage_users);
      const canDeleteNote = (n) => canEdit && (isAdmin || (myId != null && n.author_user_id === myId));
      const list = data.notes.length ? `<div class="timeline">${data.notes.map((n) =>
        `<div class="tl-item"><div class="tl-meta">${esc(n.author_name || "Team")} · ${fmtDateTime(n.created_at)}${canDeleteNote(n) ? `<button class="tl-del" data-note-id="${n.id}" title="Delete note" aria-label="Delete note">✕</button>` : ""}</div><div class="tl-body">${esc(n.body)}</div></div>`).join("")}</div>`
        : `<div class="empty" style="padding:30px"><div class="emoji">📝</div><h3>No notes yet</h3><p>Keep a running record of calls, follow-ups and decisions.</p></div>`;
      body.innerHTML = add + list;
      if (canEdit) $("#noteSaveBtn").onclick = async () => {
        const v = $("#noteInput").value.trim(); if (!v) return;
        const btn = $("#noteSaveBtn"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
        try { const r = await api(`/clients/${cl.id}/notes`, { method: "POST", body: { body: v } }); data.notes.unshift(r.note); tabCount("notes", data.notes.length); renderNotes(); toast("Note added", "success"); }
        catch (ex) { toast(ex.message, "error"); btn.disabled = false; btn.textContent = "Add note"; }
      };
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
        btn.disabled = false;
        btn.innerHTML = `${EM_ICONS.send} Send email`;
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
      if (!canEdit) return "";
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
          <p>${canEdit && cl.email
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
        const sb = $("#ivSendSave");
        if (sb) {
          sb.disabled = blocked;
          sb.title = blocked ? "Top up your wallet to send this link" : "";
        }
      }
      const ic = $("#ivCount");
      if (ic) ic.addEventListener("input", updateIvCost);
      updateIvCost();
      $("#ivSendForm").onsubmit = async (e) => {
        e.preventDefault();
        const n = Math.max(1, Math.min(20, parseInt($("#ivCount").value, 10) || 3));
        const btn = $("#ivSendSave"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Sending…';
        try {
          const r = await api(`/clients/${cl.id}/interview/invite`, { method: "POST", body: { allowed_count: n } });
          iv.invite = r.invite; closeModal(); toast(r.message || "Interview link sent", r.email_sent ? "success" : "error"); drawIv();
        } catch (ex) { const er = $("#ivSendErr"); er.textContent = ex.message; er.classList.remove("hidden"); btn.disabled = false; btn.innerHTML = "✉ Send link"; }
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
        ${canEdit ? sendHeroCard() : `<div class="cp-card iv-intro"><div class="iv-orb">🎤</div><h3>AI mock visa interview</h3><p class="muted">Only editors and admins can send or run mock interviews.</p></div>`}
        ${canEdit ? staffPreviewCard() : ""}
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
    function drawIvChat(w) {
      const typing = iv.busy ? `<div class="ai-msg bot"><div class="ai-av">🧑‍✈️</div><div class="ai-bubble"><span class="ai-typing"><i></i><i></i><i></i></span></div></div>` : "";
      const fb = iv.feedback ? `<div class="cp-card iv-feedback"><div class="cp-sub-label">📋 Interview feedback</div>${feedbackFormat(iv.feedback)}</div>` : "";
      w.innerHTML = `
        <div class="cp-card iv-chat">
          <div class="iv-chead">
            <div class="iv-ctitle">🧑‍✈️ ${esc(cl.destination_country_name)} visa officer · <span class="muted">mock interview</span></div>
            <div class="iv-cactions">
              <button class="btn btn-soft btn-sm" id="ivVoiceBtn">${iv.voiceOn ? "🔊 Voice on" : "🔈 Voice off"}</button>
              ${iv.finished ? `<button class="btn btn-soft btn-sm" id="ivRestart">↻ New interview</button>` : `<button class="btn btn-ghost btn-sm" id="ivEnd" ${iv.busy ? "disabled" : ""}>End &amp; get feedback</button>`}
            </div>
          </div>
          <div class="iv-thread" id="ivThread">${iv.history.map(ivBubble).join("")}${typing}</div>
          ${iv.finished ? `<div class="iv-done">Interview ended. ${iv.feedback ? "See feedback below." : ""}</div>` : `
          <div class="iv-inrow">
            <textarea id="ivInput" placeholder="Type ${esc((cl.full_name || "the student").split(" ")[0])}'s answer…" rows="1" ${iv.busy ? "disabled" : ""}></textarea>
            ${micSupported ? `<button class="iv-mic" id="ivMic" title="Speak the answer" ${iv.busy ? "disabled" : ""}>🎙</button>` : ""}
            <button class="btn btn-primary" id="ivSend" ${iv.busy ? "disabled" : ""}>Send</button>
          </div>`}
        </div>${fb}`;
      const thread = $("#ivThread"); if (thread) thread.scrollTop = thread.scrollHeight;
      // speak the latest officer message once
      const last = iv.history[iv.history.length - 1];
      if (iv.voiceOn && last && last.role === "officer" && iv.spoken < iv.history.length) { iv.spoken = iv.history.length; ivSpeak(last.content); }

      const inp = $("#ivInput");
      if (inp) { inp.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendIv(); } });
        inp.addEventListener("input", () => { inp.style.height = "auto"; inp.style.height = Math.min(inp.scrollHeight, 140) + "px"; }); if (!iv.busy) inp.focus(); }
      const sendBtn = $("#ivSend"); if (sendBtn) sendBtn.onclick = sendIv;
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
      };
      ivRecog.onerror = () => { btn.classList.remove("rec"); ivRecog = null; };
      ivRecog.onend = () => { btn.classList.remove("rec"); ivRecog = null; };
      try { ivRecog.start(); } catch (e) { ivRecog = null; btn.classList.remove("rec"); }
    }

    /* ---- Payments tab: collected-from-this-client ledger + secure pay-link requests.
       Reads are member-visible; money actions (request / cancel / refund) are admin-only,
       enforced server-side and mirrored in the UI. ---- */
    async function renderPayments() {
      const body = $("#cpBody");
      body.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
      let d;
      try { d = await api(`/clients/${cl.id}/payments`); }
      catch (ex) { body.innerHTML = errBox(ex); return; }
      const canManage = !!(d.permissions && d.permissions.can_manage_users);
      const t = d.totals || {};
      const fee = d.fee || { percent: 2, min_fee_rupees: 49 };
      const MANUAL_METHODS = [["cash", "Cash"], ["bank_transfer", "Bank transfer"], ["upi", "UPI"], ["card", "Card / POS"], ["cheque", "Cheque"], ["other", "Other"]];
      const manualMethodLabel = (m) => (MANUAL_METHODS.find((x) => x[0] === m) || [m, m || "Payment"])[1];
      const todayISO = () => { const dt = new Date(); return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`; };

      const chipRow = `
        <div class="pay-chips">
          <div class="pay-chip"><div class="k">Collected</div><div class="v ok">${fmtPaise(t.collected_paise || 0)}</div></div>
          <div class="pay-chip"><div class="k">Pending</div><div class="v">${fmtPaise(t.pending_paise || 0)}</div></div>
          <div class="pay-chip"><div class="k">Refunded</div><div class="v warn">${fmtPaise(t.refunded_paise || 0)}</div></div>
        </div>`;

      let gateNote = "";
      if (!d.collect_enabled) {
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
            <div class="field"><label>Amount (₹) *</label>
              <input id="payAmt" type="number" min="1" step="1" placeholder="e.g. 25000" autocomplete="off"></div>
            <div class="field"><label>Due date <span style="color:var(--muted);font-weight:500">(optional)</span></label>
              <input id="payDue" type="date"></div>
          </div>
          <div class="field"><label>What is this payment for? *</label>
            <input id="payDesc" type="text" maxlength="300" placeholder="e.g. University application service fee" autocomplete="off"></div>
          <div class="pay-split-preview" id="paySplit">Rilono fee: ${Number(fee.percent)}% (min ₹${Number(fee.min_fee_rupees)}) — enter an amount to preview your payout.</div>
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
          <div style="font-size:12.5px;color:var(--muted);margin-bottom:12px">For money already collected outside Rilono (cash, bank transfer, UPI…). This is a bookkeeping entry — it does not charge the client.</div>
          <div class="field-row">
            <div class="field"><label>Amount received (₹) *</label>
              <input id="mpAmt" type="number" min="1" step="1" placeholder="e.g. 25000" autocomplete="off"></div>
            <div class="field"><label>How was it paid? *</label>
              <select id="mpMethod">${MANUAL_METHODS.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("")}</select></div>
          </div>
          <div class="field-row">
            <div class="field"><label>Date received</label>
              <input id="mpDate" type="date" value="${todayISO()}" max="${todayISO()}"></div>
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
        if (canManage && !isManual && ["paid", "transferred", "settled", "partially_refunded"].includes(p.status)) {
          acts.push(`<button class="btn btn-ghost btn-xs danger" data-act="refund" data-id="${p.id}" data-amt="${fmtPaise(p.amount_paise - (p.refunded_amount_paise || 0))}">Refund</button>`);
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
          <td style="font-weight:700;white-space:nowrap">${fmtPaise(p.amount_paise)}</td>
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
            previewEl.textContent = `Rilono fee: ${Number(fee.percent)}% (min ₹${Number(fee.min_fee_rupees)}) — enter an amount to preview your payout.`;
            return;
          }
          const paise = Math.round(rupees * 100);
          const commission = Math.max(Math.round(paise * (Number(fee.percent) / 100)), Math.round(Number(fee.min_fee_rupees) * 100));
          const payout = paise - commission;
          previewEl.innerHTML = payout > 0
            ? `Student pays <b>${fmtPaise(paise)}</b> · Rilono fee <b>${fmtPaise(commission)}</b> · You receive <b>${fmtPaise(payout)}</b> (settled to your bank by Razorpay)`
            : `Amount is too small — after the minimum fee of ₹${Number(fee.min_fee_rupees)} there would be nothing left to pay out.`;
        };
      }

      const createBtn = $("#payCreateBtn");
      if (createBtn) createBtn.onclick = async () => {
        const rupees = parseFloat(($("#payAmt").value || "0"));
        const desc = ($("#payDesc").value || "").trim();
        const due = ($("#payDue").value || "").trim() || null;
        if (!rupees || rupees <= 0) { toast("Enter the amount to collect.", "error"); return; }
        if (desc.length < 3) { toast("Describe what this payment is for.", "error"); return; }
        createBtn.disabled = true; createBtn.textContent = "Creating…";
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
          createBtn.disabled = false; createBtn.textContent = "Create & email secure link";
        }
      };

      const mpSave = $("#mpSaveBtn");
      if (mpSave) mpSave.onclick = async () => {
        const rupees = parseFloat(($("#mpAmt").value || "0"));
        const method = $("#mpMethod").value;
        const date = ($("#mpDate").value || "").trim() || null;
        const ref = ($("#mpRef").value || "").trim();
        const desc = ($("#mpDesc").value || "").trim();
        if (!rupees || rupees <= 0) { toast("Enter the amount received.", "error"); return; }
        mpSave.disabled = true; mpSave.textContent = "Saving…";
        try {
          const res = await api(`/clients/${cl.id}/payments/manual`, {
            method: "POST",
            body: { amount_paise: Math.round(rupees * 100), method, received_on: date, reference: ref || null, description: desc || null },
          });
          toast(res.message || "Payment recorded.", "success");
          renderPayments();
        } catch (ex) {
          toast(ex.message || "Could not record the payment.", "error");
          mpSave.disabled = false; mpSave.textContent = "Record payment";
        }
      };

      body.querySelectorAll("[data-act]").forEach((btn) => {
        btn.onclick = async () => {
          const pid = btn.dataset.id;
          const act = btn.dataset.act;
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

    function uniStatusSelect(entry) {
      const opts = UNI_STATUSES.map((s) =>
        `<option value="${s.key}"${entry.status === s.key ? " selected" : ""}>${s.label}</option>`).join("");
      const color = (UNI_STATUSES.find((s) => s.key === entry.status) || UNI_STATUSES[0]).color;
      return `<select class="uni-status" style="color:${color}" onchange="__ent.setUniStatus(${cl.id},${entry.id},this.value)">${opts}</select>`;
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
          ${canEdit ? uniStatusSelect(e) : `<span class="uni-status-ro">${esc((UNI_STATUSES.find((s) => s.key === e.status) || UNI_STATUSES[0]).label)}</span>`}
          ${canEdit ? `<button class="uni-del" title="Remove" onclick="__ent.removeUni(${cl.id},${e.id})">&times;</button>` : ""}
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

      const aiCard = !canEdit ? "" : `
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

      const addCard = !canEdit ? "" : `
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
        ${canEdit ? uniSuggestionsPanel() : ""}
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
            : `<div class="uni-empty">No universities shortlisted yet${canEdit ? ` — run an AI match for ${esc(dest)} or add one manually.` : "."}</div>`}
        </div>`;

      // Export is available to viewers too — reading the shortlist doesn't require edit rights.
      const exportBtn = $("#uniExportBtn");
      if (exportBtn) exportBtn.onclick = () => exportUniversitiesCsv();

      if (canEdit) {
        const rec = $("#uniRecBtn");
        if (rec) rec.onclick = () => recommendUniversities();
        const addBtn = $("#uniAddBtn");
        if (addBtn) addBtn.onclick = () => addManualUniversity();
        const save = $("#uniSavePicks");
        if (save) save.onclick = () => addSelectedUniSuggestions();
        const dismiss = $("#uniDismissSugg");
        if (dismiss) dismiss.onclick = () => dismissUniSuggestions();
        wireUniAutocomplete();
      }
    }

    // Country-aware placeholders so a UK client never sees "$" / "GRE" hints.
    function uniBudgetHint(code) {
      return ({ US: "e.g. $30,000", UK: "e.g. £22,000", CA: "e.g. C$25,000", AU: "e.g. A$35,000", DE: "e.g. €12,000", IE: "e.g. €18,000" })[code] || "e.g. annual budget";
    }
    function uniGpaHint(code) {
      return ({ US: "e.g. 3.6/4.0", UK: "e.g. 2:1 or AAB", CA: "e.g. 3.6/4.0 or 85%", AU: "e.g. 75% or GPA 5.5/7", DE: "e.g. 1.7 (German scale)", IE: "e.g. 2:1 (Honours)" })[code] || "e.g. GPA or grade average";
    }
    function uniScoreHint(code) {
      return ({ US: "e.g. IELTS 7.5, GRE 320", UK: "e.g. IELTS 7.0", CA: "e.g. IELTS 7.0", AU: "e.g. IELTS 7.0, PTE 65", DE: "e.g. IELTS 6.5, TestDaF 4", IE: "e.g. IELTS 6.5" })[code] || "e.g. IELTS 7.0";
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
              b.onclick = () => { input.value = b.dataset.name; hide(); const p = $("#uniManualProgram"); if (p && !p.value) p.focus(); };
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
      finally { const b = $("#uniAddBtn"); if (b) { b.disabled = false; b.textContent = "Add"; } }
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
        if (b) { b.disabled = false; b.textContent = "✨ Get AI recommendations"; }
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
      const heroCard = `
        <div class="cp-card deep-scan-card" id="deepScanCard">
          <div class="deep-scan-head">
            <div class="deep-scan-copy">
              <div class="deep-scan-title"><span class="deep-scan-title-icon" aria-hidden="true">🛡️</span> Deep Scan — full client audit</div>
              <div class="deep-scan-description">Rilono AI strictly audits ${esc(first)}'s <b>entire dossier</b> — profile details, stage case records, the contents of every uploaded document, notes, emails, universities, interview results and payments — and flags anything irregular or inconsistent.
                ${!ds.aiAvailable ? "<b>Rilono AI isn't configured on this server yet.</b>"
                  : isFree ? `The first scan for each client is <b>free</b>; after that it's <b>${cost} credits</b> per scan.`
                  : `Each scan costs <b>${cost} credits</b>.`}</div>
            </div>
            ${canEdit ? `<button class="btn btn-primary btn-sm deep-scan-btn" id="deepScanBtn" ${(!ds.aiAvailable || scanning) ? "disabled" : ""}>${
              scanning ? '<span class="spinner"></span> Scanning…' : isFree ? "Run Deep Scan · Free" : `Run Deep Scan · ${cost} cr`}</button>` : ""}
          </div>
          <div class="deep-scan-visualizer hidden" id="deepScanVisualizer" aria-live="polite"></div>
        </div>`;
      const resultBlock = ds.loading
        ? `<div class="cp-card"><div class="center-load"><div class="spinner dark"></div></div></div>`
        : ds.active
          ? `<div class="cp-card" id="dsResult">${deepScanResultHtml(ds.active)}</div>`
          : `<div class="cp-card"><div class="empty" style="padding:30px"><div class="emoji">🛡️</div><h3>${ds.error ? "Couldn't load Deep Scans" : "No Deep Scan yet"}</h3>
              <p>${ds.error ? esc(ds.error) : canEdit ? `Run ${esc(first)}'s first full-dossier audit — it's free.` : "No audits have been run for this client yet."}</p>
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

  // Set by the Universities tab so these inline-onclick handlers can redraw it.
  let _uniRefresh = null;

  async function setUniStatus(clientId, entryId, status) {
    try {
      await api(`/clients/${clientId}/universities/${entryId}`, { method: "PATCH", body: { status } });
      if (_uniRefresh) await _uniRefresh();
    } catch (ex) { toast(ex.message, "error"); }
  }

  async function removeUni(clientId, entryId) {
    const ok = await confirmModal("Remove this university from the shortlist?", {
      title: "Remove university", okText: "Remove",
    });
    if (!ok) return;
    try {
      await api(`/clients/${clientId}/universities/${entryId}`, { method: "DELETE" });
      toast("Removed from shortlist", "success");
      if (_uniRefresh) await _uniRefresh();
    } catch (ex) { toast(ex.message, "error"); }
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
    const cl = state.clients.find((c) => c.id === id) || (await api("/clients/" + id)).client;
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
    try { const d = await api("/team"); teamMembersCache = d.members; return d.members; }
    catch (e) { teamMembersCache = []; return []; }
  }

  async function renderTeam() {
    const c = $("#content");
    c.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
    let d;
    try { d = await api("/team"); } catch (ex) { c.innerHTML = errBox(ex); return; }
    teamMembersCache = d.members;
    const canManage = d.permissions.can_manage_users;
    const rows = d.members.map((m) => `<div class="member-row">
      <div class="m-av">${esc(initials(m.full_name || m.email).toUpperCase())}</div>
      <div class="m-meta"><b>${esc(m.full_name || m.email)}</b><span>${esc(m.email)}${m.last_login_at ? " · last seen " + fmtDate(m.last_login_at) : ""}</span></div>
      ${canManage && m.user_id !== (state.me.user.id) ? `<select class="select-mini" onchange="__ent.changeRole(${m.user_id}, this.value)">
        ${["admin", "editor", "viewer"].map((r) => `<option value="${r}" ${m.role === r ? "selected" : ""}>${r[0].toUpperCase() + r.slice(1)}</option>`).join("")}
      </select><button class="btn btn-danger btn-sm" onclick="__ent.removeMember(${m.user_id})">Remove</button>`
        : `<span class="role-badge role-${m.role}">${esc(m.role)}</span>`}
    </div>`).join("");

    c.innerHTML = `
      ${trialBanner()}
      <div class="card"><div class="card-head"><h3>Team members (${d.members.length})</h3>
        ${canManage ? `<button class="btn btn-primary btn-sm" id="inviteBtn">+ Invite member</button>` : ""}</div>
        <div class="card-body" style="padding:6px 0">${rows}</div></div>
      ${canManage ? `<p style="color:var(--muted);font-size:13px;margin-top:14px">Invited members receive an email to set their password and join your workspace. Seats used: ${state.subscription ? state.subscription.seats_used + "/" + (state.subscription.max_seats === -1 ? "∞" : state.subscription.max_seats) : ""}.</p>` : ""}`;

    const ib = $("#inviteBtn");
    if (ib) ib.onclick = () => {
      openModal(`<div class="modal-head"><h3>Invite team member</h3><button class="x" onclick="__ent.closeModal()">×</button></div>
        <form id="inviteForm"><div class="modal-body">
          <div class="field"><label>Email</label><input type="email" name="email" required placeholder="teammate@company.com"/></div>
          <div class="field"><label>Full name (optional)</label><input name="full_name" placeholder="Their name"/></div>
          <div class="field"><label>Role</label><select name="role"><option value="editor">Editor — can manage clients</option><option value="viewer">Viewer — read only</option><option value="admin">Admin — full access</option></select></div>
          <div class="hint" style="font-size:12px;color:var(--muted)">They'll get an email to set their password and join your workspace.</div>
          <div id="inviteError" class="auth-error hidden"></div>
        </div><div class="modal-foot"><button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary" id="inviteSubmit">Send invite</button></div></form>`);
      $("#inviteForm").onsubmit = async (e) => {
        e.preventDefault(); const f = e.target; const btn = $("#inviteSubmit"); const err = $("#inviteError"); err.classList.add("hidden");
        btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
        try { await api("/team/users", { method: "POST", body: { email: f.email.value.trim(), full_name: f.full_name.value.trim() || null, role: f.role.value } });
          toast("Invitation sent", "success"); closeModal(); renderTeam(); }
        catch (ex) {
          if (ex.status === 402) { closeModal(); toast(ex.message, "error"); navigate("credits"); return; }
          err.textContent = ex.message; err.classList.remove("hidden"); btn.disabled = false; btn.textContent = "Send invite";
        }
      };
    };
  }
  async function changeRole(uid, role) {
    try { await api(`/team/users/${uid}/role`, { method: "PATCH", body: { role } }); toast("Role updated", "success"); renderTeam(); }
    catch (ex) { toast(ex.message, "error"); renderTeam(); }
  }
  async function removeMember(uid) {
    if (!(await confirmModal("They'll lose access to this workspace immediately.", { title: "Remove member?", okText: "Remove" }))) return;
    try { await api(`/team/users/${uid}`, { method: "DELETE" }); toast("Member removed", "success"); renderTeam(); }
    catch (ex) { toast(ex.message, "error"); }
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
    const canManage = state.perms.can_manage_users;

    const usagePct = sub.max_clients === -1 ? 0 : Math.min(100, Math.round((sub.clients_used / Math.max(1, sub.max_clients)) * 100));
    const cycle = state.billingCycle;
    state.billingCoupon = state.billingCoupon || null;
    state.billingPlans = d.plans || [];
    const bCoupon = state.billingCoupon;
    const cyclSuffix = cycle === "yearly" ? "yr" : "mo";

    const planPriceBlock = (p) => {
      const display = cycle === "yearly" ? p.yearly_display : p.monthly_display;
      const basePaise = cycle === "yearly" ? p.yearly_paise : p.monthly_paise;
      if (!bCoupon || !basePaise) return `<div class="price">${display}<small>/${cyclSuffix}</small></div>`;
      const discounted = Math.max(0, Math.round(basePaise * (100 - bCoupon.percent) / 100));
      return `<div class="price">${fmtPaise(discounted)}<small>/${cyclSuffix}</small><span class="price-was">${display}</span></div>
        <div class="price-off">${esc(bCoupon.percent_display)} off applied</div>`;
    };

    const planCard = (p) => {
      const isCurrent = sub.plan === p.key && !sub.is_trial;
      return `<div class="plan-card ${p.is_popular ? "popular" : ""} ${isCurrent ? "current-plan" : ""}">
        ${p.is_popular ? `<div class="pop-tag">Most popular</div>` : ""}
        <h3>${esc(p.label)}</h3><div class="tagline">${esc(p.tagline)}</div>
        ${planPriceBlock(p)}
        <ul>${p.features.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>
        ${isCurrent ? `<div class="plan-current-tag">✓ Current plan</div>`
          : (canManage ? `<button class="btn ${p.is_popular ? "btn-primary" : "btn-ghost"} btn-block" onclick="__ent.checkout('${p.key}')">${sub.is_trial ? "Start " + esc(p.label) : "Switch to " + esc(p.label)}</button>`
            : `<div class="plan-current-tag" style="color:var(--muted)">Ask an admin to upgrade</div>`)}
      </div>`;
    };

    c.innerHTML = `
      <div class="card" style="margin-bottom:24px"><div class="card-body" style="display:flex;align-items:center;gap:20px;flex-wrap:wrap">
        <div style="flex:1;min-width:220px">
          <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)">Current plan</div>
          <div style="font-size:24px;font-weight:760;margin:4px 0">${esc(sub.plan_label)} ${sub.is_trial ? `<span style="font-size:13px;color:var(--warning);font-weight:600">· ${sub.trial_expired ? "expired" : sub.trial_days_left + " days left"}</span>` : ""}</div>
          <div style="font-size:13px;color:var(--text-2)">${sub.current_period_end && !sub.is_trial ? "Renews " + fmtDate(sub.current_period_end) : sub.trial_ends_at ? "Trial ends " + fmtDate(sub.trial_ends_at) : ""}</div>
        </div>
        <div style="flex:1;min-width:220px">
          <div style="display:flex;justify-content:space-between;font-size:13px"><span style="color:var(--text-2)">Clients</span><b>${sub.clients_used} / ${sub.max_clients === -1 ? "∞" : sub.max_clients}</b></div>
          <div class="usage-bar"><div class="usage-fill" style="width:${usagePct}%"></div></div>
          <div style="display:flex;justify-content:space-between;font-size:13px;margin-top:10px"><span style="color:var(--text-2)">Team seats</span><b>${sub.seats_used} / ${sub.max_seats === -1 ? "∞" : sub.max_seats}</b></div>
        </div>
      </div></div>
      <div style="text-align:center">
        <div class="billing-toggle">
          <button class="${cycle === "monthly" ? "active" : ""}" onclick="__ent.setCycle('monthly')">Monthly</button>
          <button class="${cycle === "yearly" ? "active" : ""}" onclick="__ent.setCycle('yearly')">Yearly<span class="save">save ~17%</span></button>
        </div>
      </div>
      ${canManage && d.plans.length ? couponRow(bCoupon, "applyBillingCoupon", "removeBillingCoupon", "billingCouponInput", "plans") : ""}
      <div class="plan-grid">${d.plans.map(planCard).join("")}</div>
      ${!d.plans.length ? "" : `<p style="text-align:center;color:var(--muted);font-size:13px;margin-top:18px">Secure payments via Razorpay. Cancel anytime.</p>`}`;
  }
  function setCycle(c) { state.billingCycle = c; renderBilling(); }

  async function applyBillingCoupon() {
    const input = $("#billingCouponInput");
    const code = ((input && input.value) || "").trim();
    if (!code) { toast("Enter a discount code.", "error"); return; }
    const paid = (state.billingPlans || []).filter((p) => p.key !== "trial" && (p.monthly_paise > 0 || p.yearly_paise > 0));
    if (!paid.length) { toast("No paid plans available for discounts.", "error"); return; }
    let res;
    try {
      res = await api("/coupons/validate", { method: "POST", body: { code, context: "billing", plan: paid[0].key, billing_cycle: state.billingCycle } });
    } catch (ex) { toast(ex.message || "Invalid discount code.", "error"); return; }
    state.billingCoupon = { code: res.code, percent: res.percent_off, percent_display: res.percent_display };
    toast(res.percent_display + " discount applied.", "success");
    renderBilling();
  }
  function removeBillingCoupon() { state.billingCoupon = null; renderBilling(); }

  async function checkout(plan) {
    let res;
    const couponCode = state.billingCoupon ? state.billingCoupon.code : undefined;
    try { res = await api("/billing/checkout", { method: "POST", body: { plan, billing_cycle: state.billingCycle, coupon_code: couponCode } }); }
    catch (ex) { toast(ex.message, "error"); return; }
    if (res.action === "contact_sales") { toast(res.message || "Please contact sales.", "error"); return; }
    if (res.action !== "checkout") { toast("Checkout unavailable.", "error"); return; }
    if (typeof Razorpay === "undefined") { toast("Payment library failed to load. Please refresh.", "error"); return; }

    const rzp = new Razorpay({
      key: res.razorpay_key_id,
      amount: res.amount,
      currency: res.currency,
      name: res.organization_name || "Rilono",
      description: res.plan_label + " plan (" + res.billing_cycle + ")",
      order_id: res.order_id,
      prefill: res.prefill,
      theme: { color: "#6366f1" },
      handler: async function (resp) {
        try {
          const v = await api("/billing/verify", { method: "POST", body: {
            razorpay_order_id: resp.razorpay_order_id,
            razorpay_payment_id: resp.razorpay_payment_id,
            razorpay_signature: resp.razorpay_signature,
          }});
          state.subscription = v.subscription; updatePlanChip();
          toast(v.message || "Plan activated!", "success");
          renderBilling();
        } catch (ex) { toast("Payment verification failed: " + ex.message, "error"); }
      },
    });
    rzp.on("payment.failed", () => toast("Payment was not completed.", "error"));
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
    university_match: { label: "University shortlist", color: "#0ea5e9" },
    course_finder: { label: "Course Finder", color: "#10b981" },
    other: { label: "Usage", color: "#64748b" },
  };
  const creditActionColor = (key) => (CREDIT_ACTION_META[key] || {}).color || "#6366f1";

  // Visual identity (badge label + accent colour) for one ledger entry.
  function creditTxnMeta(t) {
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

  async function renderCredits() {
    const c = $("#content");
    c.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
    let d, tx;
    try {
      [d, tx] = await Promise.all([api("/credits/wallet"), api("/credits/transactions?limit=50")]);
    } catch (ex) { c.innerHTML = errBox(ex); return; }
    const w = d.wallet || {};
    state.credits = w; updatePlanChip();
    const canManage = state.perms.can_manage_users;
    const infra = w.infra_fee || {};
    const packages = d.packages || [];
    state.creditCoupon = state.creditCoupon || null;
    state.creditPackages = packages;
    const actions = w.actions || [];
    const usage = d.usage || {};
    const txns = (tx && tx.transactions) || [];

    const infraBanner = (infra.over_free_limit || infra.fee_due)
      ? `<div class="card" style="margin-bottom:18px;border-left:4px solid ${infra.is_current ? "var(--success,#10b981)" : "var(--warning,#f59e0b)"}">
          <div class="card-body" style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
            <div style="flex:1;min-width:240px">
              <div style="font-weight:700;margin-bottom:4px">Infrastructure server fee</div>
              <div style="font-size:13px;color:var(--text-2)">
                You have ${infra.clients_used} clients (free up to ${infra.free_student_limit}).
                ${infra.is_current
                  ? `Active until ${infra.paid_until ? fmtDate(infra.paid_until) : "—"}.`
                  : `Activate the ${fmtPaise(infra.fee_paise)}/month fee to keep adding clients.`}
              </div>
            </div>
            ${!infra.is_current && canManage
              ? `<button class="btn btn-primary" id="infraPayBtn">Activate ${esc(fmtPaise(infra.fee_paise))}/mo</button>`
              : (infra.is_current ? `<span class="plan-current-tag" style="color:var(--success,#10b981)">✓ Active</span>` : "")}
          </div>
        </div>`
      : "";

    const coupon = state.creditCoupon;
    const priceBlock = (p) => {
      if (!coupon) return `<div class="price">${esc(fmtPaise(p.amount_paise))}</div>`;
      const discounted = Math.max(0, Math.round(p.amount_paise * (100 - coupon.percent) / 100));
      return `<div class="price">${fmtPaise(discounted)}<span class="price-was">${esc(fmtPaise(p.amount_paise))}</span></div>
        <div class="price-off">${esc(coupon.percent_display)} off applied</div>`;
    };
    const pkgCard = (p) => `<div class="plan-card ${p.is_popular ? "popular" : ""}">
        ${p.is_popular ? `<div class="pop-tag">Best value</div>` : ""}
        <h3>${esc(p.label)}</h3><div class="tagline">${esc(p.tagline)}</div>
        ${priceBlock(p)}
        <ul>
          <li><b>${p.total_credits} credits</b>${p.bonus_credits ? ` <span style="color:var(--success,#10b981)">(+${p.bonus_credits} bonus)</span>` : ""}</li>
          <li>Worth ${fmtInr(p.value_inr)} of AI actions</li>
          <li>≈ ${Math.floor(p.total_credits / 5)} Deep Scans or ${Math.floor(p.total_credits / 20)} interviews</li>
        </ul>
        ${canManage
          ? `<button class="btn ${p.is_popular ? "btn-primary" : "btn-ghost"} btn-block" onclick="__ent.topup('${p.key}')">Buy ${esc(p.label)}</button>`
          : `<div class="plan-current-tag" style="color:var(--muted)">Ask an admin to top up</div>`}
      </div>`;

    const actionRows = actions.map((a) =>
      `<div style="display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:1px solid var(--border,#eee)">
        <div><b>${esc(a.label)}</b><div style="font-size:12px;color:var(--text-2)">${esc(a.description || "")}</div></div>
        <div style="text-align:right;white-space:nowrap"><b>${a.credits} cr</b><div style="font-size:12px;color:var(--text-2)">${esc(fmtInr(a.price_inr != null ? a.price_inr : (a.credits || 0) * 10))}</div></div>
      </div>`).join("");

    // --- Usage breakdown: where credits go, and who on the team spent them ---
    const byAction = (usage.by_action || []).filter((a) => a.units > 0 || a.credits_spent > 0);
    const byMember = usage.by_member || [];
    const hasUsage = (usage.total_spent_credits || 0) > 0;

    const featureRows = byAction.map((a) => {
      const color = creditActionColor(a.key);
      return `<div style="padding:11px 0;border-bottom:1px solid var(--border)">
        <div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px">
          <div><b>${esc(a.label)}</b> <span style="color:var(--text-2);font-size:12.5px">· ${a.units} ${a.units === 1 ? "use" : "uses"}</span></div>
          <div style="text-align:right;white-space:nowrap"><b>${a.credits_spent} cr</b><span style="color:var(--muted);font-size:12px"> · ${a.share_pct}%</span></div>
        </div>
        ${usageBar(a.share_pct, color)}
      </div>`;
    }).join("");

    const memberRows = byMember.length ? byMember.map((m) => {
      const col = avatarColor(m.name)[0];
      return `<div style="display:flex;align-items:center;gap:11px;padding:10px 0;border-bottom:1px solid var(--border)">
        <span style="width:30px;height:30px;border-radius:50%;background:${col};color:#fff;display:grid;place-items:center;font-size:12px;font-weight:700;flex:none">${esc(initials(m.name))}</span>
        <div style="flex:1;min-width:0">
          <div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(m.name)}</div>
          <div style="font-size:12px;color:var(--text-2)">${m.units} ${m.units === 1 ? "action" : "actions"}</div>
        </div>
        <div style="text-align:right;white-space:nowrap"><b>${m.credits_spent} cr</b><div style="font-size:12px;color:var(--muted)">${m.share_pct}%</div></div>
      </div>`;
    }).join("") : `<div class="muted" style="padding:14px 0">No team usage yet.</div>`;

    const usageCard = `
      <div class="card" style="margin-bottom:24px">
        <div class="card-head"><h3>Credit usage</h3>
          <span style="font-size:12.5px;color:var(--text-2)">${usage.total_spent_credits || 0} credits spent all-time · ${usage.spent_last_30d_credits || 0} in last 30 days</span>
        </div>
        <div class="card-body">
          ${hasUsage
            ? `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:28px">
                <div>
                  <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:2px">Where credits go</div>
                  ${featureRows}
                </div>
                <div>
                  <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:2px">By team member</div>
                  ${memberRows}
                </div>
              </div>`
            : `<div class="muted" style="padding:6px 0">No credits spent yet. Usage will appear here as your team runs Deep Scans and AI mock interviews.</div>`}
        </div>
      </div>`;

    const txnRows = txns.length ? txns.map((t) => {
      const pos = t.credits > 0;
      const sign = pos ? "+" : "";
      const meta = creditTxnMeta(t);
      const detail = t.client_name
        ? `<span style="color:var(--text)">${esc(t.client_name)}</span>`
        : `<span style="color:var(--text-2)">${esc(t.description || "—")}</span>`;
      return `<tr>
        <td style="white-space:nowrap">${fmtDateTime(t.created_at)}</td>
        <td>${creditBadge(meta)}</td>
        <td>${detail}</td>
        <td style="color:var(--text-2)">${esc(t.created_by_name || "—")}</td>
        <td style="text-align:right;color:${pos ? "var(--success,#10b981)" : "var(--text)"};font-weight:600">${t.credits === 0 ? "—" : sign + t.credits}</td>
        <td style="text-align:right">${t.balance_after}</td>
      </tr>`;
    }).join("") : `<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:22px">No credit activity yet.</td></tr>`;

    c.innerHTML = `
      ${infraBanner}
      <div class="card" style="margin-bottom:24px"><div class="card-body" style="display:flex;align-items:center;gap:24px;flex-wrap:wrap">
        <div style="flex:1;min-width:220px">
          <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)">Rilono Credits balance</div>
          <div style="font-size:38px;font-weight:800;margin:4px 0;line-height:1.1">${w.balance_credits} <span style="font-size:16px;font-weight:600;color:var(--text-2)">credits</span></div>
          <div style="font-size:13px;color:var(--text-2)">Worth ${esc(fmtInr(w.balance_value_inr != null ? w.balance_value_inr : (w.balance_credits || 0) * (w.credit_value_inr || 10)))} · 1 credit = ${esc(fmtInr(w.credit_value_inr || 10))}</div>
          ${w.low_balance ? `<div style="margin-top:8px;font-size:12px;color:var(--warning,#f59e0b);font-weight:600">⚠ Low balance — top up to keep using premium AI.</div>` : ""}
        </div>
        <div style="display:flex;gap:28px;flex-wrap:wrap">
          <div><div style="font-size:12px;color:var(--muted)">Purchased</div><b style="font-size:18px">${w.lifetime_purchased_credits || 0}</b></div>
          <div><div style="font-size:12px;color:var(--muted)">Spent</div><b style="font-size:18px">${w.lifetime_spent_credits || 0}</b></div>
        </div>
      </div></div>

      ${usageCard}

      <div class="card" style="margin-bottom:24px"><div class="card-head"><h3>How credits are spent</h3></div>
        <div class="card-body">${actionRows || '<div class="muted">No billable actions configured.</div>'}</div></div>

      <h3 style="margin:0 0 12px">Top up your wallet</h3>
      ${canManage ? couponRow(coupon, "applyCreditCoupon", "removeCreditCoupon", "creditCouponInput", "top-ups") : ""}
      <div class="plan-grid">${packages.map(pkgCard).join("")}</div>
      <p style="text-align:center;color:var(--muted);font-size:13px;margin-top:14px">Secure top-ups via Razorpay (UPI, NetBanking). Credits never expire.</p>

      <div class="card" style="margin-top:24px"><div class="card-head"><h3>Recent activity</h3>
        <span style="font-size:12.5px;color:var(--text-2)">Every top-up and credit spend, with who used it and on which client</span></div>
        <div class="card-body" style="padding:0;overflow-x:auto">
          <table class="client-table"><thead><tr>
            <th>When</th><th>Activity</th><th>Details</th><th>Member</th><th style="text-align:right">Credits</th><th style="text-align:right">Balance</th>
          </tr></thead><tbody>${txnRows}</tbody></table>
        </div></div>`;

    const ip = $("#infraPayBtn");
    if (ip) ip.onclick = () => activateInfraFee();
  }

  async function applyCreditCoupon() {
    const input = $("#creditCouponInput");
    const code = ((input && input.value) || "").trim();
    if (!code) { toast("Enter a discount code.", "error"); return; }
    const pkgs = state.creditPackages || [];
    if (!pkgs.length) { toast("No packages available.", "error"); return; }
    let res;
    try {
      res = await api("/coupons/validate", { method: "POST", body: { code, context: "credits", package: pkgs[0].key } });
    } catch (ex) { toast(ex.message || "Invalid discount code.", "error"); return; }
    state.creditCoupon = { code: res.code, percent: res.percent_off, percent_display: res.percent_display, free: !!res.free };
    toast(res.free ? `${res.percent_display} off — this top-up is free.` : res.percent_display + " discount applied.", "success");
    renderCredits();
  }
  function removeCreditCoupon() { state.creditCoupon = null; renderCredits(); }

  // ---- Credit top-up checkout (order-review modal with live coupon + breakdown) ----
  let checkoutCtx = null;

  function openCreditCheckout(pkgKey) {
    const pkg = (state.creditPackages || []).find((p) => p.key === pkgKey);
    if (!pkg) { toast("Package unavailable.", "error"); return; }
    checkoutCtx = { pkg, coupon: state.creditCoupon || null };
    renderCheckout();
  }

  function checkoutBreakdown() {
    const base = Number(checkoutCtx.pkg.amount_paise || 0);
    const c = checkoutCtx.coupon;
    const discount = c ? Math.max(0, base - Math.max(0, Math.round(base * (100 - c.percent) / 100))) : 0;
    const total = Math.max(0, base - discount);
    return { base, discount, total, free: total < 100 };
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
        <button class="btn btn-primary" onclick="__ent.saveBank()">Connect bank account</button>
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

  async function renderFinance() {
    const c = $("#content");
    c.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
    let d;
    try { d = await api("/finance/summary"); }
    catch (ex) { c.innerHTML = errBox(ex); return; }
    const canManage = state.perms.can_manage_users;
    const la = d.linked_account;
    const fee = d.fee || {};
    const enabled = !!d.payments_enabled;
    const connected = !!(la && la.activation_status && la.activation_status !== "not_started");

    const intro = `<div class="card" style="margin-bottom:18px"><div class="card-body">
      <div style="font-weight:800;font-size:16px;margin-bottom:6px">Collect payments from your students</div>
      <div style="font-size:13.5px;color:var(--text-2);line-height:1.6">
        Connect your company bank account, then raise a payment request for any student and collect it online.
        Payments are processed securely by <b>Razorpay</b> and settled straight to <b>your</b> bank —
        Rilono connects you and keeps a small fee (<b>${esc(String(fee.percent))}%</b>, min ${esc(fmtInr(fee.min_fee_rupees))}) and
        <b>never holds your money</b>. See the <a href="/terms" target="_blank" rel="noopener">Terms</a> &mdash;
        &ldquo;Payment Collection for Consultancies&rdquo;.
      </div>
    </div></div>`;

    const notEnabledBanner = !enabled ? `<div class="card" style="margin-bottom:18px;border-left:4px solid var(--warning,#f59e0b)"><div class="card-body">
        <b>Online collection is being activated.</b> You can connect your bank details now; you'll be able to
        collect student payments as soon as it goes live.</div></div>` : "";

    if (!canManage) {
      c.innerHTML = intro + `<div class="card"><div class="card-body" style="color:var(--text-2)">
        ${connected ? `Your organization's payout account is ${acctStatusChip(la.activation_status)}.` : "No payout account is connected yet."}
        <br>Only an organization admin can manage the payout bank account.</div></div>`;
      return;
    }

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
          <button class="btn btn-ghost" onclick="__ent.refreshBank()">Refresh status</button>
        </div></div></div>`;
      const next = ready
        ? `<div class="card"><div class="card-body" style="color:var(--text-2)">
            <b style="color:var(--success,#10b981)">✓ You're connected and ready to receive payouts.</b>
            <br>Raising payment requests for your students will be available here shortly.</div></div>`
        : `<div class="card"><div class="card-body" style="color:var(--text-2)">
            Razorpay is verifying your account. This usually takes a short while — use <b>Refresh status</b> to check.
            ${reqs.length ? " Please resolve the items above to continue." : ""}</div></div>`;
      c.innerHTML = intro + statusCard + next;
      return;
    }

    c.innerHTML = intro + notEnabledBanner + acctOnboardingForm(la);
  }

  async function saveLinkedAccount() {
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
    const btn = document.querySelector('[onclick="__ent.saveBank()"]');
    if (btn) { btn.disabled = true; btn.textContent = "Connecting…"; }
    try {
      const r = await api("/finance/linked-account", { method: "POST", body });
      toast(r.message || "Bank account saved.", "success");
      renderFinance();
    } catch (ex) {
      toast((ex && ex.message) || "Could not connect the bank account.", "error");
      if (btn) { btn.disabled = false; btn.textContent = "Connect bank account"; }
    }
  }

  async function refreshLinkedAccount() {
    try {
      await api("/finance/linked-account/refresh", { method: "POST" });
      toast("Status refreshed.", "success");
      renderFinance();
    } catch (ex) {
      toast((ex && ex.message) || "Could not refresh status.", "error");
    }
  }

  function renderCheckout() {
    const pkg = checkoutCtx.pkg;
    const c = checkoutCtx.coupon;
    const b = checkoutBreakdown();
    const totalCell = b.free ? `<span class="co-free">FREE</span>` : `<b>${fmtPaise(b.total)}</b>`;
    const proceedLabel = b.free ? `Get ${pkg.total_credits} credits — free` : `Pay ${fmtPaise(b.total)} securely`;
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
          <div class="co-item-price">${esc(fmtPaise(pkg.amount_paise))}</div>
        </div>
        ${couponBlock}
        <div id="coCouponErr" class="co-coupon-err hidden"></div>
        <div class="co-summary">
          <div class="co-line"><span>Subtotal</span><span>${fmtPaise(b.base)}</span></div>
          ${b.discount > 0 ? `<div class="co-line co-discount"><span>Discount · ${esc(c.code)} (${esc(c.percent_display)} off)</span><span>−${fmtPaise(b.discount)}</span></div>` : ""}
          <div class="co-line co-total"><span>Total payable</span><span>${totalCell}</span></div>
        </div>
        <div class="co-note">${b.free
          ? "✓ This order is fully covered by your discount — no payment needed."
          : "🔒 Secure payment via Razorpay · UPI, cards &amp; NetBanking"} · Credits never expire.</div>
        ${b.free ? "" : inrBilledNote(b.total)}
      </div>
      <div class="modal-foot">
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="button" class="btn btn-primary" id="coProceed">${proceedLabel}</button>
      </div>`);

    const ap = $("#coApply"); if (ap) ap.onclick = coApplyCheckoutCoupon;
    const rm = $("#coRemove"); if (rm) rm.onclick = coRemoveCheckoutCoupon;
    const ci = $("#coCouponInput"); if (ci) ci.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); coApplyCheckoutCoupon(); } };
    $("#coProceed").onclick = creditCheckoutProceed;
  }

  async function coApplyCheckoutCoupon() {
    const input = $("#coCouponInput");
    const code = ((input && input.value) || "").trim();
    if (!code) { toast("Enter a discount code.", "error"); return; }
    const btn = $("#coApply"); if (btn) { btn.disabled = true; btn.textContent = "…"; }
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
    try { res = await api("/credits/topup/checkout", { method: "POST", body: { package: pkg.key, coupon_code: couponCode } }); }
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
      prefill: res.prefill,
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

  async function activateInfraFee() {
    let res;
    try { res = await api("/credits/infra/checkout", { method: "POST" }); }
    catch (ex) { toast(ex.message, "error"); return; }
    if (res.action === "contact_sales") { toast(res.message || "Please contact us.", "error"); return; }
    if (res.action !== "checkout") { toast("Payment unavailable.", "error"); return; }
    if (typeof Razorpay === "undefined") { toast("Payment library failed to load. Please refresh.", "error"); return; }

    const rzp = new Razorpay({
      key: res.razorpay_key_id,
      amount: res.amount,
      currency: res.currency,
      name: res.organization_name || "Rilono",
      description: "Infrastructure server fee (monthly)",
      order_id: res.order_id,
      prefill: res.prefill,
      theme: { color: "#6366f1" },
      handler: async function (resp) {
        try {
          const v = await api("/credits/infra/verify", { method: "POST", body: {
            razorpay_order_id: resp.razorpay_order_id,
            razorpay_payment_id: resp.razorpay_payment_id,
            razorpay_signature: resp.razorpay_signature,
          }});
          state.credits = v.wallet; updatePlanChip();
          toast(v.message || "Infrastructure fee activated.", "success");
          renderCredits();
        } catch (ex) { toast("Payment verification failed: " + ex.message, "error"); }
      },
    });
    rzp.on("payment.failed", () => toast("Payment was not completed.", "error"));
    rzp.open();
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
    const canManage = state.perms.can_manage_users;
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
    const curNote = dc.code === "INR"
      ? "Amounts across this portal display in <b>INR (₹)</b>."
      : `Amounts display in <b>${esc(dc.code)}</b> — a ₹10,000 fee shows as ` +
        `<b>${esc(dc.symbol || "")}${(10000 * Number(dc.rate_from_inr || 0)).toLocaleString(undefined, { maximumFractionDigits: 0 })}</b> ` +
        "at today's rate, refreshed daily. Payments themselves are still charged in INR.";
    const portalHost = (org.subdomain_slug || "") + "." + rootDomain();
    const membership = state.me.membership || {};
    const role = membership.role || "";
    const bal = state.credits && state.credits.balance_credits != null ? state.credits.balance_credits : null;
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
              <span class="set-fact">${bal != null ? `<b>${bal}</b> credits` : "Pay-as-you-go credits"}</span>
              <span class="set-fact">Showing amounts in <b>${esc(dc.code || "INR")}</b></span>
            </div>
          </div>
          ${canManage ? `
          <div class="set-hero-actions">
            <button class="btn btn-ghost btn-sm" id="uploadLogoBtn">${BTN_UPLOAD_HTML}</button>
            <button class="btn btn-ghost btn-sm" id="regenLogo">${BTN_REGEN_HTML}</button>
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
              <div class="set-row"><span class="set-row-k">Billing</span><span class="set-row-v">Pay-as-you-go${bal != null ? ` · ${bal} cr left` : ""} &nbsp;<button type="button" class="link" id="setGoCredits">Manage credits</button></span></div>
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
      $("#regenLogo").onclick = async () => {
        // .spinner is white-on-transparent — on a white .btn-ghost it needs the dark variant.
        const btn = $("#regenLogo"); btn.disabled = true; btn.innerHTML = '<span class="spinner dark"></span>';
        const tile = $("#heroLogoBtn"); if (tile) tile.classList.add("busy");
        try { const r = await api("/organization/branding", { method: "PATCH", body: { generate_random_logo: true } });
          const url = (r.organization || {}).logo_url; if (url) { $("#settingsLogo").src = url; $("#settingsLogo").style.visibility = "visible"; $("#brandLogo").src = url; $("#brandLogo").style.display = ""; state.me.organization.logo_url = url; }
          toast("New logo generated", "success"); }
        catch (ex) { toast(ex.message, "error"); }
        finally { btn.disabled = false; btn.innerHTML = BTN_REGEN_HTML; if (tile) tile.classList.remove("busy"); }
      };
      $("#uploadLogoBtn").onclick = () => $("#logoFile").click();
      $("#heroLogoBtn").onclick = () => $("#logoFile").click();
      $("#logoFile").onchange = async () => {
        const f = $("#logoFile").files && $("#logoFile").files[0];
        if (!f) return;
        if (f.size > 2 * 1024 * 1024) { toast("Logo must be under 2 MB", "error"); $("#logoFile").value = ""; return; }
        const btn = $("#uploadLogoBtn"); btn.disabled = true; btn.innerHTML = '<span class="spinner dark"></span> Uploading…';
        const tile = $("#heroLogoBtn"); if (tile) tile.classList.add("busy");
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
        finally { btn.disabled = false; btn.innerHTML = BTN_UPLOAD_HTML; if (tile) tile.classList.remove("busy"); $("#logoFile").value = ""; }
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
     ============================================================ */
  function renderAIAssistant() {
    if (!state.aiHistory) state.aiHistory = [];
    const c = $("#content");
    c.innerHTML = `
      <div class="ai-wrap">
        <div class="ai-head">
          <div class="ai-orb">✨</div>
          <div><h2>Rilono AI Assistant</h2><p>Ask anything about your clients, visa statuses and activity — I read your live portal data to answer.</p></div>
        </div>
        <div class="ai-thread" id="aiThread"></div>
        <div class="ai-suggest" id="aiSuggest"></div>
        <form class="ai-input" id="aiForm">
          <textarea id="aiInput" rows="1" placeholder="e.g. Which clients need my attention today?" maxlength="4000"></textarea>
          <button type="submit" class="ai-send" id="aiSend" aria-label="Send">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M13 6l6 6-6 6" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
        </form>
        <div class="ai-disclaimer">AI can make mistakes — verify important details against the client record.</div>
      </div>`;
    renderAiThread();
    loadAiMeta();
    $("#aiForm").onsubmit = (e) => { e.preventDefault(); sendAi(); };
    const ta = $("#aiInput");
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendAi(); } });
    ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 160) + "px"; });
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

  function renderAiThread() {
    const thread = $("#aiThread"); if (!thread) return;
    if (!state.aiHistory.length) {
      thread.innerHTML = `<div class="ai-empty"><div class="ai-orb lg">✨</div>
        <h3>How can I help?</h3>
        <p>I can answer questions about your clients, their visa progress, who needs attention, recent activity and your team's workload.</p></div>`;
      return;
    }
    thread.innerHTML = state.aiHistory.map((m) => {
      if (m.role === "user") {
        return `<div class="ai-msg user"><div class="ai-bubble">${esc(m.content).replace(/\n/g, "<br>")}</div></div>`;
      }
      if (m.role === "typing") {
        return `<div class="ai-msg bot"><div class="ai-av">✨</div><div class="ai-bubble"><span class="ai-typing"><i></i><i></i><i></i></span></div></div>`;
      }
      return `<div class="ai-msg bot"><div class="ai-av">✨</div><div class="ai-bubble">${aiFormat(m.content)}</div></div>`;
    }).join("");
    thread.scrollTop = thread.scrollHeight;
  }

  function renderAiSuggestions() {
    const box = $("#aiSuggest"); if (!box) return;
    const meta = state.aiMeta;
    if (!meta || !meta.enabled || state.aiHistory.length) { box.innerHTML = ""; return; }
    box.innerHTML = (meta.suggestions || []).map((s) => `<button class="ai-chip" type="button">${esc(s)}</button>`).join("");
    $$(".ai-chip", box).forEach((ch) => ch.onclick = () => { $("#aiInput").value = ch.textContent; sendAi(); });
  }

  async function loadAiMeta() {
    if (state.aiMeta) { applyAiMeta(); return; }
    try { state.aiMeta = await api("/ai/meta"); } catch (ex) { state.aiMeta = { enabled: false, suggestions: [] }; }
    applyAiMeta();
  }
  function applyAiMeta() {
    const meta = state.aiMeta || {};
    const ta = $("#aiInput"), send = $("#aiSend");
    if (!meta.enabled) {
      if (ta) { ta.disabled = true; ta.placeholder = "AI assistant isn't configured on this server yet."; }
      if (send) send.disabled = true;
      const thread = $("#aiThread");
      if (thread && !state.aiHistory.length) {
        thread.innerHTML = `<div class="ai-empty"><div class="ai-orb lg">🔌</div><h3>AI assistant unavailable</h3><p>An administrator needs to enable Rilono AI on the server to use the Rilono AI Assistant.</p></div>`;
      }
    }
    renderAiSuggestions();
  }

  async function sendAi() {
    if (state.aiBusy) return;
    const ta = $("#aiInput"); if (!ta || ta.disabled) return;
    const msg = (ta.value || "").trim();
    if (!msg) return;
    const priorHistory = state.aiHistory.filter((m) => m.role === "user" || m.role === "model").slice(-12);
    state.aiHistory.push({ role: "user", content: msg });
    state.aiHistory.push({ role: "typing", content: "" });
    ta.value = ""; ta.style.height = "auto";
    state.aiBusy = true;
    renderAiThread(); renderAiSuggestions();
    try {
      const data = await api("/ai/chat", { method: "POST", body: { message: msg, history: priorHistory }, timeout: AI_API_TIMEOUT_MS });
      state.aiHistory = state.aiHistory.filter((m) => m.role !== "typing");
      state.aiHistory.push({ role: "model", content: data.answer || "(no answer)" });
      // Keep the credits chip in sync when a message debited the wallet.
      if (data.wallet) { state.credits = data.wallet; updatePlanChip(); }
    } catch (ex) {
      state.aiHistory = state.aiHistory.filter((m) => m.role !== "typing");
      // Out of credits for the assistant → explain in-thread and point to top-up.
      if (ex.status === 402) {
        state.aiHistory.push({ role: "model", content: ex.message || "You're out of Rilono Credits for the AI assistant. Top up to keep chatting." });
        toast(ex.message, "error");
        state.aiBusy = false; renderAiThread();
        navigate("credits");
        return;
      }
      state.aiHistory.push({
        role: "model",
        content: "Sorry, I encountered an error. We are working on it, and this issue has been raised for review."
      });
      toast("AI assistant ran into a problem. Please try again.", "error");
    } finally {
      state.aiBusy = false;
      renderAiThread();
    }
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
    state.perms = data.permissions || state.perms;
    const canEdit = state.perms.can_edit_data;
    state.calTypes = data.event_types || [];
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
          ${e.time ? `<b>${esc(e.time)}</b> ` : ""}${esc(e.title)}
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
          <span>${esc(e.type_label)}${e.client_name && e.source !== "client" ? " · " + esc(e.client_name) : ""}</span>
        </div>
        <div class="cal-up-when ${e.overdue ? "overdue" : ""}">${esc(calRel(e.date, today))}${e.time ? " · " + esc(e.time) : ""}</div>
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
          <div class="cal-legend">${legend}</div>
        </div>
        <aside class="cal-side">
          <h3>What's next</h3>
          <div class="cal-upcoming">${overdueBlock}${upcomingBlock}</div>
        </aside>
      </div>`;
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
    calEditModal(e);
  }

  function calAdd(dateStr) {
    if (!state.perms.can_edit_data) return;
    calEditModal(null, dateStr);
  }

  function calEditModal(ev, presetDate) {
    const types = state.calTypes || [{ key: "reminder", label: "Reminder" }];
    const isEdit = !!ev;
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
        <div id="calFormErr" class="auth-error hidden"></div>
      </div>
      <div class="modal-foot">
        ${isEdit ? `<button type="button" class="btn btn-danger btn-sm" onclick="__ent.calDelete(${ev.event_id})">Delete</button>
          <button type="button" class="btn btn-ghost btn-sm" onclick="__ent.calToggleDone(${ev.event_id}, ${ev.is_done ? "false" : "true"})">${ev.is_done ? "Mark not done" : "✓ Mark done"}</button>` : ""}
        <div class="spacer" style="flex:1"></div>
        <button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary" id="calSaveBtn">${isEdit ? "Save" : "Add"}</button>
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

  async function calToggleDone(eventId, done) {
    try { await api(`/calendar/events/${eventId}`, { method: "PATCH", body: { is_done: done } }); closeModal(); toast(done ? "Marked done" : "Reopened", "success"); renderCalendar(); }
    catch (ex) { toast(ex.message, "error"); }
  }
  async function calDelete(eventId) {
    if (!(await confirmModal("This reminder will be permanently deleted.", { title: "Delete event?", okText: "Delete" }))) return;
    try { await api(`/calendar/events/${eventId}`, { method: "DELETE" }); closeModal(); toast("Event deleted", "success"); renderCalendar(); }
    catch (ex) { toast(ex.message, "error"); }
  }

  /* ============================================================
     HELP & SUPPORT + feature requests
     ============================================================ */
  async function renderSupport() {
    const c = $("#content");
    c.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
    let d;
    try { d = await api("/support"); } catch (ex) { c.innerHTML = errBox(ex); return; }
    const supportEmail = d.support_email || "contact@rilono.com";
    const reqs = d.requests || [];

    const histRow = (r) => `
      <div class="sup-hist-item">
        <span class="sup-badge ${r.request_type === "feature_request" ? "feature" : "help"}">${r.request_type === "feature_request" ? "💡 Feature" : "🛟 Help"}</span>
        <div class="sup-hist-meta"><b>${esc(r.subject)}</b><span>${fmtDateTime(r.created_at)} · ${esc(r.status)}</span></div>
      </div>`;
    const history = reqs.length
      ? `<div class="card" style="margin-top:24px"><div class="card-head"><h3>Your recent requests</h3></div>
          <div class="card-body" style="padding:8px 0">${reqs.map(histRow).join("")}</div></div>`
      : "";

    const formCard = (kind) => {
      const isFeature = kind === "feature_request";
      return `<div class="card sup-card">
        <div class="sup-card-head">
          <div class="sup-icon ${isFeature ? "feature" : "help"}">${isFeature ? "💡" : "🛟"}</div>
          <div>
            <h3>${isFeature ? "Request a feature" : "Get help"}</h3>
            <p>${isFeature ? "Have an idea to make Rilono better? Tell us — we read every one." : "Stuck or something not working? Our team will get back to you by email."}</p>
          </div>
        </div>
        <form class="sup-form" data-type="${kind}">
          <div class="field"><label>${isFeature ? "What would you like to see?" : "Subject"}</label>
            <input name="subject" required maxlength="160" placeholder="${isFeature ? "e.g. Bulk import clients from CSV" : "e.g. I can't upload a document"}"/></div>
          <div class="field"><label>${isFeature ? "Tell us more" : "Describe the issue"}</label>
            <textarea name="message" required maxlength="4000" rows="4" placeholder="${isFeature ? "How would it help your team? Any details welcome." : "What happened, and what did you expect? Include any error messages."}"></textarea></div>
          <div class="sup-form-err auth-error hidden"></div>
          <button type="submit" class="btn ${isFeature ? "btn-ghost" : "btn-primary"}">${isFeature ? "Send feature request" : "Send to support"}</button>
        </form>
      </div>`;
    };

    c.innerHTML = `
      <div class="card sup-hero">
        <div>
          <h2>How can we help?</h2>
          <p>Email us any time at <a href="mailto:${esc(supportEmail)}">${esc(supportEmail)}</a> — we typically reply within one business day.</p>
        </div>
      </div>
      <div class="sup-grid">${formCard("support")}${formCard("feature_request")}</div>
      ${history}`;

    $$(".sup-form", c).forEach((form) => {
      form.onsubmit = async (e) => {
        e.preventDefault();
        const kind = form.dataset.type;
        const fd = new FormData(form);
        const body = { request_type: kind, subject: (fd.get("subject") || "").trim(), message: (fd.get("message") || "").trim() };
        if (body.subject.length < 3 || body.message.length < 5) return;
        const btn = form.querySelector("button[type=submit]");
        const orig = btn.textContent; btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Sending…';
        try {
          const r = await api("/support", { method: "POST", body });
          toast(r.message || "Sent — thank you!", "success");
          renderSupport();
        } catch (ex) {
          const er = form.querySelector(".sup-form-err"); er.textContent = ex.message; er.classList.remove("hidden");
          btn.disabled = false; btn.textContent = orig;
        }
      };
    });
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
      </div></div>
      <div id="cfBrowseBody"><div class="center-load"><div class="spinner dark"></div></div></div>`;
    const apply = () => {
      cf.country = $("#cfCountry").value;
      cf.level = $("#cfLevel").value;
      cf.discipline = $("#cfDiscipline").value;
      cf.q = $("#cfQ").value.trim();
      cf.maxTuition = $("#cfMaxTuition").value;
      cfLoadBrowse();
    };
    $("#cfApply").onclick = apply;
    $("#cfQ").onkeydown = (e) => { if (e.key === "Enter") apply(); };
    ["cfCountry", "cfLevel", "cfDiscipline"].forEach((id) => { $("#" + id).onchange = apply; });
    cfLoadBrowse();
  }

  async function cfLoadBrowse() {
    const body = $("#cfBrowseBody");
    if (!body) return;
    body.innerHTML = '<div class="center-load"><div class="spinner dark"></div></div>';
    const seq = ++cf.browseSeq;
    const p = new URLSearchParams({ country: cf.country });
    if (cf.level) p.set("level", cf.level);
    if (cf.discipline) p.set("discipline", cf.discipline);
    if (cf.q) p.set("q", cf.q);
    if (cf.maxTuition && Number(cf.maxTuition) > 0) p.set("max_tuition", String(Math.floor(Number(cf.maxTuition))));
    try {
      const d = await api("/course-catalog?" + p.toString());
      if (seq !== cf.browseSeq || state.view !== "coursefinder") return; // stale response
      cf.browse = d;
      cfDrawBrowse();
    } catch (ex) {
      if (seq !== cf.browseSeq) return;
      body.innerHTML = errBox(ex);
    }
  }

  function cfDrawBrowse() {
    const body = $("#cfBrowseBody");
    if (!body || !cf.browse) return;
    const unis = cf.browse.universities || [];
    if (!unis.length) {
      body.innerHTML = `
        <div class="empty"><div class="emoji">🛰️</div>
          <h3>Nothing here yet</h3>
          <p>No catalog matches for these filters. Rilono's research agent adds &amp; re-verifies universities every day — or try the <b>AI Shortlists</b> tab, which can also search live data.</p>
        </div>`;
      return;
    }
    body.innerHTML = unis.map((u, i) => cfUniCard(u, i)).join("");
    $$(".cf-uni-toggle", body).forEach((btn) => {
      btn.onclick = () => {
        const card = btn.closest(".cf-uni");
        if (card) card.classList.toggle("cf-uni-open");
        const tbl = card && card.querySelector(".cf-courses");
        btn.textContent = tbl && card.classList.contains("cf-uni-open") ? "Hide courses" : `View courses (${btn.dataset.n})`;
      };
    });
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
    const canEdit = state.perms && state.perms.can_edit_data;
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
          <button class="btn btn-primary" id="cfAiRun" ${(!canEdit || !m.ai_available || cf.aiBusy) ? "disabled" : ""}>${cf.aiBusy ? '<span class="spinner"></span> Rilono AI is researching…' : `Generate shortlist · ${esc(String(cost))} cr`}</button>
          ${!canEdit ? '<span class="hint">Viewers can browse, but only editors can run AI actions.</span>' : ""}
        </div>
      </div></div>
      <div id="cfAiResult"></div>
      <div class="card"><div class="card-head"><h3>Past shortlists</h3></div><div class="card-body" id="cfRecsList"><div class="center-load"><div class="spinner dark"></div></div></div></div>`;

    cfWireClientPicker();
    // Persist form state so tab switches / re-renders never wipe what was typed.
    $("#cfAiField").oninput = (e) => { cf.aiField = e.target.value; };
    $("#cfAiBudget").oninput = (e) => { cf.aiBudget = e.target.value; };
    $("#cfAiNotes").oninput = (e) => { cf.aiNotes = e.target.value; };
    $("#cfAiCountry").onchange = (e) => { cf.country = e.target.value; };
    $("#cfAiLevel").onchange = (e) => { cf.level = e.target.value; };
    $("#cfAiDiscipline").onchange = (e) => { cf.discipline = e.target.value; };
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
        runBtn.disabled = !(state.perms && state.perms.can_edit_data);
        runBtn.innerHTML = `Generate shortlist · ${esc(String(cfCost()))} cr`;
      }
    }
  }

  function cfDrawActiveRec() {
    const mount = $("#cfAiResult");
    if (!mount) return;
    const rec = cf.activeRec;
    if (!rec) { mount.innerHTML = ""; return; }
    const items = rec.recommendations || [];
    const canEdit = state.perms && state.perms.can_edit_data;
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

  window.__ent = {
    go: navigate, openClient, openClientForm: () => openClientForm(null), editClient, deleteClient, setStatus,
    closeModal, closeDrawer, changeRole, removeMember, checkout, setCycle,
    applyCreditCoupon, removeCreditCoupon, applyBillingCoupon, removeBillingCoupon,
    topup: openCreditCheckout, activateInfra: activateInfraFee,
    saveBank: saveLinkedAccount, refreshBank: refreshLinkedAccount,
    viewClients: openClientsFiltered, viewVisaType, clearSearch: clearClientSearch,
    viewInterview: viewInterviewSession, sendInterview: openSendInterviewPicker,
    setUniStatus, removeUni,
    calPrev, calNext, calToday, calSetMonth, calSetYear, calEvent, calAdd, calDelete, calToggleDone,
  };

  /* ============================================================
     INIT
     ============================================================ */
  setupAuth();
  boot();
})();
