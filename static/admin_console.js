const API_BASE = '';
const COOKIE_AUTH_SENTINEL = '__cookie_session__';
const ADMIN_PAGE_SIZE = 20;
const ADMIN_TIME_ZONE = 'UTC';
const ADMIN_TIME_ZONE_LABEL = 'UTC';

const state = {
    authToken: null,
    currentUser: null,
    adminProtectionVerified: false,
    activeTab: 'users',
    users: [],
    total: 0,
    metrics: {
        pro_plan_users: 0,
        journey_plan_users: 0
    },
    page: 1,
    pageSize: ADMIN_PAGE_SIZE,
    loading: false,
    filters: {
        search: '',
        plan: 'all',
        role: 'all'
    },
    enterpriseAccounts: [],
    enterpriseTotal: 0,
    enterpriseMetrics: {
        active_members: 0,
        active_admins: 0
    },
    enterprisePage: 1,
    enterpriseLoading: false,
    enterpriseFilters: {
        search: ''
    },
    financeAnalytics: null,
    financeLoading: false,
    turnstileSiteKey: '',
    turnstileWidgetId: null,
    actionTurnstileWidgetId: null
};

const refs = {
    flash: document.getElementById('adminFlash'),
    authPanel: document.getElementById('adminAuthPanel'),
    consolePanel: document.getElementById('adminConsolePanel'),
    loginForm: document.getElementById('adminLoginForm'),
    loginEmail: document.getElementById('adminLoginEmail'),
    loginPassword: document.getElementById('adminLoginPassword'),
    loginBtn: document.getElementById('adminLoginBtn'),
    logoutBtn: document.getElementById('adminLogoutBtn'),
    sessionBadge: document.getElementById('adminSessionBadge'),
    protectionCard: document.getElementById('adminProtectionCard'),
    protectionText: document.getElementById('adminProtectionText'),
    verifyProtectionBtn: document.getElementById('adminVerifyProtectionBtn'),
    usersTabBtn: document.getElementById('adminUsersTabBtn'),
    enterpriseTabBtn: document.getElementById('adminEnterpriseTabBtn'),
    financeTabBtn: document.getElementById('adminFinanceTabBtn'),
    usersTabPanel: document.getElementById('adminUsersTabPanel'),
    enterpriseTabPanel: document.getElementById('adminEnterpriseTabPanel'),
    financeTabPanel: document.getElementById('adminFinanceTabPanel'),
    turnstileWrap: document.getElementById('adminTurnstileWrap'),
    turnstileHint: document.getElementById('adminTurnstileHint'),
    actionTurnstileWrap: document.getElementById('adminActionTurnstileWrap'),
    actionTurnstileHint: document.getElementById('adminActionTurnstileHint'),
    usersForm: document.getElementById('adminUsersFilterForm'),
    usersSearch: document.getElementById('adminUsersSearchInput'),
    usersPlan: document.getElementById('adminUsersPlanFilter'),
    usersRole: document.getElementById('adminUsersRoleFilter'),
    usersResetBtn: document.getElementById('adminResetBtn'),
    applyBtn: document.getElementById('adminApplyBtn'),
    tableBody: document.getElementById('adminUsersTableBody'),
    usersSummary: document.getElementById('adminUsersSummary'),
    prevBtn: document.getElementById('adminUsersPrevBtn'),
    nextBtn: document.getElementById('adminUsersNextBtn'),
    pageInfo: document.getElementById('adminUsersPageInfo'),
    createdHeader: document.getElementById('adminCreatedHeader'),
    lastLoginHeader: document.getElementById('adminLastLoginHeader'),
    metricTotal: document.getElementById('adminMetricTotal'),
    metricPro: document.getElementById('adminMetricPro'),
    metricJourney: document.getElementById('adminMetricJourney'),
    enterpriseForm: document.getElementById('adminEnterpriseFilterForm'),
    enterpriseSearch: document.getElementById('adminEnterpriseSearchInput'),
    enterpriseApplyBtn: document.getElementById('adminEnterpriseApplyBtn'),
    enterpriseResetBtn: document.getElementById('adminEnterpriseResetBtn'),
    enterpriseTableBody: document.getElementById('adminEnterpriseTableBody'),
    enterpriseSummary: document.getElementById('adminEnterpriseSummary'),
    enterprisePrevBtn: document.getElementById('adminEnterprisePrevBtn'),
    enterpriseNextBtn: document.getElementById('adminEnterpriseNextBtn'),
    enterprisePageInfo: document.getElementById('adminEnterprisePageInfo'),
    enterpriseCreatedHeader: document.getElementById('adminEnterpriseCreatedHeader'),
    enterpriseMetricTotal: document.getElementById('adminEnterpriseMetricTotal'),
    enterpriseMetricActiveMembers: document.getElementById('adminEnterpriseMetricActiveMembers'),
    enterpriseMetricAdmins: document.getElementById('adminEnterpriseMetricAdmins'),
    enterpriseCredentialForm: document.getElementById('adminEnterpriseCredentialForm'),
    enterpriseCredentialName: document.getElementById('adminEnterpriseCredentialName'),
    enterpriseCredentialEmail: document.getElementById('adminEnterpriseCredentialEmail'),
    enterpriseCredentialCreateBtn: document.getElementById('adminEnterpriseCredentialCreateBtn'),
    enterpriseCredentialResult: document.getElementById('adminEnterpriseCredentialResult'),
    financeMetricNetHero: document.getElementById('adminFinanceMetricNetHero'),
    financeMetricInvested: document.getElementById('adminFinanceMetricInvested'),
    financeMetricInvestedSub: document.getElementById('adminFinanceMetricInvestedSub'),
    financeMetricReturns: document.getElementById('adminFinanceMetricReturns'),
    financeMetricReturnsSub: document.getElementById('adminFinanceMetricReturnsSub'),
    financeMetricNet: document.getElementById('adminFinanceMetricNet'),
    financeMetricBreakEven: document.getElementById('adminFinanceMetricBreakEven'),
    financeMetricRoi: document.getElementById('adminFinanceMetricRoi'),
    financeTimelineChart: document.getElementById('adminFinanceTimelineChart'),
    financeBreakdownChart: document.getElementById('adminFinanceBreakdownChart'),
    financeNotes: document.getElementById('adminFinanceNotes'),
    financeTableBody: document.getElementById('adminFinanceTableBody')
};

document.addEventListener('DOMContentLoaded', () => {
    setDateColumnTimeZoneLabels();
    bindEvents();
    void bootstrap();
});

function setDateColumnTimeZoneLabels() {
    if (refs.createdHeader) refs.createdHeader.textContent = `Created (${ADMIN_TIME_ZONE_LABEL})`;
    if (refs.lastLoginHeader) refs.lastLoginHeader.textContent = `Last Login (${ADMIN_TIME_ZONE_LABEL})`;
    if (refs.enterpriseCreatedHeader) refs.enterpriseCreatedHeader.textContent = `Created (${ADMIN_TIME_ZONE_LABEL})`;
}

