const API_BASE = '';
const COOKIE_AUTH_SENTINEL = '__cookie_session__';
const ADMIN_PAGE_SIZE = 20;
const ADMIN_TIME_ZONE = 'UTC';
const ADMIN_TIME_ZONE_LABEL = 'UTC';

const state = {
    authToken: null,
    currentUser: null,
    adminProtectionVerified: false,
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
    metricJourney: document.getElementById('adminMetricJourney')
};

document.addEventListener('DOMContentLoaded', () => {
    setDateColumnTimeZoneLabels();
    bindEvents();
    void bootstrap();
});

function setDateColumnTimeZoneLabels() {
    if (refs.createdHeader) refs.createdHeader.textContent = `Created (${ADMIN_TIME_ZONE_LABEL})`;
    if (refs.lastLoginHeader) refs.lastLoginHeader.textContent = `Last Login (${ADMIN_TIME_ZONE_LABEL})`;
}

function bindEvents() {
    refs.loginForm?.addEventListener('submit', handleLoginSubmit);
    refs.logoutBtn?.addEventListener('click', handleLogout);
    refs.verifyProtectionBtn?.addEventListener('click', handleProtectionVerifyClick);
    refs.usersForm?.addEventListener('submit', handleUserFiltersSubmit);
    refs.usersResetBtn?.addEventListener('click', resetFilters);
    refs.prevBtn?.addEventListener('click', () => changePage(-1));
    refs.nextBtn?.addEventListener('click', () => changePage(1));
    refs.tableBody?.addEventListener('click', handleTableActionClick);
}

async function bootstrap() {
    await initializeTurnstile();
    const canAccess = await refreshCurrentAdminUser({ silent: true });
    if (canAccess) {
        showConsole();
        const verified = await ensureAdminProtection({ silent: true });
        if (verified) {
            await loadUsers({ resetPage: true });
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
    updateProtectionUi();
}

function showConsole() {
    refs.authPanel.hidden = true;
    refs.consolePanel.hidden = false;
    refs.logoutBtn.hidden = false;
    refs.sessionBadge.hidden = false;
    updateProtectionUi();
    updateSessionBadge();
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
        await loadUsers({ resetPage: true });
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
        await loadUsers({ resetPage: true });
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
            await loadUsers({ resetPage: true });
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
    state.users = [];
    state.total = 0;
    state.metrics = { pro_plan_users: 0, journey_plan_users: 0 };
    state.page = 1;
    resetTurnstileWidget();
    resetActionTurnstileWidget();
    showAuth();
    showFlash('Logged out. Login with an admin account to continue.', 'info');
    renderUsersTableMessage('No users loaded yet.');
    renderUsersSummary();
    renderPagination();
    renderMetrics();
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

function resetFilters() {
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
