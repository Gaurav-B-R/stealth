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
  function fmtPaise(p) {
    return "₹" + (Number(p || 0) / 100).toLocaleString("en-IN", { maximumFractionDigits: 2 });
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

  async function api(path, opts) {
    opts = opts || {};
    let res;
    try {
      res = await fetch(API + path, {
        method: opts.method || "GET",
        credentials: "include",
        headers: opts.body ? { "Content-Type": "application/json" } : {},
        body: opts.body ? JSON.stringify(opts.body) : undefined,
      });
    } catch (_error) {
      throw publicClientError("We couldn't reach Rilono. Check your connection and try again.");
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
    renderEnterpriseTurnstile("signup");

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
    maybeShowEntHeardAbout(me);

    if (!state.perms.can_edit_data) $("#topAddClient").classList.add("hidden");

    try { state.catalog = await api("/catalog"); } catch (e) { state.catalog = { countries: [], categories: [], stages: [], priorities: [] }; }

    // Restore the view from the URL (deep-link / refresh / bookmark), replacing the
    // history entry so we don't add a spurious one on first load.
    applyRoute(location.pathname, { replace: true });
    refreshCalendarBadge();  // keep the overdue-reminder badge correct without needing to open Calendar
  }

  function updatePlanChip() {
    const s = state.subscription;
    const cr = state.credits;
    if (cr && cr.balance_credits != null) {
      $("#brandPlan").textContent = cr.balance_credits + " credits";
    } else {
      $("#brandPlan").textContent = "Free plan";
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
     NAV
     ============================================================ */
  // ---- URL routing: keep the address bar in sync with the active view so refresh,
  // deep-links, bookmarks and browser back/forward all work inside the app. ----
  const ROUTE_VIEWS = ["dashboard", "clients", "calendar", "ai", "team", "credits", "support", "billing", "settings"];
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
    const titles = { dashboard: "Dashboard", clients: "Clients", calendar: "Calendar", ai: "Rilono AI Assistant", team: "Team", credits: "Credits & Billing", support: "Help & Support", billing: "Plans & Billing", settings: "Settings" };
    $("#viewTitle").textContent = titles[view] || "";
    $("#globalSearchBox").style.display = view === "clients" || view === "dashboard" ? "" : "none";
    syncUrl(viewToPath(view), opts);
    if (view === "dashboard") renderDashboard();
    else if (view === "clients") renderClients();
    else if (view === "calendar") renderCalendar();
    else if (view === "ai") renderAIAssistant();
    else if (view === "team") renderTeam();
    else if (view === "credits") renderCredits();
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
    const money = (credits) => isInr ? ` (≈ ₹${Math.round(credits * perInr).toLocaleString()})` : "";
    const opts = clients.map((c) => `<option value="${c.id}" ${preselectId === c.id ? "selected" : ""}>${esc(c.full_name)} — ${esc(c.email)}</option>`).join("");

    openModal(`<div class="modal-head"><h3>🎤 Send a mock interview</h3><button class="x" onclick="__ent.closeModal()">×</button></div>
      <form id="sendIvForm"><div class="modal-body">
        <p style="margin:0 0 16px;color:var(--text-2);font-size:14px;line-height:1.6">We'll email a secure link to the student. They verify with a one-time code, take the interview(s) on their own time, and every result appears in their profile here.</p>
        <div class="field"><label>Student</label>
          <select id="sendIvClient" class="select-mini" style="width:100%">${opts}</select></div>
        <div class="field"><label>How many interviews can they take?</label>
          <input type="number" id="sendIvCount" min="1" max="20" value="3" /></div>
        <div id="sendIvCost" style="background:rgba(99,102,241,.07);border:1px solid var(--border);border-radius:10px;padding:10px 12px;font-size:13px;color:var(--text-2);line-height:1.5;margin:-2px 0 4px"></div>
        <div id="sendIvErr" class="auth-error hidden"></div>
      </div>
      <div class="modal-foot"><button type="button" class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
      <button type="submit" class="btn btn-primary" id="sendIvSave">✉ Send link</button></div></form>`);

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
    const docs = data.documents || [];
    const iv = { started: false, history: [], finished: false, feedback: null, busy: false, voiceOn: false, sessions: null, spoken: 0 };
    const dr = { request: undefined };  // secure document-request state (lazy-loaded)
    let overviewEditing = false;  // inline "Edit details" mode on the Overview tab
    $("#viewTitle").textContent = cl.full_name;

    const detail = (label, val) => `<div class="detail-item"><label>${label}</label><div>${val || "—"}</div></div>`;

    $("#content").innerHTML = `
      <div class="client-page">
        <div class="cp-actionbar">
          <button class="cp-back" id="cpBack"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M19 12H5M11 6l-6 6 6 6" stroke-linecap="round" stroke-linejoin="round"/></svg> Back</button>
          <div style="flex:1"></div>
          ${canEdit ? `<button class="btn btn-soft btn-sm" id="cpEdit">Edit details</button>
            <button class="btn btn-danger btn-sm" id="cpDelete">Delete</button>` : ""}
        </div>
        <div class="cp-hero" style="background:${grad}">
          <div class="cp-avatar">${esc(cl.country.flag_emoji || initials(cl.full_name).toUpperCase())}</div>
          <div class="cp-hmeta">
            <h1>${esc(cl.full_name)}</h1>
            <div class="cp-hsub">${esc(cl.country.flag_emoji)} ${esc(cl.destination_country_name)} · ${esc(cl.visa_type)}${cl.intake ? " · " + esc(cl.intake) : ""}</div>
          </div>
          <div class="cp-hstatus">${statusPill(cl.stage)}</div>
        </div>
        <div class="cp-tabs" id="cpTabs">
          <button class="cp-tab active" data-tab="overview">Overview</button>
          <button class="cp-tab" data-tab="documents">Documents${docs.length ? ` (${docs.length})` : ""}</button>
          <button class="cp-tab" data-tab="notes">Notes${data.notes.length ? ` (${data.notes.length})` : ""}</button>
          <button class="cp-tab" data-tab="emails">Emails${data.emails.length ? ` (${data.emails.length})` : ""}</button>
          <button class="cp-tab" data-tab="interview">🎤 Mock Interview</button>
        </div>
        <div class="cp-body" id="cpBody"></div>
      </div>`;

    $("#cpBack").onclick = () => navigate(state.clientReturnView || "clients");
    if (canEdit) {
      // Edit inline within the Overview pane (no popup) instead of opening a modal.
      $("#cpEdit").onclick = () => { overviewEditing = true; showTab("overview"); };
      $("#cpDelete").onclick = () => deleteClient(cl.id);
    }
    const body = $("#cpBody");

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

    function renderOverview() {
      if (overviewEditing && canEdit) { renderOverviewEdit(); return; }

      const assignField = `<div class="detail-item"><label>Assigned counselor</label><div>${cl.assigned_to_name ? esc(cl.assigned_to_name) : "—"}</div></div>`;
      const ovFirst = (cl.full_name || "the student").split(" ")[0];
      body.innerHTML = `
        ${canEdit ? `<button class="btn btn-primary btn-block cp-iv-cta" id="ovSendIv">🎤 Send ${esc(ovFirst)} a mock interview</button>` : ""}
        <div class="cp-card">
          <div class="cp-card-head"><h3>Visa status</h3>${statusPill(cl.stage)}</div>
          <div class="stage-flow" id="ovStageFlow">${stageStepsHtml(canEdit, cl.status)}</div>
          ${canEdit ? `<div class="cpe-hint" style="margin-top:10px">Click a stage to move ${esc(ovFirst)} instantly.</div>` : ""}
        </div>
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
      // Quick-select pipeline stage: clicking a stage on the Overview saves it immediately
      // (setStatus PATCHes and re-renders). Only wired when the user can edit.
      if (canEdit) {
        $$("#ovStageFlow .stage-step[data-key]").forEach((b) => {
          b.onclick = () => {
            const key = b.dataset.key;
            if (key && key !== cl.status) setStatus(cl.id, key);
          };
        });
      }
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
    }

    function renderDocs() {
      const types = state.catalog.document_types || [];
      const uploader = canEdit ? `
        <div class="cp-card doc-upload">
          <div class="cp-sub-label">Upload a document</div>
          <div class="doc-up-row">
            <select class="select-mini" id="docType">${types.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`).join("")}</select>
            <input type="file" id="docFile" class="doc-file" />
            <button class="btn btn-primary btn-sm" id="docUploadBtn">Upload document</button>
          </div>
          <div class="doc-hint">🔒 Encrypted at rest · PDF, images, Word/Excel, CSV or text · up to 25 MB</div>
        </div>` : "";
      const list = docs.length ? `<div class="doc-list">${docs.map((d) => `
        <div class="doc-card">
          <div class="doc-ic">${docIcon(d.original_filename)}</div>
          <div class="doc-meta">
            <a href="${d.download_url}" target="_blank" rel="noopener" class="doc-name">${esc(d.original_filename)}</a>
            <div class="doc-sub">${esc(d.document_type)} · ${fmtSize(d.file_size)} · ${esc(d.uploaded_by_name || "")} · ${fmtDate(d.created_at)}</div>
          </div>
          <a class="doc-act" href="${d.download_url}" target="_blank" rel="noopener" title="View / download">⬇</a>
          ${canEdit ? `<button class="doc-act doc-del" data-id="${d.id}" title="Delete">✕</button>` : ""}
        </div>`).join("")}</div>`
        : `<div class="empty" style="padding:34px"><div class="emoji">📁</div><h3>No documents yet</h3><p>${canEdit ? "Upload this student's passport, offer letter, financials, test scores and more — securely." : "No documents have been uploaded for this client."}</p></div>`;
      const deepScanCost = ((state.credits && (state.credits.actions || []).find((a) => a.key === "deep_scan")) || {}).credits || 5;
      const deepScanBar = (canEdit && docs.length) ? `
        <div class="cp-card" style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:14px">
          <div style="flex:1;min-width:220px">
            <div style="font-weight:700">🔍 Deep Scan document audit</div>
            <div style="font-size:12px;color:var(--text-2)">Rilono AI cross-references every uploaded document for mismatched dates, names & missing funds before the visa appointment. Costs <b>${deepScanCost} credits</b>.</div>
          </div>
          <button class="btn btn-primary btn-sm" id="deepScanBtn">Run Deep Scan · ${deepScanCost} cr</button>
        </div>` : "";
      const docReqHolder = canEdit ? `<div id="docReqCard" class="cp-card doc-req-card" style="margin-bottom:14px"></div>` : "";
      body.innerHTML = uploader + docReqHolder + deepScanBar + list;
      const dsb = $("#deepScanBtn");
      if (dsb) dsb.onclick = () => runDeepScan(cl);
      if (canEdit) { drawDocReq(); if (dr.request === undefined) loadDocReq(); }

      if (canEdit) {
        $("#docUploadBtn").onclick = async () => {
          const fileEl = $("#docFile");
          if (!fileEl.files || !fileEl.files[0]) { toast("Choose a file first", "error"); return; }
          const fd = new FormData();
          fd.append("file", fileEl.files[0]);
          fd.append("document_type", $("#docType").value || "Other");
          const btn = $("#docUploadBtn"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Uploading…';
          try {
            const res = await fetch(API + "/clients/" + cl.id + "/documents", { method: "POST", credentials: "include", body: fd });
            const out = await res.json().catch(() => null);
            if (!res.ok) throw makePublicApiError(res, out, "We couldn't upload this document. Please try again.");
            docs.unshift(out.document); tabCount("documents", docs.length); toast("Document uploaded", "success"); renderDocs();
          } catch (ex) { toast(ex.message, "error"); btn.disabled = false; btn.textContent = "Upload document"; }
        };
        $$(".doc-del", body).forEach((b) => b.onclick = async () => {
          const id = parseInt(b.dataset.id, 10);
          if (!confirm("Delete this document? This cannot be undone.")) return;
          try {
            await api("/clients/" + cl.id + "/documents/" + id, { method: "DELETE" });
            const i = docs.findIndex((x) => x.id === id); if (i >= 0) docs.splice(i, 1);
            tabCount("documents", docs.length); toast("Document deleted", "success"); renderDocs();
          } catch (ex) { toast(ex.message, "error"); }
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
      const types = state.catalog.document_types || [];
      const checks = types.map((t) =>
        `<label class="docreq-check"><input type="checkbox" value="${esc(t)}"> <span>${esc(t)}</span></label>`).join("");
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
      if (!confirm("Revoke this document request? The student's upload link will stop working.")) return;
      try { await api(`/clients/${cl.id}/document-requests/revoke`, { method: "POST" }); dr.request = null; toast("Request revoked", "success"); drawDocReq(); }
      catch (ex) { toast(ex.message, "error"); }
    }

    function renderNotes() {
      const add = canEdit ? `<div class="cp-card note-add">
        <div class="cp-sub-label">Add a note</div>
        <textarea id="noteInput" placeholder="Log a call, a follow-up or a decision about ${esc(cl.full_name)}…"></textarea>
        <button class="btn btn-primary btn-sm" id="noteSaveBtn">Add note</button></div>` : "";
      const list = data.notes.length ? `<div class="timeline">${data.notes.map((n) =>
        `<div class="tl-item"><div class="tl-meta">${esc(n.author_name || "Team")} · ${fmtDateTime(n.created_at)}</div><div class="tl-body">${esc(n.body)}</div></div>`).join("")}</div>`
        : `<div class="empty" style="padding:30px"><div class="emoji">📝</div><h3>No notes yet</h3><p>Keep a running record of calls, follow-ups and decisions.</p></div>`;
      body.innerHTML = add + list;
      if (canEdit) $("#noteSaveBtn").onclick = async () => {
        const v = $("#noteInput").value.trim(); if (!v) return;
        const btn = $("#noteSaveBtn"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
        try { const r = await api(`/clients/${cl.id}/notes`, { method: "POST", body: { body: v } }); data.notes.unshift(r.note); tabCount("notes", data.notes.length); renderNotes(); toast("Note added", "success"); }
        catch (ex) { toast(ex.message, "error"); btn.disabled = false; btn.textContent = "Add note"; }
      };
    }

    function renderEmails() {
      const composer = canEdit ? (cl.email ? `<div class="cp-card note-add">
          <div class="cp-sub-label">Email ${esc(cl.full_name)}</div>
          <input id="emailSubject" type="text" placeholder="Subject"/>
          <textarea id="emailBody" placeholder="Write your message…"></textarea>
          <div class="email-to">To: <b>${esc(cl.email)}</b></div>
          <button class="btn btn-primary btn-sm" id="emailSendBtn">✉ Send email</button></div>`
        : `<div class="plan-banner warn" style="margin-bottom:18px"><div class="pb-icon">✉</div><div class="pb-text"><b>No email on file.</b> <span>Add an email to message this client (Edit details).</span></div></div>`) : "";
      const hist = data.emails.length ? data.emails.map((em) =>
        `<div class="email-item"><div class="ei-top"><span class="ei-subject">${esc(em.subject)}</span><span style="font-size:12px;color:var(--muted)">${fmtDateTime(em.created_at)}</span></div>
         <div class="ei-body">${esc(em.body)}</div>${em.status !== "sent" ? `<div class="ei-fail">⚠ Failed: ${esc(em.error_message || "")}</div>` : ""}</div>`).join("")
        : `<div class="empty" style="padding:30px"><div class="emoji">✉️</div><h3>No emails sent yet</h3><p>Send the student an update in one click.</p></div>`;
      body.innerHTML = composer + hist;
      const sb = $("#emailSendBtn");
      if (sb) sb.onclick = async () => {
        const subject = $("#emailSubject").value.trim(), bodyv = $("#emailBody").value.trim();
        if (!subject || !bodyv) { toast("Add a subject and message", "error"); return; }
        sb.disabled = true; sb.innerHTML = '<span class="spinner"></span> Sending…';
        try { const r = await api(`/clients/${cl.id}/email`, { method: "POST", body: { subject, body: bodyv } });
          data.emails.unshift(r.email); tabCount("emails", data.emails.length); renderEmails(); toast("Email sent", "success"); }
        catch (ex) { toast(ex.message, "error"); sb.disabled = false; sb.innerHTML = "✉ Send email"; }
      };
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
      const money = (credits) => isInr ? ` (≈ ₹${Math.round(credits * perInr).toLocaleString()})` : "";
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
      if (!confirm("Revoke this interview link? The student won't be able to use it anymore.")) return;
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
          <div class="iv-slist">${sessions.length ? sessions.map(ivSessionRow).join("") : `<div class="muted" style="padding:6px 0">No mock interviews yet.</div>`}</div>
        </div>`;
      const sb = $("#ivSendBtn"); if (sb) sb.onclick = openSendModal;
      const rs = $("#ivResend"); if (rs) rs.onclick = openSendModal;
      const rv = $("#ivRevoke"); if (rv) rv.onclick = revokeInvite;
      const pb = $("#ivStartBtn"); if (pb) pb.onclick = () => startIv($("#ivVoicePref") && $("#ivVoicePref").checked);
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
      return `<div class="cp-card iv-hero">
        <div class="iv-hero-head"><div class="iv-orb">🎤</div>
          <div><div class="iv-hero-badge">Recommended</div><h3>Send a mock visa interview</h3></div></div>
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
            <label class="iv-voice-pref"><input type="checkbox" id="ivVoicePref"> 🎙 Voice${micSupported ? "" : " (read aloud)"}</label>
            <button class="btn btn-soft btn-sm" id="ivStartBtn">▶ Preview it yourself</button>
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
        const r = await api(`/clients/${cl.id}/interview/chat`, { method: "POST", body: { start: true } });
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
        const r = await api(`/clients/${cl.id}/interview/chat`, { method: "POST", body: { message: v, history: prior } });
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

    function showTab(tab) {
      $$(".cp-tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
      if (tab !== "interview") ivStopSpeak();
      if (tab === "overview") renderOverview();
      else if (tab === "documents") renderDocs();
      else if (tab === "notes") renderNotes();
      else if (tab === "emails") renderEmails();
      else if (tab === "interview") renderInterview();
    }
    $$(".cp-tab").forEach((t) => t.onclick = () => showTab(t.dataset.tab));
    showTab("overview");
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
  async function deleteClient(id) {
    openModal(`<div class="modal-head"><h3>Delete client?</h3><button class="x" onclick="__ent.closeModal()">×</button></div>
      <div class="modal-body"><p style="margin:0;color:var(--text-2)">This permanently removes the client and all their notes and email history. This cannot be undone.</p></div>
      <div class="modal-foot"><button class="btn btn-ghost" onclick="__ent.closeModal()">Cancel</button>
      <button class="btn btn-danger" id="confirmDel">Delete client</button></div>`);
    $("#confirmDel").onclick = async () => {
      try {
        await api("/clients/" + id, { method: "DELETE" });
        toast("Client deleted", "success"); closeModal();
        if (state.view === "clientPage") navigate(state.clientReturnView || "clients");
        else loadAndRenderClientList();
      } catch (ex) { toast(ex.message, "error"); }
    };
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
    if (!confirm("Remove this member from your workspace?")) return;
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
                  : `Activate the ${infra.fee_display}/month fee to keep adding clients.`}
              </div>
            </div>
            ${!infra.is_current && canManage
              ? `<button class="btn btn-primary" id="infraPayBtn">Activate ${esc(infra.fee_display)}/mo</button>`
              : (infra.is_current ? `<span class="plan-current-tag" style="color:var(--success,#10b981)">✓ Active</span>` : "")}
          </div>
        </div>`
      : "";

    const coupon = state.creditCoupon;
    const priceBlock = (p) => {
      if (!coupon) return `<div class="price">${esc(p.amount_display)}</div>`;
      const discounted = Math.max(0, Math.round(p.amount_paise * (100 - coupon.percent) / 100));
      return `<div class="price">${fmtPaise(discounted)}<span class="price-was">${esc(p.amount_display)}</span></div>
        <div class="price-off">${esc(coupon.percent_display)} off applied</div>`;
    };
    const pkgCard = (p) => `<div class="plan-card ${p.is_popular ? "popular" : ""}">
        ${p.is_popular ? `<div class="pop-tag">Best value</div>` : ""}
        <h3>${esc(p.label)}</h3><div class="tagline">${esc(p.tagline)}</div>
        ${priceBlock(p)}
        <ul>
          <li><b>${p.total_credits} credits</b>${p.bonus_credits ? ` <span style="color:var(--success,#10b981)">(+${p.bonus_credits} bonus)</span>` : ""}</li>
          <li>Worth ₹${p.value_inr.toLocaleString()} of AI actions</li>
          <li>≈ ${Math.floor(p.total_credits / 5)} Deep Scans or ${Math.floor(p.total_credits / 20)} interviews</li>
        </ul>
        ${canManage
          ? `<button class="btn ${p.is_popular ? "btn-primary" : "btn-ghost"} btn-block" onclick="__ent.topup('${p.key}')">Buy ${esc(p.label)}</button>`
          : `<div class="plan-current-tag" style="color:var(--muted)">Ask an admin to top up</div>`}
      </div>`;

    const actionRows = actions.map((a) =>
      `<div style="display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:1px solid var(--border,#eee)">
        <div><b>${esc(a.label)}</b><div style="font-size:12px;color:var(--text-2)">${esc(a.description || "")}</div></div>
        <div style="text-align:right;white-space:nowrap"><b>${a.credits} cr</b><div style="font-size:12px;color:var(--text-2)">${esc(a.price_display)}</div></div>
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
          <div style="font-size:13px;color:var(--text-2)">Worth ${esc(w.balance_display || "")} · 1 credit = ${esc("₹" + (w.credit_value_inr || 10))}</div>
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
            <div class="co-item-sub">${pkg.total_credits} credits${pkg.bonus_credits ? ` <span class="co-bonus">incl. +${pkg.bonus_credits} bonus</span>` : ""} · worth ₹${Number(pkg.value_inr || 0).toLocaleString("en-IN")} of AI actions</div>
          </div>
          <div class="co-item-price">${esc(pkg.amount_display)}</div>
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
  function renderSettings() {
    const c = $("#content");
    const org = state.me.organization || {};
    const canManage = state.perms.can_manage_users;
    c.innerHTML = `
      <div class="settings-section">
        <div class="card"><div class="card-head"><h3>Organization branding</h3></div>
          <div class="card-body">
            <div style="display:flex;align-items:center;gap:18px;margin-bottom:20px">
              <img class="logo-preview" id="settingsLogo" src="${esc(org.logo_url || "")}" alt="logo" onerror="this.style.visibility='hidden'"/>
              <div><b style="font-size:16px">${esc(org.company_name || "")}</b>
                <div style="color:var(--muted);font-size:13px">${esc((org.subdomain_slug || "") + "." + rootDomain())}</div></div>
            </div>
            ${canManage ? `
            <div class="field"><label>Company name</label><input id="setCompany" value="${esc(org.company_name || "")}"/></div>
            <div style="display:flex;gap:10px;flex-wrap:wrap">
              <button class="btn btn-primary btn-sm" id="saveBranding">Save name</button>
              <button class="btn btn-ghost btn-sm" id="regenLogo">🎲 Generate new logo</button>
            </div>` : `<p style="color:var(--muted);font-size:13px">Only admins can change branding.</p>`}
          </div></div>

        <div class="card" style="margin-top:20px"><div class="card-head"><h3>Workspace</h3></div>
          <div class="card-body">
            <div class="detail-grid">
              <div class="detail-item"><label>Portal URL</label><div>${esc((org.subdomain_slug || "") + "." + rootDomain())}</div></div>
              <div class="detail-item"><label>Plan</label><div>${esc(state.subscription ? state.subscription.plan_label : "—")}</div></div>
              <div class="detail-item"><label>Your role</label><div style="text-transform:capitalize">${esc((state.me.membership && state.me.membership.role) || "")}</div></div>
              <div class="detail-item"><label>Signed in as</label><div>${esc(state.me.user.email)}</div></div>
            </div>
            <button class="btn btn-danger btn-sm" style="margin-top:18px" onclick="document.getElementById('signoutBtn').click()">Sign out</button>
          </div></div>
      </div>`;

    if (canManage) {
      $("#saveBranding").onclick = async () => {
        const name = $("#setCompany").value.trim(); if (name.length < 2) { toast("Enter a company name", "error"); return; }
        const btn = $("#saveBranding"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
        try { const r = await api("/organization/branding", { method: "PATCH", body: { company_name: name } });
          state.me.organization = Object.assign(state.me.organization, r.organization || {});
          $("#brandName").textContent = name; toast("Saved", "success"); }
        catch (ex) { toast(ex.message, "error"); }
        finally { btn.disabled = false; btn.textContent = "Save name"; }
      };
      $("#regenLogo").onclick = async () => {
        const btn = $("#regenLogo"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
        try { const r = await api("/organization/branding", { method: "PATCH", body: { generate_random_logo: true } });
          const url = (r.organization || {}).logo_url; if (url) { $("#settingsLogo").src = url; $("#settingsLogo").style.visibility = "visible"; $("#brandLogo").src = url; $("#brandLogo").style.display = ""; state.me.organization.logo_url = url; }
          toast("New logo generated", "success"); }
        catch (ex) { toast(ex.message, "error"); }
        finally { btn.disabled = false; btn.innerHTML = "🎲 Generate new logo"; }
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
      const data = await api("/ai/chat", { method: "POST", body: { message: msg, history: priorHistory } });
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

  async function runDeepScan(cl) {
    const btn = $("#deepScanBtn");
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Scanning…'; }
    let res;
    try { res = await api(`/clients/${cl.id}/deep-scan`, { method: "POST" }); }
    catch (ex) {
      if (ex.status === 402) { toast(ex.message, "error"); navigate("credits"); return; }
      toast(ex.message, "error");
      if (btn) { btn.disabled = false; btn.textContent = "Run Deep Scan"; }
      return;
    }
    if (res.wallet) { state.credits = res.wallet; updatePlanChip(); }
    toast(`Deep Scan complete · ${res.credits_charged} credits used`, "success");
    if (btn) { btn.disabled = false; btn.innerHTML = "Run Deep Scan · " + (res.credits_charged || 5) + " cr"; }
    showDeepScanReport(cl, res);
  }

  // --- Deep Scan report: parse the AI's markdown into readable, styled sections ---
  function dsSections(md) {
    const out = {}; let cur = "_pre"; out[cur] = [];
    String(md || "").split(/\n/).forEach((line) => {
      const h = line.match(/^\s*#{1,4}\s+(.*)$/);
      if (h) { cur = h[1].trim().toLowerCase().replace(/[:*]+$/, "").trim(); out[cur] = []; }
      else out[cur].push(line);
    });
    return out;
  }
  function dsLines(sections, keyword) {
    const key = Object.keys(sections).find((k) => k.includes(keyword));
    return key ? sections[key] : [];
  }
  function dsText(sections, keyword) {
    return (dsLines(sections, keyword) || []).map((x) => x.trim()).filter(Boolean).join(" ").trim();
  }
  function dsItems(sections, keyword) {
    const lines = dsLines(sections, keyword);
    const items = [];
    (lines || []).forEach((l) => {
      const m = l.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
      if (m && m[1].trim()) items.push(m[1].trim());
    });
    if (items.length) return items.filter((x) => !/^none\b/i.test(x.replace(/[*_.]/g, "").trim()));
    const joined = (lines || []).map((x) => x.trim()).filter(Boolean).join(" ").trim();
    if (joined && !/^none\b/i.test(joined.replace(/[*_.#]/g, "").trim())) return [joined];
    return [];
  }
  function dsInline(s) {
    let t = esc(s);
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    t = t.replace(/`([^`]+)`/g, '<code style="background:var(--bg-2);padding:1px 5px;border-radius:5px;font-size:.92em">$1</code>');
    return t;
  }
  function dsItemText(it) {
    let cite = "";
    it = String(it).replace(/\s*\((?:DOCUMENT|DOC)\s*#?\s*(\d+)\)\s*/gi, (m, n) => { cite += `<span class="cite">Doc ${n}</span>`; return " "; }).trim();
    const tag = it.match(/^\*{0,2}(Missing|Stale|Expired|Outdated|Mismatch|Inconsistent|Incorrect)\*{0,2}\s*[:\-–]\s*(.*)$/i);
    if (tag) {
      const isMiss = /^(missing|stale|expired|outdated)$/i.test(tag[1]);
      const bg = isMiss ? "#fef3c7" : "#fee2e2", color = isMiss ? "#b45309" : "#dc2626";
      return `<span class="tag" style="background:${bg};color:${color}">${esc(tag[1])}</span>${dsInline(tag[2])}${cite}`;
    }
    return dsInline(it) + cite;
  }
  function dsFindingSection(title, items, cls, icon, clearMsg) {
    if (!items.length) return `<div class="ds-sec"><div class="ds-sec-h">${title}</div><div class="ds-clear">✓ ${esc(clearMsg)}</div></div>`;
    const rows = items.map((it) => `<div class="ds-item ${cls}"><div class="b">${icon}</div><div>${dsItemText(it)}</div></div>`).join("");
    return `<div class="ds-sec"><div class="ds-sec-h">${title} <span class="n">${items.length}</span></div><div class="ds-list">${rows}</div></div>`;
  }
  function deepScanReportHtml(res) {
    const risk = (res.risk_level || "medium").toLowerCase();
    const sections = dsSections(res.report);
    const overall = dsText(sections, "overall") || dsText(sections, "risk");
    const mism = dsItems(sections, "mismatch");
    const missing = dsItems(sections, "missing");
    const actions = dsItems(sections, "action").length ? dsItems(sections, "action") : dsItems(sections, "recommend");
    const meta = ({ high: { ic: "⚠️", word: "High risk" }, medium: { ic: "⚡", word: "Medium risk" }, low: { ic: "✅", word: "Low risk" } })[risk] || { ic: "⚡", word: "Medium risk" };
    const why = overall.replace(/^\s*(HIGH|MEDIUM|LOW)\b[\s:—–-]*/i, "").trim();
    const n = res.documents_analyzed;
    const total = (res.documents_total != null) ? res.documents_total : n;
    const skipped = res.documents_skipped || 0, overCap = res.documents_over_cap || 0, failed = res.extraction_failures || 0;
    const coverBits = [];
    if (skipped) coverBits.push(`${skipped} had no readable text yet`);
    if (overCap) coverBits.push(`${overCap} exceeded the per-scan limit`);
    if (failed) coverBits.push(`${failed} audited from a raw excerpt only`);
    const coverWarn = (skipped + overCap + failed) > 0
      ? `<div style="margin:8px 0 2px;padding:9px 12px;border-radius:9px;background:rgba(245,158,11,.12);color:#b45309;font-size:12.5px;font-weight:600;border:1px solid rgba(245,158,11,.28)">⚠️ Audited <b>${n}</b> of <b>${total}</b> documents — ${coverBits.join("; ")}.${(skipped + overCap) > 0 ? " Re-run once they're ready for full coverage." : ""}</div>`
      : "";
    return `
      <div class="ds-meta"><b>${n}</b>&nbsp;of&nbsp;<b>${total}</b>&nbsp;document${total === 1 ? "" : "s"} audited&nbsp;·&nbsp;${res.credits_charged} credits</div>
      ${coverWarn}
      <div class="ds-risk ${risk}"><div class="ds-ic">${meta.ic}</div>
        <div><div class="lvl">${meta.word}</div><div class="why">${why ? dsInline(why) : "See the findings below."}</div></div></div>
      <div class="ds-stats">
        <div class="ds-stat"><b style="color:${mism.length ? "#dc2626" : "#10b981"}">${mism.length}</b><span>Mismatches</span></div>
        <div class="ds-stat"><b style="color:${missing.length ? "#b45309" : "#10b981"}">${missing.length}</b><span>Missing / stale</span></div>
        <div class="ds-stat"><b style="color:#4338ca">${actions.length}</b><span>Actions</span></div>
      </div>
      ${dsFindingSection("⚠️ Mismatches &amp; errors", mism, "err", "!", "No mismatches or errors found across the documents.")}
      ${dsFindingSection("📄 Missing or stale documents", missing, "miss", "!", "Nothing missing — all expected documents are present and current.")}
      ${actions.length ? `<div class="ds-sec"><div class="ds-sec-h">✅ Recommended actions <span class="n">${actions.length}</span></div>
        <div class="ds-list">${actions.map((it, i) => `<div class="ds-item act"><div class="b">${i + 1}</div><div>${dsItemText(it)}</div></div>`).join("")}</div></div>` : ""}`;
  }

  function showDeepScanReport(cl, res) {
    openModal(`<div class="modal-head"><h3>🔍 Deep Scan · ${esc(cl.full_name)}</h3><button class="x" onclick="__ent.closeModal()">×</button></div>
      <div class="modal-body">${res && res.report ? deepScanReportHtml(res) : '<div class="ds-clear">✓ No findings returned.</div>'}</div>
      <div class="modal-foot"><button class="btn btn-ghost" onclick="__ent.closeModal()">Close</button></div>`);
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
    if (!confirm("Delete this event?")) return;
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

  window.__ent = {
    go: navigate, openClient, openClientForm: () => openClientForm(null), editClient, deleteClient, setStatus,
    closeModal, closeDrawer, changeRole, removeMember, checkout, setCycle,
    applyCreditCoupon, removeCreditCoupon, applyBillingCoupon, removeBillingCoupon,
    topup: openCreditCheckout, activateInfra: activateInfraFee, deepScan: runDeepScan,
    viewClients: openClientsFiltered, viewVisaType, clearSearch: clearClientSearch,
    viewInterview: viewInterviewSession, sendInterview: openSendInterviewPicker,
    calPrev, calNext, calToday, calSetMonth, calSetYear, calEvent, calAdd, calDelete, calToggleDone,
  };

  /* ============================================================
     INIT
     ============================================================ */
  setupAuth();
  boot();
})();