function bindEvents() {
    refs.loginForm?.addEventListener('submit', handleLoginSubmit);
    refs.logoutBtn?.addEventListener('click', handleLogout);
    refs.verifyProtectionBtn?.addEventListener('click', handleProtectionVerifyClick);
    refs.usersTabBtn?.addEventListener('click', () => handleTabSwitch('users'));
    refs.enterpriseTabBtn?.addEventListener('click', () => handleTabSwitch('enterprise'));
    refs.financeTabBtn?.addEventListener('click', () => handleTabSwitch('finance'));
    refs.usersForm?.addEventListener('submit', handleUserFiltersSubmit);
    refs.usersResetBtn?.addEventListener('click', resetUserFilters);
    refs.prevBtn?.addEventListener('click', () => changePage(-1));
    refs.nextBtn?.addEventListener('click', () => changePage(1));
    refs.tableBody?.addEventListener('click', handleTableActionClick);
    refs.enterpriseForm?.addEventListener('submit', handleEnterpriseFiltersSubmit);
    refs.enterpriseResetBtn?.addEventListener('click', resetEnterpriseFilters);
    refs.enterprisePrevBtn?.addEventListener('click', () => changeEnterprisePage(-1));
    refs.enterpriseNextBtn?.addEventListener('click', () => changeEnterprisePage(1));
    refs.enterpriseCredentialForm?.addEventListener('submit', handleEnterpriseCredentialSubmit);
    refs.enterpriseCredentialResult?.addEventListener('click', handleCredentialResultClick);
}

async function bootstrap() {
    await initializeTurnstile();
    const canAccess = await refreshCurrentAdminUser({ silent: true });
    if (canAccess) {
        showConsole();
        const verified = await ensureAdminProtection({ silent: true });
        if (verified) {
            await loadActiveTab({ resetPage: true });
            showFlash('Admin session active.', 'success');
        } else {
            showFlash('Complete Cloudflare check to unlock admin data.', 'info');
        }
        return;
    }
    showAuth();
}

function buildAuthHeaders(extraHeaders = {}) {
    const headers = { ...extraHeaders };
    if (state.authToken && state.authToken !== COOKIE_AUTH_SENTINEL) {
        headers.Authorization = `Bearer ${state.authToken}`;
    }
    return headers;
}

function showFlash(message, type = 'info') {
    if (!refs.flash) return;
    refs.flash.textContent = message;
    refs.flash.className = `flash ${type}`;
    refs.flash.hidden = false;
}

function clearFlash() {
    if (!refs.flash) return;
    refs.flash.hidden = true;
    refs.flash.textContent = '';
    refs.flash.className = 'flash';
}

function showAuth() {
    refs.authPanel.hidden = false;
    refs.consolePanel.hidden = true;
    refs.logoutBtn.hidden = true;
    refs.sessionBadge.hidden = true;
    state.adminProtectionVerified = false;
    state.activeTab = 'users';
    renderActiveTab();
    updateProtectionUi();
}

function showConsole() {
    refs.authPanel.hidden = true;
    refs.consolePanel.hidden = false;
    refs.logoutBtn.hidden = false;
    refs.sessionBadge.hidden = false;
    renderActiveTab();
    updateProtectionUi();
    updateSessionBadge();
}

function renderActiveTab() {
    const isUsersTab = state.activeTab === 'users';
    const isEnterpriseTab = state.activeTab === 'enterprise';
    const isFinanceTab = state.activeTab === 'finance';

    if (refs.usersTabBtn) {
        refs.usersTabBtn.classList.toggle('active', isUsersTab);
        refs.usersTabBtn.setAttribute('aria-selected', String(isUsersTab));
    }
    if (refs.enterpriseTabBtn) {
        refs.enterpriseTabBtn.classList.toggle('active', isEnterpriseTab);
        refs.enterpriseTabBtn.setAttribute('aria-selected', String(isEnterpriseTab));
    }
    if (refs.financeTabBtn) {
        refs.financeTabBtn.classList.toggle('active', isFinanceTab);
        refs.financeTabBtn.setAttribute('aria-selected', String(isFinanceTab));
    }
    if (refs.usersTabPanel) {
        refs.usersTabPanel.hidden = !isUsersTab;
    }
    if (refs.enterpriseTabPanel) {
        refs.enterpriseTabPanel.hidden = !isEnterpriseTab;
    }
    if (refs.financeTabPanel) {
        refs.financeTabPanel.hidden = !isFinanceTab;
    }
}

async function handleTabSwitch(tabName) {
    const normalized = String(tabName || '').trim().toLowerCase();
    if (!['users', 'enterprise', 'finance'].includes(normalized)) return;
    if (state.activeTab === normalized) return;

    state.activeTab = normalized;
    renderActiveTab();

    if (!state.currentUser) return;
    clearFlash();
    await loadActiveTab({ resetPage: false });
}

async function loadActiveTab({ resetPage = false } = {}) {
    if (state.activeTab === 'enterprise') {
        await loadEnterpriseAccounts({ resetPage });
        return;
    }
    if (state.activeTab === 'finance') {
        await loadFinanceAnalytics();
        return;
    }
    await loadUsers({ resetPage });
}

function updateSessionBadge() {
    if (!refs.sessionBadge) return;
    const user = state.currentUser;
    if (!user) {
        refs.sessionBadge.hidden = true;
        return;
    }
    const role = user.is_developer ? 'Developer' : 'Admin';
    const label = user.full_name || user.username || user.email || 'Admin User';
    refs.sessionBadge.textContent = `${role}: ${label}`;
    refs.sessionBadge.hidden = false;
}

function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = String(value || '');
    return div.innerHTML;
}

function normalizeErrorMessage(payload, fallbackMessage) {
    if (!payload) return fallbackMessage;
    if (Array.isArray(payload.detail)) {
        return payload.detail.map((entry) => entry?.msg || 'Invalid input').join(', ');
    }
    if (typeof payload.detail === 'string' && payload.detail.trim()) {
        return payload.detail.trim();
    }
    return fallbackMessage;
}

async function handleAdminAuthOrProtectionError(responseStatus, payload) {
    if (responseStatus !== 401 && responseStatus !== 403) return;

    const detail = String(payload?.detail || '').toLowerCase();
    if (detail.includes('cloudflare verification')) {
        state.adminProtectionVerified = false;
        updateProtectionUi();
    }

    const stillAdmin = await refreshCurrentAdminUser({ silent: true });
    if (!stillAdmin) {
        showAuth();
    }
}

async function refreshCurrentAdminUser({ silent = false } = {}) {
    try {
        const response = await fetch(`${API_BASE}/api/auth/me`, {
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });

        if (!response.ok) {
            state.currentUser = null;
            if (!silent && response.status !== 401) {
                showFlash('Session expired. Please login again.', 'error');
            }
            return false;
        }

        const user = await response.json();
        const isAdmin = Boolean(user && (user.is_admin || user.is_developer));
        if (!isAdmin) {
            state.currentUser = null;
            if (!silent) {
                showFlash('This account does not have admin access.', 'error');
            }
            return false;
        }

        state.currentUser = user;
        updateSessionBadge();
        return true;
    } catch (error) {
        console.error('Failed to check admin session:', error);
        state.currentUser = null;
        if (!silent) {
            showFlash('Could not verify session. Please retry.', 'error');
        }
        return false;
    }
}

