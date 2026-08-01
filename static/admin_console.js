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
        visa_pass_users: 0,
        free_users: 0
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
    couponOrg: null,            // { id, company } currently open in the discount modal
    couponList: [],
    couponLoading: false,
    enterpriseFilters: {
        search: ''
    },
    financeAnalytics: null,
    financeLoading: false,
    // AI Costs date filter. start/end are inclusive YYYY-MM-DD (UTC); null = server default.
    aiRange: { preset: '30d', start: null, end: null },
    aiUsageData: null,
    aiSeries: [],
    aiGranularity: 'day',
    aiChartResizeBound: false,
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
    analyticsTabBtn: document.getElementById('adminAnalyticsTabBtn'),
    financeTabBtn: document.getElementById('adminFinanceTabBtn'),
    usersTabPanel: document.getElementById('adminUsersTabPanel'),
    enterpriseTabPanel: document.getElementById('adminEnterpriseTabPanel'),
    analyticsTabPanel: document.getElementById('adminAnalyticsTabPanel'),
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
    metricPass: document.getElementById('adminMetricPass'),
    metricFree: document.getElementById('adminMetricFree'),
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
    couponModal: document.getElementById('adminCouponModal'),
    couponModalTitle: document.getElementById('adminCouponModalTitle'),
    couponModalSubtitle: document.getElementById('adminCouponModalSubtitle'),
    couponModalCloseBtn: document.getElementById('adminCouponModalCloseBtn'),
    couponForm: document.getElementById('adminCouponForm'),
    couponCodeInput: document.getElementById('adminCouponCodeInput'),
    couponPercentInput: document.getElementById('adminCouponPercentInput'),
    couponAppliesInput: document.getElementById('adminCouponAppliesInput'),
    couponMaxInput: document.getElementById('adminCouponMaxInput'),
    couponNoteInput: document.getElementById('adminCouponNoteInput'),
    couponCreateBtn: document.getElementById('adminCouponCreateBtn'),
    couponFormError: document.getElementById('adminCouponFormError'),
    couponTableBody: document.getElementById('adminCouponTableBody'),
    accountDetails: document.getElementById('adminAccountDetails'),
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
    financeContributorChart: document.getElementById('adminFinanceContributorChart'),
    financeTableBody: document.getElementById('adminFinanceTableBody'),
    financeAddBtn: document.getElementById('adminFinanceAddBtn'),
    financeExportBtn: document.getElementById('adminFinanceExportBtn'),
    financeEntryForm: document.getElementById('adminFinanceEntryForm'),
    financeEntryCancel: document.getElementById('adminFinanceEntryCancel'),
    financeEntryError: document.getElementById('adminFinanceEntryError'),
    aiTabBtn: document.getElementById('adminAiTabBtn'),
    aiTabPanel: document.getElementById('adminAiTabPanel'),
    aiMonthHero: document.getElementById('adminAiMonthHero'),
    aiTodayCost: document.getElementById('adminAiTodayCost'),
    aiTodaySub: document.getElementById('adminAiTodaySub'),
    ai7Cost: document.getElementById('adminAi7Cost'),
    ai7Sub: document.getElementById('adminAi7Sub'),
    aiMonthCost: document.getElementById('adminAiMonthCost'),
    aiMonthSub: document.getElementById('adminAiMonthSub'),
    aiAllCost: document.getElementById('adminAiAllCost'),
    aiAllSub: document.getElementById('adminAiAllSub'),
    aiTimelineChart: document.getElementById('adminAiTimelineChart'),
    aiSourceChart: document.getElementById('adminAiSourceChart'),
    aiModelChart: document.getElementById('adminAiModelChart'),
    aiHeroLabel: document.getElementById('adminAiHeroLabel'),
    aiRangeCaption: document.getElementById('adminAiRangeCaption'),
    aiRangePresets: document.getElementById('adminAiRangePresets'),
    aiRangeForm: document.getElementById('adminAiRangeForm'),
    aiRangeStart: document.getElementById('adminAiRangeStart'),
    aiRangeEnd: document.getElementById('adminAiRangeEnd'),
    aiRangeReset: document.getElementById('adminAiRangeReset'),
    aiRangeError: document.getElementById('adminAiRangeError'),
    aiRangeCost: document.getElementById('adminAiRangeCost'),
    aiRangeSub: document.getElementById('adminAiRangeSub'),
    aiRangeAvg: document.getElementById('adminAiRangeAvg'),
    aiRangeAvgSub: document.getElementById('adminAiRangeAvgSub'),
    aiRangeTopDay: document.getElementById('adminAiRangeTopDay'),
    aiRangeTopDaySub: document.getElementById('adminAiRangeTopDaySub'),
    aiRangeSaved: document.getElementById('adminAiRangeSaved'),
    aiRangeSavedSub: document.getElementById('adminAiRangeSavedSub'),
    aiRangeSearch: document.getElementById('adminAiRangeSearch'),
    aiRangeSearchSub: document.getElementById('adminAiRangeSearchSub'),
    aiTimelineTitle: document.getElementById('adminAiTimelineTitle'),
    aiTimelineSub: document.getElementById('adminAiTimelineSub'),
    aiSourceSub: document.getElementById('adminAiSourceSub'),
    aiModelSub: document.getElementById('adminAiModelSub'),
    aiDailyCaption: document.getElementById('adminAiDailyCaption'),
    aiDailyTableBody: document.getElementById('adminAiDailyTableBody'),
    aiHideEmptyDays: document.getElementById('adminAiHideEmptyDays'),
    aiDailyTotalCalls: document.getElementById('adminAiDailyTotalCalls'),
    aiDailyTotalTokens: document.getElementById('adminAiDailyTotalTokens'),
    aiDailyTotalCost: document.getElementById('adminAiDailyTotalCost'),
    revMarginHero: document.getElementById('adminRevMarginHero'),
    revTotal: document.getElementById('adminRevTotal'),
    revTotalSub: document.getElementById('adminRevTotalSub'),
    revCredits: document.getElementById('adminRevCredits'),
    revCreditsSub: document.getElementById('adminRevCreditsSub'),
    revInfra: document.getElementById('adminRevInfra'),
    revInfraSub: document.getElementById('adminRevInfraSub'),
    revCost: document.getElementById('adminRevCost'),
    revMargin: document.getElementById('adminRevMargin'),
    revMarginSub: document.getElementById('adminRevMarginSub'),
    revCreditsSold: document.getElementById('adminRevCreditsSold'),
    revCreditsSoldSub: document.getElementById('adminRevCreditsSoldSub'),
    revOutstanding: document.getElementById('adminRevOutstanding'),
    revOutstandingSub: document.getElementById('adminRevOutstandingSub'),
    revFx: document.getElementById('adminRevFx'),
    revFxNote: document.getElementById('adminRevFxNote'),
    revActionsBody: document.getElementById('adminRevActionsBody'),
    b2cMarginHero: document.getElementById('adminB2cMarginHero'),
    b2cRevenue: document.getElementById('adminB2cRevenue'),
    b2cRevenueSub: document.getElementById('adminB2cRevenueSub'),
    b2cActive: document.getElementById('adminB2cActive'),
    b2cCost: document.getElementById('adminB2cCost'),
    b2cCostSub: document.getElementById('adminB2cCostSub'),
    b2cConversion: document.getElementById('adminB2cConversion'),
    b2cConversionSub: document.getElementById('adminB2cConversionSub'),
    optSavedHero: document.getElementById('adminOptSavedHero'),
    optBlocks: document.getElementById('adminOptBlocks'),
    optBlocksSub: document.getElementById('adminOptBlocksSub'),
    optCacheHits: document.getElementById('adminOptCacheHits'),
    optCacheHitsSub: document.getElementById('adminOptCacheHitsSub'),
    optTokens: document.getElementById('adminOptTokens'),
    optSaved: document.getElementById('adminOptSaved')
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
    document.getElementById('adminGrowthRunBtn')?.addEventListener('click', runGrowthAnalysis);
    document.getElementById('adminInsightsRefreshBtn')?.addEventListener('click', loadGrowthInsights);
    document.getElementById('adminAccountBackBtn')?.addEventListener('click', closeAccountDetail);
    refs.verifyProtectionBtn?.addEventListener('click', handleProtectionVerifyClick);
    refs.usersTabBtn?.addEventListener('click', () => handleTabSwitch('users'));
    refs.enterpriseTabBtn?.addEventListener('click', () => handleTabSwitch('enterprise'));
    refs.analyticsTabBtn?.addEventListener('click', () => handleTabSwitch('analytics'));
    refs.financeTabBtn?.addEventListener('click', () => handleTabSwitch('finance'));
    refs.aiTabBtn?.addEventListener('click', () => handleTabSwitch('ai'));
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
    refs.enterpriseTableBody?.addEventListener('click', handleEnterpriseTableActionClick);
    refs.couponModalCloseBtn?.addEventListener('click', closeCouponModal);
    refs.couponModal?.addEventListener('click', (event) => {
        if (event.target === refs.couponModal) closeCouponModal();
    });
    refs.couponForm?.addEventListener('submit', handleCouponCreateSubmit);
    wireCouponPercentClamp(refs.couponPercentInput);
    refs.couponTableBody?.addEventListener('click', handleCouponTableActionClick);
    refs.financeAddBtn?.addEventListener('click', () => openFinanceEntryForm(null));
    refs.financeExportBtn?.addEventListener('click', exportFinanceLedger);
    refs.financeEntryForm?.addEventListener('submit', submitFinanceEntry);
    refs.financeEntryCancel?.addEventListener('click', () => { if (refs.financeEntryForm) refs.financeEntryForm.hidden = true; });
    refs.aiRangePresets?.addEventListener('click', (event) => {
        const btn = event.target.closest('.ai-preset-btn');
        if (btn && btn.dataset.preset) applyAiPreset(btn.dataset.preset);
    });
    refs.aiRangeForm?.addEventListener('submit', handleAiRangeSubmit);
    refs.aiRangeReset?.addEventListener('click', resetAiRange);
    refs.aiHideEmptyDays?.addEventListener('change', renderAiDailyTable);
    refs.aiTabPanel?.addEventListener('click', handleAiExportClick);
    initAiRangeInputs();
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && refs.couponModal && !refs.couponModal.hidden) closeCouponModal();
    });
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

