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
    catalog: null,
    view: "dashboard",
    clients: [],
    statusCounts: {},
    filters: { status: "", category: "", country: "", q: "" },
    billingCycle: "monthly",
    activeClient: null,
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
  function fmtDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d)) return esc(iso);
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
    const d = new Date(iso); if (isNaN(d)) return null;
    return Math.ceil((d - new Date()) / 86400000);
  }
  function rootDomain() {
    const h = location.hostname;
    if (h === "localhost" || /^\d+\.\d+\.\d+\.\d+$/.test(h)) return "rilono.com";
    if (h.endsWith("lvh.me")) return "lvh.me";
    const parts = h.split(".");
    if (parts.length <= 2) return h;
    return parts.slice(-2).join(".");
  }

  async function api(path, opts) {
    opts = opts || {};
    const res = await fetch(API + path, {
      method: opts.method || "GET",
      credentials: "include",
      headers: opts.body ? { "Content-Type": "application/json" } : {},
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch (e) { /* no body */ }
    if (!res.ok) {
      const detail = data && (data.detail || data.message);
      const err = new Error(typeof detail === "string" ? detail : "Request failed");
      err.status = res.status; err.data = data;
      throw err;
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
      throw new Error("Security check could not load. Refresh the page and try again.");
    }
    if (!enterpriseTurnstile.siteKey) return "";
    await renderEnterpriseTurnstile(key);

    const widgetId = enterpriseTurnstile.widgets[key];
    if (enterpriseTurnstile.loadFailed || !window.turnstile || widgetId === null) {
      throw new Error("Security check could not load. Refresh the page and try again.");
    }

    let token = "";
    try {
      token = window.turnstile.getResponse(widgetId) || "";
    } catch (error) {
      token = "";
    }
    if (!token) throw new Error("Please complete the security check.");
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
        if (!res.ok) throw new Error((data && (data.detail || data.message)) || "Could not send reset email.");
        ok.innerHTML = "If an account exists for <b>" + esc(email) + "</b>, a password reset link is on its way. Check your inbox (and spam folder).";
        ok.classList.remove("hidden");
        f.reset();
        resetEnterpriseTurnstile("forgot");
      } catch (ex) {
        err.textContent = ex.message; err.classList.remove("hidden");
        resetEnterpriseTurnstile("forgot");
      } finally { btn.disabled = false; btn.textContent = "Send reset link"; }
    };

    $("#signupForm").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target; const btn = $("#signupBtn");
      const err = $("#signupError"); err.classList.add("hidden");
      const body = {
        company_name: f.company_name.value.trim(),
        subdomain_slug: f.subdomain_slug.value.trim().toLowerCase(),
        full_name: f.full_name.value.trim(),
        email: f.email.value.trim(),
        password: f.password.value,
      };
      try {
        const turnstileToken = await getEnterpriseTurnstileToken("signup");
        if (turnstileToken) body.cf_turnstile_token = turnstileToken;
        btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Creating…';
        const data = await api("/signup", { method: "POST", body });
        if (redirectToPortalIfNeeded(data)) return;
        await boot({ fromAuthAction: true });
      } catch (ex) {
        err.textContent = ex.message; err.classList.remove("hidden");
        resetEnterpriseTurnstile("signup");
      } finally { btn.disabled = false; btn.textContent = "Create my workspace"; }
    };

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
    $("#signupCard").classList.remove("hidden");
    renderEnterpriseTurnstile("signup");
  }
  function showLoginCard() {
    $("#signupCard").classList.add("hidden");
    $("#forgotCard").classList.add("hidden");
    $("#loginCard").classList.remove("hidden");
    renderEnterpriseTurnstile("login");
  }
  function showForgotCard() {
    const em = ($("#loginForm").email.value || "").trim();
    if (em) $("#forgotForm").email.value = em;
    $("#loginCard").classList.add("hidden");
    $("#signupCard").classList.add("hidden");
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

    if (!state.perms.can_edit_data) $("#topAddClient").classList.add("hidden");

    try { state.catalog = await api("/catalog"); } catch (e) { state.catalog = { countries: [], categories: [], stages: [], priorities: [] }; }

    navigate(state.view || "dashboard");
  }

  function updatePlanChip() {
    const s = state.subscription;
    $("#brandPlan").textContent = "Free plan";
    if (s && s.clients_used != null) $("#clientsBadge").textContent = s.clients_used;
  }

  /* ============================================================
     NAV
     ============================================================ */
  function navigate(view) {
    state.view = view;
    $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
    $("#sidebar").classList.remove("open");
    const titles = { dashboard: "Dashboard", clients: "Clients", ai: "AI Assistant", team: "Team", billing: "Plans & Billing", settings: "Settings" };
    $("#viewTitle").textContent = titles[view] || "";
    $("#globalSearchBox").style.display = view === "clients" || view === "dashboard" ? "" : "none";
    if (view === "dashboard") renderDashboard();
    else if (view === "clients") renderClients();
    else if (view === "ai") renderAIAssistant();
    else if (view === "team") renderTeam();
    else if (view === "billing") renderBilling();
    else if (view === "settings") renderSettings();
  }
  $$(".nav-item").forEach((b) => b.onclick = () => navigate(b.dataset.view));
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

  async function loadAndRenderClientList() {
    const wrap = $("#clientListWrap"); if (!wrap) return;
    const p = new URLSearchParams();
    if (state.filters.status) p.set("status_filter", state.filters.status);
    if (state.filters.category) p.set("category", state.filters.category);
    if (state.filters.country) p.set("country", state.filters.country);
    if (state.filters.q) p.set("q", state.filters.q.trim());
    let data;
    try { data = await api("/clients?" + p.toString()); } catch (ex) { wrap.innerHTML = errBox(ex); return; }
    let clients = data.clients;
    const scope = state.dashScope;
    if (scope === "active") clients = clients.filter((c) => c.stage && c.stage.is_open);
    else if (scope === "month") { const ms = new Date(); ms.setDate(1); ms.setHours(0, 0, 0, 0); clients = clients.filter((c) => c.created_at && new Date(c.created_at) >= ms); }
    else if (scope && scope.visaType) clients = clients.filter((c) => (c.visa_type || "") === scope.visaType);
    state.clients = clients;
    state.statusCounts = data.status_counts || {};
    $("#clientsBadge").textContent = data.total_clients;
    renderClientToolbar();

    const hasFilter = state.filters.q || state.filters.status || state.filters.country || state.dashScope;
    if (!clients.length) {
      const emptyTitle = state.filters.q ? `No clients found for “${esc(state.filters.q)}”` : (hasFilter ? "No matching clients" : "No clients yet");
      const emptyHelp = state.filters.q ? "Try another name, email, phone, passport, visa type, country, intake, or counselor." : (hasFilter ? "Try clearing your filters." : "Add your first visa client to get started.");
      wrap.innerHTML = `<div class="empty"><div class="emoji">🗂️</div><h3>${emptyTitle}</h3>
        <p>${emptyHelp}</p>
        ${state.filters.q ? `<button class="btn btn-ghost" onclick="__ent.clearSearch()">Clear search</button>` : ""}
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
        <td class="hide-sm"><div class="cl-dest"><span class="fl">${esc(cl.country.flag_emoji)}</span><div>${esc(cl.destination_country_name)}<small>${esc(cl.intake || cl.country.landmark || "")}</small></div></div></td>
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
          <div class="field"><label>Phone</label><input name="phone" value="${esc(c.phone || "")}" placeholder="+91 …"/></div>
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

    $("#clientForm").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target; const btn = $("#clientSaveBtn"); const err = $("#clientFormError");
      err.classList.add("hidden");
      const body = {};
      ["full_name", "destination_country_code", "visa_type", "intake", "email", "phone",
        "nationality", "date_of_birth", "passport_number", "passport_expiry", "priority", "status",
        "target_date", "application_reference"].forEach((k) => {
        const el = f[k]; if (!el) return; const v = (el.value || "").trim(); if (v !== "") body[k] = v;
      });
      if (!isEdit) body.visa_category = "student";
      const assign = f.assigned_to_user_id.value;
      body.assigned_to_user_id = assign ? parseInt(assign, 10) : null;
      if (!isEdit && f.initial_note && f.initial_note.value.trim()) body.initial_note = f.initial_note.value.trim();

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
        if (ex.status === 402) { closeModal(); toast(ex.message, "error"); navigate("billing"); return; }
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

  async function openClient(id) {
    state.activeClient = id;
    if (state.view !== "clientPage") state.clientReturnView = state.view || "clients";
    state.view = "clientPage";
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
        </div>
        <div class="cp-body" id="cpBody"></div>
      </div>`;

    $("#cpBack").onclick = () => navigate(state.clientReturnView || "clients");
    if (canEdit) {
      $("#cpEdit").onclick = () => editClient(cl.id);
      $("#cpDelete").onclick = () => deleteClient(cl.id);
    }
    const body = $("#cpBody");

    function tabCount(tab, n) {
      const labels = { documents: "Documents", notes: "Notes", emails: "Emails" };
      const el = $(`.cp-tab[data-tab="${tab}"]`);
      if (el) el.textContent = labels[tab] + (n ? ` (${n})` : "");
    }

    function renderOverview() {
      const stages = state.catalog.stages.filter((s) => s.key !== "on_hold");
      const onHold = state.catalog.stages.find((s) => s.key === "on_hold");
      const stageFlow = stages.map((s) => {
        const active = cl.status === s.key;
        return `<button class="stage-step ${active ? "done" : ""}" ${active ? `style="background:${s.color}"` : ""} ${canEdit ? `onclick="__ent.setStatus(${cl.id},'${s.key}')"` : "disabled"}>${esc(s.label)}</button>`;
      }).join("") + (onHold ? `<button class="stage-step ${cl.status === "on_hold" ? "done" : ""}" ${cl.status === "on_hold" ? `style="background:${onHold.color}"` : ""} ${canEdit ? `onclick="__ent.setStatus(${cl.id},'on_hold')"` : "disabled"}>${esc(onHold.label)}</button>` : "");

      const assignField = `<div class="detail-item"><label>Assigned counselor</label>${
        canEdit
          ? `<select class="select-mini cp-assign" id="cpAssign"><option value="">Unassigned</option>${members.map((m) => `<option value="${m.user_id}" ${cl.assigned_to_user_id === m.user_id ? "selected" : ""}>${esc(m.full_name || m.email)}</option>`).join("")}</select>`
          : `<div>${cl.assigned_to_name ? esc(cl.assigned_to_name) : "—"}</div>`
      }</div>`;

      body.innerHTML = `
        <div class="cp-card">
          <div class="cp-card-head"><h3>Visa status</h3>${statusPill(cl.stage)}</div>
          <div class="stage-flow">${stageFlow}</div>
        </div>
        <div class="cp-card">
          <div class="cp-card-head"><h3>Client details</h3></div>
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
      const as = $("#cpAssign");
      if (as) as.onchange = async () => {
        const val = as.value ? parseInt(as.value, 10) : null;
        as.disabled = true;
        try {
          const r = await api("/clients/" + cl.id, { method: "PATCH", body: { assigned_to_user_id: val } });
          cl.assigned_to_user_id = r.client.assigned_to_user_id;
          cl.assigned_to_name = r.client.assigned_to_name;
          toast(val ? "Counselor assigned" : "Counselor unassigned", "success");
        } catch (ex) { toast(ex.message, "error"); as.value = cl.assigned_to_user_id || ""; }
        finally { as.disabled = false; }
      };
    }

    function renderDocs() {
      const types = state.catalog.document_types || [];
      const uploader = canEdit ? `
        <div class="cp-card doc-upload">
          <div class="doc-up-row">
            <select class="select-mini" id="docType">${types.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`).join("")}</select>
            <input type="file" id="docFile" class="doc-file" />
            <button class="btn btn-primary btn-sm" id="docUploadBtn">Upload document</button>
          </div>
          <div class="doc-hint">PDF, images, Word/Excel, CSV or text · up to 25 MB · stored privately</div>
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
      body.innerHTML = uploader + list;

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
            if (!res.ok) throw new Error((out && (out.detail || out.message)) || "Upload failed");
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

    function renderNotes() {
      const add = canEdit ? `<div class="cp-card note-add">
        <textarea id="noteInput" placeholder="Add a note about this client…"></textarea>
        <button class="btn btn-primary btn-sm" style="align-self:flex-start" id="noteSaveBtn">Add note</button></div>` : "";
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
          <input id="emailSubject" class="select-mini" style="width:100%;padding:11px 13px" placeholder="Subject"/>
          <textarea id="emailBody" placeholder="Write your message to ${esc(cl.full_name)}…"></textarea>
          <button class="btn btn-primary btn-sm" style="align-self:flex-start" id="emailSendBtn">✉ Send email</button>
          <div style="font-size:12px;color:var(--muted)">To: ${esc(cl.email)}</div></div>`
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

    function showTab(tab) {
      $$(".cp-tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
      if (tab === "overview") renderOverview();
      else if (tab === "documents") renderDocs();
      else if (tab === "notes") renderNotes();
      else if (tab === "emails") renderEmails();
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
          if (ex.status === 402) { closeModal(); toast(ex.message, "error"); navigate("billing"); return; }
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

    const planCard = (p) => {
      const price = cycle === "yearly" ? p.yearly_display : p.monthly_display;
      const isCurrent = sub.plan === p.key && !sub.is_trial;
      return `<div class="plan-card ${p.is_popular ? "popular" : ""} ${isCurrent ? "current-plan" : ""}">
        ${p.is_popular ? `<div class="pop-tag">Most popular</div>` : ""}
        <h3>${esc(p.label)}</h3><div class="tagline">${esc(p.tagline)}</div>
        <div class="price">${price}<small>/${cycle === "yearly" ? "yr" : "mo"}</small></div>
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
      <div class="plan-grid">${d.plans.map(planCard).join("")}</div>
      ${!d.plans.length ? "" : `<p style="text-align:center;color:var(--muted);font-size:13px;margin-top:18px">Secure payments via Razorpay. Cancel anytime.</p>`}`;
  }
  function setCycle(c) { state.billingCycle = c; renderBilling(); }

  async function checkout(plan) {
    let res;
    try { res = await api("/billing/checkout", { method: "POST", body: { plan, billing_cycle: state.billingCycle } }); }
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
     AI ASSISTANT (Rilono Copilot)
     ============================================================ */
  function renderAIAssistant() {
    if (!state.aiHistory) state.aiHistory = [];
    const c = $("#content");
    c.innerHTML = `
      <div class="ai-wrap">
        <div class="ai-head">
          <div class="ai-orb">✨</div>
          <div><h2>Rilono Copilot</h2><p>Ask anything about your clients, visa statuses and activity — I read your live portal data to answer.</p></div>
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

  function aiFormat(text) {
    let t = esc(text);
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    const lines = t.split(/\n/);
    let html = "", inList = false;
    for (const raw of lines) {
      const line = raw.replace(/\s+$/, "");
      const m = line.match(/^\s*[-*•]\s+(.*)$/);
      if (m) { if (!inList) { html += "<ul>"; inList = true; } html += "<li>" + m[1] + "</li>"; }
      else { if (inList) { html += "</ul>"; inList = false; } if (line.trim() === "") continue; html += "<p>" + line + "</p>"; }
    }
    if (inList) html += "</ul>";
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
        thread.innerHTML = `<div class="ai-empty"><div class="ai-orb lg">🔌</div><h3>AI assistant unavailable</h3><p>An administrator needs to configure the Gemini API key on the server to enable Rilono Copilot.</p></div>`;
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
    } catch (ex) {
      state.aiHistory = state.aiHistory.filter((m) => m.role !== "typing");
      state.aiHistory.push({ role: "model", content: "Sorry — " + (ex.message || "I couldn't answer that right now.") });
    } finally {
      state.aiBusy = false;
      renderAiThread();
    }
  }

  window.__ent = {
    go: navigate, openClient, openClientForm: () => openClientForm(null), editClient, deleteClient, setStatus,
    closeModal, closeDrawer, changeRole, removeMember, checkout, setCycle,
    viewClients: openClientsFiltered, viewVisaType, clearSearch: clearClientSearch,
  };

  /* ============================================================
     INIT
     ============================================================ */
  setupAuth();
  boot();
})();