async function waitForTurnstile(timeoutMs = 10000) {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
        if (window.turnstile && typeof window.turnstile.render === 'function') {
            return true;
        }
        await new Promise((resolve) => setTimeout(resolve, 120));
    }
    return false;
}

async function initializeTurnstile() {
    try {
        const response = await fetch(`${API_BASE}/api/auth/turnstile-site-key`, { credentials: 'same-origin' });
        if (!response.ok) return;

        const payload = await response.json();
        const siteKey = String(payload?.site_key || '').trim();
        state.turnstileSiteKey = siteKey;

        if (!siteKey) {
            if (refs.turnstileWrap) refs.turnstileWrap.hidden = true;
            if (refs.actionTurnstileWrap) refs.actionTurnstileWrap.hidden = true;
            state.adminProtectionVerified = true;
            return;
        }

        const available = await waitForTurnstile();
        if (!available) {
            if (refs.turnstileWrap) refs.turnstileWrap.hidden = false;
            if (refs.turnstileHint) refs.turnstileHint.textContent = 'Security widget failed to load. Refresh and try again.';
            if (refs.actionTurnstileWrap) refs.actionTurnstileWrap.hidden = false;
            if (refs.actionTurnstileHint) refs.actionTurnstileHint.textContent = 'Security widget failed to load. Refresh and try again.';
            return;
        }

        if (refs.turnstileWrap) refs.turnstileWrap.hidden = false;
        state.turnstileWidgetId = window.turnstile.render('#adminTurnstileWidget', {
            sitekey: siteKey,
            theme: 'light'
        });
        if (refs.actionTurnstileWrap) refs.actionTurnstileWrap.hidden = false;
        state.actionTurnstileWidgetId = window.turnstile.render('#adminActionTurnstileWidget', {
            sitekey: siteKey,
            theme: 'light'
        });
    } catch (error) {
        console.error('Failed to initialize Turnstile:', error);
    }
}

function getTurnstileToken() {
    if (!state.turnstileSiteKey) return '';
    if (!window.turnstile || state.turnstileWidgetId === null) return '';
    try {
        return window.turnstile.getResponse(state.turnstileWidgetId) || '';
    } catch {
        return '';
    }
}

function resetTurnstileWidget() {
    if (!state.turnstileSiteKey || !window.turnstile || state.turnstileWidgetId === null) return;
    try {
        window.turnstile.reset(state.turnstileWidgetId);
    } catch {
        // no-op
    }
}

function getActionTurnstileToken() {
    if (!state.turnstileSiteKey) return '';
    if (!window.turnstile || state.actionTurnstileWidgetId === null) return '';
    try {
        return window.turnstile.getResponse(state.actionTurnstileWidgetId) || '';
    } catch {
        return '';
    }
}

function resetActionTurnstileWidget() {
    if (!state.turnstileSiteKey || !window.turnstile || state.actionTurnstileWidgetId === null) return;
    try {
        window.turnstile.reset(state.actionTurnstileWidgetId);
    } catch {
        // no-op
    }
}

function updateProtectionUi() {
    const turnstileEnabled = Boolean(state.turnstileSiteKey);
    if (!refs.protectionCard) return;

    if (!turnstileEnabled) {
        refs.protectionCard.hidden = true;
        return;
    }

    refs.protectionCard.hidden = Boolean(state.adminProtectionVerified);
    if (refs.protectionText) {
        refs.protectionText.textContent = state.adminProtectionVerified
            ? 'Cloudflare protection verified for this admin session.'
            : 'Complete this check to unlock protected admin actions.';
    }
    if (refs.verifyProtectionBtn) {
        refs.verifyProtectionBtn.disabled = false;
    }
}

async function ensureAdminProtection({ silent = false } = {}) {
    if (!state.turnstileSiteKey) {
        state.adminProtectionVerified = true;
        updateProtectionUi();
        return true;
    }
    if (state.adminProtectionVerified) {
        updateProtectionUi();
        return true;
    }
    updateProtectionUi();
    if (!silent) {
        showFlash('Cloudflare verification required. Complete the admin protection check.', 'error');
    }
    return false;
}

async function handleProtectionVerifyClick() {
    clearFlash();

    if (!state.currentUser) {
        showAuth();
        showFlash('Login required before Cloudflare verification.', 'error');
        return;
    }

    if (!state.turnstileSiteKey) {
        state.adminProtectionVerified = true;
        updateProtectionUi();
        await loadActiveTab({ resetPage: true });
        return;
    }

    const token = getActionTurnstileToken();
    if (!token) {
        showFlash('Please complete the Cloudflare check first.', 'error');
        return;
    }

    if (refs.verifyProtectionBtn) {
        refs.verifyProtectionBtn.disabled = true;
        refs.verifyProtectionBtn.textContent = 'Verifying...';
    }

    try {
        const response = await fetch(`${API_BASE}/api/admin/turnstile/verify`, {
            method: 'POST',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            credentials: 'same-origin',
            body: JSON.stringify({ token })
        });
        const payload = await response.json().catch(() => ({}));

        if (!response.ok) {
            showFlash(normalizeErrorMessage(payload, 'Cloudflare verification failed.'), 'error');
            resetActionTurnstileWidget();
            return;
        }

        state.adminProtectionVerified = true;
        updateProtectionUi();
        resetActionTurnstileWidget();
        showFlash('Cloudflare protection verified.', 'success');
        await loadActiveTab({ resetPage: true });
    } catch (error) {
        console.error('Protection verify failed:', error);
        showFlash('Could not verify Cloudflare protection. Please retry.', 'error');
    } finally {
        if (refs.verifyProtectionBtn) {
            refs.verifyProtectionBtn.disabled = false;
            refs.verifyProtectionBtn.textContent = 'Complete Cloudflare Check';
        }
    }
}