// In-app styled confirm/prompt dialogs — replace the native window.confirm/prompt
// browser popups with on-brand modals. confirmDialog -> Promise<boolean>; promptDialog -> Promise<string|null>.
function confirmDialog(message, opts) {
    opts = opts || {};
    const title = opts.title || 'Please confirm';
    const okText = opts.okText || 'Confirm';
    const cancelText = opts.cancelText || 'Cancel';
    const danger = opts.danger !== false; // default to destructive styling
    const okBg = danger ? 'linear-gradient(135deg,#ef4444,#dc2626)' : 'linear-gradient(135deg,#4f46e5,#7c3aed)';
    return new Promise((resolve) => {
        const existing = document.getElementById('adminConfirmOverlay');
        if (existing) existing.remove();
        const overlay = document.createElement('div');
        overlay.id = 'adminConfirmOverlay';
        overlay.style.cssText = 'position:fixed;inset:0;z-index:100010;background:rgba(15,23,42,0.55);display:flex;align-items:center;justify-content:center;padding:20px;font-family:inherit;';
        overlay.innerHTML =
            '<div role="dialog" aria-modal="true" style="max-width:440px;width:100%;background:#fff;border-radius:16px;box-shadow:0 24px 60px rgba(2,6,23,0.4);overflow:hidden;">' +
                '<div style="padding:22px 24px 16px;">' +
                    '<div style="font-size:18px;font-weight:800;color:#0f172a;">' + escapeHtml(title) + '</div>' +
                    '<p style="margin:10px 0 0;color:#475569;font-size:14.5px;line-height:1.6;">' + escapeHtml(message).replace(/\n/g, '<br>') + '</p>' +
                '</div>' +
                '<div style="display:flex;gap:10px;justify-content:flex-end;padding:14px 24px 20px;">' +
                    '<button id="adminCfmCancel" style="padding:10px 18px;border-radius:10px;border:1px solid #e2e8f0;background:#fff;color:#0f172a;font-weight:600;cursor:pointer;">' + escapeHtml(cancelText) + '</button>' +
                    '<button id="adminCfmOk" style="padding:10px 18px;border-radius:10px;border:none;background:' + okBg + ';color:#fff;font-weight:700;cursor:pointer;">' + escapeHtml(okText) + '</button>' +
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
        overlay.querySelector('#adminCfmOk').onclick = () => done(true);
        overlay.querySelector('#adminCfmCancel').onclick = () => done(false);
        overlay.addEventListener('click', (e) => { if (e.target === overlay) done(false); });
        document.addEventListener('keydown', onKey, true);
        const ok = overlay.querySelector('#adminCfmOk'); if (ok) ok.focus();
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
        const existing = document.getElementById('adminPromptOverlay');
        if (existing) existing.remove();
        const overlay = document.createElement('div');
        overlay.id = 'adminPromptOverlay';
        overlay.style.cssText = 'position:fixed;inset:0;z-index:100010;background:rgba(15,23,42,0.55);display:flex;align-items:center;justify-content:center;padding:20px;font-family:inherit;';
        overlay.innerHTML =
            '<div role="dialog" aria-modal="true" style="max-width:440px;width:100%;background:#fff;border-radius:16px;box-shadow:0 24px 60px rgba(2,6,23,0.4);overflow:hidden;">' +
                '<form id="adminPromptForm"><div style="padding:22px 24px 8px;">' +
                    '<div style="font-size:18px;font-weight:800;color:#0f172a;">' + escapeHtml(title) + '</div>' +
                    '<p style="margin:10px 0 12px;color:#475569;font-size:14.5px;line-height:1.6;">' + escapeHtml(message).replace(/\n/g, '<br>') + '</p>' +
                    '<input id="adminPromptInput" type="' + escapeHtml(inputType) + '" placeholder="' + escapeHtml(placeholder) + '" value="' + escapeHtml(value) + '" style="width:100%;box-sizing:border-box;padding:11px 13px;border:1px solid #e2e8f0;border-radius:10px;font-size:14.5px;color:#0f172a;outline:none;">' +
                '</div>' +
                '<div style="display:flex;gap:10px;justify-content:flex-end;padding:14px 24px 20px;">' +
                    '<button type="button" id="adminPromptCancel" style="padding:10px 18px;border-radius:10px;border:1px solid #e2e8f0;background:#fff;color:#0f172a;font-weight:600;cursor:pointer;">Cancel</button>' +
                    '<button type="submit" id="adminPromptOk" style="padding:10px 18px;border-radius:10px;border:none;background:linear-gradient(135deg,#4f46e5,#7c3aed);color:#fff;font-weight:700;cursor:pointer;">' + escapeHtml(okText) + '</button>' +
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
        overlay.querySelector('#adminPromptForm').onsubmit = (e) => { e.preventDefault(); done(overlay.querySelector('#adminPromptInput').value); };
        overlay.querySelector('#adminPromptCancel').onclick = () => done(null);
        overlay.addEventListener('click', (e) => { if (e.target === overlay) done(null); });
        document.addEventListener('keydown', onKey, true);
        const inp = overlay.querySelector('#adminPromptInput'); if (inp) inp.focus();
    });
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
    const isAnalyticsTab = state.activeTab === 'analytics';
    const isFinanceTab = state.activeTab === 'finance';
    const isAiTab = state.activeTab === 'ai';

    if (refs.usersTabBtn) {
        refs.usersTabBtn.classList.toggle('active', isUsersTab);
        refs.usersTabBtn.setAttribute('aria-selected', String(isUsersTab));
    }
    if (refs.enterpriseTabBtn) {
        refs.enterpriseTabBtn.classList.toggle('active', isEnterpriseTab);
        refs.enterpriseTabBtn.setAttribute('aria-selected', String(isEnterpriseTab));
    }
    if (refs.analyticsTabBtn) {
        refs.analyticsTabBtn.classList.toggle('active', isAnalyticsTab);
        refs.analyticsTabBtn.setAttribute('aria-selected', String(isAnalyticsTab));
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
    if (refs.analyticsTabPanel) {
        refs.analyticsTabPanel.hidden = !isAnalyticsTab;
    }
    if (refs.financeTabPanel) {
        refs.financeTabPanel.hidden = !isFinanceTab;
    }
    if (refs.aiTabBtn) {
        refs.aiTabBtn.classList.toggle('active', isAiTab);
        refs.aiTabBtn.setAttribute('aria-selected', String(isAiTab));
    }
    if (refs.aiTabPanel) {
        refs.aiTabPanel.hidden = !isAiTab;
    }
}

async function handleTabSwitch(tabName) {
    const normalized = String(tabName || '').trim().toLowerCase();
    if (!['users', 'enterprise', 'analytics', 'finance', 'ai'].includes(normalized)) return;
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
    if (state.activeTab === 'analytics') {
        await Promise.all([loadAcquisitionBreakdown(), loadGrowthInsights()]);
        return;
    }
    if (state.activeTab === 'finance') {
        await loadFinanceAnalytics();
        return;
    }
    if (state.activeTab === 'ai') {
        await loadAiUsage();
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
    state.metrics = { visa_pass_users: 0, free_users: 0 };
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

// `amount_usd` on the company-finance screens is a real USD major-unit float (the ledger
// is kept in USD), so this stays a plain USD formatter. Everything that comes off a
// payment row goes through formatMinor() below instead.
function formatUsd(value) {
    const amount = Number(value) || 0;
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(amount);
}

/* ===================== Money rendering (mirrors app/money.py) =====================
   A stored amount is an INTEGER IN THE MINOR UNIT OF ITS OWN CURRENCY: 1299 is $12.99 on
   a USD row and ₹12.99 on an INR one. Nothing here may divide by 100 and prefix a rupee
   sign, and amounts of different currencies are never added — anything the server summed
   it summed as INR settlement (base_amount_paise) and labelled as such. */
const CURRENCY_SYMBOLS = {
    INR: '₹', USD: '$', GBP: '£', EUR: '€', CAD: 'C$', AUD: 'A$',
    AED: 'AED ', SGD: 'S$', JPY: '¥', NZD: 'NZ$', CHF: 'CHF ', HKD: 'HK$'
};
// Zero-decimal currencies: ¥999 is stored as 999, so dividing by 100 would show ¥9.99.
// Display-only — the server refuses to charge in these.
const ZERO_DECIMAL_CURRENCIES = new Set(['JPY', 'KRW', 'VND', 'ISK', 'CLP']);

function currencyCode(currency) {
    const code = String(currency || 'INR').trim().toUpperCase();
    return /^[A-Z]{3}$/.test(code) ? code : 'INR';
}

function currencySymbol(currency) {
    const code = currencyCode(currency);
    return CURRENCY_SYMBOLS[code] || (code + ' ');
}

function currencyExponent(currency) {
    return ZERO_DECIMAL_CURRENCIES.has(currencyCode(currency)) ? 0 : 2;
}

// Integer minor units → display string: (1299,'USD') → '$12.99', (99900,'INR') → '₹999'.
function formatMinor(minor, currency) {
    const code = currencyCode(currency);
    const exponent = currencyExponent(code);
    const amount = Number(minor || 0) / Math.pow(10, exponent);
    return currencySymbol(code) + amount.toLocaleString(code === 'INR' ? 'en-IN' : undefined, {
        minimumFractionDigits: Number.isInteger(amount) ? 0 : exponent,
        maximumFractionDigits: exponent
    });
}

// Prefer the server's own display string; fall back to a zero in the RIGHT currency.
// A literal '₹0' fallback is a rupee claim about money this screen cannot see.
function moneyOr(display, currency) {
    return display || formatMinor(0, currency);
}

// Label for an amount input, e.g. '$ USD', '₹ INR', 'AED' (no "AED AED").
function currencyInputLabel(currency) {
    const code = currencyCode(currency);
    const symbol = currencySymbol(code).trim();
    return symbol && symbol !== code ? `${symbol} ${code}` : code;
}

function formatPercent(value) {
    const amount = Number(value) || 0;
    return `${amount.toFixed(2)}%`;
}

// Coupon discounts must stay in the 1–100% band.
function clampCouponPercent(value) {
    return Math.min(100, Math.max(1, value));
}

// Live-clamp a coupon percent input: anything typed above 100 snaps back to 100
// immediately; values below 1 snap up to 1 once the field is committed (blur/Enter).
function wireCouponPercentClamp(input) {
    if (!input || input.dataset.pctClampWired) return;
    input.dataset.pctClampWired = '1';
    input.addEventListener('input', () => {
        const value = parseFloat(input.value);
        if (Number.isFinite(value) && value > 100) input.value = '100';
    });
    input.addEventListener('change', () => {
        const value = parseFloat(input.value);
        if (Number.isFinite(value) && (value < 1 || value > 100)) input.value = String(clampCouponPercent(value));
    });
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
    if (refs.financeContributorChart) refs.financeContributorChart.innerHTML = `<div class="table-empty">${safeMessage}</div>`;
    if (refs.financeTableBody) {
        refs.financeTableBody.innerHTML = `
            <tr>
                <td colspan="8" class="table-empty">${safeMessage}</td>
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
    // Every USD figure here was converted from INR at ONE rate; name it, and say how many
    // foreign payments are missing from the total because their INR settlement figure
    // hasn't landed — they are NOT counted, so this number is a known understatement.
    if (refs.financeMetricReturnsSub) {
        const fxRate = Number(summary?.usd_to_inr) || 0;
        const uncounted = Number(summary?.estimated_settlement_count) || 0;
        const bits = [`${returnCount} return ${returnCount === 1 ? 'entry' : 'entries'}`];
        if (fxRate > 0) bits.push(`$1 = ₹${fxRate} (${summary?.fx_source || 'fallback'})`);
        if (uncounted > 0) bits.push(`${uncounted} not counted (awaiting INR settlement)`);
        refs.financeMetricReturnsSub.textContent = bits.join(' · ');
    }
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

    const columns = series.map((point) => {
        const investment = Number(point.investment_usd) || 0;
        const returns = Number(point.returns_usd) || 0;
        const net = Number(point.net_usd) || 0;
        const investmentHeight = Math.max((investment / maxValue) * 100, investment > 0 ? 2 : 0);
        const returnsHeight = Math.max((returns / maxValue) * 100, returns > 0 ? 2 : 0);
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

    refs.financeTimelineChart.innerHTML = `
        <div class="finance-timeline-legend">
            <span class="finance-legend-item"><span class="finance-legend-dot investment"></span>Investment</span>
            <span class="finance-legend-item"><span class="finance-legend-dot returns"></span>Returns</span>
        </div>
        <div class="finance-timeline-plot">${columns}</div>
    `;
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

function renderFinanceContributorBreakdown(breakdown) {
    if (!refs.financeContributorChart) return;
    const rows = Array.isArray(breakdown) ? breakdown : [];
    if (!rows.length) {
        refs.financeContributorChart.innerHTML = '<div class="table-empty">No founder spend breakdown available.</div>';
        return;
    }

    refs.financeContributorChart.innerHTML = rows.map((item) => {
        const percentage = Math.min(Math.max(Number(item.percentage) || 0, 0), 100);
        const amount = Number(item.amount_usd) || 0;
        return `
            <div class="finance-breakdown-row contributor-row">
                <div class="finance-breakdown-top">
                    <strong>${escapeHtml(item.label || 'Unassigned')}</strong>
                    <span>${escapeHtml(formatUsd(amount))}</span>
                </div>
                <div class="finance-breakdown-track contributor-track">
                    <span style="width: ${percentage.toFixed(2)}%"></span>
                </div>
                <div class="finance-breakdown-percent">${escapeHtml(formatPercent(percentage))} of founder spend</div>
            </div>
        `;
    }).join('');
}

function financeLedgerEntryId(item) {
    // Only company_finance_entries rows are editable; they carry an id of "finance-<n>".
    // Subscription-revenue returns carry "payment-<n>" and are read-only here.
    const id = String((item && item.id) || '');
    return id.startsWith('finance-') ? id.slice('finance-'.length) : null;
}

function financeLedgerItemByEntryId(fid) {
    const ledger = (state.financeAnalytics && state.financeAnalytics.ledger) || [];
    return ledger.find((it) => financeLedgerEntryId(it) === String(fid)) || null;
}

function renderFinanceLedger(ledger) {
    if (!refs.financeTableBody) return;
    const rows = Array.isArray(ledger) ? ledger : [];
    if (!rows.length) {
        refs.financeTableBody.innerHTML = `
            <tr>
                <td colspan="9" class="table-empty">No finance ledger rows found.</td>
            </tr>
        `;
        return;
    }

    refs.financeTableBody.innerHTML = rows.map((item) => {
        const amount = Number(item.amount_usd) || 0;
        const isReturn = amount >= 0;
        const fid = financeLedgerEntryId(item);
        const actions = fid
            ? `<button type="button" class="table-btn" data-finance-edit="${escapeHtml(fid)}">Edit</button>
               <button type="button" class="table-btn danger" data-finance-delete="${escapeHtml(fid)}">Delete</button>`
            : '<span class="finance-source">Auto</span>';
        // Payment rows carry what the customer was actually charged. A foreign row with no
        // INR settlement figure is shown at zero and marked — never dropped (a missing row
        // reads as no revenue) and never booked at its charged amount (cents are not paise).
        const chargedNote = item.charged_display
            ? `<div class="finance-source">charged ${escapeHtml(item.charged_display)}</div>`
            : '';
        const estimatedNote = item.settlement_estimated
            ? '<div class="finance-source" title="Razorpay has not reported an INR settlement figure for this payment yet, so it is not counted in returns. Its charged amount is in a foreign currency and cannot be added to the INR books.">⚠ not counted</div>'
            : '';
        return `
            <tr>
                <td>${escapeHtml(item.occurred_on || '-')}</td>
                <td><span class="finance-kind ${isReturn ? 'return' : 'investment'}">${escapeHtml(item.kind || '-')}</span></td>
                <td><div class="user-name">${escapeHtml(item.vendor || '-')}</div></td>
                <td>${escapeHtml(item.category || '-')}</td>
                <td><span class="finance-source">${escapeHtml(item.paid_by || '-')}</span></td>
                <td>${escapeHtml(item.description || '-')}</td>
                <td class="finance-amount ${isReturn ? 'positive' : 'negative'}">${escapeHtml(formatUsd(amount))}${chargedNote}${estimatedNote}</td>
                <td><span class="finance-source">${escapeHtml(item.source || '-')}</span></td>
                <td class="finance-actions">${actions}</td>
            </tr>
        `;
    }).join('');

    refs.financeTableBody.querySelectorAll('[data-finance-edit]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const fid = btn.getAttribute('data-finance-edit');
            openFinanceEntryForm(financeLedgerItemByEntryId(fid), fid);
        });
    });
    refs.financeTableBody.querySelectorAll('[data-finance-delete]').forEach((btn) => {
        btn.addEventListener('click', () => deleteFinanceEntry(btn.getAttribute('data-finance-delete')));
    });
}

function filenameFromDisposition(header, fallback) {
    const match = /filename="?([^";]+)"?/i.exec(String(header || ''));
    return (match && match[1]) ? match[1].trim() : fallback;
}

async function exportFinanceLedger() {
    const btn = refs.financeExportBtn;
    if (!await ensureAdminProtection({ silent: false })) return;

    const originalLabel = btn ? btn.textContent : '';
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Preparing…';
    }

    try {
        const response = await fetch(`${API_BASE}/api/admin/company-finance/export?format=xlsx`, {
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });

        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            const message = normalizeErrorMessage(payload, 'Failed to export the finance ledger.');
            await handleAdminAuthOrProtectionError(response.status, payload);
            showFlash(message, 'error');
            return;
        }

        const blob = await response.blob();
        const filename = filenameFromDisposition(
            response.headers.get('Content-Disposition'),
            'rilono-finance.xlsx'
        );
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        // Revoke after the click so the download has a live URL to read from.
        setTimeout(() => URL.revokeObjectURL(url), 2000);
        showFlash(`Downloaded ${filename}`, 'success');
    } catch (error) {
        console.error('Failed to export finance ledger:', error);
        showFlash('Could not export the finance ledger. Please retry.', 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalLabel;
        }
    }
}

function setFinanceFormError(message) {
    if (!refs.financeEntryError) return;
    if (message) {
        refs.financeEntryError.textContent = message;
        refs.financeEntryError.hidden = false;
    } else {
        refs.financeEntryError.textContent = '';
        refs.financeEntryError.hidden = true;
    }
}

function openFinanceEntryForm(item, fid) {
    const form = refs.financeEntryForm;
    if (!form) return;
    form.hidden = false;
    setFinanceFormError('');
    const amount = item ? Number(item.amount_usd) || 0 : 0;
    const g = (id) => document.getElementById(id);
    g('adminFinanceEntryId').value = fid || '';
    g('adminFinanceEntryDate').value = item ? String(item.occurred_on || '').slice(0, 10) : new Date().toISOString().slice(0, 10);
    g('adminFinanceEntryType').value = item ? (amount >= 0 ? 'return' : 'expense') : 'expense';
    g('adminFinanceEntryVendor').value = item ? (item.vendor || '') : '';
    g('adminFinanceEntryCategory').value = item ? (item.category || '') : '';
    g('adminFinanceEntryPaidBy').value = item ? (item.paid_by || 'Gaurav') : 'Gaurav';
    g('adminFinanceEntryAmount').value = item ? Math.abs(amount).toFixed(2) : '';
    g('adminFinanceEntryDesc').value = item ? (item.description || '') : '';
    g('adminFinanceEntrySave').textContent = fid ? 'Save changes' : 'Add entry';
    form.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    g('adminFinanceEntryVendor').focus();
}

async function submitFinanceEntry(event) {
    if (event) event.preventDefault();
    if (!await ensureAdminProtection({ silent: false })) return;
    const g = (id) => document.getElementById(id);
    const fid = String(g('adminFinanceEntryId').value || '').trim();
    const occurred_on = g('adminFinanceEntryDate').value;
    const entry_type = g('adminFinanceEntryType').value;
    const vendor = String(g('adminFinanceEntryVendor').value || '').trim();
    const category = String(g('adminFinanceEntryCategory').value || '').trim();
    const paid_by = String(g('adminFinanceEntryPaidBy').value || '').trim() || 'Gaurav';
    const amount_usd = Number(g('adminFinanceEntryAmount').value);
    const description = String(g('adminFinanceEntryDesc').value || '').trim();

    if (!occurred_on) { setFinanceFormError('Pick a date.'); return; }
    if (!vendor || !category) { setFinanceFormError('Vendor and category are required.'); return; }
    if (!Number.isFinite(amount_usd) || amount_usd <= 0) { setFinanceFormError('Enter an amount greater than 0.'); return; }
    setFinanceFormError('');

    const isEdit = !!fid;
    const saveBtn = g('adminFinanceEntrySave');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = isEdit ? 'Saving…' : 'Adding…'; }
    try {
        const url = isEdit
            ? `${API_BASE}/api/admin/company-finance/entries/${encodeURIComponent(fid)}`
            : `${API_BASE}/api/admin/company-finance/entries`;
        const response = await fetch(url, {
            method: isEdit ? 'PATCH' : 'POST',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            credentials: 'same-origin',
            body: JSON.stringify({ occurred_on, entry_type, vendor, category, paid_by, amount_usd, description }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            await handleAdminAuthOrProtectionError(response.status, payload);
            setFinanceFormError(normalizeErrorMessage(payload, 'Could not save the entry.'));
            return;
        }
        if (refs.financeEntryForm) refs.financeEntryForm.hidden = true;
        showFlash(isEdit ? 'Entry updated.' : 'Entry added.', 'success');
        await loadFinanceAnalytics();
    } catch (error) {
        console.error('Save finance entry failed:', error);
        setFinanceFormError('Could not save the entry.');
    } finally {
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = isEdit ? 'Save changes' : 'Add entry'; }
    }
}

async function deleteFinanceEntry(fid) {
    if (!await ensureAdminProtection({ silent: false })) return;
    const item = financeLedgerItemByEntryId(fid);
    const label = item ? `${item.vendor} · ${formatUsd(Number(item.amount_usd) || 0)}` : `entry #${fid}`;
    if (!(await confirmDialog(`This finance entry (${label}) will be permanently removed from the ledger and analytics.`, { title: 'Delete finance entry?', okText: 'Delete' }))) return;
    try {
        const response = await fetch(`${API_BASE}/api/admin/company-finance/entries/${encodeURIComponent(fid)}`, {
            method: 'DELETE',
            headers: buildAuthHeaders(),
            credentials: 'same-origin',
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            await handleAdminAuthOrProtectionError(response.status, payload);
            showFlash(normalizeErrorMessage(payload, 'Could not delete the entry.'), 'error');
            return;
        }
        showFlash('Entry deleted.', 'success');
        await loadFinanceAnalytics();
    } catch (error) {
        console.error('Delete finance entry failed:', error);
        showFlash('Could not delete the entry.', 'error');
    }
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
    renderFinanceContributorBreakdown(payload.contributor_breakdown || []);
    renderFinanceLedger(payload.ledger || []);
}

function renderUsersTableMessage(message) {
    if (!refs.tableBody) return;
    refs.tableBody.innerHTML = `
        <tr>
            <td colspan="8" class="table-empty">${escapeHtml(message)}</td>
        </tr>
    `;
}

const B2C_COUNTRIES = {
    US: { flag: '🇺🇸', name: 'United States' },
    UK: { flag: '🇬🇧', name: 'United Kingdom' },
    CA: { flag: '🇨🇦', name: 'Canada' },
    AU: { flag: '🇦🇺', name: 'Australia' }
};
const B2C_VISA_LABELS = {
    us_f1: 'F-1 Student', us_j1: 'J-1 Exchange', us_m1: 'M-1 Vocational',
    uk_student: 'Student Visa', uk_short_study: 'Short-Term Study',
    ca_study_permit: 'Study Permit', ca_sds: 'SDS',
    au_subclass500: 'Subclass 500'
};

function renderUserCountryCell(user) {
    const code = String(user.destination_country_code || '').toUpperCase();
    const country = B2C_COUNTRIES[code];
    if (!country) return '<span class="user-meta">—</span>';
    const visaLabel = B2C_VISA_LABELS[user.visa_type_key] || '';
    return `<div class="user-name">${country.flag} ${escapeHtml(country.name)}</div>` +
        (visaLabel ? `<div class="user-meta">${escapeHtml(visaLabel)}</div>` : '');
}

const ACQ_CHANNELS = {
    google_organic: { label: 'Google', color: '#4285F4' }, google_ads: { label: 'Google Ads', color: '#1a73e8' },
    bing: { label: 'Bing', color: '#0b8484' }, duckduckgo: { label: 'DuckDuckGo', color: '#de5833' }, yahoo: { label: 'Yahoo', color: '#6001d2' },
    instagram: { label: 'Instagram', color: '#e1306c' }, facebook: { label: 'Facebook', color: '#1877f2' },
    twitter: { label: 'X / Twitter', color: '#111827' }, linkedin: { label: 'LinkedIn', color: '#0a66c2' },
    reddit: { label: 'Reddit', color: '#ff4500' }, youtube: { label: 'YouTube', color: '#ff0000' }, tiktok: { label: 'TikTok', color: '#010101' },
    quora: { label: 'Quora', color: '#b92b27' }, telegram: { label: 'Telegram', color: '#229ed9' }, whatsapp: { label: 'WhatsApp', color: '#25d366' },
    pinterest: { label: 'Pinterest', color: '#e60023' }, medium: { label: 'Medium', color: '#111827' }, github: { label: 'GitHub', color: '#24292e' },
    chatgpt: { label: 'ChatGPT', color: '#10a37f' }, perplexity: { label: 'Perplexity', color: '#20808d' },
    gemini: { label: 'AI Referral', color: '#8b6cef' }, claude: { label: 'AI Referral', color: '#d97757' }, email: { label: 'Email', color: '#f59e0b' },
    referral: { label: 'Referral', color: '#8b5cf6' }, direct: { label: 'Direct', color: '#94a3b8' },
    other: { label: 'Other', color: '#64748b' }, untracked: { label: '', color: '#cbd5e1' }
};

function renderUserSourceBadge(user) {
    const ch = user.acquisition_channel;
    if (!ch || ch === 'untracked') return '';
    const meta = ACQ_CHANNELS[ch] || ACQ_CHANNELS.other;
    return `<div class="user-meta" style="margin-top:3px;display:inline-flex;align-items:center;gap:5px;">`
        + `<span style="width:7px;height:7px;border-radius:50%;background:${meta.color};display:inline-block;flex:none;"></span>`
        + `<span>via ${escapeHtml(meta.label || 'Other')}</span></div>`;
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
                    ${renderUserSourceBadge(user)}
                </td>
                <td>${renderUserCountryCell(user)}</td>
                <td><span class="role-chip">${escapeHtml(role)}</span></td>
                <td><span class="status-chip ${isActive ? 'active' : 'inactive'}">${isActive ? 'Active' : 'Inactive'}</span></td>
                <td>${escapeHtml(verified)}</td>
                <td>${escapeHtml(formatDateTime(user.created_at))}</td>
                <td>${escapeHtml(formatDateTime(user.last_login_at))}</td>
                <td>
                    <div class="row-actions">
                        <button class="table-btn" data-action="manage-user" data-user-id="${user.id}">Manage</button>
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
    if (refs.metricPass) refs.metricPass.textContent = String(state.metrics.visa_pass_users || 0);
    if (refs.metricFree) refs.metricFree.textContent = String(state.metrics.free_users || 0);
}

function renderEnterpriseTableMessage(message) {
    if (!refs.enterpriseTableBody) return;
    refs.enterpriseTableBody.innerHTML = `
        <tr>
            <td colspan="6" class="table-empty">${escapeHtml(message)}</td>
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
                <td>
                    <button type="button" class="table-btn" data-action="manage-coupons"
                        data-org-id="${escapeHtml(String(account.organization_id))}"
                        data-company="${escapeHtml(companyName)}">Manage</button>
                </td>
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
            state.metrics = { visa_pass_users: 0, free_users: 0 };
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
            visa_pass_users: Number(payload?.metrics?.visa_pass_users) || 0,
            free_users: Number(payload?.metrics?.free_users) || 0
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
        state.metrics = { visa_pass_users: 0, free_users: 0 };
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

function formatAiUsd(value) {
    const n = Number(value) || 0;
    if (n === 0) return '$0.00';
    if (n < 1) return '$' + n.toFixed(4);
    if (n < 100) return '$' + n.toFixed(2);
    return '$' + n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatTokens(value) {
    const v = Number(value) || 0;
    if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M';
    if (v >= 1e3) return (v / 1e3).toFixed(1) + 'k';
    return String(v);
}

function aiUsageEmptyState(message) {
    const m = escapeHtml(message || 'No AI usage recorded yet.');
    [refs.aiTimelineChart, refs.aiSourceChart, refs.aiModelChart].forEach((el) => {
        if (el) el.innerHTML = `<div class="table-empty">${m}</div>`;
    });
    if (refs.aiDailyTableBody) refs.aiDailyTableBody.innerHTML = `<tr><td colspan="5" class="table-empty">${m}</td></tr>`;
}

function setAiRefreshing(on) {
    [refs.aiTimelineChart, refs.aiSourceChart, refs.aiModelChart, refs.aiDailyTableBody]
        .forEach((el) => { if (el) el.classList.toggle('is-refreshing', !!on); });
}

// --- AI Costs date filter --------------------------------------------------
// Dates are handled as plain YYYY-MM-DD strings in UTC, matching the usage ledger's
// created_at (the table header says UTC), so a preset never shifts by the viewer's
// timezone the way toISOString() on a local-midnight Date would.
function aiUtcToday() {
    const now = new Date();
    return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
}

function aiDateToIso(d) {
    return d.toISOString().slice(0, 10);
}

function aiShiftDays(d, days) {
    const copy = new Date(d.getTime());
    copy.setUTCDate(copy.getUTCDate() + days);
    return copy;
}

function aiPresetRange(preset) {
    const today = aiUtcToday();
    switch (preset) {
        case 'today':
            return { start: aiDateToIso(today), end: aiDateToIso(today) };
        case '7d':
            return { start: aiDateToIso(aiShiftDays(today, -6)), end: aiDateToIso(today) };
        case '90d':
            return { start: aiDateToIso(aiShiftDays(today, -89)), end: aiDateToIso(today) };
        case 'month': {
            const first = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), 1));
            return { start: aiDateToIso(first), end: aiDateToIso(today) };
        }
        case 'prev_month': {
            const first = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth() - 1, 1));
            const last = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), 0));
            return { start: aiDateToIso(first), end: aiDateToIso(last) };
        }
        case 'all': {
            // Falls back to a wide window until the first payload tells us the real start.
            const earliest = (state.aiUsageData && state.aiUsageData.earliest_event_date) || null;
            return { start: earliest || aiDateToIso(aiShiftDays(today, -730)), end: aiDateToIso(today) };
        }
        case '30d':
        default:
            return { start: aiDateToIso(aiShiftDays(today, -29)), end: aiDateToIso(today) };
    }
}

function initAiRangeInputs() {
    if (!refs.aiRangeStart && !refs.aiRangeEnd) return;
    const today = aiDateToIso(aiUtcToday());
    const preset = aiPresetRange(state.aiRange.preset);
    if (refs.aiRangeStart) { refs.aiRangeStart.value = preset.start; refs.aiRangeStart.max = today; }
    if (refs.aiRangeEnd) { refs.aiRangeEnd.value = preset.end; refs.aiRangeEnd.max = today; }
    syncAiPresetButtons();
}

function setAiRangeError(message) {
    if (!refs.aiRangeError) return;
    refs.aiRangeError.textContent = message || '';
    refs.aiRangeError.hidden = !message;
}

function syncAiPresetButtons() {
    if (!refs.aiRangePresets) return;
    refs.aiRangePresets.querySelectorAll('.ai-preset-btn').forEach((btn) => {
        btn.classList.toggle('is-active', btn.dataset.preset === state.aiRange.preset);
    });
}

function applyAiPreset(preset) {
    const range = aiPresetRange(preset);
    state.aiRange = { preset, start: range.start, end: range.end };
    if (refs.aiRangeStart) refs.aiRangeStart.value = range.start;
    if (refs.aiRangeEnd) refs.aiRangeEnd.value = range.end;
    syncAiPresetButtons();
    setAiRangeError('');
    void loadAiUsage({ chartsOnly: true });
}

function handleAiRangeSubmit(event) {
    event.preventDefault();
    const start = (refs.aiRangeStart?.value || '').trim();
    const end = (refs.aiRangeEnd?.value || '').trim();
    if (!start || !end) { setAiRangeError('Pick both a From and a To date.'); return; }
    if (start > end) { setAiRangeError('The From date must be on or before the To date.'); return; }
    setAiRangeError('');
    state.aiRange = { preset: 'custom', start, end };
    syncAiPresetButtons();
    void loadAiUsage({ chartsOnly: true });
}

function resetAiRange() {
    applyAiPreset('30d');
}

async function loadAiUsage(options = {}) {
    const chartsOnly = !!options.chartsOnly;   // a filter change shouldn't refetch revenue panels
    if (!state.currentUser) {
        const canAccess = await refreshCurrentAdminUser({ silent: true });
        if (!canAccess) { showAuth(); showFlash('Please login with an admin account.', 'error'); return; }
    }
    if (!await ensureAdminProtection({ silent: false })) return;
    // Refetch keeps the frame: hold the previous render at reduced opacity rather than
    // blanking to a skeleton, so changing the date range doesn't jump the layout.
    if (state.aiUsageData) setAiRefreshing(true); else aiUsageEmptyState('Loading AI usage...');
    try {
        const params = new URLSearchParams();
        if (state.aiRange.start) params.set('start', state.aiRange.start);
        if (state.aiRange.end) params.set('end', state.aiRange.end);
        const query = params.toString();
        const response = await fetch(`${API_BASE}/api/admin/ai-usage/analytics${query ? `?${query}` : ''}`, {
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            const message = normalizeErrorMessage(payload, 'Failed to load AI usage.');
            aiUsageEmptyState(message);
            await handleAdminAuthOrProtectionError(response.status, payload);
            showFlash(message, 'error');
            return;
        }
        renderAiUsage(payload);
        clearFlash();
    } catch (error) {
        console.error('Failed to load AI usage:', error);
        aiUsageEmptyState('Could not load AI usage. Please retry.');
        showFlash('Could not load AI usage. Please retry.', 'error');
    } finally {
        setAiRefreshing(false);
    }
    if (chartsOnly) return;
    await loadEnterpriseRevenue();
    await loadB2cRevenue();
    await loadOptimization();
}

async function loadB2cRevenue() {
    try {
        const response = await fetch(`${API_BASE}/api/admin/b2c/revenue`, { headers: buildAuthHeaders(), credentials: 'same-origin' });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) { await handleAdminAuthOrProtectionError(response.status, payload); return; }
        renderB2cRevenue(payload);
    } catch (error) { console.error('Failed to load B2C revenue:', error); }
}

async function loadAcquisitionBreakdown() {
    const el = document.getElementById('adminAcquisitionBreakdown');
    const metaEl = document.getElementById('adminAcquisitionMeta');
    if (!el) return;
    try {
        const response = await fetch(`${API_BASE}/api/admin/acquisition/analytics`, { headers: buildAuthHeaders(), credentials: 'same-origin' });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) { el.innerHTML = '<div class="table-empty">Could not load traffic sources.</div>'; return; }
        const channels = (data && data.channels) || [];
        if (!channels.length) { el.innerHTML = '<div class="table-empty">No signups yet.</div>'; return; }
        const maxCount = Math.max.apply(null, channels.map((c) => c.count).concat(1));
        if (metaEl) metaEl.textContent = `${data.tracked_total} tracked · +${data.new_last_30d} in 30d`;
        const channelsHtml = channels.map((c) => {
            const pct = Math.round((c.count / maxCount) * 100);
            const recent = c.last_30d ? ` · +${c.last_30d} (30d)` : '';
            return `<div class="finance-breakdown-row">
                <div class="finance-breakdown-top">
                    <strong><span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${c.color};margin-right:7px;vertical-align:middle;"></span>${escapeHtml(c.label)}</strong>
                    <span>${c.count}${recent}</span>
                </div>
                <div class="finance-breakdown-track"><span style="width:${pct}%;background:${c.color};"></span></div>
                <div class="finance-breakdown-percent">${c.percent}% of all signups</div>
            </div>`;
        }).join('');
        // Self-reported "How did you hear about us?" (asked once post-signup).
        const sr = (data && data.self_reported) || [];
        let srHtml = '';
        if (sr.length) {
            srHtml = `<div style="margin-top:18px;padding-top:14px;border-top:1px solid var(--border-color,#e2e8f0);">
                <div style="font-size:11px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;color:#94a3b8;margin-bottom:12px;">How they heard — self-reported (${data.self_reported_total})</div>`
                + sr.map((s) => `<div class="finance-breakdown-row">
                    <div class="finance-breakdown-top"><strong>${escapeHtml(s.label)}</strong><span>${s.count}</span></div>
                    <div class="finance-breakdown-track"><span style="width:${s.percent}%;background:#6366f1;"></span></div>
                    <div class="finance-breakdown-percent">${s.percent}% of self-reported</div>
                </div>`).join('')
                + `</div>`;
        }
        el.innerHTML = channelsHtml + srHtml;
    } catch (error) {
        console.error('Failed to load acquisition breakdown:', error);
        el.innerHTML = '<div class="table-empty">Could not load traffic sources.</div>';
    }
}

// ---- Internal Conversion Agent (which free accounts to pitch the Pass to, and how) ----
const GROWTH_INTENT_STYLE = {
    high: { bg: 'rgba(16,185,129,.14)', fg: '#047857', label: 'HIGH' },
    medium: { bg: 'rgba(245,158,11,.16)', fg: '#b45309', label: 'MED' },
    low: { bg: 'rgba(148,163,184,.18)', fg: '#475569', label: 'LOW' },
};

function renderGrowthRecommendations(data) {
    const el = document.getElementById('adminGrowthResults');
    const metaEl = document.getElementById('adminGrowthMeta');
    const recs = (data && data.recommendations) || [];
    if (metaEl) {
        const via = data.ai_used ? 'Rilono AI' : 'rule-based (AI unavailable)';
        metaEl.textContent = `${data.analyzed_count} of ${data.total_free_accounts} free accounts · strategy via ${via}`;
    }
    if (!recs.length) {
        el.innerHTML = '<div class="table-empty">No free accounts to target right now.</div>';
        return;
    }
    el.innerHTML = recs.map((r) => {
        const a = r.account || {};
        const st = GROWTH_INTENT_STYLE[r.intent] || GROWTH_INTENT_STYLE.low;
        const limitChip = a.hit_any_limit
            ? '<span style="font-size:10.5px;font-weight:800;color:#b91c1c;background:rgba(239,68,68,.1);padding:1px 7px;border-radius:999px;">HIT A LIMIT</span>' : '';
        const lastSeen = a.days_since_last_login == null ? 'never logged in'
            : (a.days_since_last_login === 0 ? 'active today' : `${a.days_since_last_login}d since login`);
        const u = a.usage_detail || {};
        const usage = `AI ${u.ai_messages || '-'} · Mock ${u.mock_interviews || '-'} · Uploads ${u.document_uploads || '-'} · Prep ${u.prep_sessions || '-'}`;
        const msg = r.suggested_message
            ? `<div style="margin-top:8px;background:#f8fafc;border:1px solid var(--border-color,#e7e9f3);border-left:3px solid #7c3aed;border-radius:8px;padding:9px 12px;font-size:13px;color:#0f172a;">
                 “${escapeHtml(r.suggested_message)}”
                 <button type="button" class="ghost-btn small-btn" style="margin-left:8px;padding:2px 10px;font-size:11px;" data-copy="${escapeHtml(r.suggested_message)}">Copy</button>
               </div>` : '';
        return `<div style="border:1px solid var(--border-color,#e7e9f3);border-radius:12px;padding:13px 15px;margin-bottom:10px;background:#fff;">
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
                <span style="font-size:11px;font-weight:900;color:#fff;background:#7c3aed;border-radius:8px;min-width:34px;text-align:center;padding:3px 7px;">${r.priority}</span>
                <strong style="font-size:14.5px;">${escapeHtml(a.name || 'Student')}</strong>
                <span style="font-size:12px;color:#64748b;">${escapeHtml(a.email || '')}</span>
                <span style="font-size:10.5px;font-weight:800;color:${st.fg};background:${st.bg};padding:2px 8px;border-radius:999px;">${st.label} INTENT · ${a.intent_score}</span>
                ${limitChip}
                <span style="margin-left:auto;font-size:12px;color:#94a3b8;">${escapeHtml(lastSeen)}</span>
            </div>
            <div style="margin-top:8px;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;">
                <span style="font-size:12.5px;font-weight:800;color:#6d28d9;">${escapeHtml(r.promotion_label || r.recommended_promotion)}</span>
                <span style="font-size:12px;color:#475569;">— ${escapeHtml(r.segment || '')}</span>
                <span style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.03em;">via ${escapeHtml(r.channel || 'email')}</span>
            </div>
            <div style="margin-top:4px;font-size:12.5px;color:#64748b;">${escapeHtml(r.reason || '')}</div>
            <div style="margin-top:6px;font-size:11.5px;color:#94a3b8;">${escapeHtml(usage)}${a.destination ? ' · ' + escapeHtml(a.destination) : ''}</div>
            ${msg}
        </div>`;
    }).join('');
    el.querySelectorAll('button[data-copy]').forEach((btn) => {
        btn.addEventListener('click', () => {
            try { navigator.clipboard.writeText(btn.getAttribute('data-copy') || ''); btn.textContent = 'Copied'; setTimeout(() => { btn.textContent = 'Copy'; }, 1500); } catch (e) {}
        });
    });
}

async function runGrowthAnalysis() {
    const btn = document.getElementById('adminGrowthRunBtn');
    const el = document.getElementById('adminGrowthResults');
    if (!el) return;
    if (btn) { btn.disabled = true; btn.textContent = 'Analyzing…'; }
    el.innerHTML = '<div class="table-empty">The agent is scoring accounts and drafting conversion plays… this can take a few seconds.</div>';
    try {
        const response = await fetch(`${API_BASE}/api/admin/growth/conversion-analysis?limit=30`, {
            method: 'POST', headers: buildAuthHeaders(), credentials: 'same-origin',
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            el.innerHTML = `<div class="table-empty">${escapeHtml((data && data.detail) || 'Could not run the analysis.')}</div>`;
            return;
        }
        renderGrowthRecommendations(data);
    } catch (error) {
        console.error('Growth analysis failed:', error);
        el.innerHTML = '<div class="table-empty">Could not run the analysis.</div>';
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Run analysis'; }
    }
}

/* ===================== Activation funnel + approval rate ===================== */
async function loadGrowthInsights() {
    const funnelEl = document.getElementById('adminFunnelBody');
    const outcomesEl = document.getElementById('adminOutcomesBody');
    if (!funnelEl && !outcomesEl) return;
    try {
        const [fRes, oRes] = await Promise.all([
            fetch(`${API_BASE}/api/admin/growth/funnel`, { headers: buildAuthHeaders(), credentials: 'same-origin' }),
            fetch(`${API_BASE}/api/admin/growth/outcomes`, { headers: buildAuthHeaders(), credentials: 'same-origin' }),
        ]);
        if (fRes.ok) { renderFunnel(await fRes.json().catch(() => ({}))); }
        else if (funnelEl) { funnelEl.innerHTML = '<div class="table-empty">Could not load the funnel.</div>'; }
        if (oRes.ok) { renderOutcomes(await oRes.json().catch(() => ({}))); }
        else if (outcomesEl) { outcomesEl.innerHTML = '<div class="table-empty">Could not load approval data.</div>'; }
    } catch (error) {
        console.error('Growth insights failed:', error);
        if (funnelEl) funnelEl.innerHTML = '<div class="table-empty">Could not load insights.</div>';
    }
}

function renderFunnel(data) {
    const el = document.getElementById('adminFunnelBody');
    if (!el) return;
    const stages = (data && data.stages) || [];
    if (!stages.length) { el.innerHTML = '<div class="table-empty">No students yet.</div>'; return; }
    const max = Math.max(1, ...stages.map((s) => s.users || 0));
    const kc = (data && data.key_conversions) || {};
    const bars = stages.map((s) => {
        const w = Math.max(2, Math.round(((s.users || 0) / max) * 100));
        const pct = s.pct_of_signups != null ? `${s.pct_of_signups}%` : '—';
        return `<div class="funnel-row">
            <div class="funnel-row-top"><span>${escapeHtml(s.label)}</span><span><strong>${(s.users || 0).toLocaleString()}</strong> · ${pct}</span></div>
            <div class="funnel-bar"><span style="width:${w}%"></span></div></div>`;
    }).join('');
    const conv = (label, v) => `<span class="acct-chip grey">${label}: <strong>${v != null ? v + '%' : '—'}</strong></span>`;
    el.innerHTML = `${bars}
        <div class="funnel-conv">
            ${conv('activated→scan', kc.activated_to_scan)}
            ${conv('scan→purchase', kc.scan_to_purchase)}
            ${conv('signup→purchase', kc.overall_signup_to_purchase)}
        </div>
        ${data.biggest_leak ? `<div class="funnel-leak">⚠️ Biggest drop-off: <strong>${escapeHtml(data.biggest_leak)}</strong></div>` : ''}`;
}

function renderOutcomes(data) {
    const el = document.getElementById('adminOutcomesBody');
    if (!el) return;
    const overall = (data && data.overall) || {};
    const scan = (data && data.red_flag_scan_users) || {};
    const noscan = (data && data.non_red_flag_scan_users) || {};
    const base = (data && data.market_baseline) || {};
    if (!overall.total_recorded) {
        el.innerHTML = '<div class="table-empty">No visa decisions recorded yet. Students report these from their dashboard once they finish interview prep.</div>';
        return;
    }
    const rate = (v) => (v != null ? `${v}%` : '—');
    const lift = data.red_flag_lift_pts;
    el.innerHTML = `
        <div class="outcome-hero">
            <div class="outcome-hero-num">${rate(scan.approval_rate)}</div>
            <div class="outcome-hero-cap">approval rate for <strong>red-flag-scan users</strong><br>
                <span style="color:#94a3b8">${scan.decided_on_merits || 0} decisions · vs ~${base.low}–${base.high}% market baseline</span></div>
        </div>
        <div class="outcome-compare">
            <div><span>Red-flag users</span><strong style="color:#047857">${rate(scan.approval_rate)}</strong><small>${scan.approved || 0}/${scan.decided_on_merits || 0}</small></div>
            <div><span>Did not scan</span><strong>${rate(noscan.approval_rate)}</strong><small>${noscan.approved || 0}/${noscan.decided_on_merits || 0}</small></div>
            <div><span>Overall</span><strong>${rate(overall.approval_rate)}</strong><small>${overall.approved || 0}/${overall.decided_on_merits || 0}</small></div>
        </div>
        ${lift != null ? `<div class="funnel-conv"><span class="acct-chip ${lift >= 0 ? 'green' : 'amber'}">Red-flag lift: <strong>${lift >= 0 ? '+' : ''}${lift} pts</strong></span></div>` : ''}
        ${data.sample_is_thin ? '<div class="funnel-leak">⚠️ Small sample — don’t quote this rate publicly until more decisions are in.</div>' : ''}`;
}

/* ===================== Account "Manage" full-screen view ===================== */
function acctFmt(dt) { return dt ? formatDateTime(dt) : '—'; }
// `minor` is in the row's OWN currency, so the currency has to travel with it — the old
// acctInr() printed "₹12.99" for a $12.99 charge.
function acctMoney(minor, currency) { return (minor == null) ? '—' : formatMinor(minor, currency); }

async function openAccountDetail(userId) {
    const overlay = document.getElementById('adminAccountDetail');
    const body = document.getElementById('adminAccountBody');
    const title = document.getElementById('adminAccountTitle');
    if (!overlay || !body) return;
    overlay.hidden = false;
    document.body.style.overflow = 'hidden';
    if (title) title.textContent = 'Account';
    document.getElementById('adminAccountActions').innerHTML = '';
    body.innerHTML = '<div class="table-empty">Loading account…</div>';
    try {
        const response = await fetch(`${API_BASE}/api/admin/users/${userId}/detail`, {
            headers: buildAuthHeaders(), credentials: 'same-origin',
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            body.innerHTML = `<div class="table-empty">${escapeHtml((data && data.detail) || 'Could not load this account.')}</div>`;
            return;
        }
        renderAccountDetail(userId, data);
    } catch (error) {
        console.error('Account detail failed:', error);
        body.innerHTML = '<div class="table-empty">Could not load this account.</div>';
    }
}

function closeAccountDetail() {
    const overlay = document.getElementById('adminAccountDetail');
    if (overlay) overlay.hidden = true;
    document.body.style.overflow = '';
}

function renderAccountDetail(userId, data) {
    const a = data.account || {}, sub = data.subscription || {}, intent = data.intent || {};
    const title = document.getElementById('adminAccountTitle');
    if (title) title.textContent = `${a.name || 'Account'} · ${a.email || ''}`;

    // Top-bar actions mirror the old row buttons; only shown when this admin can manage the target.
    const active = a.is_active;
    const isSelf = Number(userId) === Number(state.currentUser && state.currentUser.id);
    const canManage = !isSelf && ((a.role === 'student') || (state.currentUser && state.currentUser.is_developer));
    document.getElementById('adminAccountActions').innerHTML = canManage
        ? `<button class="table-btn" id="acctToggleBtn">${active ? 'Deactivate' : 'Activate'}</button>
           <button class="table-btn danger" id="acctDeleteBtn">Delete</button>`
        : '<span class="acct-chip grey">View only</span>';

    let lastUsageGroup = null;
    const usageHtml = (sub.usage || []).map((u) => {
        // Effective limit: pass holders get u.pass_limit (-1 = unlimited), free accounts get
        // u.free_limit. Pass features can still be capped (e.g. voice interviews: 3 per pass).
        const lim = sub.is_pass_active ? (u.pass_limit === undefined ? -1 : u.pass_limit) : u.free_limit;
        const unlimited = lim < 0;
        const pct = lim > 0 ? Math.min(100, Math.round((u.used / lim) * 100)) : (u.used > 0 ? 100 : 0);
        const full = !unlimited && lim > 0 && u.used >= lim;
        const limLabel = unlimited ? '∞' : (lim > 0 ? lim : '—');
        let header = '';
        if (u.group && u.group !== lastUsageGroup) {
            lastUsageGroup = u.group;
            const tag = u.group === 'Visa Success Pass features' ? ' <span class="acct-chip purple">web app</span>' : '';
            header = `<div class="acct-usage-group">${escapeHtml(u.group)}${tag}</div>`;
        }
        return `${header}<div><div class="acct-usage-row"><span>${escapeHtml(u.label)}</span><span>${u.used} / ${limLabel}</span></div>
            <div class="acct-usage-bar"><span class="${full ? 'full' : ''}" style="width:${unlimited ? 100 : pct}%"></span></div></div>`;
    }).join('');
    const planChip = sub.is_pass_active
        ? `<span class="acct-chip green">Visa Success Pass · active${sub.pass_days_left != null ? ` (${sub.pass_days_left}d left)` : ''}</span>`
        : '<span class="acct-chip grey">Free plan</span>';

    const couponsHtml = (data.coupons || []).length
        ? data.coupons.map((c) => `<div class="acct-line">
            <span><strong>${escapeHtml(c.code)}</strong>${c.percent_off ? ` · ${c.percent_off}% off` : ''} <span class="acct-chip ${c.status === 'verified' ? 'green' : 'grey'}">${escapeHtml(c.status)}</span> <span style="color:#94a3b8">on ${escapeHtml(c.on)}</span></span>
            <span style="color:#64748b">${escapeHtml(acctFmt(c.applied_at))}</span></div>`).join('')
        : '<div class="acct-empty">No coupon codes applied on this account.</div>';

    // Show the charged amount in the currency it was charged in, plus Razorpay's INR
    // settlement for a foreign card — the two are different numbers and both matter.
    const paymentsHtml = (data.payments || []).length
        ? data.payments.map((p) => `<div class="acct-line">
            <span>${escapeHtml(p.amount_display || acctMoney(p.amount_paise, p.currency))} <span class="acct-chip ${p.status === 'verified' ? 'green' : (p.status === 'failed' ? 'amber' : 'grey')}">${escapeHtml(p.status)}</span>${p.is_international ? '<span class="acct-chip purple">international</span>' : ''}${p.settled_inr_display ? ` · settled ${escapeHtml(p.settled_inr_display)}` : ''}${p.coupon_code ? ` · coupon <strong>${escapeHtml(p.coupon_code)}</strong>` : ''}</span>
            <span style="color:#64748b">${escapeHtml(acctFmt(p.verified_at || p.created_at))}</span></div>`).join('')
        : '<div class="acct-empty">No payments yet.</div>';

    const acq = a.acquisition || {}, ref = a.referral || {}, vd = a.visa_decision || {};
    const vdChipClass = { approved: 'green', refused: 'amber', withdrawn: 'grey', deferred: 'grey' }[vd.decision] || 'grey';

    // Coupon codes issued FOR this account (per-account "conversion play" offers).
    const offers = data.coupon_offers || [];
    const offersHtml = offers.length
        ? offers.map((c) => `<div class="acct-line">
            <span><strong>${escapeHtml(c.code)}</strong> · ${c.percent_off}% off
              · used ${c.verified_uses}${c.max_uses_per_user != null ? ` / ${c.max_uses_per_user}` : ' (no cap)'}
            </span>
            <span style="display:inline-flex;align-items:center;gap:8px;color:#64748b">${c.created_at ? escapeHtml(acctFmt(c.created_at)) : ''}
              <button type="button" class="table-btn danger" data-coupon-delete="${escapeHtml(c.code)}">Delete</button></span>
          </div>`).join('')
        : '<div class="acct-empty">No coupon codes issued for this account yet.</div>';
    const suggestedCode = `${String((a.name || 'SAVE').split(' ')[0] || 'SAVE').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 12) || 'SAVE'}20`;

    document.getElementById('adminAccountBody').innerHTML = `
      <div class="acct-grid">
        <div style="display:grid;gap:16px">
          <div class="acct-card"><h3>Profile</h3>
            <dl class="acct-kv">
              <dt>Status</dt><dd>${active ? '<span class="acct-chip green">Active</span>' : '<span class="acct-chip grey">Inactive</span>'} ${a.email_verified ? '<span class="acct-chip green">Verified</span>' : '<span class="acct-chip amber">Unverified</span>'}</dd>
              <dt>Role</dt><dd>${escapeHtml(a.role || 'student')}</dd>
              <dt>Sign-in</dt><dd>${escapeHtml(a.auth_provider || 'password')}</dd>
              <dt>Destination</dt><dd>${escapeHtml(a.country_name || '—')}${a.visa_type_label ? ' · ' + escapeHtml(a.visa_type_label) : ''}</dd>
              <dt>University</dt><dd>${escapeHtml(a.university || '—')}</dd>
              <dt>Home country</dt><dd>${escapeHtml(a.home_country || '—')}</dd>
              <dt>Created</dt><dd>${escapeHtml(acctFmt(a.created_at))}</dd>
              <dt>Last login</dt><dd>${escapeHtml(acctFmt(a.last_login_at))}</dd>
              <dt>Onboarded</dt><dd>${a.onboarding_completed_at ? escapeHtml(acctFmt(a.onboarding_completed_at)) : 'Not completed'}</dd>
              <dt>Marketing opt-in</dt><dd>${a.marketing_consent ? 'Yes' : 'No'}</dd>
            </dl>
          </div>
          <div class="acct-card"><h3>Plan &amp; usage &nbsp; ${planChip}</h3>${usageHtml || '<div class="acct-empty">No subscription record.</div>'}</div>
          <div class="acct-card"><h3>Coupons applied &amp; when</h3>${couponsHtml}</div>
          <div class="acct-card"><h3>Payments</h3>${paymentsHtml}</div>
        </div>
        <div style="display:grid;gap:16px">
          <div class="acct-card acct-reco-card"><h3>🎯 Rilono AI — Conversion play</h3>
            <div id="acctRecoBody">
              <p style="font-size:13px;color:#64748b;margin:0 0 10px">Intent score <strong>${intent.score != null ? intent.score : '—'}</strong>${intent.hit_any_limit ? ' · <span class="acct-chip amber">hit a free limit</span>' : ''}. Run the agent for a tailored coupon/promotion + outreach message for this account.</p>
              <button class="primary-btn small-btn" id="acctRecoBtn">Get AI recommendation</button>
            </div>
          </div>
          <div class="acct-card"><h3>Coupon codes for this account</h3>
            <p style="font-size:12px;color:#94a3b8;margin:0 0 10px">Only this account can redeem these codes — at the
              Visa Success Pass checkout. Deleting a code stops future use; past payments keep their discount.</p>
            <div id="acctCouponList">${offersHtml}</div>
            <form id="acctCouponForm" class="coupon-form" style="margin-top:12px">
              <div class="coupon-form-grid">
                <label class="coupon-field">
                  <span>Code</span>
                  <input type="text" id="acctCouponCode" placeholder="${escapeHtml(suggestedCode)}" maxlength="32" autocomplete="off">
                </label>
                <label class="coupon-field coupon-field-narrow">
                  <span>% off</span>
                  <input type="number" id="acctCouponPct" placeholder="20" min="1" max="100" step="0.01">
                </label>
                <label class="coupon-field coupon-field-narrow">
                  <span>Max uses</span>
                  <input type="number" id="acctCouponMax" value="1" min="1" step="1">
                </label>
              </div>
              <button type="submit" class="primary-btn small-btn" id="acctCouponCreateBtn">Create coupon</button>
            </form>
          </div>
          <div class="acct-card"><h3>Visa decision (outcome)</h3>
            <div id="acctDecisionBody">
              <div style="margin-bottom:8px">${vd.decision
                ? `<span class="acct-chip ${vdChipClass}">${escapeHtml(String(vd.decision).toUpperCase())}</span> <span style="color:#94a3b8;font-size:12px">${vd.decision_at ? acctFmt(vd.decision_at) : ''}${vd.source ? ' · ' + escapeHtml(vd.source) : ''}</span>`
                : '<span class="acct-empty">No decision recorded yet.</span>'}</div>
              <div class="acct-decision-set">
                <button type="button" class="table-btn" data-decision="approved">Approved</button>
                <button type="button" class="table-btn" data-decision="refused">Refused</button>
                <button type="button" class="table-btn" data-decision="withdrawn">Withdrawn</button>
                <button type="button" class="table-btn" data-decision="deferred">Deferred</button>
                ${vd.decision ? '<button type="button" class="table-btn danger" data-decision="clear">Clear</button>' : ''}
              </div>
            </div>
          </div>
          <div class="acct-card"><h3>Acquisition</h3>
            <dl class="acct-kv">
              <dt>Channel</dt><dd>${escapeHtml(acq.channel || 'untracked')}</dd>
              <dt>Source</dt><dd>${escapeHtml(acq.source || '—')}</dd>
              <dt>Campaign</dt><dd>${escapeHtml(acq.campaign || '—')}</dd>
              <dt>Landing page</dt><dd>${escapeHtml(acq.landing_page || '—')}</dd>
              <dt>Heard about us</dt><dd>${escapeHtml(a.heard_about_label || '—')}</dd>
            </dl>
          </div>
          <div class="acct-card"><h3>Referral</h3>
            <dl class="acct-kv">
              <dt>Their code</dt><dd>${escapeHtml(ref.code || '—')}</dd>
              <dt>Referred by</dt><dd>${ref.referred_by ? escapeHtml(ref.referred_by.email) : '—'}</dd>
              <dt>Referrals made</dt><dd>${ref.referrals_made || 0}</dd>
              <dt>Reward granted</dt><dd>${ref.reward_granted_at ? escapeHtml(acctFmt(ref.reward_granted_at)) : '—'}</dd>
            </dl>
          </div>
        </div>
      </div>`;

    const recoBtn = document.getElementById('acctRecoBtn');
    if (recoBtn) recoBtn.addEventListener('click', () => runAccountReco(userId));
    const toggleBtn = document.getElementById('acctToggleBtn');
    if (toggleBtn) toggleBtn.addEventListener('click', async () => { const ok = await updateUserStatus(userId, !active, a.email || a.name || ''); if (ok) closeAccountDetail(); });
    const delBtn = document.getElementById('acctDeleteBtn');
    if (delBtn) delBtn.addEventListener('click', async () => { await deleteUser(userId, a.email || 'this user', a.name || ''); closeAccountDetail(); });
    document.querySelectorAll('#acctDecisionBody .acct-decision-set button').forEach((btn) => {
        btn.addEventListener('click', () => setAccountVisaDecision(userId, btn.getAttribute('data-decision')));
    });
    const couponForm = document.getElementById('acctCouponForm');
    if (couponForm) couponForm.addEventListener('submit', (e) => { e.preventDefault(); void createAccountCoupon(userId); });
    wireCouponPercentClamp(document.getElementById('acctCouponPct'));
    document.querySelectorAll('#acctCouponList [data-coupon-delete]').forEach((btn) => {
        btn.addEventListener('click', () => deleteAccountCoupon(userId, btn.getAttribute('data-coupon-delete')));
    });
}

// Create a coupon code restricted to this account (the actionable half of the
// growth agent's "offer them a tailored coupon" recommendation).
async function createAccountCoupon(userId) {
    if (!await ensureAdminProtection({ silent: false })) return;
    const codeInput = document.getElementById('acctCouponCode');
    const pctInput = document.getElementById('acctCouponPct');
    const maxInput = document.getElementById('acctCouponMax');
    const createBtn = document.getElementById('acctCouponCreateBtn');

    const code = String(codeInput?.value || '').trim().toUpperCase();
    const pctRaw = String(pctInput?.value || '').trim();
    const maxRaw = String(maxInput?.value || '').trim();
    const maxUses = maxRaw === '' ? null : Number(maxRaw);
    if (!code) { showFlash('Enter a coupon code (e.g. HENRY20).', 'error'); codeInput?.focus(); return; }
    if (pctRaw === '' || !Number.isFinite(Number(pctRaw))) { showFlash('Enter a discount between 1 and 100 percent.', 'error'); pctInput?.focus(); return; }
    const pct = clampCouponPercent(Number(pctRaw));
    if (maxUses !== null && (!Number.isInteger(maxUses) || maxUses < 1)) { showFlash('Max uses must be a whole number of at least 1 (or empty for unlimited).', 'error'); maxInput?.focus(); return; }

    if (createBtn) { createBtn.disabled = true; createBtn.textContent = 'Creating…'; }
    try {
        const response = await fetch(`${API_BASE}/api/admin/coupons`, {
            method: 'POST',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            credentials: 'same-origin',
            body: JSON.stringify({ code, percent_off: pct, max_uses_per_user: maxUses, restricted_to_user_id: userId }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            await handleAdminAuthOrProtectionError(response.status, payload);
            showFlash(normalizeErrorMessage(payload, 'Failed to create the coupon.'), 'error');
            return;
        }
        showFlash(`Coupon ${code} created for this account.`, 'success');
        await openAccountDetail(userId);
    } catch (error) {
        console.error('Create coupon failed:', error);
        showFlash('Failed to create the coupon.', 'error');
    } finally {
        if (createBtn) { createBtn.disabled = false; createBtn.textContent = 'Create coupon'; }
    }
}

async function deleteAccountCoupon(userId, code) {
    if (!await ensureAdminProtection({ silent: false })) return;
    if (!(await confirmDialog(`Students will no longer be able to apply "${code}". Past payments keep their discount.`, { title: 'Delete coupon?', okText: 'Delete' }))) return;
    try {
        const response = await fetch(`${API_BASE}/api/admin/coupons/${encodeURIComponent(code)}`, {
            method: 'DELETE',
            headers: buildAuthHeaders(),
            credentials: 'same-origin',
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            await handleAdminAuthOrProtectionError(response.status, payload);
            showFlash(normalizeErrorMessage(payload, 'Failed to delete the coupon.'), 'error');
            return;
        }
        showFlash(`Coupon ${code} deleted.`, 'success');
        await openAccountDetail(userId);
    } catch (error) {
        console.error('Delete coupon failed:', error);
        showFlash('Failed to delete the coupon.', 'error');
    }
}

async function setAccountVisaDecision(userId, decision) {
    const body = document.getElementById('acctDecisionBody');
    if (!body) return;
    try {
        const response = await fetch(`${API_BASE}/api/admin/users/${userId}/visa-decision`, {
            method: 'POST', headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            credentials: 'same-origin', body: JSON.stringify({ decision }),
        });
        if (!response.ok) { showFlash('Could not update the decision.', 'error'); return; }
        // Re-open the detail so the whole view (incl. approval analytics upstream) reflects the change.
        openAccountDetail(userId);
    } catch (error) {
        console.error('Set visa decision failed:', error);
        showFlash('Could not update the decision.', 'error');
    }
}

async function runAccountReco(userId) {
    const body = document.getElementById('acctRecoBody');
    if (!body) return;
    body.innerHTML = '<div class="acct-empty">Rilono AI is analyzing this account and drafting a play…</div>';
    try {
        const response = await fetch(`${API_BASE}/api/admin/users/${userId}/conversion-reco`, {
            method: 'POST', headers: buildAuthHeaders(), credentials: 'same-origin',
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            body.innerHTML = `<div class="acct-empty">${escapeHtml((data && data.detail) || 'Could not generate a recommendation.')}</div>`;
            return;
        }
        const reco = data.recommendation || {};
        const intentClass = reco.intent === 'high' ? 'green' : (reco.intent === 'medium' ? 'amber' : 'grey');
        const via = data.ai_used ? 'Rilono AI' : 'rule-based fallback';
        body.innerHTML = `
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px">
            <span class="acct-chip ${intentClass}">${escapeHtml(String(reco.intent || '').toUpperCase())} INTENT</span>
            <span class="acct-chip purple">${escapeHtml(reco.promotion_label || reco.recommended_promotion || '')}</span>
            ${data.is_pass_active ? '<span class="acct-chip green">Already on Pass</span>' : ''}
            <span style="margin-left:auto;font-size:11px;color:#94a3b8">via ${via}</span>
          </div>
          <div style="font-size:12.5px;color:#475569"><strong>${escapeHtml(reco.segment || '')}</strong>${reco.reason ? ' — ' + escapeHtml(reco.reason) : ''}</div>
          ${reco.suggested_message ? `<div class="acct-reco-msg">“${escapeHtml(reco.suggested_message)}”
             <button type="button" class="ghost-btn small-btn" style="margin-left:8px;padding:2px 10px;font-size:11px" id="acctRecoCopy">Copy</button></div>` : ''}
          <div style="margin-top:10px;display:flex;gap:8px;align-items:center">
            ${reco.channel ? `<span class="acct-chip grey">channel: ${escapeHtml(reco.channel)}</span>` : ''}
            <button class="ghost-btn small-btn" id="acctRecoRerun" style="margin-left:auto">Re-run</button>
          </div>`;
        const copyBtn = document.getElementById('acctRecoCopy');
        if (copyBtn) copyBtn.addEventListener('click', function () {
            try { navigator.clipboard.writeText(reco.suggested_message || ''); this.textContent = 'Copied'; } catch (e) { /* clipboard unavailable */ }
        });
        const rerun = document.getElementById('acctRecoRerun');
        if (rerun) rerun.addEventListener('click', () => runAccountReco(userId));
    } catch (error) {
        console.error('Account reco failed:', error);
        body.innerHTML = '<div class="acct-empty">Could not generate a recommendation.</div>';
    }
}

function renderB2cRevenue(data) {
    const s = (data && data.summary) || {};
    // This book is denominated in the currency the server reports (payments are booked at
    // their INR settlement, then compared against Gemini cost in the same currency). The
    // zero fallbacks follow that currency instead of hardcoding a rupee sign.
    const bookCurrency = (data && data.currency) || 'INR';
    const setText = (el, v) => { if (el) el.textContent = v; };
    setText(refs.b2cMarginHero, moneyOr(s.gross_margin_display, bookCurrency));
    setText(refs.b2cRevenue, moneyOr(s.revenue_display, bookCurrency));
    // build_revenue_analytics EXCLUDES foreign passes with no INR settlement figure rather
    // than adding their cents as paise, so revenue is a known understatement while any
    // exist. Say so next to the number instead of letting it read as complete.
    const b2cUnsettled = Number(s.unsettled_payments || 0);
    setText(refs.b2cRevenueSub, `${(s.passes_sold || 0).toLocaleString()} passes sold`
        + (b2cUnsettled > 0 ? ` · ${b2cUnsettled} not counted (awaiting INR settlement)` : ''));
    setText(refs.b2cActive, (s.active_passes || 0).toLocaleString());
    setText(refs.b2cCost, moneyOr(s.gemini_cost_display, bookCurrency));
    setText(refs.b2cCostSub, `${moneyOr(s.avg_cost_per_pass_display, bookCurrency)} / pass`);
    setText(refs.b2cConversion, s.conversion_pct != null ? `${s.conversion_pct}%` : '—');
    setText(refs.b2cConversionSub, `${(s.free_users || 0).toLocaleString()} free users`);
}

async function loadOptimization() {
    try {
        const response = await fetch(`${API_BASE}/api/admin/ai-optimization`, { headers: buildAuthHeaders(), credentials: 'same-origin' });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) { await handleAdminAuthOrProtectionError(response.status, payload); return; }
        renderOptimization(payload);
    } catch (error) { console.error('Failed to load AI optimization:', error); }
}

function renderOptimization(data) {
    const g = (data && data.guardrail) || {};
    const ch = (data && data.cache_hits) || {};
    const t = (data && data.totals) || {};
    const setText = (el, v) => { if (el) el.textContent = v; };
    setText(refs.optSavedHero, formatAiUsd(t.cost_saved_usd));
    setText(refs.optBlocks, (g.count || 0).toLocaleString());
    setText(refs.optBlocksSub, `${formatTokens(g.tokens_saved)} tokens saved`);
    setText(refs.optCacheHits, (ch.count || 0).toLocaleString());
    setText(refs.optCacheHitsSub, data && data.cache_hit_rate_pct != null ? `${data.cache_hit_rate_pct}% hit rate` : '0% hit rate');
    setText(refs.optTokens, formatTokens(t.tokens_saved));
    setText(refs.optSaved, formatAiUsd(t.cost_saved_usd));
}

async function loadEnterpriseRevenue() {
    try {
        const response = await fetch(`${API_BASE}/api/admin/enterprise/revenue`, {
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            await handleAdminAuthOrProtectionError(response.status, payload);
            return;
        }
        renderEnterpriseRevenue(payload);
    } catch (error) {
        console.error('Failed to load enterprise revenue:', error);
    }
}

function fxNoteText(data) {
    if (!data || data.fx_source !== 'live') return 'USD → INR · estimated (env fallback)';
    var note = 'USD → INR · 🟢 live';
    var ts = Number(data.fx_updated_at || 0);
    if (ts > 0) {
        var mins = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60));
        note += ' · updated ' + (mins < 60 ? mins + 'm' : Math.round(mins / 60) + 'h') + ' ago';
    }
    return note;
}

function renderEnterpriseRevenue(data) {
    const s = (data && data.summary) || {};
    // Credits are an INR-denominated unit of account and foreign payments are summed at
    // their INR settlement, so this book is single-currency by construction — but read the
    // currency off the payload rather than assuming it in fourteen separate string literals.
    const bookCurrency = (data && data.currency) || 'INR';
    const setText = (el, val) => { if (el) el.textContent = val; };
    setText(refs.revMarginHero, moneyOr(s.gross_margin_display, bookCurrency));
    setText(refs.revTotal, moneyOr(s.total_revenue_display, bookCurrency));
    // _kind_money EXCLUDES foreign payments with no INR settlement figure rather than
    // adding their cents as paise, so any non-zero count means this total is short.
    const revUnsettled = Number(s.unsettled_payments || 0);
    setText(refs.revTotalSub, ((s.refunds_paise || 0) > 0
        ? `Net · ${moneyOr(s.gross_revenue_display, bookCurrency)} gross − ${moneyOr(s.refunds_display, bookCurrency)} refunds`
        : 'Net of refunds · credits + infra fees')
        + (revUnsettled > 0 ? ` · ${revUnsettled} not counted (awaiting INR settlement)` : ''));
    setText(refs.revCredits, moneyOr(s.credit_revenue_display, bookCurrency));
    setText(refs.revCreditsSub, `${(s.credit_payment_count || 0).toLocaleString()} payments`);
    setText(refs.revInfra, moneyOr(s.infra_revenue_display, bookCurrency));
    setText(refs.revInfraSub, `${(s.infra_payment_count || 0).toLocaleString()} payments`);
    setText(refs.revCost, moneyOr(s.gemini_cost_display, bookCurrency));
    setText(refs.revMargin, moneyOr(s.gross_margin_display, bookCurrency));
    setText(refs.revMarginSub, s.margin_pct != null ? `${s.margin_pct}% margin` : 'Revenue − AI cost');
    setText(refs.revCreditsSold, (s.credits_sold || 0).toLocaleString());
    setText(refs.revCreditsSoldSub, `${(s.credits_spent || 0).toLocaleString()} spent`);
    setText(refs.revOutstanding, (s.credits_outstanding || 0).toLocaleString());
    setText(refs.revOutstandingSub, `Liability ${moneyOr(s.credits_outstanding_display, bookCurrency)}`);
    if (refs.revFx) refs.revFx.textContent = `$1 = ₹${data && data.usd_to_inr != null ? data.usd_to_inr : 0}`;
    if (refs.revFxNote) refs.revFxNote.textContent = fxNoteText(data);

    if (refs.revActionsBody) {
        const rows = Array.isArray(data && data.per_action) ? data.per_action : [];
        if (!rows.length) {
            refs.revActionsBody.innerHTML = '<tr><td colspan="6" class="table-empty">No premium AI actions billed yet.</td></tr>';
        } else {
            refs.revActionsBody.innerHTML = rows.map((r) => `
                <tr>
                    <td>${escapeHtml(r.label || r.key || '—')}</td>
                    <td>${escapeHtml(r.price_display || '—')} <span class="metric-subtext">(${escapeHtml(String(r.price_credits || 0))} cr)</span></td>
                    <td>${escapeHtml((r.units_sold || 0).toLocaleString())}</td>
                    <td>${escapeHtml(moneyOr(r.revenue_display, bookCurrency))}</td>
                    <td>${escapeHtml(moneyOr(r.avg_cost_per_unit_display, bookCurrency))}</td>
                    <td><strong>${r.margin_pct != null ? escapeHtml(String(r.margin_pct)) + '%' : '—'}</strong></td>
                </tr>`).join('');
        }
    }
}

function formatAiDate(iso) {
    const raw = String(iso || '');
    if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw || '—';
    const d = new Date(`${raw}T00:00:00Z`);
    return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
}

function aiRangeLabel(range) {
    if (!range) return '';
    if (range.start === range.end) return formatAiDate(range.start);
    return `${formatAiDate(range.start)} – ${formatAiDate(range.end)}`;
}

function renderAiUsage(data) {
    state.aiUsageData = data || null;
    const totals = (data && data.totals) || {};
    const setMetric = (costEl, subEl, t) => {
        const s = t || { cost_usd: 0, tokens: 0, calls: 0 };
        if (costEl) costEl.textContent = formatAiUsd(s.cost_usd);
        if (subEl) {
            let sub = `${(s.calls || 0).toLocaleString()} calls · ${formatTokens(s.tokens)} tokens`;
            if (s.cache_hit_pct) sub += ` · ${s.cache_hit_pct}% cached 🟢`;
            subEl.textContent = sub;
        }
    };
    setMetric(refs.aiTodayCost, refs.aiTodaySub, totals.today);
    setMetric(refs.ai7Cost, refs.ai7Sub, totals.last_7_days);
    setMetric(refs.aiMonthCost, refs.aiMonthSub, totals.this_month);
    setMetric(refs.aiAllCost, refs.aiAllSub, totals.all_time);

    // --- selected range -----------------------------------------------------
    const range = (data && data.range) || null;
    const label = aiRangeLabel(range);
    if (range) {
        // Keep the inputs and state in step with what the server actually applied
        // (it clamps a future end date and swaps a reversed pair).
        state.aiRange.start = range.start;
        state.aiRange.end = range.end;
        if (refs.aiRangeStart && refs.aiRangeStart.value !== range.start) refs.aiRangeStart.value = range.start;
        if (refs.aiRangeEnd && refs.aiRangeEnd.value !== range.end) refs.aiRangeEnd.value = range.end;
    }
    if (refs.aiRangeStart && data && data.earliest_event_date) refs.aiRangeStart.min = data.earliest_event_date;

    setMetric(refs.aiRangeCost, refs.aiRangeSub, range);
    if (refs.aiMonthHero) refs.aiMonthHero.textContent = formatAiUsd((range || {}).cost_usd);
    if (refs.aiHeroLabel) refs.aiHeroLabel.textContent = label ? `${label} (est.)` : 'Selected range (est.)';
    if (refs.aiRangeCaption && range) {
        refs.aiRangeCaption.textContent =
            `Showing ${label} · ${range.days} day${range.days === 1 ? '' : 's'}. Everything below — totals, charts and the daily table — follows this range.`;
    }
    if (refs.aiRangeAvg) refs.aiRangeAvg.textContent = formatAiUsd((range || {}).avg_per_day_usd);
    if (refs.aiRangeAvgSub && range) {
        refs.aiRangeAvgSub.textContent = `${range.active_days} of ${range.days} day${range.days === 1 ? '' : 's'} had activity`;
    }
    if (refs.aiRangeTopDay) {
        const top = range && range.top_day;
        refs.aiRangeTopDay.textContent = top ? formatAiUsd(top.cost_usd) : '—';
        if (refs.aiRangeTopDaySub) {
            refs.aiRangeTopDaySub.textContent = top ? formatAiDate(top.date) : 'No usage in this range';
        }
    }
    if (refs.aiRangeSaved) refs.aiRangeSaved.textContent = formatAiUsd((range || {}).cache_saved_usd);
    if (refs.aiRangeSavedSub && range) {
        refs.aiRangeSavedSub.textContent = `${range.cache_hit_pct || 0}% of input tokens served from cache`;
    }
    // Google Search grounding is a PER-REQUEST fee with its own free tier, so it moves
    // independently of token spend — shown separately or it looks like a token spike.
    if (refs.aiRangeSearch) refs.aiRangeSearch.textContent = formatAiUsd((range || {}).search_cost_usd);
    if (refs.aiRangeSearchSub && range) {
        const queries = Number(range.search_queries) || 0;
        const total = Number(range.cost_usd) || 0;
        const share = total > 0 ? Math.round((Number(range.search_cost_usd) || 0) / total * 100) : 0;
        refs.aiRangeSearchSub.textContent = queries
            ? `${queries.toLocaleString()} search request${queries === 1 ? '' : 's'} · ${share}% of spend`
            : 'No grounded searches in this range';
    }

    const rangeSuffix = label ? ` · ${label}` : '';
    const granularity = (range && range.granularity) || 'day';
    const granularityWord = granularity === 'month' ? 'month' : (granularity === 'week' ? 'week' : 'day');
    if (refs.aiTimelineTitle) {
        refs.aiTimelineTitle.textContent = `AI Cost by ${granularityWord === 'day' ? 'Day' : (granularityWord === 'week' ? 'Week' : 'Month')}`;
    }
    if (refs.aiTimelineSub) refs.aiTimelineSub.textContent = `Estimated USD spent per ${granularityWord}${rangeSuffix}.`;
    if (refs.aiSourceSub) refs.aiSourceSub.textContent = `Which features drive AI processing spend${rangeSuffix}.`;
    if (refs.aiModelSub) refs.aiModelSub.textContent = `Spend across configured AI model tiers${rangeSuffix}.`;
    if (refs.aiDailyCaption) refs.aiDailyCaption.textContent = `Every day in ${label || 'the selected range'}, newest first.`;

    const series = Array.isArray(data && data.series) && data.series.length
        ? data.series
        : (Array.isArray(data && data.daily) ? data.daily : []);
    state.aiSeries = series;
    state.aiGranularity = granularity;
    renderAiTimelineChart();

    renderAiBreakdown(refs.aiSourceChart, (data && data.by_source) || [], (r) => r.label);
    renderAiBreakdown(refs.aiModelChart, (data && data.by_model) || [], (_r, index) => `AI Model ${index + 1}`);
    renderAiDailyTable();
}

// --- AI Costs CSV export ---------------------------------------------------
// Built client-side from the payload already on screen, so the file always matches
// exactly what the selected date range is showing (no second server round-trip).
function csvCell(value) {
    const s = value === null || value === undefined ? '' : String(value);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function csvRows(rows) {
    return rows.map((row) => row.map(csvCell).join(',')).join('\r\n');
}

function aiExportSections(kind, data) {
    const range = data.range || {};
    const sections = [];
    if (kind === 'sources' || kind === 'all') {
        sections.push({
            title: 'Cost by feature',
            header: ['Feature', 'Source key', 'Calls', 'Tokens', 'Searches', 'Search cost (USD)', 'Est. cost (USD)'],
            rows: (data.by_source || []).map((r) => [
                r.label || r.source, r.source, r.calls || 0, r.tokens || 0,
                r.search_queries || 0, r.search_cost_usd || 0, r.cost_usd || 0,
            ]),
        });
    }
    if (kind === 'models' || kind === 'all') {
        sections.push({
            title: 'Cost by model',
            header: ['Model', 'Calls', 'Tokens', 'Est. cost (USD)'],
            rows: (data.by_model || []).map((r) => [r.model, r.calls || 0, r.tokens || 0, r.cost_usd || 0]),
        });
    }
    if (kind === 'daily' || kind === 'all') {
        const total = Number(range.cost_usd) || 0;
        // The per-card export mirrors the table (so the hide-empty toggle beside the
        // button applies); "export everything" always carries every day in the range.
        const hideEmpty = kind === 'daily' && (!refs.aiHideEmptyDays || refs.aiHideEmptyDays.checked);
        const days = hideEmpty ? (data.daily || []).filter((d) => (d.calls || 0) > 0) : (data.daily || []);
        sections.push({
            title: 'Spend by date',
            header: ['Date (UTC)', 'Calls', 'Tokens', 'Est. cost (USD)', 'Share of range (%)'],
            rows: days.map((d) => [
                d.date, d.calls || 0, d.tokens || 0, d.cost_usd || 0,
                total > 0 ? Number(((d.cost_usd || 0) / total * 100).toFixed(2)) : 0,
            ]),
        });
    }
    return sections.filter(Boolean);
}

function exportAiCsv(kind, btn) {
    const data = state.aiUsageData;
    if (!data || !data.range) { showFlash('Load the AI usage data before exporting.', 'error'); return; }
    const range = data.range;
    const lines = [
        ['Rilono — AI usage & cost (estimated)'],
        ['Range (UTC)', range.start, 'to', range.end],
        ['Days in range', range.days, 'Days with activity', range.active_days],
        ['Total est. cost (USD)', range.cost_usd, 'Calls', range.calls, 'Tokens', range.tokens],
        ['Average per day (USD)', range.avg_per_day_usd, 'Cache hit (%)', range.cache_hit_pct],
        ['Note', 'Estimated from per-token pricing; cross-check the provider invoice.'],
    ];
    aiExportSections(kind, data).forEach((section) => {
        lines.push([], [section.title], section.header, ...section.rows);
    });

    // BOM so Excel reads the em-dashes in feature labels as UTF-8.
    const blob = new Blob(['\uFEFF' + csvRows(lines)], { type: 'text/csv;charset=utf-8;' });
    const suffix = kind === 'all' ? 'full' : kind;
    const filename = `rilono-ai-costs-${suffix}-${range.start}_to_${range.end}.csv`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    // Revoke after the click so the download has a live URL to read from.
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    showFlash(`Downloaded ${filename}`, 'success');
}

function handleAiExportClick(event) {
    const btn = event.target.closest('.ai-export-btn');
    if (!btn) return;
    exportAiCsv(btn.dataset.aiExport || 'all', btn);
}

function renderAiDailyTable() {
    if (!refs.aiDailyTableBody) return;
    const data = state.aiUsageData || {};
    const daily = Array.isArray(data.daily) ? data.daily : [];
    const rangeTotal = Number((data.range || {}).cost_usd) || 0;
    const hideEmpty = !refs.aiHideEmptyDays || refs.aiHideEmptyDays.checked;
    const rows = (hideEmpty ? daily.filter((d) => (d.calls || 0) > 0) : daily).slice().reverse();

    if (!rows.length) {
        const message = daily.length && hideEmpty
            ? 'No AI usage on any day in this range.'
            : 'No AI usage in the selected range.';
        refs.aiDailyTableBody.innerHTML = `<tr><td colspan="5" class="table-empty">${escapeHtml(message)}</td></tr>`;
    } else {
        refs.aiDailyTableBody.innerHTML = rows.map((d) => {
            const cost = Number(d.cost_usd) || 0;
            const share = rangeTotal > 0 ? (cost / rangeTotal) * 100 : 0;
            return `
                <tr${(d.calls || 0) ? '' : ' class="ai-daily-empty-row"'}>
                    <td>${escapeHtml(formatAiDate(d.date))}</td>
                    <td>${escapeHtml((d.calls || 0).toLocaleString())}</td>
                    <td>${escapeHtml(formatTokens(d.tokens))}</td>
                    <td><strong>${escapeHtml(formatAiUsd(cost))}</strong></td>
                    <td>${escapeHtml(share.toFixed(1))}%</td>
                </tr>`;
        }).join('');
    }

    const put = (el, v) => { if (el) el.textContent = v; };
    const totalCalls = daily.reduce((sum, d) => sum + (d.calls || 0), 0);
    const totalTokens = daily.reduce((sum, d) => sum + (d.tokens || 0), 0);
    put(refs.aiDailyTotalCalls, totalCalls.toLocaleString());
    put(refs.aiDailyTotalTokens, formatTokens(totalTokens));
    put(refs.aiDailyTotalCost, formatAiUsd(rangeTotal));
}

// --- AI cost timeline (SVG column chart) -----------------------------------
// Single series, so no legend — the card title names what is plotted. One hue
// (#6366f1, validated against the white card surface), hairline solid gridlines,
// value axis, per-column hover/keyboard tooltip, and a direct label on the peak
// only. Every value is also in the "Spend by date" table below, so the tooltip
// enhances rather than gates.
const AI_CHART = {
    height: 300,
    pad: { top: 24, right: 14, bottom: 30, left: 58 },
    series: '#6366f1',
    seriesHover: '#4338ca',
    wash: 'rgba(99, 102, 241, 0.10)',
    grid: '#e4e4e7',
    baseline: '#d4d4d8',
    axisInk: '#71717a',
    labelInk: '#18181b',
};

// Steps of 1/2/5 × 10ⁿ only — a 2.5 step would render as "$3" beside "$5" once the
// label is rounded, which misstates the gridline.
function niceAxis(max, targetCount = 4) {
    if (!(max > 0)) return { top: 1, step: 1, ticks: [0, 1] };
    const rawStep = max / targetCount;
    const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const normalized = rawStep / magnitude;
    const step = (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) * magnitude;
    const top = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = 0; v <= top + step / 2; v += step) ticks.push(Number(v.toPrecision(12)));
    return { top, step, ticks };
}

function formatAxisUsd(value, step) {
    const decimals = step >= 1 ? 0 : Math.min(4, Math.ceil(-Math.log10(step)));
    return `$${Number(value).toFixed(decimals)}`;
}

// Square at the baseline, 4px rounded at the data end.
function aiBarPath(x, y, w, h) {
    const r = Math.max(0, Math.min(4, w / 2, h));
    return `M${x} ${y + h} L${x} ${y + r} Q${x} ${y} ${x + r} ${y} `
        + `L${x + w - r} ${y} Q${x + w} ${y} ${x + w} ${y + r} L${x + w} ${y + h} Z`;
}

function aiBucketSpan(d) {
    const start = formatAiDate(d.date);
    return d.end && d.end !== d.date ? `${start} – ${formatAiDate(d.end)}` : start;
}

function renderAiTimelineChart() {
    const host = refs.aiTimelineChart;
    if (!host) return;
    const series = Array.isArray(state.aiSeries) ? state.aiSeries : [];
    const values = series.map((d) => Number(d.cost_usd) || 0);
    if (!series.length || !values.some((v) => v > 0)) {
        host.innerHTML = '<div class="table-empty">No AI usage in the selected range.</div>';
        return;
    }
    if (series.length < 2) {
        // A single bucket is a number, not a chart — "Spent in range" above already
        // states it, and a lone column would just be that number drawn badly.
        host.innerHTML = '<div class="table-empty">One day selected — see <strong>Spent in range</strong> above.'
            + '<br>Pick a wider range to see the trend.</div>';
        return;
    }

    const { height } = AI_CHART;
    const width = Math.max(320, Math.round(host.clientWidth) || 640);
    // Narrow cards get a tighter value gutter so the plot keeps its width.
    const pad = { ...AI_CHART.pad, left: width < 480 ? 42 : AI_CHART.pad.left };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const baselineY = pad.top + plotH;
    const axis = niceAxis(Math.max(...values));
    const band = plotW / series.length;
    const barW = Math.max(2, Math.min(24, band - 2, band * 0.7));
    const yOf = (v) => pad.top + plotH * (1 - v / axis.top);

    // Label density follows the plot width (~64px per label) so a narrow card thins
    // its axis instead of colliding; at most 8 labels, plus the final bucket when it
    // clears the previous one.
    const maxLabels = Math.max(3, Math.min(8, Math.floor(plotW / 64)));
    const step = Math.max(1, Math.ceil(series.length / maxLabels));
    const labelled = new Set();
    let lastLabelled = 0;
    for (let i = 0; i < series.length; i += step) { labelled.add(i); lastLabelled = i; }
    if (series.length - 1 - lastLabelled >= Math.ceil(step / 2)) labelled.add(series.length - 1);

    const svgNS = 'http://www.w3.org/2000/svg';
    const make = (tag, attrs) => {
        const node = document.createElementNS(svgNS, tag);
        Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, String(v)));
        return node;
    };

    const svg = make('svg', {
        class: 'ai-chart-svg', width: '100%', height, viewBox: `0 0 ${width} ${height}`,
        preserveAspectRatio: 'xMidYMid meet', 'aria-hidden': 'true',
    });

    // Gridlines + value axis (solid hairlines, one step off the surface).
    axis.ticks.forEach((tick) => {
        const y = yOf(tick);
        svg.appendChild(make('line', {
            x1: pad.left, x2: pad.left + plotW, y1: y, y2: y,
            stroke: tick === 0 ? AI_CHART.baseline : AI_CHART.grid, 'stroke-width': 1,
        }));
        const text = make('text', {
            x: pad.left - 10, y: y + 4, 'text-anchor': 'end', class: 'ai-chart-axis-text',
        });
        text.textContent = formatAxisUsd(tick, axis.step);
        svg.appendChild(text);
    });

    // Columns.
    const peakIndex = values.indexOf(Math.max(...values));
    series.forEach((d, i) => {
        const value = values[i];
        if (value <= 0) return;
        const x = pad.left + i * band + (band - barW) / 2;
        const y = yOf(value);
        const h = Math.max(1, baselineY - y);   // 1px floor so a tiny day is still visible
        svg.appendChild(make('path', {
            d: aiBarPath(x, baselineY - h, barW, h),
            fill: AI_CHART.series, class: 'ai-chart-bar', 'data-index': i,
        }));
    });

    // Direct-label the peak only; everything else is carried by the axis and tooltip.
    if (values[peakIndex] > 0) {
        const label = formatAiUsd(values[peakIndex]);
        const centre = pad.left + peakIndex * band + band / 2;
        const halfText = label.length * 3.4;
        const x = Math.min(Math.max(centre, pad.left + halfText), pad.left + plotW - halfText);
        const text = make('text', {
            x, y: Math.max(12, yOf(values[peakIndex]) - 8), 'text-anchor': 'middle', class: 'ai-chart-peak',
        });
        text.textContent = label;
        svg.appendChild(text);
    }

    // X axis labels.
    series.forEach((d, i) => {
        if (!labelled.has(i)) return;
        const text = make('text', {
            x: pad.left + i * band + band / 2, y: baselineY + 18,
            'text-anchor': 'middle', class: 'ai-chart-axis-text',
        });
        text.textContent = d.label || String(d.date || '').slice(5);
        svg.appendChild(text);
    });

    // Hit targets: the whole band, not just the painted column.
    series.forEach((d, i) => {
        svg.appendChild(make('rect', {
            x: pad.left + i * band, y: pad.top, width: band, height: plotH,
            fill: 'transparent', class: 'ai-chart-hit', 'data-index': i,
        }));
    });

    host.innerHTML = '';
    host.appendChild(svg);
    const tip = document.createElement('div');
    tip.className = 'ai-chart-tip';
    tip.hidden = true;
    host.appendChild(tip);

    host.tabIndex = 0;
    host.setAttribute('aria-label',
        `Estimated AI cost per ${state.aiGranularity || 'day'}, ${series.length} points. Values are listed in the Spend by date table below.`);

    let active = -1;
    const clear = () => {
        active = -1;
        tip.hidden = true;
        svg.querySelectorAll('.ai-chart-bar.is-active').forEach((b) => b.classList.remove('is-active'));
    };
    const show = (index) => {
        const d = series[index];
        if (!d) return;
        active = index;
        svg.querySelectorAll('.ai-chart-bar.is-active').forEach((b) => b.classList.remove('is-active'));
        const bar = svg.querySelector(`.ai-chart-bar[data-index="${index}"]`);
        if (bar) bar.classList.add('is-active');

        // Labels are data — build the readout with textContent, never innerHTML.
        tip.textContent = '';
        const value = document.createElement('strong');
        value.textContent = formatAiUsd(values[index]);
        const when = document.createElement('span');
        when.textContent = aiBucketSpan(d);
        const detail = document.createElement('span');
        detail.textContent = `${(d.calls || 0).toLocaleString()} calls · ${formatTokens(d.tokens)} tokens`;
        tip.append(value, when, detail);
        tip.hidden = false;

        const centre = pad.left + index * band + band / 2;
        const scale = host.clientWidth / width;
        tip.style.left = `${Math.round(centre * scale)}px`;
        tip.style.top = `${Math.round(yOf(values[index]) * scale)}px`;
        // Flip the tooltip inside the card when the column sits near an edge.
        tip.classList.toggle('flip-left', centre * scale > host.clientWidth - 130);
        tip.classList.toggle('flip-right', centre * scale < 130);
    };

    svg.addEventListener('pointermove', (event) => {
        const hit = event.target.closest('.ai-chart-hit');
        if (!hit) { clear(); return; }
        const index = Number(hit.dataset.index);
        if (index !== active) show(index);
    });
    svg.addEventListener('pointerleave', clear);
    host.addEventListener('blur', clear);
    host.addEventListener('keydown', (event) => {
        if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
            event.preventDefault();
            const next = active < 0
                ? (event.key === 'ArrowRight' ? 0 : series.length - 1)
                : Math.min(series.length - 1, Math.max(0, active + (event.key === 'ArrowRight' ? 1 : -1)));
            show(next);
        } else if (event.key === 'Escape') {
            clear();
        }
    });

    // Re-render on width changes so the axis and bands stay honest.
    if (!state.aiChartResizeBound) {
        state.aiChartResizeBound = true;
        if (typeof ResizeObserver === 'function') {
            let lastWidth = host.clientWidth;
            new ResizeObserver(() => {
                const nextWidth = host.clientWidth;
                if (Math.abs(nextWidth - lastWidth) < 8) return;
                lastWidth = nextWidth;
                renderAiTimelineChart();
            }).observe(host);
        }
    }
}

function renderAiBreakdown(el, rows, labelFn) {
    if (!el) return;
    const list = Array.isArray(rows) ? rows.slice() : [];
    if (!list.length) { el.innerHTML = '<div class="table-empty">No AI usage recorded yet.</div>'; return; }
    const total = list.reduce((sum, r) => sum + (Number(r.cost_usd) || 0), 0) || 1;
    el.innerHTML = list.map((r, index) => {
        const amount = Number(r.cost_usd) || 0;
        const pct = Math.min(Math.max((amount / total) * 100, 0), 100);
        return `
            <div class="finance-breakdown-row">
                <div class="finance-breakdown-top"><strong>${escapeHtml(labelFn(r, index) || '—')}</strong><span>${escapeHtml(formatAiUsd(amount))}</span></div>
                <div class="finance-breakdown-track"><span style="width: ${pct.toFixed(2)}%"></span></div>
                <div class="finance-breakdown-percent">${escapeHtml((r.calls || 0).toLocaleString())} calls · ${escapeHtml(formatTokens(r.tokens))} tokens</div>
            </div>`;
    }).join('');
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

// ---------------------------------------------------------------------------
// Per-account discount codes (admin)
// ---------------------------------------------------------------------------

const COUPON_APPLIES_LABELS = {
    all: 'Top-ups & billing',
    credits: 'Credit top-ups',
    billing: 'Plan billing'
};

async function handleEnterpriseTableActionClick(event) {
    const button = event.target.closest('[data-action="manage-coupons"]');
    if (!button || button.disabled || state.enterpriseLoading) return;
    const orgId = Number(button.dataset.orgId || 0);
    if (!Number.isFinite(orgId) || orgId <= 0) return;
    openCouponModal(orgId, String(button.dataset.company || 'this account'));
}

function setCouponFormError(message) {
    if (!refs.couponFormError) return;
    if (!message) {
        refs.couponFormError.hidden = true;
        refs.couponFormError.textContent = '';
        return;
    }
    refs.couponFormError.textContent = message;
    refs.couponFormError.hidden = false;
}

async function openCouponModal(orgId, company) {
    state.couponOrg = { id: orgId, company };
    state.couponList = [];
    if (refs.couponModalTitle) refs.couponModalTitle.textContent = 'Manage account';
    if (refs.couponModalSubtitle) refs.couponModalSubtitle.textContent = company;
    refs.couponForm?.reset();
    setCouponFormError('');
    if (refs.accountDetails) {
        refs.accountDetails.innerHTML = '<p class="account-details-status">Loading account details…</p>';
    }
    renderCouponTableMessage('Loading discount codes...');
    if (refs.couponModal) refs.couponModal.hidden = false;
    document.body.classList.add('admin-modal-open');
    await Promise.all([loadAccountDetails(), loadCoupons()]);
}

async function loadAccountDetails() {
    if (!state.couponOrg || !refs.accountDetails) return;
    if (!await ensureAdminProtection({ silent: true })) {
        refs.accountDetails.innerHTML = '<p class="account-details-status">Verify the security check above to load account details.</p>';
        return;
    }
    try {
        const response = await fetch(`${API_BASE}/api/admin/enterprise/accounts/${state.couponOrg.id}/details`, {
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            await handleAdminAuthOrProtectionError(response.status, payload);
            refs.accountDetails.innerHTML = `<p class="account-details-status">${escapeHtml(normalizeErrorMessage(payload, 'Failed to load account details.'))}</p>`;
            return;
        }
        renderAccountDetails(payload);
    } catch (error) {
        console.error('Failed to load account details:', error);
        refs.accountDetails.innerHTML = '<p class="account-details-status">Could not load account details. Please retry.</p>';
    }
}

function renderAccountDetails(data) {
    if (!refs.accountDetails) return;
    const org = data.organization || {};
    const wallet = data.wallet || {};
    const totals = data.totals || {};
    const infra = wallet.infra_fee || {};
    const purchases = Array.isArray(data.purchases) ? data.purchases : [];
    const activity = Array.isArray(data.recent_activity) ? data.recent_activity : [];

    const metaBits = [];
    if (org.subdomain_slug) metaBits.push(`subdomain: ${escapeHtml(org.subdomain_slug)}`);
    metaBits.push(`${Number(org.members_active || 0)} active member${Number(org.members_active) === 1 ? '' : 's'}`);
    metaBits.push(`${Number(org.admins || 0)} admin${Number(org.admins) === 1 ? '' : 's'}`);
    if (org.created_by_name) metaBits.push(`created by ${escapeHtml(org.created_by_name)}`);

    const infraStatus = infra.is_current
        ? `Active until ${formatDateTime(infra.paid_until)}`
        : (infra.over_free_limit ? 'Due (past free limit)' : 'Not required yet');

    // The totals block is the INR SETTLEMENT of every payment (base_amount_paise), which is
    // what makes it addable at all — so it is labelled with the currency the server states.
    // When this org has non-INR refunds the server sends the refund-derived figures as null
    // rather than a wrong number, and we say "mixed" instead of inventing one.
    const totalsCurrency = totals.currency || 'INR';
    const paymentCurrencies = Array.isArray(totals.payment_currencies) ? totals.payment_currencies : [];
    const paymentCount = Number(totals.verified_payment_count || 0);
    let totalPaidSub = `${paymentCount} payment${paymentCount === 1 ? '' : 's'}`;
    if (paymentCurrencies.length > 1) {
        totalPaidSub += ` · settled ${totalsCurrency} from ${paymentCurrencies.join(', ')}`;
    }
    const mixedRefundNote = totals.refunds_mixed_currency
        ? `<p class="account-meta-line">⚠ Refunds on this account were issued in ${escapeHtml((totals.refund_currencies || []).join(', ') || 'more than one currency')}, so a net-paid total can't be stated in a single currency. See the refunds table below.</p>`
        : '';
    // A foreign payment with no Razorpay INR settlement figure is EXCLUDED from the totals
    // above rather than having its cents added as paise. Silently dropping it would make
    // "Total paid" read as though the money never arrived, so say it out loud.
    const uncountedPayments = Number(totals.unsettled_payment_count || 0);
    const uncountedNote = uncountedPayments > 0
        ? `<p class="account-meta-line">⚠ ${uncountedPayments} foreign-currency payment${uncountedPayments === 1 ? ' is' : 's are'} not included in the totals above — Razorpay hasn't reported an INR settlement figure for ${uncountedPayments === 1 ? 'it' : 'them'} yet, and a foreign amount can't be added to an INR total. Total paid is an understatement until then; the purchases table below shows the charged amounts.</p>`
        : '';

    const metrics = `
        <div class="account-metrics-grid">
            <article class="metric-card"><span>Credits remaining</span>
                <strong>${Number(wallet.balance_credits || 0).toLocaleString()}</strong>
                <small>${escapeHtml(wallet.balance_display || '')}</small></article>
            <article class="metric-card"><span>Lifetime purchased</span>
                <strong>${Number(wallet.lifetime_purchased_credits || 0).toLocaleString()}</strong>
                <small>credits</small></article>
            <article class="metric-card"><span>Lifetime used</span>
                <strong>${Number(wallet.lifetime_spent_credits || 0).toLocaleString()}</strong>
                <small>credits</small></article>
            <article class="metric-card"><span>Total paid</span>
                <strong>${escapeHtml(moneyOr(totals.total_paid_display, totalsCurrency))}</strong>
                <small>${escapeHtml(totalPaidSub)}</small></article>
        </div>
        <p class="account-meta-line">Infrastructure fee: ${escapeHtml(infraStatus)} · ${Number(infra.clients_used || 0)} / ${Number(infra.free_student_limit || 0)} free students used</p>
        ${uncountedNote}${mixedRefundNote}`;

    const purchaseRows = purchases.length
        ? purchases.map((p) => {
            const credits = p.kind === 'credits'
                ? `+${Number(p.total_credits || 0).toLocaleString()}${p.bonus_credits ? ` <span class="account-coupon-tag">+${Number(p.bonus_credits)} bonus</span>` : ''}`
                : '—';
            const coupon = p.coupon_code
                ? `<span class="account-coupon-tag">${escapeHtml(p.coupon_code)}${p.coupon_percent_off ? ` −${p.coupon_percent_off}%` : ''}</span>`
                : '—';
            let statusCls = 'created';
            if (p.status === 'verified') statusCls = 'verified';
            else if (p.status === 'failed') statusCls = 'failed';
            else if (p.status === 'refunded' || p.status === 'partially_refunded') statusCls = 'refunded';
            const statusLabel = (p.status || '').replace(/_/g, ' ');
            const refundNote = (p.refunded_amount_paise > 0)
                ? `<div class="enterprise-meta">refunded ${escapeHtml(p.refunded_amount_display)}</div>` : '';
            // A foreign charge has two numbers: what the customer paid, and what Razorpay
            // settled to us in INR. Show both — only the second is comparable to anything.
            const settledNote = p.settled_inr_display
                ? `<div class="enterprise-meta">settled ${escapeHtml(p.settled_inr_display)}</div>`
                // Foreign charge with no settlement figure: it is excluded from the INR
                // totals above, so mark the row rather than letting it look counted.
                : ((currencyCode(p.currency) !== 'INR' && p.base_amount_paise == null)
                    ? '<div class="enterprise-meta" title="Razorpay has not reported an INR settlement figure for this payment yet, so it is not included in the totals above.">⚠ not counted in totals</div>'
                    : '');
            const wasNote = p.original_amount_display
                ? `<div class="enterprise-meta">was ${escapeHtml(p.original_amount_display)}</div>` : '';
            const intlTag = p.is_international
                ? '<span class="account-coupon-tag">international</span>' : '';
            // Razorpay blocks refunds past 6 months; say so where the admin decides.
            const windowNote = (p.refundable_paise > 0 && p.refund_window_open === false)
                ? '<div class="enterprise-meta">refund window closed (6-month Razorpay limit)</div>' : '';
            return `<tr>
                <td>${escapeHtml(formatDateTime(p.created_at))}</td>
                <td>${escapeHtml(p.kind_label || p.kind)}${p.package_key ? `<div class="enterprise-meta">${escapeHtml(p.package_key)}</div>` : ''}</td>
                <td>${credits}</td>
                <td>${escapeHtml(moneyOr(p.amount_display, p.currency))} ${intlTag}${wasNote}${settledNote}</td>
                <td>${coupon}</td>
                <td><span class="account-status-chip ${statusCls}">${escapeHtml(statusLabel)}</span>${refundNote}${windowNote}</td>
            </tr>`;
        }).join('')
        : '<tr><td colspan="6" class="table-empty">No purchases yet.</td></tr>';

    const purchasesBlock = `
        <h4 class="account-section-title">Purchases &amp; top-ups</h4>
        <div class="coupon-list-wrap">
            <table class="users-table">
                <thead><tr><th>Date</th><th>Type</th><th>Credits</th><th>Amount</th><th>Coupon</th><th>Status</th></tr></thead>
                <tbody>${purchaseRows}</tbody>
            </table>
        </div>`;

    const activityBlock = activity.length ? `
        <h4 class="account-section-title">Recent credit usage</h4>
        <div class="account-activity">
            ${activity.map((t) => {
                const pos = Number(t.credits) > 0;
                const label = t.action_label || t.description || (t.type || '').replace(/_/g, ' ');
                const who = t.created_by_name ? ` · ${escapeHtml(t.created_by_name)}` : '';
                return `<div class="account-activity-row">
                    <span class="aa-main">${escapeHtml(label)}${who}</span>
                    <span class="aa-when">${escapeHtml(formatDateTime(t.created_at))}</span>
                    <span class="aa-credits ${pos ? 'pos' : 'neg'}">${t.credits === 0 ? '—' : (pos ? '+' : '') + Number(t.credits)}</span>
                </div>`;
            }).join('')}
        </div>` : '';

    state.accountDetails = data;
    const refundsBlock = buildRefundsHistoryBlock(data);
    const refundFormBlock = buildRefundFormBlock(data);

    refs.accountDetails.innerHTML =
        `<h4 class="account-section-title">Wallet &amp; billing</h4>` +
        `<p class="account-meta-line" style="margin-top:-0.2rem">${metaBits.join(' · ')}</p>` +
        metrics + purchasesBlock + refundFormBlock + refundsBlock + activityBlock;

    wireRefundForm(data);
}

function buildRefundsHistoryBlock(data) {
    const refunds = Array.isArray(data.refunds) ? data.refunds : [];
    if (!refunds.length) return '';
    const rows = refunds.map((r) => {
        const isMoney = r.kind === 'money';
        // A refund is recorded in the ORIGINAL payment's currency, and the server's
        // `amount_display` is still INR-formatted, so render from (amount_paise, currency)
        // here — otherwise a $60 refund prints as ₹60.
        const amount = isMoney ? escapeHtml(formatMinor(r.amount_paise, r.currency)) : '—';
        const cr = r.credits_delta ? `${r.credits_delta > 0 ? '+' : ''}${Number(r.credits_delta)} cr` : '—';
        const statusCls = ['processed', 'completed'].includes(r.status) ? 'verified' : (r.status === 'failed' ? 'failed' : 'created');
        const reason = r.reason ? `<div class="enterprise-meta">${escapeHtml(r.reason)}</div>` : '';
        return `<tr>
            <td>${escapeHtml(formatDateTime(r.created_at))}${r.created_by_name ? `<div class="enterprise-meta">by ${escapeHtml(r.created_by_name)}</div>` : ''}</td>
            <td>${isMoney ? 'Money (Razorpay)' : 'Credits'}${reason}</td>
            <td>${amount}</td>
            <td>${cr}</td>
            <td><span class="account-status-chip ${statusCls}">${escapeHtml(r.status)}</span></td>
        </tr>`;
    }).join('');
    return `
        <h4 class="account-section-title">Refunds issued</h4>
        <div class="coupon-list-wrap">
            <table class="users-table">
                <thead><tr><th>Date</th><th>Type</th><th>Amount</th><th>Credits</th><th>Status</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>`;
}

function buildRefundFormBlock(data) {
    // `is_refundable` already accounts for Razorpay's 6-month window, so a payment past it
    // never reaches the picker; the purchases table above says why it's missing.
    const refundable = (data.purchases || []).filter((p) => p.is_refundable);
    const razorpayOn = !!data.razorpay_enabled;
    // Each option shows its own currency, and the amount field is re-labelled from whichever
    // payment is selected — a refund is issued in THAT payment's currency, not in rupees.
    const moneyOptions = refundable.map((p) =>
        `<option value="${p.id}">${escapeHtml(p.kind_label)} · ${escapeHtml(moneyOr(p.amount_display, p.currency))} · ${escapeHtml(formatDateTime(p.created_at))} (refundable ${escapeHtml(moneyOr(p.refundable_display, p.currency))})</option>`
    ).join('');

    let moneyInner;
    if (!razorpayOn) {
        moneyInner = '<p class="account-details-status">Razorpay isn\'t configured, so money refunds are unavailable.</p>';
    } else if (!refundable.length) {
        moneyInner = '<p class="account-details-status">No refundable Razorpay payments on this account. Payments older than 6 months can no longer be refunded through Razorpay — use a goodwill credit refund instead.</p>';
    } else {
        const firstCurrency = currencyCode(refundable[0].currency);
        moneyInner = `
            <div class="refund-grid">
                <label class="coupon-field coupon-field-wide"><span>Payment to refund</span>
                    <select id="refundPaymentSelect">${moneyOptions}</select></label>
                <label class="coupon-field"><span id="refundAmountLabel">Amount (${escapeHtml(currencyInputLabel(firstCurrency))})</span>
                    <input type="number" id="refundAmount" min="0.01" step="0.01" placeholder="0.00"></label>
                <label class="coupon-field"><span>Claw back credits</span>
                    <input type="number" id="refundClawback" min="0" step="1" placeholder="0"></label>
                <label class="coupon-field coupon-field-wide"><span>Reason (optional)</span>
                    <input type="text" id="refundMoneyReason" maxlength="200" placeholder="e.g. Customer requested partial refund"></label>
            </div>
            <button type="button" id="refundMoneyBtn" class="primary-btn small-btn refund-danger">Refund money via Razorpay</button>
            <p class="account-meta-line" style="margin:0.4rem 0 0">⚠ This sends real money back to the customer and can't be undone. Refunds go out in the currency the payment was charged in, and Razorpay only allows them within 6 months of the payment.</p>`;
    }

    return `
        <h4 class="account-section-title">Issue a refund</h4>
        <div class="refund-tabs">
            <button type="button" class="refund-tab active" data-refund-mode="credits">Credit / goodwill</button>
            <button type="button" class="refund-tab" data-refund-mode="money">Money (Razorpay)</button>
        </div>
        <div class="refund-mode" data-mode="credits">
            <div class="refund-grid">
                <label class="coupon-field"><span>Credits to add</span>
                    <input type="number" id="refundCredits" min="1" step="1" placeholder="50"></label>
                <label class="coupon-field coupon-field-wide"><span>Reason (optional)</span>
                    <input type="text" id="refundCreditReason" maxlength="200" placeholder="e.g. Goodwill — failed Deep Scan"></label>
            </div>
            <button type="button" id="refundCreditBtn" class="primary-btn small-btn">Add credits to wallet</button>
            <p class="account-meta-line" style="margin:0.4rem 0 0">No money moves — credits are added to their wallet and logged.</p>
        </div>
        <div class="refund-mode hidden" data-mode="money">${moneyInner}</div>
        <p id="refundFormError" class="coupon-form-error" hidden></p>`;
}

function setRefundError(message) {
    const el = document.getElementById('refundFormError');
    if (!el) return;
    if (!message) { el.hidden = true; el.textContent = ''; return; }
    el.textContent = message;
    el.hidden = false;
}

function wireRefundForm(data) {
    // mode toggle
    document.querySelectorAll('.refund-tab').forEach((tab) => {
        tab.addEventListener('click', () => {
            const mode = tab.dataset.refundMode;
            document.querySelectorAll('.refund-tab').forEach((t) => t.classList.toggle('active', t === tab));
            document.querySelectorAll('.refund-mode').forEach((m) => m.classList.toggle('hidden', m.dataset.mode !== mode));
            setRefundError('');
        });
    });

    // money mode: prefill amount + clawback when a payment is selected, recompute clawback on amount change
    const paymentSelect = document.getElementById('refundPaymentSelect');
    const amountInput = document.getElementById('refundAmount');
    const clawbackInput = document.getElementById('refundClawback');
    const purchaseById = {};
    (data.purchases || []).forEach((p) => { purchaseById[p.id] = p; });

    const amountLabel = document.getElementById('refundAmountLabel');
    const selectedPurchase = () => (paymentSelect ? purchaseById[Number(paymentSelect.value)] : null);
    // The typed amount is in the SELECTED payment's major unit; everything sent to the
    // server is minor units of that same currency. One conversion, in one place.
    const toMinor = (major, currency) => Math.round(Number(major || 0) * Math.pow(10, currencyExponent(currency)));
    const toMajor = (minor, currency) => Number(minor || 0) / Math.pow(10, currencyExponent(currency));

    const syncMoneyDefaults = (resetAmount) => {
        const p = selectedPurchase();
        if (!p) return;
        const code = currencyCode(p.currency);
        const exponent = currencyExponent(code);
        // Re-label the box for the payment being refunded — an unlabelled number box is
        // how "5000" against a $60 charge became a $50.00 refund.
        if (amountLabel) amountLabel.textContent = `Amount (${currencyInputLabel(code)})`;
        if (amountInput) {
            const step = exponent === 0 ? '1' : (1 / Math.pow(10, exponent)).toFixed(exponent);
            amountInput.step = step;
            amountInput.min = step;
            amountInput.max = toMajor(p.refundable_paise, code).toFixed(exponent);
            if (resetAmount) amountInput.value = toMajor(p.refundable_paise, code).toFixed(exponent);
        }
        recomputeClawback();
    };
    const recomputeClawback = () => {
        if (!clawbackInput || !amountInput) return;
        const p = selectedPurchase();
        if (!p) return;
        if (p.kind !== 'credits' || !p.amount_paise) { clawbackInput.value = '0'; return; }
        // Ratio of two minor amounts in the SAME currency — dimensionless, so it is safe.
        const amountMinor = toMinor(amountInput.value, p.currency);
        const suggested = Math.round((p.total_credits || 0) * (amountMinor / p.amount_paise));
        clawbackInput.value = String(Math.max(0, suggested));
    };
    if (paymentSelect) { paymentSelect.addEventListener('change', () => syncMoneyDefaults(true)); syncMoneyDefaults(true); }
    if (amountInput) amountInput.addEventListener('input', recomputeClawback);

    const creditBtn = document.getElementById('refundCreditBtn');
    if (creditBtn) creditBtn.addEventListener('click', async () => {
        setRefundError('');
        const credits = Math.floor(Number((document.getElementById('refundCredits') || {}).value || 0));
        if (!Number.isFinite(credits) || credits <= 0) { setRefundError('Enter how many credits to add.'); return; }
        const reason = (document.getElementById('refundCreditReason') || {}).value || '';
        await issueRefund(creditBtn, { kind: 'credits', credits, reason });
    });

    const moneyBtn = document.getElementById('refundMoneyBtn');
    if (moneyBtn) moneyBtn.addEventListener('click', async () => {
        setRefundError('');
        const paymentId = Number((paymentSelect || {}).value || 0);
        const amount = Number((amountInput || {}).value || 0);
        const clawback = Math.floor(Number((clawbackInput || {}).value || 0));
        const reason = (document.getElementById('refundMoneyReason') || {}).value || '';
        if (!paymentId) { setRefundError('Select a payment to refund.'); return; }
        if (!Number.isFinite(amount) || amount <= 0) { setRefundError('Enter the amount to refund.'); return; }
        const p = selectedPurchase();
        if (!p) { setRefundError('Select a payment to refund.'); return; }
        const code = currencyCode(p.currency);
        const amountMinor = toMinor(amount, code);
        if (amountMinor > Number(p.refundable_paise || 0)) {
            setRefundError(`That's more than the ${moneyOr(p.refundable_display, code)} still refundable on this payment.`);
            return;
        }
        // Confirm in the currency the money will actually leave in, and send the currency
        // along so the server can reject a mismatch before anything moves.
        const amountLabelText = formatMinor(amountMinor, code);
        const company = (state.couponOrg && state.couponOrg.company) || 'this account';
        if (!(await confirmDialog(`Refund ${amountLabelText} (${code}) to ${company} via Razorpay and claw back ${clawback} credits. This moves real money and cannot be undone.`, { title: 'Issue refund?', okText: `Refund ${amountLabelText}` }))) return;
        await issueRefund(moneyBtn, {
            kind: 'money',
            payment_id: paymentId,
            amount_minor: amountMinor,
            amount_currency: code,
            clawback_credits: clawback,
            reason
        });
    });
}

async function issueRefund(button, body) {
    if (!state.couponOrg) return;
    if (!await ensureAdminProtection({ silent: false })) return;
    const originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = 'Processing…';
    try {
        const response = await fetch(`${API_BASE}/api/admin/enterprise/accounts/${state.couponOrg.id}/refunds`, {
            method: 'POST',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            credentials: 'same-origin',
            body: JSON.stringify(body)
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            await handleAdminAuthOrProtectionError(response.status, payload);
            setRefundError(normalizeErrorMessage(payload, 'Refund failed.'));
            return;
        }
        // success — reload the full account details to reflect the new balance/history
        await loadAccountDetails();
        await loadEnterpriseAccounts({ silent: true }).catch(() => {});
    } catch (error) {
        console.error('Refund failed:', error);
        setRefundError('Could not issue the refund. Please retry.');
    } finally {
        button.disabled = false;
        button.textContent = originalLabel;
    }
}

function closeCouponModal() {
    if (refs.couponModal) refs.couponModal.hidden = true;
    document.body.classList.remove('admin-modal-open');
    state.couponOrg = null;
    state.couponList = [];
    setCouponFormError('');
}

function renderCouponTableMessage(message) {
    if (!refs.couponTableBody) return;
    refs.couponTableBody.innerHTML = `<tr><td colspan="6" class="table-empty">${escapeHtml(message)}</td></tr>`;
}

function renderCouponTable() {
    if (!refs.couponTableBody) return;
    if (!state.couponList.length) {
        renderCouponTableMessage('No discount codes yet. Add one above.');
        return;
    }
    refs.couponTableBody.innerHTML = state.couponList.map((c) => {
        const used = Number(c.redemptions_used || 0);
        const cap = c.max_redemptions == null ? '∞' : escapeHtml(String(c.max_redemptions));
        const appliesLabel = COUPON_APPLIES_LABELS[c.applies_to] || 'Top-ups & billing';
        const statusChip = c.is_active
            ? '<span class="coupon-chip active">Active</span>'
            : '<span class="coupon-chip inactive">Paused</span>';
        const toggleLabel = c.is_active ? 'Pause' : 'Activate';
        const noteRow = c.note
            ? `<div class="enterprise-meta">${escapeHtml(c.note)}</div>`
            : '';
        return `
            <tr>
                <td><div class="user-name coupon-code-cell">${escapeHtml(c.code)}</div>${noteRow}</td>
                <td>${escapeHtml(c.percent_display || (c.percent_off + '%'))}</td>
                <td>${escapeHtml(appliesLabel)}</td>
                <td>${escapeHtml(String(used))} / ${cap}</td>
                <td>${statusChip}</td>
                <td>
                    <button type="button" class="table-btn" data-coupon-action="email"
                        data-coupon-id="${escapeHtml(String(c.id))}" data-coupon-code="${escapeHtml(c.code)}">Email</button>
                    <button type="button" class="table-btn" data-coupon-action="toggle"
                        data-coupon-id="${escapeHtml(String(c.id))}" data-next-active="${c.is_active ? 'false' : 'true'}">${toggleLabel}</button>
                    <button type="button" class="table-btn danger" data-coupon-action="delete"
                        data-coupon-id="${escapeHtml(String(c.id))}" data-coupon-code="${escapeHtml(c.code)}">Delete</button>
                </td>
            </tr>
        `;
    }).join('');
}

async function loadCoupons() {
    if (!state.couponOrg) return;
    if (!await ensureAdminProtection({ silent: false })) return;
    state.couponLoading = true;
    try {
        const response = await fetch(`${API_BASE}/api/admin/enterprise/accounts/${state.couponOrg.id}/coupons`, {
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            await handleAdminAuthOrProtectionError(response.status, payload);
            renderCouponTableMessage(normalizeErrorMessage(payload, 'Failed to load discount codes.'));
            return;
        }
        state.couponList = Array.isArray(payload.coupons) ? payload.coupons : [];
        if (refs.couponModalSubtitle && payload.company_name) {
            refs.couponModalSubtitle.textContent = payload.company_name;
        }
        renderCouponTable();
    } catch (error) {
        console.error('Failed to load discount codes:', error);
        renderCouponTableMessage('Could not load discount codes. Please retry.');
    } finally {
        state.couponLoading = false;
    }
}

async function handleCouponCreateSubmit(event) {
    event.preventDefault();
    if (!state.couponOrg) return;
    if (!await ensureAdminProtection({ silent: false })) return;
    setCouponFormError('');

    const code = (refs.couponCodeInput?.value || '').trim();
    const percentRaw = (refs.couponPercentInput?.value || '').trim();
    const appliesTo = refs.couponAppliesInput?.value || 'all';
    const maxRaw = (refs.couponMaxInput?.value || '').trim();
    const note = (refs.couponNoteInput?.value || '').trim();

    if (!code) { setCouponFormError('Enter a discount code.'); return; }
    if (percentRaw === '' || !Number.isFinite(parseFloat(percentRaw))) {
        setCouponFormError('Enter a discount between 1 and 100%.');
        return;
    }
    const percent = clampCouponPercent(parseFloat(percentRaw));

    const body = {
        code,
        percent_off: percent,
        applies_to: appliesTo,
        is_active: true,
        max_redemptions: maxRaw === '' ? null : Number(maxRaw),
        note: note || null
    };

    if (refs.couponCreateBtn) { refs.couponCreateBtn.disabled = true; refs.couponCreateBtn.textContent = 'Adding...'; }
    try {
        const response = await fetch(`${API_BASE}/api/admin/enterprise/accounts/${state.couponOrg.id}/coupons`, {
            method: 'POST',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            credentials: 'same-origin',
            body: JSON.stringify(body)
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            await handleAdminAuthOrProtectionError(response.status, payload);
            setCouponFormError(normalizeErrorMessage(payload, 'Failed to add discount code.'));
            return;
        }
        refs.couponForm?.reset();
        showFlash(`Discount code ${code.toUpperCase()} added.`, 'success');
        await loadCoupons();
    } catch (error) {
        console.error('Failed to add discount code:', error);
        setCouponFormError('Could not add discount code. Please retry.');
    } finally {
        if (refs.couponCreateBtn) { refs.couponCreateBtn.disabled = false; refs.couponCreateBtn.textContent = 'Add discount code'; }
    }
}

async function handleCouponTableActionClick(event) {
    const button = event.target.closest('[data-coupon-action]');
    if (!button || button.disabled || !state.couponOrg) return;
    const couponId = Number(button.dataset.couponId || 0);
    if (!Number.isFinite(couponId) || couponId <= 0) return;

    if (button.dataset.couponAction === 'toggle') {
        const nextActive = String(button.dataset.nextActive || '').toLowerCase() === 'true';
        await updateCoupon(couponId, { is_active: nextActive });
    } else if (button.dataset.couponAction === 'delete') {
        const code = String(button.dataset.couponCode || 'this code');
        if (!(await confirmDialog(`Discount code "${code}" will be permanently deleted. This cannot be undone.`, { title: 'Delete discount code?', okText: 'Delete' }))) return;
        await deleteCoupon(couponId, code);
    } else if (button.dataset.couponAction === 'email') {
        const code = String(button.dataset.couponCode || 'this code');
        await sendCouponEmail(couponId, code, button);
    }
}

async function sendCouponEmail(couponId, code, button) {
    if (!state.couponOrg) return;
    const company = state.couponOrg.company || 'this account';
    if (!(await confirmDialog(`The "${code}" discount will be emailed to ${company}'s team.`, { title: 'Send discount email?', okText: 'Send email', danger: false }))) return;
    if (!await ensureAdminProtection({ silent: false })) return;
    const original = button ? button.textContent : '';
    if (button) { button.disabled = true; button.textContent = 'Sending...'; }
    try {
        const response = await fetch(`${API_BASE}/api/admin/enterprise/accounts/${state.couponOrg.id}/coupons/${couponId}/send-email`, {
            method: 'POST',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            credentials: 'same-origin',
            body: JSON.stringify({})
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            await handleAdminAuthOrProtectionError(response.status, payload);
            showFlash(normalizeErrorMessage(payload, 'Failed to send the promotion email.'), 'error');
            return;
        }
        showFlash(String(payload?.message || `Promotion email sent for ${code}.`), 'success');
    } catch (error) {
        console.error('Failed to send discount promo email:', error);
        showFlash('Could not send the promotion email. Please retry.', 'error');
    } finally {
        if (button) { button.disabled = false; button.textContent = original || 'Email'; }
    }
}

async function updateCoupon(couponId, patch) {
    if (!state.couponOrg) return;
    if (!await ensureAdminProtection({ silent: false })) return;
    try {
        const response = await fetch(`${API_BASE}/api/admin/enterprise/accounts/${state.couponOrg.id}/coupons/${couponId}`, {
            method: 'PATCH',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            credentials: 'same-origin',
            body: JSON.stringify(patch)
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            await handleAdminAuthOrProtectionError(response.status, payload);
            showFlash(normalizeErrorMessage(payload, 'Failed to update discount code.'), 'error');
            return;
        }
        showFlash('Discount code updated.', 'success');
        await loadCoupons();
    } catch (error) {
        console.error('Failed to update discount code:', error);
        showFlash('Could not update discount code. Please retry.', 'error');
    }
}

async function deleteCoupon(couponId, code) {
    if (!state.couponOrg) return;
    if (!await ensureAdminProtection({ silent: false })) return;
    try {
        const response = await fetch(`${API_BASE}/api/admin/enterprise/accounts/${state.couponOrg.id}/coupons/${couponId}`, {
            method: 'DELETE',
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            await handleAdminAuthOrProtectionError(response.status, payload);
            showFlash(normalizeErrorMessage(payload, 'Failed to delete discount code.'), 'error');
            return;
        }
        showFlash(`Discount code ${code} deleted.`, 'success');
        await loadCoupons();
    } catch (error) {
        console.error('Failed to delete discount code:', error);
        showFlash('Could not delete discount code. Please retry.', 'error');
    }
}

async function handleTableActionClick(event) {
    const button = event.target.closest('[data-action]');
    if (!button || button.disabled || state.loading) return;

    const action = button.dataset.action;
    const userId = Number(button.dataset.userId || 0);
    if (!Number.isFinite(userId) || userId <= 0) return;

    if (action === 'manage-user') {
        await openAccountDetail(userId);
        return;
    }

    if (action === 'toggle-status') {
        const nextActive = String(button.dataset.nextActive || '').toLowerCase() === 'true';
        await updateUserStatus(userId, nextActive, String(button.dataset.userEmail || ''));
        return;
    }

    if (action === 'delete-user') {
        const userEmail = String(button.dataset.userEmail || 'this user');
        const userName = String(button.dataset.userName || '').trim();
        await deleteUser(userId, userEmail, userName);
    }
}

async function updateUserStatus(userId, nextIsActive, userLabel = '') {
    if (!await ensureAdminProtection({ silent: false })) return false;

    // Secondary confirmation — activating/deactivating is an account state change
    // that must never fire from an accidental single click (mirrors delete).
    const who = (userLabel || '').trim() || 'this account';
    const confirmed = await confirmDialog(
        nextIsActive
            ? `${who} will be able to sign in again.`
            : `${who} will be signed out and blocked from signing in until you reactivate the account.`,
        nextIsActive
            ? { title: `Reactivate ${who}?`, okText: 'Reactivate', danger: false }
            : { title: `Deactivate ${who}?`, okText: 'Deactivate' }
    );
    if (!confirmed) return false;

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
        return true;
    } catch (error) {
        console.error('Status update failed:', error);
        showFlash('Failed to update user status.', 'error');
    } finally {
        setRowActionsDisabled(false);
    }
    return false;
}

async function deleteUser(userId, userEmail, userName) {
    if (!await ensureAdminProtection({ silent: false })) return;

    const expectedName = (userName || '').trim();
    if (expectedName) {
        const typedName = await promptDialog(
            `Type this user's name to confirm deletion: ${expectedName}`,
            { title: 'Confirm user deletion', placeholder: expectedName, okText: 'Continue' }
        );
        if (typedName === null) return;
        if (typedName.trim().toLowerCase() !== expectedName.toLowerCase()) {
            showFlash('Name mismatch. User deletion canceled.', 'error');
            return;
        }
    }

    const confirmed = await confirmDialog(`${userEmail} will be permanently deleted. This cannot be undone.`, { title: 'Delete user?', okText: 'Delete' });
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
