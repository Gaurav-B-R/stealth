(function () {
    "use strict";

    const $ = (sel, ctx = document) => ctx.querySelector(sel);
    const $$ = (sel, ctx = document) => Array.from(ctx.querySelectorAll(sel));

    const authScreen = $("#entAuthScreen");
    const dashboard = $("#entDashboard");
    const onboardingScreen = $("#entOnboardingScreen");
    const loginForm = $("#entLoginForm");
    const loginBtn = $("#entLoginBtn");
    const authFlash = $("#entAuthFlash");

    const onboardingForm = $("#entOnboardingForm");
    const onboardingBtn = $("#entOnboardingBtn");
    const onboardingFlash = $("#entOnboardingFlash");
    const companyNameInput = $("#entCompanyName");
    const subdomainInput = $("#entSubdomainSlug");
    const subdomainPreview = $("#entSubdomainPreview");

    const sidebar = $("#entSidebar");
    const sidebarOverlay = $("#entSidebarOverlay");
    const mobileToggle = $("#entMobileToggle");
    const pageTitle = $("#entPageTitle");

    const teamFlash = $("#entTeamFlash");
    const teamTableBody = $("#entTeamTableBody");
    const teamAddForm = $("#entTeamAddForm");
    const teamAddBtn = $("#entTeamAddBtn");
    const teamEmailInput = $("#entTeamEmail");
    const teamNameInput = $("#entTeamName");
    const teamRoleInput = $("#entTeamRole");
    const teamAccessNotice = $("#entTeamAccessNotice");

    const userNameEl = $("#entUserName");
    const userAvatarEl = $("#entUserAvatar");
    const userRoleEl = $(".ent-user-role");
    const orgNameEl = $("#entOrgName");
    const orgAvatarEl = $(".ent-org-avatar");
    const orgPortalEl = $("#entOrgPortalUrl");

    const turnstileWrap = $("#entTurnstileWrap");
    const turnstileHint = $("#entTurnstileHint");

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

    const ROLE_LABEL = {
        admin: "Organization Admin",
        editor: "Editor",
        viewer: "Viewer",
    };

    const ENTERPRISE_ROOT_DOMAIN = "rilono.com";
    const SUBDOMAIN_MIN_LENGTH = 3;
    const SUBDOMAIN_MAX_LENGTH = 32;
    const SUBDOMAIN_PATTERN = /^[a-z0-9](?:[a-z0-9-]{1,30}[a-z0-9])$/;
    const RESERVED_SUBDOMAINS = new Set([
        "www",
        "app",
        "api",
        "admin",
        "auth",
        "portal",
        "enterprise",
        "mail",
        "status",
        "support",
        "docs",
        "blog",
        "cdn",
        "m",
        "ftp",
        "smtp",
        "imap",
        "pop",
        "rilono",
    ]);

    const state = {
        user: null,
        organization: null,
        membership: null,
        permissions: {
            can_view_data: false,
            can_edit_data: false,
            can_manage_users: false,
        },
        currentSection: "overview",
        teamMembers: [],
        teamLoading: false,
        turnstile: {
            siteKey: "",
            widgetId: null,
        },
    };

    function normalizeRole(role) {
        const raw = String(role || "").trim().toLowerCase();
        if (raw === "owner" || raw === "org_admin" || raw === "organization_admin") return "admin";
        if (raw === "edit" || raw === "write") return "editor";
        if (raw === "read" || raw === "view") return "viewer";
        if (raw === "admin" || raw === "editor" || raw === "viewer") return raw;
        return "viewer";
    }

    function roleToLabel(role) {
        const normalized = normalizeRole(role);
        return ROLE_LABEL[normalized] || "Viewer";
    }

    function getInitials(source, fallback) {
        const value = String(source || "").trim();
        if (!value) return fallback || "U";

        const words = value
            .replace(/[^a-zA-Z0-9\s@._-]/g, " ")
            .split(/\s+/)
            .filter(Boolean);

        if (words.length >= 2) {
            return (words[0][0] + words[1][0]).toUpperCase();
        }

        if (value.includes("@")) {
            const local = value.split("@")[0];
            const clean = local.replace(/[^a-zA-Z0-9]/g, "");
            return (clean.slice(0, 2) || fallback || "U").toUpperCase();
        }

        return value.slice(0, 2).toUpperCase();
    }

    function escapeHtml(input) {
        return String(input == null ? "" : input)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function formatDateTime(isoString) {
        if (!isoString) return "Never";
        const date = new Date(isoString);
        if (Number.isNaN(date.getTime())) return "Never";
        return new Intl.DateTimeFormat(undefined, {
            month: "short",
            day: "numeric",
            year: "numeric",
            hour: "numeric",
            minute: "2-digit",
        }).format(date);
    }

    function normalizeSubdomainInput(rawValue) {
        return String(rawValue || "")
            .trim()
            .toLowerCase()
            .replace(/\s+/g, "-");
    }

    function buildPortalUrlPreview(slug) {
        const safeSlug = String(slug || "").trim().toLowerCase();
        const displaySlug = safeSlug || "your-company";
        return `https://${displaySlug}.${ENTERPRISE_ROOT_DOMAIN}/enterprise`;
    }

    function updateSubdomainPreview() {
        if (!subdomainPreview) return;
        const slug = normalizeSubdomainInput(subdomainInput ? subdomainInput.value : "");
        subdomainPreview.textContent = buildPortalUrlPreview(slug);
    }

    function validateSubdomainOrError(slug) {
        const normalized = normalizeSubdomainInput(slug);
        if (!normalized) {
            return "Organization URL is required.";
        }
        if (normalized.length < SUBDOMAIN_MIN_LENGTH || normalized.length > SUBDOMAIN_MAX_LENGTH) {
            return `Organization URL must be ${SUBDOMAIN_MIN_LENGTH}-${SUBDOMAIN_MAX_LENGTH} characters.`;
        }
        if (RESERVED_SUBDOMAINS.has(normalized)) {
            return "This organization URL is reserved. Please choose a different one.";
        }
        if (!SUBDOMAIN_PATTERN.test(normalized)) {
            return (
                "Organization URL can only contain lowercase letters, numbers, and hyphens, " +
                "and cannot start or end with a hyphen."
            );
        }
        return "";
    }

    function setButtonLoading(btn, loading, loadingText, idleText) {
        if (!btn) return;
        if (!btn.dataset.defaultText) {
            btn.dataset.defaultText = idleText || btn.textContent || "";
        }
        btn.disabled = !!loading;
        if (loading) {
            btn.textContent = loadingText;
            return;
        }
        btn.textContent = idleText || btn.dataset.defaultText;
    }

    function showInlineFlash(el, message, type) {
        if (!el) return;
        el.textContent = message || "";
        el.className = `ent-flash ${type || "info"}`;
        el.style.display = "";
    }

    function hideInlineFlash(el) {
        if (!el) return;
        el.style.display = "none";
    }

    function showAuthFlash(message, type = "info") {
        showInlineFlash(authFlash, message, type);
    }

    function hideAuthFlash() {
        hideInlineFlash(authFlash);
    }

    function showOnboardingFlash(message, type = "info") {
        showInlineFlash(onboardingFlash, message, type);
    }

    function hideOnboardingFlash() {
        hideInlineFlash(onboardingFlash);
    }

    function showTeamFlash(message, type = "info") {
        showInlineFlash(teamFlash, message, type);
    }

    function hideTeamFlash() {
        hideInlineFlash(teamFlash);
    }

    function openMobileSidebar() {
        if (sidebar) sidebar.classList.add("open");
        if (sidebarOverlay) sidebarOverlay.classList.add("open");
    }

    function closeMobileSidebar() {
        if (sidebar) sidebar.classList.remove("open");
        if (sidebarOverlay) sidebarOverlay.classList.remove("open");
    }

    function switchToSection(sectionKey) {
        if (!SECTION_MAP[sectionKey]) return;
        state.currentSection = sectionKey;

        $$(".ent-section").forEach((section) => section.classList.remove("active"));
        const target = document.getElementById(SECTION_MAP[sectionKey]);
        if (target) target.classList.add("active");

        $$(".ent-nav-item[data-section]").forEach((button) => {
            button.classList.toggle("active", button.dataset.section === sectionKey);
        });

        if (pageTitle) {
            pageTitle.textContent = TITLE_MAP[sectionKey] || "Overview";
        }

        if (sectionKey === "team") {
            loadTeamMembers();
        }

        closeMobileSidebar();
    }

    function showAuthScreen() {
        hideOnboardingScreen();
        if (dashboard) dashboard.style.display = "none";
        if (authScreen) authScreen.style.display = "";
    }

    function showDashboardShell() {
        hideOnboardingScreen();
        if (authScreen) authScreen.style.display = "none";
        if (dashboard) dashboard.style.display = "";
    }

    function showOnboardingScreen() {
        if (!onboardingScreen) return;
        if (authScreen) authScreen.style.display = "none";
        if (dashboard) dashboard.style.display = "none";
        onboardingScreen.style.display = "flex";
        if (companyNameInput && !companyNameInput.value && state.organization && state.organization.company_name) {
            companyNameInput.value = state.organization.company_name;
        }
        if (subdomainInput && !subdomainInput.value && state.organization && state.organization.subdomain_slug) {
            subdomainInput.value = state.organization.subdomain_slug;
        }
        updateSubdomainPreview();
        if (companyNameInput && !companyNameInput.value) {
            companyNameInput.focus();
        } else if (subdomainInput && !subdomainInput.value) {
            subdomainInput.focus();
        }
    }

    function hideOnboardingScreen() {
        if (!onboardingScreen) return;
        onboardingScreen.style.display = "none";
    }

    function applyOrganizationUI() {
        const rawCompanyName = (state.organization && state.organization.company_name)
            ? String(state.organization.company_name).trim()
            : "";
        const companyName = rawCompanyName || "Enterprise Organization";
        const subdomainSlug = (state.organization && state.organization.subdomain_slug) || "";
        const orgInitials = getInitials(companyName, "EO");
        if (orgNameEl) orgNameEl.textContent = companyName;
        if (orgAvatarEl) orgAvatarEl.textContent = orgInitials;
        if (orgPortalEl) {
            orgPortalEl.textContent = subdomainSlug
                ? `${subdomainSlug}.${ENTERPRISE_ROOT_DOMAIN}`
                : "Enterprise Plan";
        }
        if (companyNameInput && rawCompanyName && !companyNameInput.value) {
            companyNameInput.value = rawCompanyName;
        }
        if (subdomainInput && subdomainSlug && !subdomainInput.value) {
            subdomainInput.value = subdomainSlug;
        }
        updateSubdomainPreview();
    }

    function applyUserUI() {
        const user = state.user;
        if (!user) return;
        if (userNameEl) userNameEl.textContent = user.full_name || user.email || "Enterprise User";
        if (userAvatarEl) {
            userAvatarEl.textContent = getInitials(user.full_name || user.email, "EU");
        }
        const role = state.membership ? normalizeRole(state.membership.role) : "viewer";
        if (userRoleEl) {
            userRoleEl.textContent = roleToLabel(role);
        }
    }

    function applyTeamAccessState() {
        const canManageUsers = !!(state.permissions && state.permissions.can_manage_users);

        if (teamAccessNotice) {
            teamAccessNotice.textContent = canManageUsers
                ? "You can invite team members and manage access levels for this organization."
                : "View-only mode: only organization admins can add, remove, or change member roles.";
        }

        if (teamEmailInput) teamEmailInput.disabled = !canManageUsers;
        if (teamNameInput) teamNameInput.disabled = !canManageUsers;
        if (teamRoleInput) teamRoleInput.disabled = !canManageUsers;
        if (teamAddBtn) {
            teamAddBtn.disabled = !canManageUsers;
            teamAddBtn.textContent = canManageUsers ? "Add User" : "Admin Access Required";
        }
    }

    function buildTeamRoleOptions(currentRole) {
        const normalized = normalizeRole(currentRole);
        return [
            { value: "viewer", label: "Viewer" },
            { value: "editor", label: "Editor" },
            { value: "admin", label: "Admin" },
        ]
            .map((item) => {
                const selected = item.value === normalized ? " selected" : "";
                return `<option value="${item.value}"${selected}>${item.label}</option>`;
            })
            .join("");
    }

    function renderTeamRows() {
        if (!teamTableBody) return;

        if (!Array.isArray(state.teamMembers) || state.teamMembers.length === 0) {
            teamTableBody.innerHTML =
                '<tr><td colspan="5" style="text-align:center;color:var(--ent-ink-muted);">No team members found.</td></tr>';
            return;
        }

        const canManageUsers = !!(state.permissions && state.permissions.can_manage_users);
        const currentUserId = state.user ? Number(state.user.id) : null;

        teamTableBody.innerHTML = state.teamMembers
            .map((member) => {
                const memberUserId = Number(member.user_id);
                const role = normalizeRole(member.role);
                const isCurrentUser = currentUserId !== null && memberUserId === currentUserId;
                const displayName = member.full_name || member.email || "User";
                const initials = getInitials(displayName, "U");

                const userCell = `
                    <div class="ent-student-cell">
                        <div class="ent-student-avatar" style="background:linear-gradient(135deg,#2563eb,#7c3aed)">${escapeHtml(initials)}</div>
                        <div>
                            <div class="ent-student-name">${escapeHtml(displayName)}${isCurrentUser ? " (You)" : ""}</div>
                            <div class="ent-student-email">${escapeHtml(member.email || "")}</div>
                        </div>
                    </div>
                `;

                let roleCell = `<span class="ent-chip ent-chip-gray">${escapeHtml(roleToLabel(role))}</span>`;
                if (canManageUsers) {
                    const disabledAttr = isCurrentUser ? " disabled" : "";
                    roleCell = `
                        <select class="ent-role-select" data-role-user-id="${memberUserId}" data-prev-role="${escapeHtml(role)}"${disabledAttr}>
                            ${buildTeamRoleOptions(role)}
                        </select>
                    `;
                }

                let actionsCell = '<span style="color:var(--ent-ink-muted);">-</span>';
                if (canManageUsers && !isCurrentUser) {
                    actionsCell = `
                        <span class="ent-inline-actions">
                            <button
                                class="ent-btn ent-btn-ghost ent-btn-sm"
                                type="button"
                                data-remove-user-id="${memberUserId}"
                            >
                                Remove
                            </button>
                        </span>
                    `;
                }

                return `
                    <tr>
                        <td>${userCell}</td>
                        <td style="color:var(--ent-ink-secondary); font-size:0.82rem;">${escapeHtml(member.email || "")}</td>
                        <td>${roleCell}</td>
                        <td style="color:var(--ent-ink-secondary); font-size:0.82rem;">${escapeHtml(formatDateTime(member.last_login_at))}</td>
                        <td>${actionsCell}</td>
                    </tr>
                `;
            })
            .join("");

        bindTeamRowEvents();
    }

    function bindTeamRowEvents() {
        if (!teamTableBody) return;

        $$("select[data-role-user-id]", teamTableBody).forEach((select) => {
            select.addEventListener("change", async () => {
                const memberUserId = Number(select.getAttribute("data-role-user-id"));
                const newRole = normalizeRole(select.value);
                const previousRole = normalizeRole(select.getAttribute("data-prev-role") || "");
                if (!memberUserId || newRole === previousRole) return;

                select.disabled = true;
                try {
                    const data = await apiRequest(`/api/enterprise/team/users/${memberUserId}/role`, {
                        method: "PATCH",
                        body: { role: newRole },
                    });
                    showTeamFlash(data.message || "Role updated.", "success");
                    if (Array.isArray(data.members)) {
                        state.teamMembers = data.members;
                        renderTeamRows();
                    } else {
                        await loadTeamMembers(true);
                    }
                } catch (error) {
                    select.value = previousRole;
                    showTeamFlash(error.detail || "Failed to update role.", "error");
                } finally {
                    if (document.body.contains(select)) {
                        select.disabled = false;
                    }
                }
            });
        });

        $$("button[data-remove-user-id]", teamTableBody).forEach((button) => {
            button.addEventListener("click", async () => {
                const memberUserId = Number(button.getAttribute("data-remove-user-id"));
                if (!memberUserId) return;

                const confirmRemove = window.confirm("Remove this user from your organization?");
                if (!confirmRemove) return;

                const originalText = button.textContent || "Remove";
                button.disabled = true;
                button.textContent = "Removing...";
                try {
                    const data = await apiRequest(`/api/enterprise/team/users/${memberUserId}`, {
                        method: "DELETE",
                    });
                    showTeamFlash(data.message || "User removed.", "success");
                    if (Array.isArray(data.members)) {
                        state.teamMembers = data.members;
                        renderTeamRows();
                    } else {
                        await loadTeamMembers(true);
                    }
                } catch (error) {
                    showTeamFlash(error.detail || "Failed to remove user.", "error");
                } finally {
                    if (document.body.contains(button)) {
                        button.disabled = false;
                        button.textContent = originalText;
                    }
                }
            });
        });
    }

    function setTeamLoadingRow() {
        if (!teamTableBody) return;
        teamTableBody.innerHTML =
            '<tr><td colspan="5" style="text-align:center;color:var(--ent-ink-muted);">Loading team members...</td></tr>';
    }

    async function loadTeamMembers(forceReload) {
        if (state.teamLoading && !forceReload) return;
        if (!state.permissions || !state.permissions.can_view_data) return;

        state.teamLoading = true;
        setTeamLoadingRow();
        try {
            const data = await apiRequest("/api/enterprise/team");
            state.permissions = data.permissions || state.permissions;
            state.teamMembers = Array.isArray(data.members) ? data.members : [];
            applyTeamAccessState();
            renderTeamRows();
        } catch (error) {
            showTeamFlash(error.detail || "Unable to load team members.", "error");
            if (teamTableBody) {
                teamTableBody.innerHTML =
                    '<tr><td colspan="5" style="text-align:center;color:var(--ent-ink-muted);">Failed to load team members.</td></tr>';
            }
        } finally {
            state.teamLoading = false;
        }
    }

    async function apiRequest(url, options) {
        const method = (options && options.method) || "GET";
        const body = options && options.body;
        const headers = Object.assign({}, (options && options.headers) || {});

        let payload;
        if (body !== undefined) {
            headers["Content-Type"] = "application/json";
            payload = JSON.stringify(body);
        }

        let response;
        try {
            response = await fetch(url, {
                method,
                headers,
                credentials: "same-origin",
                body: payload,
            });
        } catch (_) {
            throw { detail: "Network error. Please try again." };
        }

        const raw = await response.text();
        let data = {};
        if (raw) {
            try {
                data = JSON.parse(raw);
            } catch (_) {
                data = {};
            }
        }

        if (!response.ok) {
            const detail = data && typeof data.detail === "string" ? data.detail : "Request failed.";
            throw { detail, status: response.status, data };
        }
        return data;
    }

    function applyEnterpriseContext(payload) {
        state.user = payload.user || null;
        state.organization = payload.organization || null;
        state.membership = payload.membership || null;
        state.permissions = payload.permissions || {
            can_view_data: false,
            can_edit_data: false,
            can_manage_users: false,
        };

        applyUserUI();
        applyOrganizationUI();
        applyTeamAccessState();
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

    async function waitForTurnstileApi(timeoutMs) {
        if (window.turnstile && typeof window.turnstile.render === "function") return true;
        const started = Date.now();
        while (Date.now() - started < timeoutMs) {
            await new Promise((resolve) => setTimeout(resolve, 100));
            if (window.turnstile && typeof window.turnstile.render === "function") {
                return true;
            }
        }
        return false;
    }

    function getTurnstileToken() {
        if (!state.turnstile.siteKey || state.turnstile.widgetId === null) return "";
        if (!window.turnstile || typeof window.turnstile.getResponse !== "function") return "";
        try {
            return window.turnstile.getResponse(state.turnstile.widgetId) || "";
        } catch (_) {
            return "";
        }
    }

    function resetTurnstileWidget() {
        if (!state.turnstile.siteKey || state.turnstile.widgetId === null) return;
        if (!window.turnstile || typeof window.turnstile.reset !== "function") return;
        try {
            window.turnstile.reset(state.turnstile.widgetId);
        } catch (_) {}
    }

    async function initializeTurnstile() {
        state.turnstile.siteKey = await fetchTurnstileSiteKey();
        if (!state.turnstile.siteKey) {
            if (turnstileWrap) turnstileWrap.hidden = true;
            return;
        }

        if (turnstileWrap) turnstileWrap.hidden = false;
        const ready = await waitForTurnstileApi(5000);
        if (!ready) {
            if (turnstileHint) {
                turnstileHint.textContent = "Security widget failed to load. Refresh and try again.";
            }
            return;
        }

        try {
            state.turnstile.widgetId = window.turnstile.render("#entTurnstileWidget", {
                sitekey: state.turnstile.siteKey,
            });
        } catch (_) {
            if (turnstileHint) {
                turnstileHint.textContent = "Security widget failed to load. Refresh and try again.";
            }
        }
    }

    async function bootstrapSession() {
        try {
            const data = await apiRequest("/api/enterprise/me");
            applyEnterpriseContext(data);
            if (data.onboarding_required) {
                showOnboardingScreen();
            } else {
                showDashboardShell();
                switchToSection("overview");
            }
            return;
        } catch (_) {
            showAuthScreen();
        }
    }

    if (loginForm) {
        loginForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            hideAuthFlash();

            const emailInput = $("#entEmail");
            const passwordInput = $("#entPassword");
            const email = emailInput ? emailInput.value.trim() : "";
            const password = passwordInput ? passwordInput.value : "";

            if (!email || !password) {
                showAuthFlash("Please enter both email and password.", "error");
                return;
            }

            const payload = { email, password };
            if (state.turnstile.siteKey) {
                const turnstileToken = getTurnstileToken();
                if (!turnstileToken) {
                    showAuthFlash("Please complete security verification.", "error");
                    return;
                }
                payload.cf_turnstile_token = turnstileToken;
            }

            setButtonLoading(loginBtn, true, "Signing in...", "Sign In");

            try {
                const data = await apiRequest("/api/enterprise/login", {
                    method: "POST",
                    body: payload,
                });
                applyEnterpriseContext(data);
                if (data.onboarding_required) {
                    showOnboardingScreen();
                } else {
                    showDashboardShell();
                    switchToSection("overview");
                }
            } catch (error) {
                showAuthFlash(error.detail || "Login failed.", "error");
                resetTurnstileWidget();
            } finally {
                setButtonLoading(loginBtn, false, "Signing in...", "Sign In");
            }
        });
    }

    if (onboardingForm) {
        onboardingForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            hideOnboardingFlash();

            const companyName = companyNameInput ? companyNameInput.value.trim() : "";
            const subdomainSlug = normalizeSubdomainInput(subdomainInput ? subdomainInput.value : "");
            if (companyName.length < 2) {
                showOnboardingFlash("Company name must be at least 2 characters.", "error");
                return;
            }
            const subdomainError = validateSubdomainOrError(subdomainSlug);
            if (subdomainError) {
                showOnboardingFlash(subdomainError, "error");
                if (subdomainInput) subdomainInput.focus();
                return;
            }
            if (subdomainInput) {
                subdomainInput.value = subdomainSlug;
            }
            updateSubdomainPreview();

            setButtonLoading(onboardingBtn, true, "Saving...", "Continue to dashboard");
            try {
                const data = await apiRequest("/api/enterprise/onboarding", {
                    method: "POST",
                    body: {
                        company_name: companyName,
                        subdomain_slug: subdomainSlug,
                    },
                });
                applyEnterpriseContext(data);
                showDashboardShell();
                switchToSection("overview");
            } catch (error) {
                showOnboardingFlash(error.detail || "Unable to complete onboarding.", "error");
            } finally {
                setButtonLoading(onboardingBtn, false, "Saving...", "Continue to dashboard");
            }
        });
    }

    if (teamAddForm) {
        teamAddForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            hideTeamFlash();

            const canManageUsers = !!(state.permissions && state.permissions.can_manage_users);
            if (!canManageUsers) {
                showTeamFlash("Only organization admins can add team users.", "error");
                return;
            }

            const email = teamEmailInput ? teamEmailInput.value.trim() : "";
            const fullName = teamNameInput ? teamNameInput.value.trim() : "";
            const role = normalizeRole(teamRoleInput ? teamRoleInput.value : "viewer");
            if (!email) {
                showTeamFlash("User email is required.", "error");
                return;
            }

            setButtonLoading(teamAddBtn, true, "Adding...", "Add User");
            try {
                const data = await apiRequest("/api/enterprise/team/users", {
                    method: "POST",
                    body: {
                        email,
                        role,
                        full_name: fullName || null,
                    },
                });
                showTeamFlash(data.message || "User added successfully.", "success");
                if (teamEmailInput) teamEmailInput.value = "";
                if (teamNameInput) teamNameInput.value = "";
                if (teamRoleInput) teamRoleInput.value = "viewer";

                if (Array.isArray(data.members)) {
                    state.teamMembers = data.members;
                    renderTeamRows();
                } else {
                    await loadTeamMembers(true);
                }
            } catch (error) {
                showTeamFlash(error.detail || "Unable to add user.", "error");
            } finally {
                setButtonLoading(teamAddBtn, false, "Adding...", "Add User");
                applyTeamAccessState();
            }
        });
    }

    $$(".ent-nav-item[data-section]").forEach((button) => {
        button.addEventListener("click", () => switchToSection(button.dataset.section));
    });

    if (mobileToggle) {
        mobileToggle.addEventListener("click", openMobileSidebar);
    }
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener("click", closeMobileSidebar);
    }

    if (subdomainInput) {
        subdomainInput.addEventListener("input", () => {
            const normalized = normalizeSubdomainInput(subdomainInput.value);
            if (subdomainInput.value !== normalized) {
                subdomainInput.value = normalized;
            }
            updateSubdomainPreview();
        });
        subdomainInput.addEventListener("blur", () => {
            updateSubdomainPreview();
        });
    }

    initializeTurnstile();
    updateSubdomainPreview();
    bootstrapSession();
})();