async function handleLoginSubmit(event) {
    event.preventDefault();
    clearFlash();

    const email = (refs.loginEmail?.value || '').trim();
    const password = refs.loginPassword?.value || '';

    if (!email || !password) {
        showFlash('Enter both email and password.', 'error');
        return;
    }

    const turnstileToken = getTurnstileToken();
    if (state.turnstileSiteKey && !turnstileToken) {
        showFlash('Please complete the security check.', 'error');
        return;
    }

    refs.loginBtn.disabled = true;
    refs.loginBtn.textContent = 'Signing in...';

    try {
        const formData = new URLSearchParams();
        formData.append('username', email);
        formData.append('password', password);
        if (turnstileToken) {
            formData.append('cf_turnstile_token', turnstileToken);
        }

        const response = await fetch(`${API_BASE}/api/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: formData,
            credentials: 'same-origin'
        });

        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            showFlash(normalizeErrorMessage(payload, 'Login failed.'), 'error');
            resetTurnstileWidget();
            return;
        }

        state.authToken = COOKIE_AUTH_SENTINEL;
        let canAccess = await refreshCurrentAdminUser({ silent: true });
        if (!canAccess && payload?.access_token) {
            state.authToken = payload.access_token;
            canAccess = await refreshCurrentAdminUser({ silent: true });
        }

        if (!canAccess) {
            showFlash('Logged in, but this account does not have admin access.', 'error');
            showAuth();
            return;
        }

        showConsole();
        refs.loginForm.reset();
        resetTurnstileWidget();
        state.adminProtectionVerified = !state.turnstileSiteKey;
        updateProtectionUi();
        if (await ensureAdminProtection({ silent: true })) {
            showFlash('Welcome to the admin console.', 'success');
            await loadActiveTab({ resetPage: true });
        } else {
            showFlash('Login successful. Complete Cloudflare check to continue.', 'info');
        }
    } catch (error) {
        console.error('Admin login failed:', error);
        showFlash('Could not sign in right now. Please try again.', 'error');
    } finally {
        refs.loginBtn.disabled = false;
        refs.loginBtn.textContent = 'Sign In to Admin Console';
    }
}

async function handleLogout() {
    if (state.currentUser) {
        try {
            await fetch(`${API_BASE}/api/admin/turnstile/clear`, {
                method: 'POST',
                headers: buildAuthHeaders(),
                credentials: 'same-origin'
            });
        } catch {
            // no-op
        }
    }

    try {
        await fetch(`${API_BASE}/api/auth/logout`, {
            method: 'POST',
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });
    } catch {
        // no-op
    }

    state.authToken = null;
    state.currentUser = null;
    state.adminProtectionVerified = false;
    state.activeTab = 'users';
    state.users = [];
    state.total = 0;
    state.metrics = { pro_plan_users: 0, journey_plan_users: 0 };
    state.page = 1;
    state.loading = false;
    state.enterpriseAccounts = [];
    state.enterpriseTotal = 0;
    state.enterpriseMetrics = { active_members: 0, active_admins: 0 };
    state.enterprisePage = 1;
    state.enterpriseLoading = false;
    state.enterpriseFilters = { search: '' };
    state.financeAnalytics = null;
    state.financeLoading = false;
    resetTurnstileWidget();
    resetActionTurnstileWidget();
    showAuth();
    showFlash('Logged out. Login with an admin account to continue.', 'info');
    renderUsersTableMessage('No users loaded yet.');
    renderUsersSummary();
    renderPagination();
    renderMetrics();
    renderEnterpriseTableMessage('No enterprise accounts loaded yet.');
    renderEnterpriseSummary();
    renderEnterprisePagination();
    renderEnterpriseMetrics();
    clearEnterpriseCredentialResult();
    renderFinanceEmptyState('No finance data loaded yet.');
}

function getRoleLabel(user) {
    if (user?.is_developer) return 'Developer';
    if (user?.is_admin) return 'Admin';
    return 'Student';
}

function canManageTargetUser(user) {
    if (!state.currentUser || !user) return false;
    if (Number(user.id) === Number(state.currentUser.id)) return false;
    if ((user.is_admin || user.is_developer) && !state.currentUser.is_developer) return false;
    return true;
}

function formatDateTime(value) {
    if (!value) return '-';
    const raw = String(value).trim();
    if (!raw) return '-';

    // Backend returns some timestamps without timezone (e.g. `timestamp` columns).
    // Treat those as UTC so display stays consistent with DB semantics.
    const hasTimeZone = /([zZ]|[+-]\d{2}:\d{2})$/.test(raw);
    const normalized = hasTimeZone ? raw : `${raw}Z`;

    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) return '-';
    return date.toLocaleString(undefined, { timeZone: ADMIN_TIME_ZONE });
}

function formatUsd(value) {
    const amount = Number(value) || 0;
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(amount);
}

function formatPercent(value) {
    const amount = Number(value) || 0;
    return `${amount.toFixed(2)}%`;
}

function formatMonthLabel(monthKey) {
    const [year, month] = String(monthKey || '').split('-').map((part) => Number(part));
    if (!year || !month) return String(monthKey || '-');
    const date = new Date(Date.UTC(year, month - 1, 1));
    return new Intl.DateTimeFormat(undefined, {
        month: 'short',
        year: '2-digit',
        timeZone: 'UTC'
    }).format(date);
}

function renderFinanceEmptyState(message) {
    const safeMessage = escapeHtml(message || 'No finance data loaded yet.');
    if (refs.financeMetricNetHero) refs.financeMetricNetHero.textContent = '$0.00';
    if (refs.financeMetricInvested) refs.financeMetricInvested.textContent = '$0.00';
    if (refs.financeMetricInvestedSub) refs.financeMetricInvestedSub.textContent = '0 investment entries';
    if (refs.financeMetricReturns) refs.financeMetricReturns.textContent = '$0.00';
    if (refs.financeMetricReturnsSub) refs.financeMetricReturnsSub.textContent = '0 return entries';
    if (refs.financeMetricNet) refs.financeMetricNet.textContent = '$0.00';
    if (refs.financeMetricBreakEven) refs.financeMetricBreakEven.textContent = 'Break-even gap: $0.00';
    if (refs.financeMetricRoi) refs.financeMetricRoi.textContent = '0.00%';
    if (refs.financeTimelineChart) refs.financeTimelineChart.innerHTML = `<div class="table-empty">${safeMessage}</div>`;
    if (refs.financeBreakdownChart) refs.financeBreakdownChart.innerHTML = `<div class="table-empty">${safeMessage}</div>`;
    if (refs.financeNotes) refs.financeNotes.innerHTML = '';
    if (refs.financeTableBody) {
        refs.financeTableBody.innerHTML = `
            <tr>
                <td colspan="7" class="table-empty">${safeMessage}</td>
            </tr>
        `;
    }
}

function renderFinanceMetrics(summary) {
    const totalInvested = Number(summary?.total_invested_usd) || 0;
    const totalReturns = Number(summary?.total_returns_usd) || 0;
    const net = Number(summary?.net_usd) || 0;
    const roi = Number(summary?.roi_percent) || 0;
    const breakEvenGap = Number(summary?.break_even_gap_usd) || 0;
    const investmentCount = Number(summary?.investment_entry_count) || 0;
    const returnCount = Number(summary?.return_entry_count) || 0;
    const netLabel = formatUsd(net);

    if (refs.financeMetricNetHero) {
        refs.financeMetricNetHero.textContent = netLabel;
        refs.financeMetricNetHero.classList.toggle('negative', net < 0);
        refs.financeMetricNetHero.classList.toggle('positive', net >= 0);
    }
    if (refs.financeMetricInvested) refs.financeMetricInvested.textContent = formatUsd(totalInvested);
    if (refs.financeMetricInvestedSub) refs.financeMetricInvestedSub.textContent = `${investmentCount} investment ${investmentCount === 1 ? 'entry' : 'entries'}`;
    if (refs.financeMetricReturns) refs.financeMetricReturns.textContent = formatUsd(totalReturns);
    if (refs.financeMetricReturnsSub) refs.financeMetricReturnsSub.textContent = `${returnCount} return ${returnCount === 1 ? 'entry' : 'entries'}`;
    if (refs.financeMetricNet) {
        refs.financeMetricNet.textContent = netLabel;
        refs.financeMetricNet.classList.toggle('negative', net < 0);
        refs.financeMetricNet.classList.toggle('positive', net >= 0);
    }
    if (refs.financeMetricBreakEven) refs.financeMetricBreakEven.textContent = `Break-even gap: ${formatUsd(breakEvenGap)}`;
    if (refs.financeMetricRoi) {
        refs.financeMetricRoi.textContent = formatPercent(roi);
        refs.financeMetricRoi.classList.toggle('negative', roi < 0);
        refs.financeMetricRoi.classList.toggle('positive', roi >= 0);
    }
}

function renderFinanceTimeline(monthlySeries) {
    if (!refs.financeTimelineChart) return;
    const series = Array.isArray(monthlySeries) ? monthlySeries : [];
    if (!series.length) {
        refs.financeTimelineChart.innerHTML = '<div class="table-empty">No monthly finance data available.</div>';
        return;
    }

    const maxValue = Math.max(
        1,
        ...series.map((point) => Math.max(Number(point.investment_usd) || 0, Number(point.returns_usd) || 0))
    );

    refs.financeTimelineChart.innerHTML = series.map((point) => {
        const investment = Number(point.investment_usd) || 0;
        const returns = Number(point.returns_usd) || 0;
        const net = Number(point.net_usd) || 0;
        const investmentHeight = Math.max((investment / maxValue) * 100, investment > 0 ? 4 : 0);
        const returnsHeight = Math.max((returns / maxValue) * 100, returns > 0 ? 4 : 0);
        return `
            <div class="finance-month">
                <div class="finance-bars" title="Invested ${escapeHtml(formatUsd(investment))}, Returns ${escapeHtml(formatUsd(returns))}">
                    <span class="finance-bar investment" style="height: ${investmentHeight.toFixed(2)}%"></span>
                    <span class="finance-bar returns" style="height: ${returnsHeight.toFixed(2)}%"></span>
                </div>
                <div class="finance-month-label">${escapeHtml(formatMonthLabel(point.month))}</div>
                <div class="finance-month-net ${net < 0 ? 'negative' : 'positive'}">${escapeHtml(formatUsd(net))}</div>
            </div>
        `;
    }).join('');
}

function renderFinanceBreakdown(breakdown) {
    if (!refs.financeBreakdownChart) return;
    const rows = Array.isArray(breakdown) ? breakdown : [];
    if (!rows.length) {
        refs.financeBreakdownChart.innerHTML = '<div class="table-empty">No expense breakdown available.</div>';
        return;
    }

    refs.financeBreakdownChart.innerHTML = rows.map((item) => {
        const percentage = Math.min(Math.max(Number(item.percentage) || 0, 0), 100);
        const amount = Number(item.amount_usd) || 0;
        return `
            <div class="finance-breakdown-row">
                <div class="finance-breakdown-top">
                    <strong>${escapeHtml(item.label || 'Uncategorized')}</strong>
                    <span>${escapeHtml(formatUsd(amount))}</span>
                </div>
                <div class="finance-breakdown-track">
                    <span style="width: ${percentage.toFixed(2)}%"></span>
                </div>
                <div class="finance-breakdown-percent">${escapeHtml(formatPercent(percentage))} of spend</div>
            </div>
        `;
    }).join('');
}

function renderFinanceLedger(ledger) {
    if (!refs.financeTableBody) return;
    const rows = Array.isArray(ledger) ? ledger : [];
    if (!rows.length) {
        refs.financeTableBody.innerHTML = `
            <tr>
                <td colspan="7" class="table-empty">No finance ledger rows found.</td>
            </tr>
        `;
        return;
    }

    refs.financeTableBody.innerHTML = rows.map((item) => {
        const amount = Number(item.amount_usd) || 0;
        const isReturn = amount >= 0;
        return `
            <tr>
                <td>${escapeHtml(item.occurred_on || '-')}</td>
                <td><span class="finance-kind ${isReturn ? 'return' : 'investment'}">${escapeHtml(item.kind || '-')}</span></td>
                <td><div class="user-name">${escapeHtml(item.vendor || '-')}</div></td>
                <td>${escapeHtml(item.category || '-')}</td>
                <td>${escapeHtml(item.description || '-')}</td>
                <td class="finance-amount ${isReturn ? 'positive' : 'negative'}">${escapeHtml(formatUsd(amount))}</td>
                <td><span class="finance-source">${escapeHtml(item.source || '-')}</span></td>
            </tr>
        `;
    }).join('');
}

function renderFinanceNotes(notes) {
    if (!refs.financeNotes) return;
    const rows = Array.isArray(notes) ? notes.filter(Boolean) : [];
    if (!rows.length) {
        refs.financeNotes.innerHTML = '';
        return;
    }
    refs.financeNotes.innerHTML = rows.map((note) => `<span>${escapeHtml(note)}</span>`).join('');
}

function renderFinanceAnalytics() {
    const payload = state.financeAnalytics;
    if (!payload) {
        renderFinanceEmptyState('No finance data loaded yet.');
        return;
    }
    renderFinanceMetrics(payload.summary || {});
    renderFinanceTimeline(payload.monthly_series || []);
    renderFinanceBreakdown(payload.expense_breakdown || []);
    renderFinanceLedger(payload.ledger || []);
    renderFinanceNotes(payload.notes || []);
}

function renderUsersTableMessage(message) {
    if (!refs.tableBody) return;
    refs.tableBody.innerHTML = `
        <tr>
            <td colspan="7" class="table-empty">${escapeHtml(message)}</td>
        </tr>
    `;
}

function renderUsersTable() {
    if (!refs.tableBody) return;
    if (!state.users.length) {
        renderUsersTableMessage('No users found for selected filters.');
        return;
    }

    const rows = state.users.map((user) => {
        const role = getRoleLabel(user);
        const isActive = Boolean(user.is_active);
        const verified = user.email_verified ? 'Verified' : 'Pending';
        const canManage = canManageTargetUser(user);
        const disableAttr = canManage ? '' : 'disabled';
        const statusActionLabel = isActive ? 'Deactivate' : 'Activate';
        const statusActionClass = isActive ? 'table-btn warn' : 'table-btn';
        const hint = canManage
            ? ''
            : (Number(user.id) === Number(state.currentUser?.id)
                ? 'You cannot modify your own account.'
                : 'Only developers can manage admin/developer users.');
        const titleAttr = hint ? ` title="${escapeHtml(hint)}"` : '';
        const userName = user.full_name || user.username || user.email || 'Unknown user';
        const userMeta = [user.email, user.university].filter(Boolean).join(' • ');

        return `
            <tr>
                <td>
                    <div class="user-name">${escapeHtml(userName)}</div>
                    <div class="user-meta">${escapeHtml(userMeta || '-')}</div>
                </td>
                <td><span class="role-chip">${escapeHtml(role)}</span></td>
                <td><span class="status-chip ${isActive ? 'active' : 'inactive'}">${isActive ? 'Active' : 'Inactive'}</span></td>
                <td>${escapeHtml(verified)}</td>
                <td>${escapeHtml(formatDateTime(user.created_at))}</td>
                <td>${escapeHtml(formatDateTime(user.last_login_at))}</td>
                <td>
                    <div class="row-actions">
                        <button class="${statusActionClass}" data-action="toggle-status" data-user-id="${user.id}" data-next-active="${isActive ? 'false' : 'true'}" ${disableAttr}${titleAttr}>${statusActionLabel}</button>
                        <button class="table-btn danger" data-action="delete-user" data-user-id="${user.id}" data-user-email="${escapeHtml(user.email || 'this user')}" data-user-name="${escapeHtml(userName)}" ${disableAttr}${titleAttr}>Delete</button>
                    </div>
                </td>
            </tr>
        `;
    });

    refs.tableBody.innerHTML = rows.join('');
}

function renderUsersSummary() {
    if (!refs.usersSummary) return;
    if (state.total <= 0) {
        refs.usersSummary.textContent = 'No users found.';
        return;
    }
    const start = ((state.page - 1) * state.pageSize) + 1;
    const end = Math.min(state.total, start + state.users.length - 1);
    refs.usersSummary.textContent = `Showing ${start}-${end} of ${state.total} users`;
}

function renderPagination() {
    const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
    if (refs.pageInfo) refs.pageInfo.textContent = `Page ${state.page} of ${totalPages}`;
    if (refs.prevBtn) refs.prevBtn.disabled = state.loading || state.page <= 1;
    if (refs.nextBtn) refs.nextBtn.disabled = state.loading || state.page >= totalPages;
    if (refs.applyBtn) refs.applyBtn.disabled = state.loading;
}

function renderMetrics() {
    if (refs.metricTotal) refs.metricTotal.textContent = String(state.total || 0);
    if (refs.metricPro) refs.metricPro.textContent = String(state.metrics.pro_plan_users || 0);
    if (refs.metricJourney) refs.metricJourney.textContent = String(state.metrics.journey_plan_users || 0);
}

function renderEnterpriseTableMessage(message) {
    if (!refs.enterpriseTableBody) return;
    refs.enterpriseTableBody.innerHTML = `
        <tr>
            <td colspan="5" class="table-empty">${escapeHtml(message)}</td>
        </tr>
    `;
}

function renderEnterpriseTable() {
    if (!refs.enterpriseTableBody) return;
    if (!state.enterpriseAccounts.length) {
        renderEnterpriseTableMessage('No enterprise accounts found for selected filters.');
        return;
    }

    const rows = state.enterpriseAccounts.map((account) => {
        const companyName = account.company_name || 'Untitled Organization';
        const companyMeta = account.subdomain_slug ? `subdomain: ${account.subdomain_slug}` : 'No subdomain';
        const portalUrl = String(account.portal_url || '').trim();
        const portalCell = portalUrl
            ? `<a class="portal-link" href="${escapeHtml(portalUrl)}" target="_blank" rel="noopener noreferrer">Open portal</a>`
            : '<span class="user-meta">Not configured</span>';
        const creatorLabel = account.created_by_name || account.created_by_email || 'Unknown';
        const creatorMeta = account.created_by_email && account.created_by_name
            ? account.created_by_email
            : '';

        return `
            <tr>
                <td>
                    <div class="user-name">${escapeHtml(companyName)}</div>
                    <div class="enterprise-meta">${escapeHtml(companyMeta)}</div>
                </td>
                <td>${portalCell}</td>
                <td>
                    <div class="user-name">${escapeHtml(String(account.active_members || 0))} active</div>
                    <div class="enterprise-meta">${escapeHtml(String(account.total_members || 0))} total • ${escapeHtml(String(account.active_admins || 0))} admins</div>
                </td>
                <td>
                    <div class="user-name">${escapeHtml(creatorLabel)}</div>
                    <div class="enterprise-meta">${escapeHtml(creatorMeta)}</div>
                </td>
                <td>${escapeHtml(formatDateTime(account.created_at))}</td>
            </tr>
        `;
    });

    refs.enterpriseTableBody.innerHTML = rows.join('');
}

function renderEnterpriseSummary() {
    if (!refs.enterpriseSummary) return;
    if (state.enterpriseTotal <= 0) {
        refs.enterpriseSummary.textContent = 'No enterprise accounts found.';
        return;
    }
    const start = ((state.enterprisePage - 1) * state.pageSize) + 1;
    const end = Math.min(state.enterpriseTotal, start + state.enterpriseAccounts.length - 1);
    refs.enterpriseSummary.textContent = `Showing ${start}-${end} of ${state.enterpriseTotal} enterprise accounts`;
}

function renderEnterprisePagination() {
    const totalPages = Math.max(1, Math.ceil(state.enterpriseTotal / state.pageSize));
    if (refs.enterprisePageInfo) refs.enterprisePageInfo.textContent = `Page ${state.enterprisePage} of ${totalPages}`;
    if (refs.enterprisePrevBtn) refs.enterprisePrevBtn.disabled = state.enterpriseLoading || state.enterprisePage <= 1;
    if (refs.enterpriseNextBtn) refs.enterpriseNextBtn.disabled = state.enterpriseLoading || state.enterprisePage >= totalPages;
    if (refs.enterpriseApplyBtn) refs.enterpriseApplyBtn.disabled = state.enterpriseLoading;
}

function renderEnterpriseMetrics() {
    if (refs.enterpriseMetricTotal) refs.enterpriseMetricTotal.textContent = String(state.enterpriseTotal || 0);
    if (refs.enterpriseMetricActiveMembers) refs.enterpriseMetricActiveMembers.textContent = String(state.enterpriseMetrics.active_members || 0);
    if (refs.enterpriseMetricAdmins) refs.enterpriseMetricAdmins.textContent = String(state.enterpriseMetrics.active_admins || 0);
}

function clearEnterpriseCredentialResult() {
    if (!refs.enterpriseCredentialResult) return;
    refs.enterpriseCredentialResult.hidden = true;
    refs.enterpriseCredentialResult.innerHTML = '';
}

function renderEnterpriseCredentialResult(payload) {
    if (!refs.enterpriseCredentialResult) return;
    const email = String(payload?.email || '').trim();
    const fullName = String(payload?.full_name || '').trim();
    const tempPassword = String(payload?.temporary_password || '').trim();
    const usesExistingMainPassword = Boolean(payload?.uses_existing_main_password);
    const hasTemporaryPassword = Boolean(tempPassword) && !usesExistingMainPassword;
    const message = String(payload?.message || 'Credentials created.');
    const statusLine = usesExistingMainPassword
        ? 'Existing main platform account linked for enterprise access.'
        : (payload?.credential_created
            ? 'New enterprise credentials created.'
            : 'Existing enterprise credentials updated.');
    const passwordLine = hasTemporaryPassword
        ? `
        <div>
            <strong>Temporary Password:</strong>
            <span class="credential-password">
                ${escapeHtml(tempPassword)}
                <button type="button" class="table-btn copy-credential-btn" data-action="copy-credential" data-password="${escapeHtml(tempPassword)}">Copy</button>
            </span>
        </div>
        `
        : `
        <div><strong>Password:</strong> Uses existing main platform password (not shown).</div>
        `;
    const helperLine = usesExistingMainPassword
        ? 'Client can login at <code>/enterprise</code> with the same email and password used in the main platform.'
        : 'Client should log in at <code>/enterprise</code> and change/reset password after first access.';
    const credentialShareLine = usesExistingMainPassword
        ? 'Enterprise access is now enabled for this email.'
        : 'Share these credentials securely with the client.';

    refs.enterpriseCredentialResult.innerHTML = `
        <strong>${escapeHtml(message)}</strong>
        <div>${escapeHtml(statusLine)} ${escapeHtml(credentialShareLine)}</div>
        <div><strong>Name:</strong> ${escapeHtml(fullName || '-')}</div>
        <div><strong>Email:</strong> ${escapeHtml(email || '-')}</div>
        ${passwordLine}
        <div class="enterprise-meta">${helperLine}</div>
    `;
    refs.enterpriseCredentialResult.hidden = false;
}

async function handleCredentialResultClick(event) {
    const button = event.target.closest('[data-action="copy-credential"]');
    if (!button) return;
    const password = String(button.dataset.password || '').trim();
    if (!password) return;

    try {
        if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
            await navigator.clipboard.writeText(password);
            showFlash('Temporary password copied to clipboard.', 'success');
            return;
        }
    } catch {
        // no-op fallback
    }
    showFlash('Could not copy automatically. Please copy the password manually.', 'info');
}

function setRowActionsDisabled(disabled) {
    document.querySelectorAll('[data-action]').forEach((button) => {
        button.disabled = disabled;
    });
}

async function loadUsers({ resetPage = false } = {}) {
    if (!state.currentUser) {
        const canAccess = await refreshCurrentAdminUser({ silent: true });
        if (!canAccess) {
            showAuth();
            showFlash('Please login with an admin account.', 'error');
            return;
        }
    }

    if (!await ensureAdminProtection({ silent: false })) {
        return;
    }

    if (resetPage) {
        state.page = 1;
    }

    state.filters.search = (refs.usersSearch?.value || '').trim();
    state.filters.plan = (refs.usersPlan?.value || 'all').trim().toLowerCase();
    state.filters.role = (refs.usersRole?.value || 'all').trim().toLowerCase();

    state.loading = true;
    renderUsersTableMessage('Loading users...');
    renderPagination();

    try {
        const params = new URLSearchParams();
        params.set('page', String(state.page));
        params.set('page_size', String(state.pageSize));
        params.set('plan', state.filters.plan);
        params.set('role', state.filters.role);
        if (state.filters.search) {
            params.set('search', state.filters.search);
        }

        const response = await fetch(`${API_BASE}/api/admin/users?${params.toString()}`, {
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });
        const payload = await response.json().catch(() => ({}));

        if (!response.ok) {
            const message = normalizeErrorMessage(payload, 'Failed to load users.');
            state.users = [];
            state.total = 0;
            state.metrics = { pro_plan_users: 0, journey_plan_users: 0 };
            renderUsersTableMessage(message);
            renderUsersSummary();
            renderMetrics();
            await handleAdminAuthOrProtectionError(response.status, payload);
            showFlash(message, 'error');
            return;
        }

        state.users = Array.isArray(payload.users) ? payload.users : [];
        state.total = Number(payload.total) || 0;
        state.metrics = {
            pro_plan_users: Number(payload?.metrics?.pro_plan_users) || 0,
            journey_plan_users: Number(payload?.metrics?.journey_plan_users) || 0
        };

        const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
        if (state.page > totalPages) {
            state.page = totalPages;
            await loadUsers({ resetPage: false });
            return;
        }

        renderUsersTable();
        renderUsersSummary();
        renderMetrics();
        clearFlash();
    } catch (error) {
        console.error('Failed to load users:', error);
        state.users = [];
        state.total = 0;
        state.metrics = { pro_plan_users: 0, journey_plan_users: 0 };
        renderUsersTableMessage('Could not load users. Please retry.');
        renderUsersSummary();
        renderMetrics();
        showFlash('Could not load users. Please retry.', 'error');
    } finally {
        state.loading = false;
        renderPagination();
    }
}

function handleUserFiltersSubmit(event) {
    event.preventDefault();
    state.page = 1;
    void loadUsers({ resetPage: false });
}

function resetUserFilters() {
    if (refs.usersSearch) refs.usersSearch.value = '';
    if (refs.usersPlan) refs.usersPlan.value = 'all';
    if (refs.usersRole) refs.usersRole.value = 'all';
    state.page = 1;
    void loadUsers({ resetPage: false });
}

function changePage(delta) {
    if (state.loading) return;
    const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
    const nextPage = state.page + Number(delta || 0);
    if (nextPage < 1 || nextPage > totalPages) return;
    state.page = nextPage;
    void loadUsers({ resetPage: false });
}

async function loadEnterpriseAccounts({ resetPage = false } = {}) {
    if (!state.currentUser) {
        const canAccess = await refreshCurrentAdminUser({ silent: true });
        if (!canAccess) {
            showAuth();
            showFlash('Please login with an admin account.', 'error');
            return;
        }
    }

    if (!await ensureAdminProtection({ silent: false })) {
        return;
    }

    if (resetPage) {
        state.enterprisePage = 1;
    }

    state.enterpriseFilters.search = (refs.enterpriseSearch?.value || '').trim();

    state.enterpriseLoading = true;
    renderEnterpriseTableMessage('Loading enterprise accounts...');
    renderEnterprisePagination();

    try {
        const params = new URLSearchParams();
        params.set('page', String(state.enterprisePage));
        params.set('page_size', String(state.pageSize));
        if (state.enterpriseFilters.search) {
            params.set('search', state.enterpriseFilters.search);
        }

        const response = await fetch(`${API_BASE}/api/admin/enterprise/accounts?${params.toString()}`, {
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });
        const payload = await response.json().catch(() => ({}));

        if (!response.ok) {
            const message = normalizeErrorMessage(payload, 'Failed to load enterprise accounts.');
            state.enterpriseAccounts = [];
            state.enterpriseTotal = 0;
            state.enterpriseMetrics = { active_members: 0, active_admins: 0 };
            renderEnterpriseTableMessage(message);
            renderEnterpriseSummary();
            renderEnterpriseMetrics();
            await handleAdminAuthOrProtectionError(response.status, payload);
            showFlash(message, 'error');
            return;
        }

        state.enterpriseAccounts = Array.isArray(payload.accounts) ? payload.accounts : [];
        state.enterpriseTotal = Number(payload.total) || 0;
        state.enterpriseMetrics = {
            active_members: Number(payload?.metrics?.active_members) || 0,
            active_admins: Number(payload?.metrics?.active_admins) || 0
        };

        const totalPages = Math.max(1, Math.ceil(state.enterpriseTotal / state.pageSize));
        if (state.enterprisePage > totalPages) {
            state.enterprisePage = totalPages;
            await loadEnterpriseAccounts({ resetPage: false });
            return;
        }

        renderEnterpriseTable();
        renderEnterpriseSummary();
        renderEnterpriseMetrics();
        clearFlash();
    } catch (error) {
        console.error('Failed to load enterprise accounts:', error);
        state.enterpriseAccounts = [];
        state.enterpriseTotal = 0;
        state.enterpriseMetrics = { active_members: 0, active_admins: 0 };
        renderEnterpriseTableMessage('Could not load enterprise accounts. Please retry.');
        renderEnterpriseSummary();
        renderEnterpriseMetrics();
        showFlash('Could not load enterprise accounts. Please retry.', 'error');
    } finally {
        state.enterpriseLoading = false;
        renderEnterprisePagination();
    }
}

async function loadFinanceAnalytics() {
    if (!state.currentUser) {
        const canAccess = await refreshCurrentAdminUser({ silent: true });
        if (!canAccess) {
            showAuth();
            showFlash('Please login with an admin account.', 'error');
            return;
        }
    }

    if (!await ensureAdminProtection({ silent: false })) {
        return;
    }

    state.financeLoading = true;
    renderFinanceEmptyState('Loading finance analytics...');

    try {
        const response = await fetch(`${API_BASE}/api/admin/company-finance/analytics`, {
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });
        const payload = await response.json().catch(() => ({}));

        if (!response.ok) {
            const message = normalizeErrorMessage(payload, 'Failed to load finance analytics.');
            state.financeAnalytics = null;
            renderFinanceEmptyState(message);
            await handleAdminAuthOrProtectionError(response.status, payload);
            showFlash(message, 'error');
            return;
        }

        state.financeAnalytics = payload;
        renderFinanceAnalytics();
        clearFlash();
    } catch (error) {
        console.error('Failed to load finance analytics:', error);
        state.financeAnalytics = null;
        renderFinanceEmptyState('Could not load finance analytics. Please retry.');
        showFlash('Could not load finance analytics. Please retry.', 'error');
    } finally {
        state.financeLoading = false;
    }
}

function handleEnterpriseFiltersSubmit(event) {
    event.preventDefault();
    state.enterprisePage = 1;
    void loadEnterpriseAccounts({ resetPage: false });
}

function resetEnterpriseFilters() {
    if (refs.enterpriseSearch) refs.enterpriseSearch.value = '';
    state.enterprisePage = 1;
    void loadEnterpriseAccounts({ resetPage: false });
}

function changeEnterprisePage(delta) {
    if (state.enterpriseLoading) return;
    const totalPages = Math.max(1, Math.ceil(state.enterpriseTotal / state.pageSize));
    const nextPage = state.enterprisePage + Number(delta || 0);
    if (nextPage < 1 || nextPage > totalPages) return;
    state.enterprisePage = nextPage;
    void loadEnterpriseAccounts({ resetPage: false });
}

async function handleEnterpriseCredentialSubmit(event) {
    event.preventDefault();
    if (!await ensureAdminProtection({ silent: false })) return;

    const fullName = (refs.enterpriseCredentialName?.value || '').trim();
    const email = (refs.enterpriseCredentialEmail?.value || '').trim().toLowerCase();
    if (!fullName || !email) {
        showFlash('Enter both name and email to create enterprise credentials.', 'error');
        return;
    }

    if (refs.enterpriseCredentialCreateBtn) {
        refs.enterpriseCredentialCreateBtn.disabled = true;
        refs.enterpriseCredentialCreateBtn.textContent = 'Creating...';
    }

    try {
        const response = await fetch(`${API_BASE}/api/admin/enterprise/credentials`, {
            method: 'POST',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            credentials: 'same-origin',
            body: JSON.stringify({
                full_name: fullName,
                email
            })
        });
        const payload = await response.json().catch(() => ({}));

        if (!response.ok) {
            await handleAdminAuthOrProtectionError(response.status, payload);
            showFlash(normalizeErrorMessage(payload, 'Failed to create enterprise credentials.'), 'error');
            return;
        }

        renderEnterpriseCredentialResult(payload);
        showFlash(String(payload?.message || 'Enterprise credentials updated successfully.'), 'success');
        refs.enterpriseCredentialForm?.reset();
    } catch (error) {
        console.error('Failed to create enterprise credentials:', error);
        showFlash('Could not create enterprise credentials. Please retry.', 'error');
    } finally {
        if (refs.enterpriseCredentialCreateBtn) {
            refs.enterpriseCredentialCreateBtn.disabled = false;
            refs.enterpriseCredentialCreateBtn.textContent = 'Create Credentials';
        }
    }
}

async function handleTableActionClick(event) {
    const button = event.target.closest('[data-action]');
    if (!button || button.disabled || state.loading) return;

    const action = button.dataset.action;
    const userId = Number(button.dataset.userId || 0);
    if (!Number.isFinite(userId) || userId <= 0) return;

    if (action === 'toggle-status') {
        const nextActive = String(button.dataset.nextActive || '').toLowerCase() === 'true';
        await updateUserStatus(userId, nextActive);
        return;
    }

    if (action === 'delete-user') {
        const userEmail = String(button.dataset.userEmail || 'this user');
        const userName = String(button.dataset.userName || '').trim();
        await deleteUser(userId, userEmail, userName);
    }
}

async function updateUserStatus(userId, nextIsActive) {
    if (!await ensureAdminProtection({ silent: false })) return;
    setRowActionsDisabled(true);
    try {
        const response = await fetch(`${API_BASE}/api/admin/users/${userId}/status`, {
            method: 'PATCH',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ is_active: Boolean(nextIsActive) }),
            credentials: 'same-origin'
        });

        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            await handleAdminAuthOrProtectionError(response.status, payload);
            showFlash(normalizeErrorMessage(payload, 'Failed to update user status.'), 'error');
            return;
        }

        showFlash(`User ${nextIsActive ? 'activated' : 'deactivated'} successfully.`, 'success');
        await loadUsers({ resetPage: false });
    } catch (error) {
        console.error('Status update failed:', error);
        showFlash('Failed to update user status.', 'error');
    } finally {
        setRowActionsDisabled(false);
    }
}

async function deleteUser(userId, userEmail, userName) {
    if (!await ensureAdminProtection({ silent: false })) return;

    const expectedName = (userName || '').trim();
    if (expectedName) {
        const typedName = window.prompt(
            `Type this user's name to confirm deletion:\n${expectedName}`
        );
        if (typedName === null) return;
        if (typedName.trim().toLowerCase() !== expectedName.toLowerCase()) {
            showFlash('Name mismatch. User deletion canceled.', 'error');
            return;
        }
    }

    const confirmed = window.confirm(`Delete ${userEmail} permanently? This cannot be undone.`);
    if (!confirmed) return;

    setRowActionsDisabled(true);
    try {
        const response = await fetch(`${API_BASE}/api/admin/users/${userId}`, {
            method: 'DELETE',
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });

        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            await handleAdminAuthOrProtectionError(response.status, payload);
            showFlash(normalizeErrorMessage(payload, 'Failed to delete user.'), 'error');
            return;
        }

        if (state.users.length === 1 && state.page > 1) {
            state.page -= 1;
        }
        showFlash(`Deleted ${userEmail} successfully.`, 'success');
        await loadUsers({ resetPage: false });
    } catch (error) {
        console.error('Delete failed:', error);
        showFlash('Failed to delete user.', 'error');
    } finally {
        setRowActionsDisabled(false);
    }
}
