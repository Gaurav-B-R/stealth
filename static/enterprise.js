(function () {
    "use strict";

    const $ = (sel, ctx = document) => ctx.querySelector(sel);
    const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

    const authScreen = $("#entAuthScreen");
    const dashboard = $("#entDashboard");
    const loginForm = $("#entLoginForm");
    const loginBtn = $("#entLoginBtn");
    const authFlash = $("#entAuthFlash");
    const turnstileWrap = $("#entTurnstileWrap");
    const turnstileHint = $("#entTurnstileHint");

    const sidebar = $("#entSidebar");
    const sidebarOverlay = $("#entSidebarOverlay");
    const mobileToggle = $("#entMobileToggle");
    const pageTitle = $("#entPageTitle");

    const SECTION_MAP = {
        overview: "entSectionOverview",
        students: "entSectionStudents",
        visas: "entSectionVisas",
        documents: "entSectionDocuments",
        analytics: "entSectionAnalytics",
        compliance: "entSectionCompliance",
        team: "entSectionTeam",
        settings: "entSectionSettings",
    };

    const TITLE_MAP = {
        overview: "Overview",
        students: "Students",
        visas: "Visa Cases",
        documents: "Documents",
        analytics: "Analytics",
        compliance: "Compliance",
        team: "Team",
        settings: "Settings",
    };

    let currentSection = "overview";
    let entUser = null;
    const turnstileState = {
        siteKey: "",
        widgetId: null,
    };

    function showFlash(msg, type = "info") {
        authFlash.textContent = msg;
        authFlash.className = `ent-flash ${type}`;
        authFlash.style.display = "";
    }

    function hideFlash() {
        authFlash.style.display = "none";
    }

    function switchToSection(key) {
        if (!SECTION_MAP[key]) return;
        currentSection = key;

        $$(".ent-section").forEach((s) => s.classList.remove("active"));
        const target = $(`#${SECTION_MAP[key]}`);
        if (target) target.classList.add("active");

        $$(".ent-nav-item[data-section]").forEach((btn) => {
            btn.classList.toggle("active", btn.dataset.section === key);
        });

        if (pageTitle) pageTitle.textContent = TITLE_MAP[key] || key;

        closeMobileSidebar();
    }

    function applyUserToUI(user) {
        entUser = user;
        if (!user) return;
        const initials = (user.full_name || user.email || "U")
            .split(" ")
            .map((w) => w[0])
            .join("")
            .slice(0, 2)
            .toUpperCase();
        const nameEl = $("#entUserName");
        const avatarEl = $("#entUserAvatar");
        if (nameEl) nameEl.textContent = user.full_name || user.email;
        if (avatarEl) avatarEl.textContent = initials;
    }

    function showDashboard() {
        authScreen.style.display = "none";
        dashboard.style.display = "";
        switchToSection("overview");
    }

    function showAuth() {
        dashboard.style.display = "none";
        authScreen.style.display = "";
    }

    async function fetchTurnstileSiteKey() {
        try {
            const response = await fetch("/api/auth/turnstile-site-key", {
                credentials: "same-origin",
            });
            if (!response.ok) return "";
            const data = await response.json();
            return typeof data.site_key === "string" ? data.site_key.trim() : "";
        } catch (_) {
            return "";
        }
    }

    async function waitForTurnstileApi(timeoutMs = 5000) {
        if (window.turnstile && typeof window.turnstile.render === "function") {
            return true;
        }
        const started = Date.now();
        while (Date.now() - started < timeoutMs) {
            await new Promise((resolve) => setTimeout(resolve, 100));
            if (window.turnstile && typeof window.turnstile.render === "function") {
                return true;
            }
        }
        return false;
    }

    function resetTurnstileWidget() {
        if (!turnstileState.siteKey || !window.turnstile || turnstileState.widgetId === null) return;
        try {
            window.turnstile.reset(turnstileState.widgetId);
        } catch (_) {}
    }

    function getTurnstileToken() {
        if (!turnstileState.siteKey || !window.turnstile || turnstileState.widgetId === null) {
            return "";
        }
        try {
            return window.turnstile.getResponse(turnstileState.widgetId) || "";
        } catch (_) {
            return "";
        }
    }

    async function initializeTurnstile() {
        turnstileState.siteKey = await fetchTurnstileSiteKey();
        if (!turnstileState.siteKey) {
            if (turnstileWrap) turnstileWrap.hidden = true;
            return;
        }

        if (!turnstileWrap) return;
        turnstileWrap.hidden = false;

        const apiReady = await waitForTurnstileApi();
        if (!apiReady) {
            if (turnstileHint) {
                turnstileHint.textContent = "Security widget failed to load. Refresh and try again.";
            }
            return;
        }

        try {
            turnstileState.widgetId = window.turnstile.render("#entTurnstileWidget", {
                sitekey: turnstileState.siteKey,
            });
        } catch (_) {
            if (turnstileHint) {
                turnstileHint.textContent = "Security widget failed to load. Refresh and try again.";
            }
        }
    }

    async function checkSession() {
        try {
            const res = await fetch("/api/auth/me", {
                credentials: "same-origin",
            });
            if (res.ok) {
                const user = await res.json();
                if (!(user && (user.is_admin || user.is_developer))) {
                    showFlash("Enterprise access is restricted to authorized team members.", "error");
                    showAuth();
                    return;
                }
                applyUserToUI(user);
                showDashboard();
                return;
            }
        } catch (_) {}
        showAuth();
    }

    function openMobileSidebar() {
        sidebar.classList.add("open");
        sidebarOverlay.classList.add("open");
    }

    function closeMobileSidebar() {
        sidebar.classList.remove("open");
        sidebarOverlay.classList.remove("open");
    }

    loginForm.addEventListener("submit", async function (e) {
        e.preventDefault();
        hideFlash();
        const email = $("#entEmail").value.trim();
        const password = $("#entPassword").value;
        if (!email || !password) {
            showFlash("Please enter both email and password.", "error");
            return;
        }
        loginBtn.disabled = true;
        loginBtn.textContent = "Signing in...";

        try {
            const payload = { email, password };
            if (turnstileState.siteKey) {
                const turnstileToken = getTurnstileToken();
                if (!turnstileToken) {
                    showFlash("Please complete security verification.", "error");
                    loginBtn.disabled = false;
                    loginBtn.textContent = "Sign In";
                    return;
                }
                payload.cf_turnstile_token = turnstileToken;
            }

            const res = await fetch("/api/enterprise/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify(payload),
            });
            const data = await res.json();
            if (!res.ok) {
                showFlash(data.detail || "Login failed.", "error");
                resetTurnstileWidget();
                loginBtn.disabled = false;
                loginBtn.textContent = "Sign In";
                return;
            }
            applyUserToUI(data.user);
            showDashboard();
        } catch (err) {
            showFlash("Network error. Please try again.", "error");
            resetTurnstileWidget();
        } finally {
            loginBtn.disabled = false;
            loginBtn.textContent = "Sign In";
        }
    });

    $$(".ent-nav-item[data-section]").forEach((btn) => {
        btn.addEventListener("click", () => switchToSection(btn.dataset.section));
    });

    if (mobileToggle) {
        mobileToggle.addEventListener("click", openMobileSidebar);
    }
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener("click", closeMobileSidebar);
    }

    initializeTurnstile();
    checkSession();
})();
