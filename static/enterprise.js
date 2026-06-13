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
    const settingsFlash = $("#entSettingsFlash");
    const settingsForm = $("#entSettingsBrandingForm");
    const settingsCompanyNameInput = $("#entSettingsCompanyName");
    const settingsLogoUrlInput = $("#entSettingsLogoUrl");
    const settingsLogoFileInput = $("#entSettingsLogoFileInput");
    const settingsChooseLogoBtn = $("#entSettingsChooseLogoBtn");
    const settingsUploadLogoBtn = $("#entSettingsUploadLogoBtn");
    const settingsLogoFileName = $("#entSettingsLogoFileName");
    const settingsAccessNotice = $("#entSettingsAccessNotice");
    const settingsRandomLogoBtn = $("#entSettingsRandomLogoBtn");
    const settingsSaveBtn = $("#entSettingsSaveBtn");
    const settingsLogoPreviewImg = $("#entSettingsLogoPreviewImg");
    const settingsPreviewCompanyName = $("#entSettingsPreviewCompanyName");
    const settingsPreviewPortalUrl = $("#entSettingsPreviewPortalUrl");
    const studentsFlash = $("#entStudentsFlash");
    const studentsTableBody = $("#entStudentsTableBody");
    const studentsEmpty = $("#entStudentsEmpty");
    const studentsAccessNotice = $("#entStudentsAccessNotice");
    const studentsNavBadge = $("#entStudentsNavBadge");
    const addStudentBtnOverview = $("#entAddStudentBtnOverview");
    const addStudentBtnStudents = $("#entAddStudentBtnStudents");
    const studentModal = $("#entStudentModal");
    const studentModalCloseBtn = $("#entStudentModalClose");
    const studentModalCancelBtn = $("#entStudentCancelBtn");
    const studentModalFlash = $("#entStudentModalFlash");
    const studentForm = $("#entStudentForm");
    const studentNameInput = $("#entStudentName");
    const studentCountrySelect = $("#entStudentCountry");
    const studentVisaTypeSelect = $("#entStudentVisaType");
    const studentIntakeSelect = $("#entStudentIntake");
    const studentSaveBtn = $("#entStudentSaveBtn");
    const studentWorkspaceBackBtn = $("#entStudentWorkspaceBackBtn");
    const studentWorkspaceStudentName = $("#entStudentWorkspaceStudentName");
    const studentWorkspaceSubline = $("#entStudentWorkspaceSubline");
    const studentWorkspaceAvatar = $("#entStudentWorkspaceAvatar");
    const studentWorkspaceDestination = $("#entStudentWorkspaceDestination");
    const studentWorkspaceVisaType = $("#entStudentWorkspaceVisaType");
    const studentWorkspaceIntake = $("#entStudentWorkspaceIntake");
    const studentWorkspaceProgressLabel = $("#entStudentWorkspaceProgressLabel");
    const studentWorkspaceProgressPercent = $("#entStudentWorkspaceProgressPercent");
    const studentWorkspaceProgressBar = $("#entStudentWorkspaceProgressBar");
    const studentWorkspaceStatus = $("#entStudentWorkspaceStatus");
    const studentWorkspaceEta = $("#entStudentWorkspaceEta");
    const studentWorkspaceStageCounter = $("#entStudentWorkspaceStageCounter");
    const studentWorkspaceCurrentStageTitle = $("#entStudentWorkspaceCurrentStageTitle");
    const studentWorkspaceCurrentStageDesc = $("#entStudentWorkspaceCurrentStageDesc");
    const studentWorkspaceChecklist = $("#entStudentWorkspaceChecklist");
    const studentWorkspaceStageRail = $("#entStudentWorkspaceStageRail");
    const studentWorkspaceProfileAvatar = $("#entStudentWorkspaceProfileAvatar");
    const studentWorkspaceProfileName = $("#entStudentWorkspaceProfileName");
    const studentWorkspaceProfileMeta = $("#entStudentWorkspaceProfileMeta");
    const studentWorkspaceOptionList = $("#entStudentWorkspaceOptionList");
    const studentWorkspaceOptionHint = $("#entStudentWorkspaceOptionHint");

    const userNameEl = $("#entUserName");
    const userAvatarImgEl = $("#entUserAvatarImg");
    const userRoleEl = $(".ent-user-role");
    const orgNameEl = $("#entOrgName");
    const orgCardAvatarImgEl = $("#entOrgCardAvatarImg");
    const orgPortalEl = $("#entOrgPortalUrl");
    const sidebarOrgNameEl = $("#entSidebarOrgName");
    const sidebarOrgAvatarImgEl = $("#entSidebarOrgAvatarImg");
    const sidebarOrgPortalEl = $("#entSidebarOrgPortal");
    const sidebarLogoutBtn = $("#entSidebarLogoutBtn");

    const turnstileWrap = $("#entTurnstileWrap");
    const turnstileHint = $("#entTurnstileHint");

    const SECTION_MAP = {
        overview: "entSectionOverview",
        students: "entSectionStudents",
        student_workspace: "entSectionStudentWorkspace",
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
        student_workspace: "Student Journey",
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

    const WORKSPACE_PROFILE_OPTIONS = [
        {
            key: "journey",
            label: "Journey Overview",
            description: "Track stage progression, current focus, and estimated completion timeline.",
            hint: "Use this as your default command center for end-to-end journey progress.",
        },
        {
            key: "documents",
            label: "Documents",
            description: "Review document readiness and required evidence for the current phase.",
            hint: "Prioritize missing records, naming consistency, and support-file validation.",
        },
        {
            key: "interview",
            label: "Interview Prep",
            description: "Focus on response clarity, mock practice, and interview confidence.",
            hint: "Use this view before interviews to tighten messaging and reduce rejection risk.",
        },
        {
            key: "finance",
            label: "Finance & Fees",
            description: "Track sponsor proof, tuition support, and visa fee readiness.",
            hint: "Keep this area updated to avoid last-minute financial documentation blocks.",
        },
        {
            key: "notes",
            label: "Notes & Risk Flags",
            description: "Capture advisor notes, blockers, and escalation follow-ups.",
            hint: "Use this area to coordinate internal follow-ups and risk mitigation actions.",
        },
    ];

    const ENTERPRISE_ROOT_DOMAIN = "rilono.com";
    const CONTACT_SALES_URL = "https://rilono.com/contact";
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
        students: [],
        studentsLoading: false,
        activeStudentWorkspaceId: null,
        activeWorkspaceOption: "journey",
        studentOptions: {
            countries: [],
            visaTypesByCountry: {},
            intakesByCountryVisa: {},
        },
        turnstile: {
            siteKey: "",
            widgetId: null,
        },
    };

    function hideAllScreens() {
        closeStudentModal();
        if (authScreen) authScreen.style.display = "none";
        if (dashboard) dashboard.style.display = "none";
        if (onboardingScreen) onboardingScreen.style.display = "none";
    }

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

    /** Deterministic “random” photo per org/user (stable across sessions). */
    function hashStringFnv1a(input) {
        const str = String(input || "");
        let h = 2166136261;
        for (let i = 0; i < str.length; i += 1) {
            h ^= str.charCodeAt(i);
            h = Math.imul(h, 16777619);
        }
        return (h >>> 0).toString(16);
    }

    function picsumPortraitUrl(seedKey, size) {
        const seed = hashStringFnv1a(seedKey).replace(/[^a-f0-9]/g, "") || "0";
        const n = Math.max(48, Math.min(512, Number(size) || 128));
        return `https://picsum.photos/seed/rilono-${seed}/${n}/${n}`;
    }

    function resolveOrganizationLogoUrl(org, size) {
        const logoFromApi = org && org.logo_url ? String(org.logo_url).trim() : "";
        if (logoFromApi) return logoFromApi;

        const orgId = org && org.id != null ? String(org.id) : "pending";
        const companyName = org && org.company_name ? String(org.company_name) : "";
        const subdomain = org && org.subdomain_slug ? String(org.subdomain_slug) : "";
        return picsumPortraitUrl(`org-${orgId}|${companyName}|${subdomain}`, size || 128);
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

    function isInviteOnlyAccessError(error) {
        const detail = String(error && error.detail ? error.detail : "").toLowerCase();
        const status = Number(error && error.status ? error.status : 0);
        return status === 403 && detail.includes("invite-only");
    }

    function showAuthInviteOnlyFlash() {
        if (!authFlash) return;
        authFlash.className = "ent-flash info";
        authFlash.innerHTML =
            `Enterprise access is invite-only. ` +
            `<a href="${CONTACT_SALES_URL}" class="ent-flash-link">Contact Sales</a> ` +
            `to request access.`;
        authFlash.style.display = "";
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

    function showStudentsFlash(message, type = "info") {
        showInlineFlash(studentsFlash, message, type);
    }

    function hideStudentsFlash() {
        hideInlineFlash(studentsFlash);
    }

    function showSettingsFlash(message, type = "info") {
        showInlineFlash(settingsFlash, message, type);
    }

    function hideSettingsFlash() {
        hideInlineFlash(settingsFlash);
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
            const navSection = String(button.dataset.section || "");
            const shouldBeActive = sectionKey === "student_workspace"
                ? navSection === "students"
                : navSection === sectionKey;
            button.classList.toggle("active", shouldBeActive);
        });

        if (pageTitle) {
            pageTitle.textContent = TITLE_MAP[sectionKey] || "Overview";
        }

        if (sectionKey === "team") {
            loadTeamMembers();
        }
        if (sectionKey === "students") {
            loadStudents();
        }
        if (sectionKey === "student_workspace") {
            const workspaceId = Number(state.activeStudentWorkspaceId);
            if (Number.isFinite(workspaceId) && workspaceId > 0) {
                renderStudentWorkspaceById(workspaceId);
            }
        }
        if (sectionKey === "settings") {
            hideSettingsFlash();
            syncSettingsFormFromState();
            applySettingsAccessState();
        }

        closeMobileSidebar();
    }

    function showAuthScreen() {
        hideAllScreens();
        if (authScreen) authScreen.style.display = "";
    }

    function showDashboardShell() {
        hideAllScreens();
        if (dashboard) dashboard.style.display = "";
    }

    function showOnboardingScreen() {
        if (!onboardingScreen) return;
        hideAllScreens();
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
        const org = state.organization;
        if (!org) {
            if (orgCardAvatarImgEl) {
                orgCardAvatarImgEl.src = "/static/logo.png";
                orgCardAvatarImgEl.alt = "";
            }
            if (sidebarOrgAvatarImgEl) {
                sidebarOrgAvatarImgEl.src = "/static/logo.png";
                sidebarOrgAvatarImgEl.alt = "";
            }
            if (orgNameEl) orgNameEl.textContent = "Your organization";
            if (sidebarOrgNameEl) sidebarOrgNameEl.textContent = "Your organization";
            if (orgPortalEl) orgPortalEl.textContent = "Enterprise Plan";
            if (sidebarOrgPortalEl) sidebarOrgPortalEl.textContent = `your-company.${ENTERPRISE_ROOT_DOMAIN}`;
            if (settingsPreviewCompanyName) settingsPreviewCompanyName.textContent = "Your organization";
            if (settingsPreviewPortalUrl) settingsPreviewPortalUrl.textContent = `your-company.${ENTERPRISE_ROOT_DOMAIN}`;
            updateSubdomainPreview();
            return;
        }

        const rawCompanyName = org.company_name ? String(org.company_name).trim() : "";
        const companyName = rawCompanyName || "Enterprise Organization";
        const subdomainSlug = org.subdomain_slug || "";
        const photoUrl = resolveOrganizationLogoUrl(org, 128);

        if (orgCardAvatarImgEl) {
            orgCardAvatarImgEl.src = photoUrl;
            orgCardAvatarImgEl.alt = `${companyName} logo`;
        }
        if (sidebarOrgAvatarImgEl) {
            sidebarOrgAvatarImgEl.src = photoUrl;
            sidebarOrgAvatarImgEl.alt = `${companyName} logo`;
        }

        if (orgNameEl) orgNameEl.textContent = companyName;
        if (sidebarOrgNameEl) sidebarOrgNameEl.textContent = companyName;
        if (orgPortalEl) {
            orgPortalEl.textContent = subdomainSlug
                ? `${subdomainSlug}.${ENTERPRISE_ROOT_DOMAIN}`
                : "Enterprise Plan";
        }
        if (sidebarOrgPortalEl) {
            sidebarOrgPortalEl.textContent = subdomainSlug
                ? `${subdomainSlug}.${ENTERPRISE_ROOT_DOMAIN}`
                : `your-company.${ENTERPRISE_ROOT_DOMAIN}`;
        }
        if (settingsPreviewCompanyName) settingsPreviewCompanyName.textContent = companyName;
        if (settingsPreviewPortalUrl) {
            settingsPreviewPortalUrl.textContent = subdomainSlug
                ? `${subdomainSlug}.${ENTERPRISE_ROOT_DOMAIN}`
                : `your-company.${ENTERPRISE_ROOT_DOMAIN}`;
        }
        if (settingsLogoPreviewImg) {
            settingsLogoPreviewImg.src = photoUrl;
            settingsLogoPreviewImg.alt = `${companyName} logo preview`;
        }
        if (companyNameInput && rawCompanyName && !companyNameInput.value) {
            companyNameInput.value = rawCompanyName;
        }
        if (subdomainInput && subdomainSlug && !subdomainInput.value) {
            subdomainInput.value = subdomainSlug;
        }
        updateSubdomainPreview();
    }

    function applySettingsAccessState() {
        const canManageUsers = !!(state.permissions && state.permissions.can_manage_users);
        if (settingsAccessNotice) {
            settingsAccessNotice.textContent = canManageUsers
                ? "You can update your organization name and branding from here."
                : "View-only mode: only organization admins can change branding settings.";
        }
        if (settingsCompanyNameInput) settingsCompanyNameInput.disabled = !canManageUsers;
        if (settingsLogoUrlInput) settingsLogoUrlInput.disabled = !canManageUsers;
        if (settingsLogoFileInput) settingsLogoFileInput.disabled = !canManageUsers;
        if (settingsChooseLogoBtn) settingsChooseLogoBtn.disabled = !canManageUsers;
        if (settingsUploadLogoBtn) settingsUploadLogoBtn.disabled = !canManageUsers;
        if (settingsRandomLogoBtn) settingsRandomLogoBtn.disabled = !canManageUsers;
        if (settingsSaveBtn) settingsSaveBtn.disabled = !canManageUsers;
    }

    function syncSettingsFormFromState() {
        const org = state.organization || {};
        if (settingsCompanyNameInput) {
            settingsCompanyNameInput.value = org.company_name ? String(org.company_name) : "";
        }
        if (settingsLogoUrlInput) {
            settingsLogoUrlInput.value = org.logo_url ? String(org.logo_url) : "";
        }
        const previewUrl = resolveOrganizationLogoUrl(org, 128);
        if (settingsLogoPreviewImg) {
            settingsLogoPreviewImg.src = previewUrl;
            settingsLogoPreviewImg.alt = `${org.company_name || "Organization"} logo preview`;
        }
        if (settingsPreviewCompanyName) {
            settingsPreviewCompanyName.textContent = (org.company_name || "Your organization").trim();
        }
        if (settingsPreviewPortalUrl) {
            const slug = (org.subdomain_slug || "").trim();
            settingsPreviewPortalUrl.textContent = slug
                ? `${slug}.${ENTERPRISE_ROOT_DOMAIN}`
                : `your-company.${ENTERPRISE_ROOT_DOMAIN}`;
        }
        if (settingsLogoFileInput) {
            settingsLogoFileInput.value = "";
        }
        if (settingsLogoFileName) {
            settingsLogoFileName.textContent = "No file selected.";
        }
    }

    function updateSettingsPreviewFromInputs() {
        const inputName = settingsCompanyNameInput ? settingsCompanyNameInput.value.trim() : "";
        const inputLogo = settingsLogoUrlInput ? settingsLogoUrlInput.value.trim() : "";
        const fallbackOrg = state.organization || {};
        const previewName = inputName || fallbackOrg.company_name || "Your organization";
        const previewSlug = (fallbackOrg.subdomain_slug || "").trim();
        const previewLogo = inputLogo || resolveOrganizationLogoUrl(fallbackOrg, 128);

        if (settingsPreviewCompanyName) settingsPreviewCompanyName.textContent = previewName;
        if (settingsPreviewPortalUrl) {
            settingsPreviewPortalUrl.textContent = previewSlug
                ? `${previewSlug}.${ENTERPRISE_ROOT_DOMAIN}`
                : `your-company.${ENTERPRISE_ROOT_DOMAIN}`;
        }
        if (settingsLogoPreviewImg) {
            settingsLogoPreviewImg.src = previewLogo;
            settingsLogoPreviewImg.alt = `${previewName} logo preview`;
        }
    }

    function buildStudentVisaChipClass(visaType) {
        const value = String(visaType || "").toUpperCase();
        if (value.startsWith("F-")) return "ent-chip-blue";
        if (value.startsWith("J-")) return "ent-chip-purple";
        if (value.startsWith("M-")) return "ent-chip-amber";
        if (value.includes("PERMIT")) return "ent-chip-green";
        return "ent-chip-gray";
    }

    function buildVisaJourneyStagesForStudent(student) {
        const countryCode = String(student && student.study_country_code ? student.study_country_code : "")
            .trim()
            .toUpperCase();
        const countryName = String(student && student.study_country_name ? student.study_country_name : "")
            .trim() || "destination country";
        const visaType = String(student && student.visa_type ? student.visa_type : "")
            .trim() || "student visa";
        const visaKey = visaType.toLowerCase();

        if (countryCode === "US") {
            if (visaKey.includes("j-1")) {
                return [
                    { title: "Program Sponsor Confirmation", description: "Secure sponsorship and receive your DS-2019 form for the exchange category." },
                    { title: "SEVIS and Funding Readiness", description: "Pay I-901 SEVIS fee and prepare clear funding and program-support documents." },
                    { title: "Application Filing", description: "Complete DS-160, pay visa fee, and schedule biometric/interview slots." },
                    { title: "Interview Preparation", description: "Prepare program purpose, return intent, and supporting academic or sponsor records." },
                    { title: "Interview and Visa Decision", description: "Attend consulate interview and complete passport submission if approved." },
                    { title: "Arrival and Program Check-in", description: "Travel with DS-2019 packet and finish SEVIS activation on arrival." },
                ];
            }
            if (visaKey.includes("m-1")) {
                return [
                    { title: "School Acceptance and I-20", description: "Finalize vocational program admission and obtain your M-1 I-20." },
                    { title: "SEVIS and Finance Evidence", description: "Pay SEVIS fee and prepare tuition, sponsor, and living-expense documentation." },
                    { title: "DS-160 Submission", description: "Complete DS-160, pay visa fee, and set biometric/interview appointments." },
                    { title: "Document Bundle Review", description: "Compile I-20, passport, finances, and vocational intent justification." },
                    { title: "Consular Interview", description: "Attend interview and complete passport processing for visa stamping." },
                    { title: "Travel and Entry Compliance", description: "Enter the US with M-1 documents and follow school reporting requirements." },
                ];
            }
            return [
                { title: "Admission and I-20 Issuance", description: "Confirm admission in the selected program and secure your F-1 I-20." },
                { title: "SEVIS and Finance Preparation", description: "Pay I-901 SEVIS fee and finalize strong financial sponsorship evidence." },
                { title: "DS-160 and Fee Payment", description: "Submit DS-160, pay visa fee, and create your interview profile." },
                { title: "Interview Scheduling and Documents", description: "Book slots and organize passport, I-20, academics, and funding proofs." },
                { title: "Visa Interview and Decision", description: "Attend interview and complete passport submission if approved." },
                { title: "Pre-departure and Port-of-Entry", description: "Plan travel and carry compliant documents for smooth US entry." },
            ];
        }

        if (countryCode === "UK") {
            if (visaKey.includes("child")) {
                return [
                    { title: "School Offer and CAS", description: "Obtain a valid CAS from the sponsoring UK institution." },
                    { title: "Guardian and Financial Proofs", description: "Prepare parental consent, guardian details, and funds evidence." },
                    { title: "Application and IHS", description: "Submit UK Student route application and complete Immigration Health Surcharge." },
                    { title: "Biometrics and Document Upload", description: "Attend biometrics and submit required supporting records." },
                    { title: "Decision and Passport Return", description: "Track decision and receive passport with vignette if approved." },
                    { title: "Arrival and BRP/eVisa Steps", description: "Travel to UK and complete post-arrival identity and residence formalities." },
                ];
            }
            return [
                { title: "Offer Acceptance and CAS", description: "Secure university offer and receive CAS for UK Student Visa processing." },
                { title: "Financial Evidence and TB Test", description: "Prepare funds proof and TB certificate where applicable." },
                { title: "Application and IHS Payment", description: "Submit visa application and pay required IHS charges." },
                { title: "Biometric Appointment", description: "Complete biometrics and upload passport, CAS, and supporting files." },
                { title: "Decision and Passport Collection", description: "Track processing and collect passport after decision." },
                { title: "Travel and Post-arrival Setup", description: "Enter the UK and complete BRP or eVisa onboarding steps." },
            ];
        }

        if (countryCode === "CA") {
            if (visaKey.includes("sds")) {
                return [
                    { title: "LOA and SDS Eligibility", description: "Confirm letter of acceptance and SDS eligibility requirements." },
                    { title: "GIC, Tuition, and English Proof", description: "Arrange GIC, tuition payment proof, and accepted language scores." },
                    { title: "Application Package Submission", description: "Submit SDS study permit application with complete supporting evidence." },
                    { title: "Biometrics and Medical Steps", description: "Finish biometrics and medical checks if requested." },
                    { title: "Decision and Passport Request", description: "Track IRCC updates and complete passport submission if approved." },
                    { title: "Travel and Border Documents", description: "Carry POE letter, LOA, and financials for Canadian entry." },
                ];
            }
            return [
                { title: "Offer and Program Confirmation", description: "Secure admission and validate study permit eligibility." },
                { title: "Funding and Core Documents", description: "Prepare tuition plans, sponsor support, and statement of purpose." },
                { title: "Study Permit Application", description: "Submit complete application with correct forms and evidence." },
                { title: "Biometrics and Medical", description: "Complete required biometrics and medical procedures." },
                { title: "Decision and Passport Stamping", description: "Track approval and submit passport if requested." },
                { title: "Arrival and POE Compliance", description: "Travel with permit documents and complete entry checks at POE." },
            ];
        }

        if (countryCode === "AU") {
            return [
                { title: "Admission and COE", description: "Confirm admission and obtain your Confirmation of Enrolment (COE)." },
                { title: "OSHC and Financial Setup", description: "Arrange OSHC coverage and prepare finance documents." },
                { title: "GS and Document Preparation", description: "Draft Genuine Student statement and compile academics and identity records." },
                { title: "Subclass Application Filing", description: `Submit ${visaType} application with complete supporting package.` },
                { title: "Biometrics/Medical and Review", description: "Complete requested checks and respond to case officer updates." },
                { title: "Grant and Travel Readiness", description: "Receive visa grant and finalize travel plus enrollment checkpoints." },
            ];
        }

        if (countryCode === "DE") {
            return [
                { title: "Admission and Program Verification", description: "Confirm admission and validate course eligibility for German study route." },
                { title: "Blocked Account and Insurance", description: "Arrange blocked account funds and acceptable health insurance proof." },
                { title: "Appointment and Document File", description: "Book embassy appointment and prepare translated legal documents if needed." },
                { title: "Visa Interview Submission", description: "Attend interview and submit complete Type D or applicant-visa file." },
                { title: "Decision and Passport Collection", description: "Track processing timeline and collect visa decision." },
                { title: "Arrival and Residence Registration", description: "Complete city registration and residence permit formalities after arrival." },
            ];
        }

        if (countryCode === "FR") {
            return [
                { title: "Admission and Campus France", description: "Secure admission and complete Campus France process where required." },
                { title: "Funding and Stay Documents", description: "Prepare finance proofs, accommodation details, and travel insurance." },
                { title: "VLS-TS Application", description: "Submit long-stay student visa application with supporting records." },
                { title: "Biometrics and Interview", description: "Attend appointment and complete biometrics or interview instructions." },
                { title: "Decision and Passport Return", description: "Track processing and receive decision outcome." },
                { title: "Arrival and VLS-TS Validation", description: "Validate your long-stay status and complete local registration tasks." },
            ];
        }

        if (countryCode === "IE") {
            return [
                { title: "Offer and Fee Confirmation", description: "Confirm institute offer and initial fee payment evidence." },
                { title: "Financial and Insurance Readiness", description: "Prepare sponsor funds and required private insurance proofs." },
                { title: "Visa Application Filing", description: "Submit D Study visa application and upload all mandatory records." },
                { title: "Supporting Documents Review", description: "Resolve checklist gaps and clarify purpose-of-study narrative." },
                { title: "Decision and Passport Handling", description: "Track outcome and complete passport submission or return." },
                { title: "Arrival and IRP Registration", description: "Complete post-arrival registration and immigration compliance in Ireland." },
            ];
        }

        if (countryCode === "NZ") {
            return [
                { title: "Admission and Fee Planning", description: "Receive offer and confirm tuition/payment timeline." },
                { title: "Funds and Health Documents", description: "Prepare finances, medicals, and police clearances if required." },
                { title: "Student Visa Application", description: "Submit Fee Paying Student Visa application with full evidence." },
                { title: "Identity Checks and Updates", description: "Complete biometrics or additional identity checks when requested." },
                { title: "Decision and Travel Prep", description: "Track visa decision and finalize travel documents." },
                { title: "Arrival and Enrollment Confirmation", description: "Arrive in New Zealand and complete institution onboarding." },
            ];
        }

        return [
            { title: "Eligibility and Program Confirmation", description: `Confirm admission path and eligibility for ${visaType} in ${countryName}.` },
            { title: "Documentation and Financial Readiness", description: "Prepare identity, academics, and sponsor/financial support proofs." },
            { title: "Visa Application Submission", description: "Submit forms, pay fees, and upload complete evidence." },
            { title: "Biometrics or Interview Stage", description: "Complete biometrics/interview steps if required by the consulate." },
            { title: "Decision and Passport Processing", description: "Track status updates and complete passport issuance steps." },
            { title: "Pre-departure Compliance", description: "Finalize arrival checklist and ensure entry-ready documentation." },
        ];
    }

    function parseStudentIntakeDate(intakeLabel) {
        const raw = String(intakeLabel || "").trim().toLowerCase();
        if (!raw) return null;

        const monthMap = {
            january: 0, february: 1, march: 2, april: 3, may: 4, june: 5,
            july: 6, august: 7, september: 8, october: 9, november: 10, december: 11,
            spring: 0, summer: 4, fall: 8, winter: 10,
        };

        let matchedMonth = null;
        Object.keys(monthMap).forEach((key) => {
            if (matchedMonth !== null) return;
            if (raw.includes(key)) matchedMonth = monthMap[key];
        });
        if (matchedMonth === null) return null;

        const yearMatch = raw.match(/\b(20\d{2})\b/);
        const year = yearMatch ? Number(yearMatch[1]) : null;
        if (!Number.isFinite(year)) return null;
        return new Date(Date.UTC(year, matchedMonth, 1, 0, 0, 0));
    }

    function estimateStudentJourneyProgress(student, stageCount) {
        const intakeDate = parseStudentIntakeDate(student && student.intake);
        const now = new Date();
        let progressPercent = 12;
        let etaText = "Intake timeline unavailable";

        if (intakeDate && !Number.isNaN(intakeDate.getTime())) {
            const monthsDiff = ((intakeDate.getUTCFullYear() - now.getUTCFullYear()) * 12)
                + (intakeDate.getUTCMonth() - now.getUTCMonth());
            if (monthsDiff >= 8) progressPercent = 12;
            else if (monthsDiff >= 5) progressPercent = 24;
            else if (monthsDiff >= 3) progressPercent = 38;
            else if (monthsDiff >= 1) progressPercent = 52;
            else if (monthsDiff === 0) progressPercent = 68;
            else progressPercent = 84;

            if (monthsDiff > 1) etaText = `${monthsDiff} months to intake`;
            else if (monthsDiff === 1) etaText = "1 month to intake";
            else if (monthsDiff === 0) etaText = "Intake month in progress";
            else if (monthsDiff === -1) etaText = "Intake started last month";
            else etaText = "Intake already started";
        }

        const safeStageCount = Math.max(1, Number(stageCount) || 1);
        const currentStageIndex = Math.max(
            0,
            Math.min(safeStageCount - 1, Math.floor(progressPercent / (100 / safeStageCount)))
        );

        let statusLabel = "On track";
        if (progressPercent >= 80) statusLabel = "Late-stage execution";
        else if (progressPercent >= 50) statusLabel = "Interview readiness window";
        else if (progressPercent >= 30) statusLabel = "Document build-up phase";
        else statusLabel = "Early preparation phase";

        return {
            progressPercent,
            currentStageIndex,
            statusLabel,
            etaText,
        };
    }

    function buildStudentStageChecklist(stage, student) {
        const countryName = String(student && student.study_country_name ? student.study_country_name : "destination country");
        const visaType = String(student && student.visa_type ? student.visa_type : "visa");
        const stageTitle = String(stage && stage.title ? stage.title : "").toLowerCase();

        if (stageTitle.includes("interview")) {
            return [
                `Prepare concise answers matching ${visaType} intent and study goals.`,
                "Run at least 2 mock interview rounds and refine weak areas.",
                `Organize interview-day documents for ${countryName} consular review.`,
            ];
        }
        if (stageTitle.includes("application") || stageTitle.includes("submission")) {
            return [
                "Complete all required form fields without inconsistencies.",
                "Cross-check fee payment receipts and appointment references.",
                "Upload supporting evidence in the required format and order.",
            ];
        }
        if (stageTitle.includes("arrival") || stageTitle.includes("travel")) {
            return [
                "Prepare travel packet: passport, approval letter, and admission records.",
                "Keep sponsor and accommodation details ready for border checks.",
                "Plan first-week compliance tasks after reaching destination.",
            ];
        }
        return [
            `Collect mandatory documents for ${visaType}.`,
            "Validate financial and identity records for consistency.",
            "Review this stage with your organization admin before proceeding.",
        ];
    }

    function getWorkspaceOptionByKey(optionKey) {
        const normalizedKey = String(optionKey || "").trim().toLowerCase();
        return WORKSPACE_PROFILE_OPTIONS.find((option) => option.key === normalizedKey) || WORKSPACE_PROFILE_OPTIONS[0];
    }

    function buildWorkspaceOptionContext(optionKey, currentStage, progress) {
        const stageTitle = currentStage && currentStage.title ? currentStage.title : "Current stage";
        const stageDescription = currentStage && currentStage.description
            ? currentStage.description
            : "No stage details available.";

        if (optionKey === "documents") {
            return {
                subline: "Document-focused tracking for this student's journey",
                progressLabel: "Document readiness coverage",
                statusLabel: "Document preparation focus",
                stageTitle: `${stageTitle} · Document Focus`,
                stageDescription: `Focus on collecting and validating documents for this phase. ${stageDescription}`,
            };
        }
        if (optionKey === "interview") {
            return {
                subline: "Interview-readiness view for stronger outcome confidence",
                progressLabel: "Interview preparation readiness",
                statusLabel: "Interview preparation focus",
                stageTitle: `${stageTitle} · Interview Focus`,
                stageDescription: `Refine speaking clarity, response confidence, and consistency for this stage. ${stageDescription}`,
            };
        }
        if (optionKey === "finance") {
            return {
                subline: "Finance and fee readiness focus for this student's case",
                progressLabel: "Finance and fee readiness",
                statusLabel: "Finance verification focus",
                stageTitle: `${stageTitle} · Finance Focus`,
                stageDescription: `Verify funds, sponsor proofs, and fee evidence before moving ahead. ${stageDescription}`,
            };
        }
        if (optionKey === "notes") {
            return {
                subline: "Advisor notes and risk-flag view for student-specific follow-up",
                progressLabel: "Advisor follow-up coverage",
                statusLabel: "Advisory follow-up focus",
                stageTitle: `${stageTitle} · Risk and Notes`,
                stageDescription: `Capture blockers, case notes, and escalation points linked to this stage. ${stageDescription}`,
            };
        }
        return {
            subline: "Dedicated student journey progress and next actions",
            progressLabel: "Estimated journey completion",
            statusLabel: progress && progress.statusLabel ? progress.statusLabel : "On track",
            stageTitle,
            stageDescription,
        };
    }

    function buildWorkspaceOptionChecklist(optionKey, baseChecklist, student, currentStage) {
        const stageTitle = String(currentStage && currentStage.title ? currentStage.title : "this stage");
        const countryName = String(student && student.study_country_name ? student.study_country_name : "destination country");
        const visaType = String(student && student.visa_type ? student.visa_type : "visa");
        const extraChecklistByOption = {
            documents: [
                `Create a dedicated folder for ${stageTitle} documents with clear file naming.`,
                "Collect both original and scan-ready copies for mandatory records.",
                `Review format and validity rules for ${countryName} ${visaType} submissions.`,
            ],
            interview: [
                `Practice 3 short answers explaining ${visaType} purpose and study intent.`,
                "Run mock interview rounds with confidence, eye contact, and timing checks.",
                "Prepare a one-page speaking outline for difficult follow-up questions.",
            ],
            finance: [
                "Confirm sponsor balance history and stable transaction pattern.",
                "Reconcile tuition, living costs, and fee receipts in one finance summary.",
                "Keep bank letters and sponsor affidavits updated with current dates.",
            ],
            notes: [
                "Record current blockers with owner and expected resolution date.",
                "Flag risk items that could delay submission or interview readiness.",
                "Log advisor decisions so the next reviewer has full context.",
            ],
        };

        const merged = []
            .concat(Array.isArray(baseChecklist) ? baseChecklist : [])
            .concat(extraChecklistByOption[optionKey] || []);

        const uniqueChecklist = [];
        const seen = new Set();
        merged.forEach((item) => {
            const clean = String(item || "").trim();
            if (!clean) return;
            const key = clean.toLowerCase();
            if (seen.has(key)) return;
            seen.add(key);
            uniqueChecklist.push(clean);
        });
        return uniqueChecklist.slice(0, 6);
    }

    function bindStudentWorkspaceOptionEvents() {
        if (!studentWorkspaceOptionList) return;
        $$("button[data-workspace-option]", studentWorkspaceOptionList).forEach((button) => {
            button.addEventListener("click", () => {
                const optionKey = String(button.getAttribute("data-workspace-option") || "").trim().toLowerCase();
                if (!optionKey) return;
                if (state.activeWorkspaceOption === optionKey) return;
                state.activeWorkspaceOption = optionKey;
                renderStudentWorkspaceById(state.activeStudentWorkspaceId);
            });
        });
    }

    function renderStudentWorkspaceOptionList(hasStudent) {
        const activeOption = getWorkspaceOptionByKey(state.activeWorkspaceOption);
        if (studentWorkspaceOptionList) {
            studentWorkspaceOptionList.innerHTML = WORKSPACE_PROFILE_OPTIONS.map((option) => {
                const activeClass = option.key === activeOption.key ? " is-active" : "";
                const disabledAttr = hasStudent ? "" : " disabled";
                const pressedAttr = option.key === activeOption.key ? "true" : "false";
                return `
                    <button
                        class="ent-student-profile-option${activeClass}"
                        type="button"
                        data-workspace-option="${escapeHtml(option.key)}"
                        aria-pressed="${pressedAttr}"${disabledAttr}
                    >
                        <span class="ent-student-profile-option-label">${escapeHtml(option.label)}</span>
                        <span class="ent-student-profile-option-desc">${escapeHtml(option.description)}</span>
                    </button>
                `;
            }).join("");
        }
        if (studentWorkspaceOptionHint) {
            studentWorkspaceOptionHint.textContent = hasStudent
                ? activeOption.hint
                : "Select a student from the directory to unlock student-specific profile options.";
        }
        bindStudentWorkspaceOptionEvents();
    }

    function renderStudentWorkspace(student) {
        if (!student || typeof student !== "object") {
            state.activeWorkspaceOption = "journey";
            if (studentWorkspaceStudentName) studentWorkspaceStudentName.textContent = "Student";
            if (studentWorkspaceSubline) studentWorkspaceSubline.textContent = "Personalized visa journey workspace";
            if (studentWorkspaceDestination) studentWorkspaceDestination.textContent = "-";
            if (studentWorkspaceVisaType) studentWorkspaceVisaType.textContent = "-";
            if (studentWorkspaceIntake) studentWorkspaceIntake.textContent = "-";
            if (studentWorkspaceProgressLabel) studentWorkspaceProgressLabel.textContent = "Journey progress";
            if (studentWorkspaceProgressPercent) studentWorkspaceProgressPercent.textContent = "0%";
            if (studentWorkspaceProgressBar) studentWorkspaceProgressBar.style.width = "0%";
            if (studentWorkspaceStatus) studentWorkspaceStatus.textContent = "-";
            if (studentWorkspaceEta) studentWorkspaceEta.textContent = "-";
            if (studentWorkspaceStageCounter) studentWorkspaceStageCounter.textContent = "-";
            if (studentWorkspaceCurrentStageTitle) studentWorkspaceCurrentStageTitle.textContent = "Stage title";
            if (studentWorkspaceCurrentStageDesc) studentWorkspaceCurrentStageDesc.textContent = "Stage guidance will appear here.";
            if (studentWorkspaceChecklist) studentWorkspaceChecklist.innerHTML = "";
            if (studentWorkspaceStageRail) studentWorkspaceStageRail.innerHTML = "";
            if (studentWorkspaceAvatar) studentWorkspaceAvatar.textContent = "S";
            if (studentWorkspaceProfileAvatar) studentWorkspaceProfileAvatar.textContent = "S";
            if (studentWorkspaceProfileName) studentWorkspaceProfileName.textContent = "Student";
            if (studentWorkspaceProfileMeta) studentWorkspaceProfileMeta.textContent = "Select a student to view details";
            renderStudentWorkspaceOptionList(false);
            return;
        }

        const studentName = String(student.student_name || "Student").trim() || "Student";
        const countryName = String(student.study_country_name || "").trim() || "Unknown";
        const countryCode = String(student.study_country_code || "").trim().toUpperCase();
        const visaType = String(student.visa_type || "").trim() || "Not set";
        const intake = String(student.intake || "").trim() || "Not set";
        const stages = buildVisaJourneyStagesForStudent(student);
        const progress = estimateStudentJourneyProgress(student, stages.length);
        const currentStage = stages[progress.currentStageIndex] || stages[0] || null;
        const option = getWorkspaceOptionByKey(state.activeWorkspaceOption);
        const context = buildWorkspaceOptionContext(option.key, currentStage, progress);
        const checklist = buildWorkspaceOptionChecklist(
            option.key,
            buildStudentStageChecklist(currentStage, student),
            student,
            currentStage
        );

        if (studentWorkspaceStudentName) studentWorkspaceStudentName.textContent = studentName;
        if (studentWorkspaceSubline) studentWorkspaceSubline.textContent = context.subline;
        if (studentWorkspaceDestination) {
            studentWorkspaceDestination.textContent = countryCode ? `${countryName} (${countryCode})` : countryName;
        }
        if (studentWorkspaceVisaType) studentWorkspaceVisaType.textContent = visaType;
        if (studentWorkspaceIntake) studentWorkspaceIntake.textContent = intake;
        if (studentWorkspaceProgressLabel) studentWorkspaceProgressLabel.textContent = context.progressLabel;
        if (studentWorkspaceProgressPercent) studentWorkspaceProgressPercent.textContent = `${progress.progressPercent}%`;
        if (studentWorkspaceProgressBar) {
            studentWorkspaceProgressBar.style.width = `${progress.progressPercent}%`;
        }
        if (studentWorkspaceStatus) studentWorkspaceStatus.textContent = context.statusLabel;
        if (studentWorkspaceEta) studentWorkspaceEta.textContent = progress.etaText;
        if (studentWorkspaceStageCounter) {
            studentWorkspaceStageCounter.textContent = `Stage ${progress.currentStageIndex + 1} of ${stages.length}`;
        }
        if (studentWorkspaceCurrentStageTitle) {
            studentWorkspaceCurrentStageTitle.textContent = context.stageTitle;
        }
        if (studentWorkspaceCurrentStageDesc) {
            studentWorkspaceCurrentStageDesc.textContent = context.stageDescription;
        }
        if (studentWorkspaceAvatar) {
            studentWorkspaceAvatar.textContent = getInitials(studentName, "S");
        }
        if (studentWorkspaceProfileAvatar) {
            studentWorkspaceProfileAvatar.textContent = getInitials(studentName, "S");
        }
        if (studentWorkspaceProfileName) {
            studentWorkspaceProfileName.textContent = studentName;
        }
        if (studentWorkspaceProfileMeta) {
            studentWorkspaceProfileMeta.textContent = `${countryCode ? `${countryName} (${countryCode})` : countryName} • ${visaType}`;
        }

        if (studentWorkspaceChecklist) {
            studentWorkspaceChecklist.innerHTML = checklist
                .map((item) => `<li>${escapeHtml(item)}</li>`)
                .join("");
        }

        if (studentWorkspaceStageRail) {
            studentWorkspaceStageRail.innerHTML = stages
                .map((stage, index) => {
                    const statusClass = index < progress.currentStageIndex
                        ? " is-done"
                        : (index === progress.currentStageIndex ? " is-current" : "");
                    const statusText = index < progress.currentStageIndex
                        ? "Completed"
                        : (index === progress.currentStageIndex ? "Current Stage" : "Upcoming");
                    return `
                        <div class="ent-stage-rail-item${statusClass}">
                            <span class="ent-stage-rail-index">${index + 1}</span>
                            <div>
                                <div class="ent-stage-rail-title">${escapeHtml(stage.title || `Stage ${index + 1}`)}</div>
                                <div class="ent-stage-rail-status">${escapeHtml(statusText)}</div>
                            </div>
                        </div>
                    `;
                })
                .join("");
        }

        renderStudentWorkspaceOptionList(true);
    }

    function renderStudentWorkspaceById(studentId) {
        const targetId = Number(studentId);
        if (!Number.isFinite(targetId) || targetId <= 0) {
            renderStudentWorkspace(null);
            return;
        }
        const student = Array.isArray(state.students)
            ? state.students.find((item) => Number(item && item.id) === targetId)
            : null;
        if (!student) {
            renderStudentWorkspace(null);
            return;
        }
        renderStudentWorkspace(student);
    }

    function openStudentWorkspace(studentId) {
        const targetId = Number(studentId);
        if (!Number.isFinite(targetId) || targetId <= 0) return;
        state.activeStudentWorkspaceId = targetId;
        state.activeWorkspaceOption = "journey";
        renderStudentWorkspaceById(targetId);
        switchToSection("student_workspace");
    }

    function bindStudentActionEvents() {
        if (!studentsTableBody) return;
        $$("button[data-manage-student-id]", studentsTableBody).forEach((button) => {
            button.addEventListener("click", () => {
                openStudentWorkspace(button.getAttribute("data-manage-student-id"));
            });
        });
    }

    function applyStudentsAccessState() {
        const canEditData = !!(state.permissions && state.permissions.can_edit_data);
        if (studentsAccessNotice) {
            studentsAccessNotice.textContent = canEditData
                ? "Add students with destination country and visa type to start enterprise tracking. Click Manage for each student's dedicated journey workspace."
                : "View-only mode: only admins or editors can add student records.";
        }
        if (addStudentBtnOverview) addStudentBtnOverview.disabled = !canEditData;
        if (addStudentBtnStudents) addStudentBtnStudents.disabled = !canEditData;
    }

    function updateStudentCounts(countValue) {
        const numericCount = Number(countValue);
        const safeCount = Number.isFinite(numericCount) && numericCount >= 0
            ? Math.floor(numericCount)
            : (Array.isArray(state.students) ? state.students.length : 0);
        const formattedCount = new Intl.NumberFormat().format(safeCount);
        if (studentsNavBadge) studentsNavBadge.textContent = formattedCount;
        const metricStudents = $("#entMetricStudents");
        if (metricStudents) metricStudents.textContent = formattedCount;
    }

    function getCountryOptionLabel(country) {
        const flag = String(country && country.flag_emoji ? country.flag_emoji : "").trim();
        const name = String(country && country.name ? country.name : country && country.code ? country.code : "").trim();
        const iconicPlace = String(country && country.iconic_place ? country.iconic_place : "").trim();

        if (!name) return "";
        const prefix = flag ? `${flag} ` : "";
        return iconicPlace ? `${prefix}${name} • ${iconicPlace}` : `${prefix}${name}`;
    }

    function setStudentCountryOptions(countries) {
        state.studentOptions.countries = Array.isArray(countries) ? countries : [];
        const visaMap = {};
        const intakeMap = {};
        state.studentOptions.countries.forEach((country) => {
            const code = String(country && country.code ? country.code : "").trim().toUpperCase();
            if (!code) return;
            const visaTypes = Array.isArray(country.visa_types) ? country.visa_types : [];
            visaMap[code] = visaTypes;
            const intakesByVisa = country && typeof country.intakes_by_visa === "object" && country.intakes_by_visa
                ? country.intakes_by_visa
                : {};
            visaTypes.forEach((visaType) => {
                const visaLabel = String(visaType || "").trim();
                if (!visaLabel) return;
                const compositeKey = `${code}||${visaLabel.toLowerCase()}`;
                intakeMap[compositeKey] = Array.isArray(intakesByVisa[visaLabel]) ? intakesByVisa[visaLabel] : [];
            });
        });
        state.studentOptions.visaTypesByCountry = visaMap;
        state.studentOptions.intakesByCountryVisa = intakeMap;

        if (!studentCountrySelect) return;
        const selectedValue = String(studentCountrySelect.value || "").trim().toUpperCase();
        const options = state.studentOptions.countries
            .map((country) => {
                const code = String(country.code || "").trim().toUpperCase();
                const optionLabel = getCountryOptionLabel(country);
                if (!code || !optionLabel) return "";
                const selectedAttr = code === selectedValue ? " selected" : "";
                return `<option value="${escapeHtml(code)}"${selectedAttr}>${escapeHtml(optionLabel)}</option>`;
            })
            .filter(Boolean)
            .join("");

        studentCountrySelect.innerHTML = `<option value="">Select destination country</option>${options}`;
    }

    function setIntakeOptionsForCountryVisa(countryCode, visaType) {
        if (!studentIntakeSelect) return;
        const normalizedCode = String(countryCode || "").trim().toUpperCase();
        const normalizedVisa = String(visaType || "").trim().toLowerCase();
        if (!normalizedCode || !normalizedVisa) {
            studentIntakeSelect.innerHTML = '<option value="">Select intake</option>';
            studentIntakeSelect.disabled = true;
            return;
        }

        const key = `${normalizedCode}||${normalizedVisa}`;
        const intakes = state.studentOptions.intakesByCountryVisa[key] || [];
        const options = intakes
            .map((intake) => `<option value="${escapeHtml(intake)}">${escapeHtml(intake)}</option>`)
            .join("");
        studentIntakeSelect.innerHTML = `<option value="">Select intake</option>${options}`;
        studentIntakeSelect.disabled = intakes.length === 0;
    }

    function setVisaTypeOptionsForCountry(countryCode) {
        if (!studentVisaTypeSelect) return;
        const normalizedCode = String(countryCode || "").trim().toUpperCase();
        const visaTypes = state.studentOptions.visaTypesByCountry[normalizedCode] || [];
        const options = visaTypes
            .map((visaType) => `<option value="${escapeHtml(visaType)}">${escapeHtml(visaType)}</option>`)
            .join("");
        studentVisaTypeSelect.innerHTML = `<option value="">Select visa type</option>${options}`;
        studentVisaTypeSelect.disabled = visaTypes.length === 0;
        setIntakeOptionsForCountryVisa(normalizedCode, "");
    }

    function setStudentsLoadingRow() {
        if (!studentsTableBody) return;
        studentsTableBody.innerHTML =
            '<tr><td colspan="6" style="text-align:center;color:var(--ent-ink-muted);">Loading students...</td></tr>';
        if (studentsEmpty) studentsEmpty.style.display = "none";
    }

    function renderStudentRows() {
        if (!studentsTableBody) return;
        const rows = Array.isArray(state.students) ? state.students : [];
        if (rows.length === 0) {
            studentsTableBody.innerHTML = "";
            if (studentsEmpty) studentsEmpty.style.display = "";
            return;
        }

        if (studentsEmpty) studentsEmpty.style.display = "none";
        studentsTableBody.innerHTML = rows
            .map((student) => {
                const studentId = Number(student.id);
                const hasStudentId = Number.isFinite(studentId) && studentId > 0;
                const name = String(student.student_name || "Student").trim() || "Student";
                const initials = getInitials(name, "S");
                const countryName = String(student.study_country_name || "").trim() || "Unknown";
                const countryCode = String(student.study_country_code || "").trim().toUpperCase();
                const visaType = String(student.visa_type || "").trim() || "Not set";
                const intake = String(student.intake || "").trim() || "Not set";
                const visaChipClass = buildStudentVisaChipClass(visaType);
                const createdAtText = formatDateTime(student.created_at);
                const manageButton = hasStudentId
                    ? `<button class="ent-btn ent-btn-ghost ent-btn-sm" type="button" data-manage-student-id="${studentId}">Manage</button>`
                    : '<span style="color:var(--ent-ink-muted);">-</span>';
                return `
                    <tr>
                        <td>
                            <div class="ent-student-cell">
                                <div class="ent-student-avatar" style="background:linear-gradient(135deg,#2563eb,#7c3aed)">${escapeHtml(initials)}</div>
                                <div>
                                    <div class="ent-student-name">${escapeHtml(name)}</div>
                                </div>
                            </div>
                        </td>
                        <td style="color:var(--ent-ink-secondary); font-size:0.82rem;">${escapeHtml(countryName)}${countryCode ? ` (${escapeHtml(countryCode)})` : ""}</td>
                        <td><span class="ent-chip ${visaChipClass}">${escapeHtml(visaType)}</span></td>
                        <td style="color:var(--ent-ink-secondary); font-size:0.82rem;">${escapeHtml(intake)}</td>
                        <td style="color:var(--ent-ink-secondary); font-size:0.82rem;">${escapeHtml(createdAtText)}</td>
                        <td><span class="ent-table-actions">${manageButton}</span></td>
                    </tr>
                `;
            })
            .join("");
        bindStudentActionEvents();
    }

    async function loadStudentOptions(forceReload) {
        const hasCachedOptions =
            Array.isArray(state.studentOptions.countries) && state.studentOptions.countries.length > 0;
        if (hasCachedOptions && !forceReload) {
            setStudentCountryOptions(state.studentOptions.countries);
            return state.studentOptions.countries;
        }

        const data = await apiRequest("/api/enterprise/students/options");
        if (data && data.permissions) {
            state.permissions = data.permissions;
        }
        const optionsPayload = data && data.options ? data.options : {};
        const countries = Array.isArray(optionsPayload.countries) ? optionsPayload.countries : [];
        setStudentCountryOptions(countries);
        applyStudentsAccessState();
        return countries;
    }

    async function loadStudents(forceReload) {
        if (state.studentsLoading && !forceReload) return;
        if (!state.permissions || !state.permissions.can_view_data) return;

        state.studentsLoading = true;
        setStudentsLoadingRow();
        try {
            const data = await apiRequest("/api/enterprise/students");
            if (data && data.permissions) {
                state.permissions = data.permissions;
            }
            state.students = Array.isArray(data.students) ? data.students : [];
            updateStudentCounts(typeof data.students_count === "number" ? data.students_count : state.students.length);
            renderStudentRows();
            applyStudentsAccessState();
            if (state.currentSection === "student_workspace") {
                renderStudentWorkspaceById(state.activeStudentWorkspaceId);
            }
        } catch (error) {
            showStudentsFlash(error.detail || "Unable to load students.", "error");
            if (studentsTableBody) {
                studentsTableBody.innerHTML =
                    '<tr><td colspan="6" style="text-align:center;color:var(--ent-ink-muted);">Failed to load students.</td></tr>';
            }
            if (studentsEmpty) studentsEmpty.style.display = "none";
            if (state.currentSection === "student_workspace") {
                renderStudentWorkspace(null);
            }
        } finally {
            state.studentsLoading = false;
        }
    }

    function showStudentModalFlash(message, type = "info") {
        showInlineFlash(studentModalFlash, message, type);
    }

    function hideStudentModalFlash() {
        hideInlineFlash(studentModalFlash);
    }

    function closeStudentModal() {
        if (!studentModal) return;
        studentModal.hidden = true;
        studentModal.style.display = "none";
        document.body.classList.remove("ent-no-scroll");
        hideStudentModalFlash();
        if (studentForm) studentForm.reset();
        if (studentVisaTypeSelect) {
            studentVisaTypeSelect.innerHTML = '<option value="">Select visa type</option>';
            studentVisaTypeSelect.disabled = true;
        }
        if (studentIntakeSelect) {
            studentIntakeSelect.innerHTML = '<option value="">Select intake</option>';
            studentIntakeSelect.disabled = true;
        }
    }

    async function openStudentModal() {
        const canEditData = !!(state.permissions && state.permissions.can_edit_data);
        if (!canEditData) {
            showStudentsFlash("Only admins or editors can add students.", "error");
            switchToSection("students");
            return;
        }
        if (!studentModal) return;

        hideStudentsFlash();
        hideStudentModalFlash();
        try {
            // Refresh options on each open so intake year labels stay aligned with current date.
            await loadStudentOptions(true);
        } catch (error) {
            showStudentsFlash(error.detail || "Unable to load country visa options.", "error");
            switchToSection("students");
            return;
        }

        studentModal.hidden = false;
        studentModal.style.display = "flex";
        document.body.classList.add("ent-no-scroll");

        const countries = state.studentOptions.countries || [];
        const firstCountryCode = countries.length ? String(countries[0].code || "").trim().toUpperCase() : "";
        if (studentCountrySelect) {
            studentCountrySelect.value = firstCountryCode || "";
            setVisaTypeOptionsForCountry(studentCountrySelect.value);
        }
        if (studentNameInput) studentNameInput.focus();
    }

    function applyUserUI() {
        const user = state.user;
        if (!user) return;
        const displayName = user.full_name || user.email || "Enterprise User";
        if (userNameEl) userNameEl.textContent = displayName;
        if (userAvatarImgEl) {
            const uid = user.id != null ? String(user.id) : displayName;
            userAvatarImgEl.src = picsumPortraitUrl(`user-${uid}|${user.email || ""}|${displayName}`, 128);
            userAvatarImgEl.alt = displayName;
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
            const isFormData = typeof FormData !== "undefined" && body instanceof FormData;
            if (isFormData) {
                payload = body;
            } else {
                headers["Content-Type"] = "application/json";
                payload = JSON.stringify(body);
            }
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

    function redirectToOrganizationPortalIfNeeded(payload) {
        const portalUrl = payload && payload.organization && payload.organization.portal_url
            ? String(payload.organization.portal_url).trim()
            : "";
        if (!portalUrl) return false;

        let target;
        try {
            target = new URL(portalUrl, window.location.origin);
        } catch (_) {
            return false;
        }

        const currentHost = String(window.location.host || "").toLowerCase();
        const targetHost = String(target.host || "").toLowerCase();
        if (!targetHost || targetHost === currentHost) return false;

        window.location.replace(target.toString());
        return true;
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
        applyStudentsAccessState();
        applySettingsAccessState();
        syncSettingsFormFromState();
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
            if (redirectToOrganizationPortalIfNeeded(data)) {
                return;
            }
            applyEnterpriseContext(data);
            if (data.onboarding_required) {
                showOnboardingScreen();
            } else {
                showDashboardShell();
                switchToSection("overview");
                loadStudents(true);
            }
            return;
        } catch (error) {
            showAuthScreen();
            if (isInviteOnlyAccessError(error)) {
                showAuthInviteOnlyFlash();
            }
        }
    }

    async function handlePortalLogout() {
        if (!sidebarLogoutBtn || sidebarLogoutBtn.disabled) return;
        setButtonLoading(sidebarLogoutBtn, true, "Logging out...", "Logout");
        try {
            await apiRequest("/api/auth/logout", { method: "POST" });
        } catch (error) {
            const message = error.detail || "Unable to logout right now. Please try again.";
            if (state.currentSection === "team") {
                showTeamFlash(message, "error");
            } else {
                window.alert(message);
            }
            setButtonLoading(sidebarLogoutBtn, false, "Logging out...", "Logout");
            return;
        }

        state.user = null;
        state.organization = null;
        state.membership = null;
        state.permissions = {
            can_view_data: false,
            can_edit_data: false,
            can_manage_users: false,
        };
        state.teamMembers = [];
        state.students = [];
        state.activeStudentWorkspaceId = null;
        state.activeWorkspaceOption = "journey";
        state.studentOptions = {
            countries: [],
            visaTypesByCountry: {},
            intakesByCountryVisa: {},
        };
        closeStudentModal();
        updateStudentCounts(0);
        renderStudentRows();
        renderStudentWorkspace(null);

        hideAuthFlash();
        hideTeamFlash();
        hideStudentsFlash();
        hideSettingsFlash();
        if (loginForm) loginForm.reset();
        resetTurnstileWidget();
        showAuthScreen();
        showAuthFlash("Logged out successfully.", "success");
        setButtonLoading(sidebarLogoutBtn, false, "Logging out...", "Logout");
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
                if (redirectToOrganizationPortalIfNeeded(data)) {
                    return;
                }
                applyEnterpriseContext(data);
                if (data.onboarding_required) {
                    showOnboardingScreen();
                } else {
                    showDashboardShell();
                    switchToSection("overview");
                    loadStudents(true);
                }
            } catch (error) {
                if (isInviteOnlyAccessError(error)) {
                    showAuthInviteOnlyFlash();
                } else {
                    showAuthFlash(error.detail || "Login failed.", "error");
                }
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
                if (redirectToOrganizationPortalIfNeeded(data)) {
                    return;
                }
                applyEnterpriseContext(data);
                showDashboardShell();
                switchToSection("overview");
                loadStudents(true);
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

    if (addStudentBtnOverview) {
        addStudentBtnOverview.addEventListener("click", () => {
            openStudentModal();
        });
    }

    if (addStudentBtnStudents) {
        addStudentBtnStudents.addEventListener("click", () => {
            openStudentModal();
        });
    }

    if (studentWorkspaceBackBtn) {
        studentWorkspaceBackBtn.addEventListener("click", () => {
            switchToSection("students");
        });
    }

    if (studentCountrySelect) {
        studentCountrySelect.addEventListener("change", () => {
            setVisaTypeOptionsForCountry(studentCountrySelect.value);
        });
    }

    if (studentVisaTypeSelect) {
        studentVisaTypeSelect.addEventListener("change", () => {
            const countryCode = studentCountrySelect ? studentCountrySelect.value : "";
            setIntakeOptionsForCountryVisa(countryCode, studentVisaTypeSelect.value);
        });
    }

    if (studentModalCloseBtn) {
        studentModalCloseBtn.addEventListener("click", () => {
            closeStudentModal();
        });
    }

    if (studentModalCancelBtn) {
        studentModalCancelBtn.addEventListener("click", () => {
            closeStudentModal();
        });
    }

    if (studentModal) {
        studentModal.addEventListener("click", (event) => {
            if (event.target === studentModal) {
                closeStudentModal();
            }
        });
    }
    document.addEventListener(
        "click",
        (event) => {
            if (!studentModal || studentModal.hidden) return;
            const closeTrigger = event.target && event.target.closest
                ? event.target.closest("#entStudentModalClose, #entStudentCancelBtn")
                : null;
            if (!closeTrigger) return;
            event.preventDefault();
            closeStudentModal();
        },
        true
    );

    if (studentForm) {
        studentForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            hideStudentModalFlash();

            const canEditData = !!(state.permissions && state.permissions.can_edit_data);
            if (!canEditData) {
                showStudentModalFlash("Only admins or editors can add students.", "error");
                return;
            }

            const studentName = studentNameInput ? studentNameInput.value.trim() : "";
            const studyCountryCode = studentCountrySelect ? String(studentCountrySelect.value || "").trim().toUpperCase() : "";
            const visaType = studentVisaTypeSelect ? String(studentVisaTypeSelect.value || "").trim() : "";
            const intake = studentIntakeSelect ? String(studentIntakeSelect.value || "").trim() : "";

            if (studentName.length < 2) {
                showStudentModalFlash("Student name must be at least 2 characters.", "error");
                if (studentNameInput) studentNameInput.focus();
                return;
            }
            if (!studyCountryCode) {
                showStudentModalFlash("Please select destination country.", "error");
                if (studentCountrySelect) studentCountrySelect.focus();
                return;
            }
            if (!visaType) {
                showStudentModalFlash("Please select visa type.", "error");
                if (studentVisaTypeSelect) studentVisaTypeSelect.focus();
                return;
            }
            if (!intake) {
                showStudentModalFlash("Please select intake.", "error");
                if (studentIntakeSelect) studentIntakeSelect.focus();
                return;
            }

            setButtonLoading(studentSaveBtn, true, "Adding...", "Add Student");
            try {
                const data = await apiRequest("/api/enterprise/students", {
                    method: "POST",
                    body: {
                        student_name: studentName,
                        study_country_code: studyCountryCode,
                        visa_type: visaType,
                        intake,
                    },
                });
                closeStudentModal();
                showStudentsFlash(data.message || "Student added successfully.", "success");
                await loadStudents(true);
            } catch (error) {
                showStudentModalFlash(error.detail || "Unable to add student.", "error");
            } finally {
                setButtonLoading(studentSaveBtn, false, "Adding...", "Add Student");
            }
        });
    }

    if (settingsLogoUrlInput) {
        settingsLogoUrlInput.addEventListener("input", () => {
            updateSettingsPreviewFromInputs();
        });
    }

    if (settingsChooseLogoBtn) {
        settingsChooseLogoBtn.addEventListener("click", () => {
            const canManageUsers = !!(state.permissions && state.permissions.can_manage_users);
            if (!canManageUsers) {
                showSettingsFlash("Only organization admins can change company profile picture.", "error");
                return;
            }
            if (!settingsLogoFileInput) return;
            settingsLogoFileInput.click();
        });
    }

    if (settingsLogoFileInput) {
        settingsLogoFileInput.addEventListener("change", () => {
            const selected = settingsLogoFileInput.files && settingsLogoFileInput.files[0]
                ? settingsLogoFileInput.files[0]
                : null;
            if (settingsLogoFileName) {
                settingsLogoFileName.textContent = selected ? selected.name : "No file selected.";
            }
            if (selected) {
                showSettingsFlash("Image selected. Click Upload Picture, then Save Branding.", "info");
            }
        });
    }

    if (settingsUploadLogoBtn) {
        settingsUploadLogoBtn.addEventListener("click", async () => {
            hideSettingsFlash();
            const canManageUsers = !!(state.permissions && state.permissions.can_manage_users);
            if (!canManageUsers) {
                showSettingsFlash("Only organization admins can change company profile picture.", "error");
                return;
            }
            const selected = settingsLogoFileInput && settingsLogoFileInput.files && settingsLogoFileInput.files[0]
                ? settingsLogoFileInput.files[0]
                : null;
            if (!selected) {
                showSettingsFlash("Choose an image file first.", "error");
                return;
            }

            setButtonLoading(settingsUploadLogoBtn, true, "Uploading...", "Upload Picture");
            try {
                const formData = new FormData();
                formData.append("file", selected);

                const data = await apiRequest("/api/upload/image", {
                    method: "POST",
                    body: formData,
                });

                const uploadedUrl = data && data.url ? String(data.url).trim() : "";
                if (!uploadedUrl) {
                    throw { detail: "Upload succeeded but no image URL was returned." };
                }

                if (settingsLogoUrlInput) settingsLogoUrlInput.value = uploadedUrl;
                updateSettingsPreviewFromInputs();
                showSettingsFlash("Company profile picture uploaded. Click Save Branding to apply.", "success");
            } catch (error) {
                showSettingsFlash(error.detail || "Unable to upload company profile picture.", "error");
            } finally {
                setButtonLoading(settingsUploadLogoBtn, false, "Uploading...", "Upload Picture");
            }
        });
    }

    if (settingsCompanyNameInput) {
        settingsCompanyNameInput.addEventListener("input", () => {
            updateSettingsPreviewFromInputs();
        });
    }

    if (settingsRandomLogoBtn) {
        settingsRandomLogoBtn.addEventListener("click", () => {
            hideSettingsFlash();
            const canManageUsers = !!(state.permissions && state.permissions.can_manage_users);
            if (!canManageUsers) {
                showSettingsFlash("Only organization admins can randomize organization branding.", "error");
                return;
            }
            if (!settingsLogoUrlInput) return;
            settingsLogoUrlInput.value = picsumPortraitUrl(
                `org-random|${Date.now()}|${Math.random()}|${(state.organization && state.organization.id) || "org"}`,
                256
            );
            updateSettingsPreviewFromInputs();
            showSettingsFlash("Random logo generated. Click Save Branding to apply it.", "info");
        });
    }

    if (settingsForm) {
        settingsForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            hideSettingsFlash();

            const canManageUsers = !!(state.permissions && state.permissions.can_manage_users);
            if (!canManageUsers) {
                showSettingsFlash("Only organization admins can update branding.", "error");
                return;
            }

            const companyName = settingsCompanyNameInput ? settingsCompanyNameInput.value.trim() : "";
            const logoUrl = settingsLogoUrlInput ? settingsLogoUrlInput.value.trim() : "";
            if (companyName.length < 2) {
                showSettingsFlash("Organization name must be at least 2 characters.", "error");
                return;
            }

            setButtonLoading(settingsSaveBtn, true, "Saving...", "Save Branding");
            try {
                const data = await apiRequest("/api/enterprise/organization/branding", {
                    method: "PATCH",
                    body: {
                        company_name: companyName,
                        logo_url: logoUrl,
                    },
                });

                if (data && data.organization) {
                    state.organization = data.organization;
                } else if (state.organization) {
                    state.organization.company_name = companyName;
                    state.organization.logo_url = logoUrl || state.organization.logo_url;
                }

                applyOrganizationUI();
                syncSettingsFormFromState();
                showSettingsFlash(data.message || "Organization branding updated successfully.", "success");
            } catch (error) {
                showSettingsFlash(error.detail || "Unable to save organization branding.", "error");
            } finally {
                setButtonLoading(settingsSaveBtn, false, "Saving...", "Save Branding");
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
    if (sidebarLogoutBtn) {
        sidebarLogoutBtn.addEventListener("click", handlePortalLogout);
    }
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && studentModal && !studentModal.hidden) {
            closeStudentModal();
        }
    });

    hideAllScreens();
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
