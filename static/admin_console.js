const API_BASE = '';
const COOKIE_AUTH_SENTINEL = '__cookie_session__';
const ADMIN_PAGE_SIZE = 20;
const ADMIN_TIME_ZONE = 'UTC';
const ADMIN_TIME_ZONE_LABEL = 'UTC';
const ADMIN_SECTIONS = ['users', 'enterprise', 'analytics', 'finance', 'ai', 'team'];
const ADMIN_SECTION_LABELS = { users: 'Student Accounts', enterprise: 'Enterprise Accounts', analytics: 'Analytics & Agent', finance: 'Investment Analytics', ai: 'AI Costs', team: 'Team' };
// Sidebar tabs in display order. Tasks is not a grantable section: every console member
// gets it, and the server decides task by task who may see or change what.
const ADMIN_TABS = ['users', 'enterprise', 'analytics', 'finance', 'ai', 'tasks', 'team'];
const TASK_STATUSES = [
    { key: 'pending', label: 'Pending' },
    { key: 'in_progress', label: 'In progress' },
    { key: 'on_hold', label: 'On hold' },
    { key: 'done', label: 'Done' },
    { key: 'closed', label: 'Closed' }
];
const TASK_STATUS_LABELS = Object.fromEntries(TASK_STATUSES.map((item) => [item.key, item.label]));
const TASK_OPEN_STATUSES = ['pending', 'in_progress', 'on_hold'];
const TASK_PRIORITIES = [
    { key: 'urgent', label: 'Urgent' },
    { key: 'high', label: 'High' },
    { key: 'medium', label: 'Medium' },
    { key: 'low', label: 'Low' }
];
const TASK_PRIORITY_LABELS = Object.fromEntries(TASK_PRIORITIES.map((item) => [item.key, item.label]));
const TASK_PRIORITY_RANK = { urgent: 0, high: 1, medium: 2, low: 3 };
const TASK_SCOPES = ['mine', 'created', 'all'];
const TASK_PREFS_KEY = 'rilonoAdminTaskPrefs';

const state = {
    authToken: null,
    currentUser: null,
    access: null,
    accessRevision: 0,
    accessRequestId: 0,
    team: { members: [], sections: [], loading: false, saving: false, editingId: null },
    tasks: freshTaskState(),
    taskBadgeRequestId: 0,
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
    usersExportFormat: null,
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
    // Billing controls on the account modal: the open tab survives the re-render that
    // follows every save, and the last result (with any server warnings) is shown above the
    // forms for THAT org only — a notice must never appear on a different account.
    billingTab: 'payment',
    billingNotice: null,        // { orgId, tone: 'success'|'info', text, warnings: [] }
    enterpriseFilters: {
        search: ''
    },
    financeAnalytics: null,
    financeLoading: false,
    financeLeveling: false,
    // AI Costs date filter. start/end are inclusive YYYY-MM-DD (UTC); null = server default.
    aiRange: { preset: '30d', start: null, end: null },
    aiUsageData: null,
    aiUsageRequestId: 0,
    aiProfiles: { page: 1, pageSize: 25, total: 0, search: '', loading: false, exporting: false, requestId: 0, data: null },
    aiAccounts: { loading: false, exporting: false, requestId: 0, data: null },
    aiProfileId: null,
    aiProfileRequestId: 0,
    aiBilling: { data: null, loading: false, syncing: false, requestId: 0 },
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
    teamTabBtn: document.getElementById('adminTeamTabBtn'),
    teamTabPanel: document.getElementById('adminTeamTabPanel'),
    teamForm: document.getElementById('adminTeamForm'),
    teamEmail: document.getElementById('adminTeamEmail'),
    teamRole: document.getElementById('adminTeamRole'),
    teamPassword: document.getElementById('adminTeamPassword'),
    teamPasswordConfirm: document.getElementById('adminTeamPasswordConfirm'),
    teamSections: document.getElementById('adminTeamSections'),
    teamSave: document.getElementById('adminTeamSave'),
    teamCancel: document.getElementById('adminTeamCancel'),
    teamError: document.getElementById('adminTeamError'),
    teamTableBody: document.getElementById('adminTeamTableBody'),
    teamSummary: document.getElementById('adminTeamSummary'),
    teamFormTitle: document.getElementById('adminTeamFormTitle'),
    tasksTabBtn: document.getElementById('adminTasksTabBtn'),
    tasksTabPanel: document.getElementById('adminTasksTabPanel'),
    tasksNavBadge: document.getElementById('adminTasksNavBadge'),
    taskNewBtn: document.getElementById('adminTaskNewBtn'),
    taskScopes: document.getElementById('adminTaskScopes'),
    taskScopeAllLabel: document.getElementById('adminTaskScopeAllLabel'),
    taskSearch: document.getElementById('adminTaskSearch'),
    taskPerson: document.getElementById('adminTaskPerson'),
    taskPersonWrap: document.getElementById('adminTaskPersonWrap'),
    taskShowClosed: document.getElementById('adminTaskShowClosed'),
    taskError: document.getElementById('adminTaskError'),
    taskHint: document.getElementById('adminTaskHint'),
    taskBoard: document.getElementById('adminTaskBoard'),
    taskModal: document.getElementById('adminTaskModal'),
    taskModalEyebrow: document.getElementById('adminTaskModalEyebrow'),
    taskModalTitle: document.getElementById('adminTaskModalTitle'),
    taskModalClose: document.getElementById('adminTaskModalClose'),
    taskModalBody: document.getElementById('adminTaskModalBody'),
    sessionBadge: document.getElementById('adminSessionBadge'),
    sidebar: document.getElementById('adminSidebar'),
    sidebarClose: document.getElementById('adminSidebarClose'),
    sidebarBackdrop: document.getElementById('adminSidebarBackdrop'),
    menuToggle: document.getElementById('adminMenuToggle'),
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
    usersExportActions: document.getElementById('adminUsersExportActions'),
    usersExportCsvBtn: document.getElementById('adminUsersExportCsvBtn'),
    usersExportExcelBtn: document.getElementById('adminUsersExportExcelBtn'),
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
    financeLevelBtn: document.getElementById('adminFinanceLevelBtn'),
    financeLevelStatus: document.getElementById('adminFinanceLevelStatus'),
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
    aiHeroNote: document.getElementById('adminAiHeroNote'),
    aiRangeCaption: document.getElementById('adminAiRangeCaption'),
    aiRangePresets: document.getElementById('adminAiRangePresets'),
    aiRangeForm: document.getElementById('adminAiRangeForm'),
    aiRangeStart: document.getElementById('adminAiRangeStart'),
    aiRangeEnd: document.getElementById('adminAiRangeEnd'),
    aiRangeReset: document.getElementById('adminAiRangeReset'),
    aiRangeError: document.getElementById('adminAiRangeError'),
    aiRangeCost: document.getElementById('adminAiRangeCost'),
    aiCalculatedCost: document.getElementById('adminAiCalculatedCost'),
    aiCalculatedCostSub: document.getElementById('adminAiCalculatedCostSub'),
    aiCalculatedCoverage: document.getElementById('adminAiCalculatedCoverage'),
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
    aiDailyCalculatedTotal: document.getElementById('adminAiDailyCalculatedTotal'),
    aiDailyTotalShare: document.getElementById('adminAiDailyTotalShare'),
    aiProfilesForm: document.getElementById('adminAiProfilesForm'),
    aiProfilesSearch: document.getElementById('adminAiProfilesSearch'),
    aiProfilesApplyBtn: document.getElementById('adminAiProfilesApplyBtn'),
    aiProfilesResetBtn: document.getElementById('adminAiProfilesResetBtn'),
    aiProfilesExportBtn: document.getElementById('adminAiProfilesExportBtn'),
    aiAccountsSummary: document.getElementById('adminAiAccountsSummary'),
    aiOrgsTableBody: document.getElementById('adminAiOrgsTableBody'),
    aiUnlistedTableBody: document.getElementById('adminAiUnlistedTableBody'),
    aiSharedTableBody: document.getElementById('adminAiSharedTableBody'),
    aiUnattributedTableBody: document.getElementById('adminAiUnattributedTableBody'),
    aiAccountsExportBtn: document.getElementById('adminAiAccountsExportBtn'),
    aiProfilesTableBody: document.getElementById('adminAiProfilesTableBody'),
    aiProfilesSummary: document.getElementById('adminAiProfilesSummary'),
    aiProfilesPrevBtn: document.getElementById('adminAiProfilesPrevBtn'),
    aiProfilesNextBtn: document.getElementById('adminAiProfilesNextBtn'),
    aiProfilesPageInfo: document.getElementById('adminAiProfilesPageInfo'),
    aiCoverage: document.getElementById('adminAiCoverage'),
    aiProfileDetail: document.getElementById('adminAiProfileDetail'),
    aiProfileDetailTitle: document.getElementById('adminAiProfileDetailTitle'),
    aiProfileDetailSubtitle: document.getElementById('adminAiProfileDetailSubtitle'),
    aiProfileDetailBody: document.getElementById('adminAiProfileDetailBody'),
    aiProfileCloseBtn: document.getElementById('adminAiProfileCloseBtn'),
    aiReconciliation: document.getElementById('adminAiReconciliation'),
    aiBillingSyncBtn: document.getElementById('adminAiBillingSyncBtn'),
    b2cRevenuePanel: document.getElementById('adminB2cRevenuePanel'),
    b2cRevenue: document.getElementById('adminB2cRevenue'),
    b2cRevenueSub: document.getElementById('adminB2cRevenueSub'),
    b2cActive: document.getElementById('adminB2cActive'),
    b2cCost: document.getElementById('adminB2cCost'),
    b2cCostSub: document.getElementById('adminB2cCostSub'),
    b2cConversion: document.getElementById('adminB2cConversion'),
    b2cConversionSub: document.getElementById('adminB2cConversionSub'),

};

document.addEventListener('DOMContentLoaded', () => {
    setDateColumnTimeZoneLabels();
    bindEvents();
    void bootstrap();
});

function canAccessSection(section) {
    if (section === 'tasks') return Boolean(state.access);
    return Boolean(state.access?.sections?.includes(section)
        && (section !== 'team' || (state.access.role === 'admin' && state.access.can_manage_team)));
}

function canWriteSection(section) {
    if (section === 'tasks') return Boolean(state.access);
    return canAccessSection(section) && ['admin', 'editor'].includes(state.access.role)
        && state.access.can_write_sections.includes(section);
}

function canDeleteSection(section) {
    // Tasks: the server allows a delete only to the task's creator or a team manager.
    if (section === 'tasks') return Boolean(state.access);
    return canAccessSection(section) && state.access.role === 'admin'
        && state.access.can_delete_sections.includes(section);
}

function canProvisionEnterprise() {
    return canWriteSection('enterprise') && Boolean(state.access?.can_provision_enterprise
        ?? (state.currentUser?.is_admin || state.currentUser?.is_developer));
}

function requireAdminPermission(section, action = 'read') {
    const allowed = action === 'delete' ? canDeleteSection(section)
        : action === 'write' ? canWriteSection(section) : canAccessSection(section);
    if (!allowed) showFlash(action === 'read' ? 'You do not have access to this section.'
        : 'Your role does not allow this action.', 'error');
    return allowed;
}

function applyAdminPermissions() {
    if (!document.querySelectorAll) return;
    document.querySelectorAll('[data-admin-write], [data-admin-delete], [data-admin-provision], [data-admin-read]').forEach((element) => {
        const allowed = element.hasAttribute('data-admin-provision') ? canProvisionEnterprise()
            : element.dataset.adminDelete ? canDeleteSection(element.dataset.adminDelete)
                : element.dataset.adminWrite ? canWriteSection(element.dataset.adminWrite)
                    : canAccessSection(element.dataset.adminRead);
        // Restore only visibility hidden by this guard; retain form/dialog lifecycle state.
        if (!allowed) {
            if (!element.hidden) { element.dataset.adminPermissionHidden = 'true'; element.hidden = true; }
            if ('disabled' in element && !element.disabled) { element.dataset.adminPermissionDisabled = 'true'; element.disabled = true; }
        } else {
            if (element.dataset.adminPermissionHidden) { element.hidden = false; delete element.dataset.adminPermissionHidden; }
            if (element.dataset.adminPermissionDisabled) { element.disabled = false; delete element.dataset.adminPermissionDisabled; }
        }
    });
}

function adminRequestSection(url) {
    const path = String(url).split('?')[0];
    if (/\/api\/admin\/team(?:\/|$)/.test(path)) return 'team';
    if (/\/api\/admin\/tasks(?:\/|$)/.test(path)) return 'tasks';
    if (/\/api\/admin\/(?:users|coupons)(?:\/|$)/.test(path)) return 'users';
    if (/\/api\/admin\/enterprise(?:\/|$)/.test(path)) return 'enterprise';
    if (/\/api\/admin\/(?:growth|acquisition)(?:\/|$)/.test(path)) return 'analytics';
    if (/\/api\/admin\/(?:company-finance|b2c)(?:\/|$)/.test(path)) return 'finance';
    if (/\/api\/admin\/ai-usage(?:\/|$)/.test(path)) return 'ai';
    return null;
}

function deniedAdminResponse(message, status = 403) {
    return { ok: false, status, headers: { get: () => null }, json: async () => ({ detail: message }) };
}

// Writes the server files under the Admin ("delete") role rather than Editor: refunds, and
// the billing controls that hand out plan time or credits without a gateway payment
// (app/routers/admin.py "Billing controls"). Mirrored here so an Editor's click is refused
// before a request is sent, with the same message the server would give.
const ADMIN_ROLE_WRITE_PATH_RE = /\/enterprise\/accounts\/[^/]+\/(?:refunds|offline-payment|credits\/adjust|overrides)$/;

async function adminFetch(url, options = {}) {
    const section = adminRequestSection(url);
    const method = String(options.method || 'GET').toUpperCase();
    const destructive = method === 'DELETE'
        || (['POST', 'PUT'].includes(method) && ADMIN_ROLE_WRITE_PATH_RE.test(String(url).split('?')[0]));
    const allowed = section && (destructive ? canDeleteSection(section)
        : ['GET', 'HEAD'].includes(method) ? canAccessSection(section) : canWriteSection(section));
    if (!allowed || (String(url).split('?')[0].endsWith('/enterprise/credentials') && !canProvisionEnterprise())) {
        return deniedAdminResponse('Your role does not allow this action.');
    }
    const revision = state.accessRevision;
    const response = await fetch(url, { ...options, headers: buildAuthHeaders(options.headers) });
    if (revision !== state.accessRevision) return deniedAdminResponse('Your console access changed. Refresh this view.', 409);
    // Access is rechecked for every server denial, including readers whose grants were revoked.
    if (response.status === 401 || response.status === 403) {
        const payload = await response.json().catch(() => ({}));
        await handleAdminAuthOrProtectionError(response.status, payload);
        return deniedAdminResponse(normalizeErrorMessage(payload, 'Your console access changed.'), response.status);
    }
    // Body reads can finish after logout or an access update. Discard those old responses.
    return {
        get ok() { return revision === state.accessRevision && response.ok; },
        status: response.status,
        headers: response.headers,
        async json() {
            const payload = await response.json();
            return revision === state.accessRevision ? payload : { detail: 'Your console access changed.' };
        },
        async blob() {
            const blob = await response.blob();
            if (revision !== state.accessRevision) throw new Error('Your console access changed.');
            return blob;
        }
    };
}

function clearPrivilegedState() {
    state.accessRevision += 1;
    if (refs.loginPassword) refs.loginPassword.value = '';
    ['adminConfirmOverlay', 'adminPromptOverlay'].forEach((id) => {
        const overlay = document.getElementById(id);
        overlay?.dismiss?.();
        overlay?.remove?.();
    });
    state.users = []; state.total = 0; state.loading = false; state.usersExportFormat = null;
    state.metrics = { visa_pass_users: 0, free_users: 0 };
    state.enterpriseAccounts = []; state.enterpriseTotal = 0; state.enterpriseLoading = false;
    state.enterpriseMetrics = { active_members: 0, active_admins: 0 };
    state.financeAnalytics = null; state.financeLoading = false;
    state.accountDetails = null;
    state.couponOrg = null; state.couponList = []; state.couponLoading = false;
    state.billingNotice = null; state.billingTab = 'payment';
    state.aiUsageRequestId += 1; state.aiUsageData = null; state.aiSeries = [];
    state.aiProfiles.requestId += 1; state.aiProfiles.data = null; state.aiProfiles.total = 0;
    state.aiProfiles.loading = false; state.aiProfiles.exporting = false;
    state.aiProfileId = null; state.aiProfileRequestId += 1;
    state.aiBilling.requestId += 1; state.aiBilling.data = null; state.aiBilling.loading = false; state.aiBilling.syncing = false;
    state.team = { members: [], sections: [], loading: false, saving: false, editingId: null };
    clearTaskState();
    const cacheRefs = ['tableBody', 'enterpriseTableBody', 'financeTableBody', 'financeTimelineChart', 'financeBreakdownChart', 'financeContributorChart',
        'aiProfilesTableBody', 'aiProfileDetailBody', 'aiCoverage', 'aiReconciliation', 'aiDailyTableBody', 'aiTimelineChart', 'aiSourceChart', 'aiModelChart',
        'enterpriseCredentialResult', 'accountDetails', 'couponTableBody', 'teamTableBody', 'teamSummary', 'usersSummary', 'enterpriseSummary',
        'aiMonthHero', 'aiTodayCost', 'aiTodaySub', 'ai7Cost', 'ai7Sub', 'aiMonthCost', 'aiMonthSub', 'aiAllCost', 'aiAllSub',
        'aiHeroLabel', 'aiHeroNote', 'aiRangeCaption', 'aiRangeCost', 'aiCalculatedCost', 'aiCalculatedCostSub', 'aiCalculatedCoverage', 'aiRangeSub',
        'aiRangeAvg', 'aiRangeAvgSub', 'aiRangeTopDay', 'aiRangeTopDaySub', 'aiRangeSaved', 'aiRangeSavedSub', 'aiRangeSearch', 'aiRangeSearchSub',
        'aiDailyTotalCalls', 'aiDailyTotalTokens', 'aiDailyTotalCost', 'aiDailyCalculatedTotal', 'aiDailyTotalShare',
        'b2cRevenue', 'b2cRevenueSub', 'b2cActive', 'b2cCost', 'b2cCostSub', 'b2cConversion', 'b2cConversionSub'];
    cacheRefs.forEach((key) => { if (refs[key]) refs[key].textContent = ''; });
    state.financeLeveling = false;
    renderFinanceFounderBalance(null);
    ['adminGrowthResults', 'adminGrowthMeta', 'adminAcquisitionBreakdown', 'adminAcquisitionMeta', 'adminFunnelBody', 'adminOutcomesBody', 'adminAccountBody', 'adminAccountActions', 'adminAccountTitle'].forEach((id) => {
        const element = document.getElementById(id); if (element) element.textContent = '';
    });
    ['couponModal', 'aiProfileDetail', 'enterpriseCredentialResult', 'financeEntryForm'].forEach((key) => { if (refs[key]) refs[key].hidden = true; });
    const accountPanel = document.getElementById('adminAccountDetail');
    if (accountPanel) accountPanel.hidden = true;
    if (document.body?.style) document.body.style.overflow = '';
    document.querySelectorAll?.('.metric-card strong, .finance-hero-stat strong, .metric-subtext').forEach((element) => { element.textContent = '—'; });
    refs.enterpriseCredentialForm?.reset(); refs.financeEntryForm?.reset();
    resetTeamForm();
}

function applyAdminAccess(payload) {
    const sections = ADMIN_SECTIONS.filter((key) => Array.isArray(payload?.sections) && payload.sections.includes(key));
    const access = {
        role: payload?.role,
        sections,
        can_manage_team: Boolean(payload?.can_manage_team),
        can_provision_enterprise: Boolean(payload?.can_provision_enterprise ?? (payload?.user?.is_admin || payload?.user?.is_developer)),
        can_write_sections: sections.filter((key) => payload?.can_write_sections?.includes(key)),
        can_delete_sections: sections.filter((key) => payload?.can_delete_sections?.includes(key))
    };
    if (!payload?.user || !['admin', 'editor', 'viewer'].includes(access.role) || !sections.length) return false;
    if (state.currentUser?.id !== payload.user.id || JSON.stringify(state.access) !== JSON.stringify(access)) clearPrivilegedState();
    state.currentUser = payload.user;
    state.access = access;
    if (!canAccessSection(state.activeTab)) state.activeTab = ADMIN_TABS.find(canAccessSection) || null;
    renderActiveTab(); applyAdminPermissions(); updateSessionBadge();
    return Boolean(state.activeTab);
}

function setTeamError(message = '') {
    if (!refs.teamError) return;
    refs.teamError.textContent = message;
    refs.teamError.hidden = !message;
}

function selectedTeamSections() {
    return Array.from(refs.teamSections?.querySelectorAll('input:checked') || []).map((input) => input.value);
}

function renderTeamSections(selected = []) {
    if (!refs.teamSections) return;
    const adminRole = refs.teamRole?.value === 'admin';
    refs.teamSections.innerHTML = ADMIN_SECTIONS.filter(canAccessSection).map((key) => {
        const disabled = key === 'team' && !adminRole;
        const label = state.team.sections.find((item) => item.key === key)?.label || ADMIN_SECTION_LABELS[key];
        return `<label class="team-section-option${disabled ? ' is-unavailable' : ''}">
            <input type="checkbox" name="sections" value="${key}" ${!disabled && selected.includes(key) ? 'checked' : ''} ${disabled ? 'disabled' : ''}>
            <span>${escapeHtml(label)}${key === 'team' ? '<small>Admin role only</small>' : ''}</span></label>`;
    }).join('');
}

function clearTeamPasswordFields() {
    if (refs.teamPassword) refs.teamPassword.value = '';
    if (refs.teamPasswordConfirm) refs.teamPasswordConfirm.value = '';
}

function resetTeamForm({ focus = false } = {}) {
    state.team.editingId = null;
    refs.teamForm?.reset();
    clearTeamPasswordFields();
    if (refs.teamEmail) { refs.teamEmail.disabled = false; refs.teamEmail.value = ''; }
    if (refs.teamRole) refs.teamRole.value = 'viewer';
    if (refs.teamFormTitle) refs.teamFormTitle.textContent = 'Add a team member';
    if (refs.teamSave) refs.teamSave.textContent = 'Add member';
    if (refs.teamCancel) refs.teamCancel.textContent = 'Reset';
    setTeamError(); renderTeamSections();
    if (focus) refs.teamEmail?.focus();
}

function renderTeamMembers() {
    if (!refs.teamTableBody) return;
    refs.teamTableBody.innerHTML = state.team.members.map((member) => {
        const manageable = Boolean(member.can_manage && !member.protected && canWriteSection('team'));
        const sections = (member.sections || []).filter((key) => ADMIN_SECTIONS.includes(key));
        const roleLabel = { admin: 'Admin', editor: 'Editor', viewer: 'Viewer' }[member.role] || member.role;
        return `<tr><td><div class="user-name">${escapeHtml(member.full_name || member.email)}</div><div class="user-meta">${escapeHtml(member.email)}</div></td>
            <td><span class="role-chip">${escapeHtml(roleLabel)}</span><div class="user-meta">${member.has_console_password ? 'Console password set' : 'Existing Rilono password'}</div>${member.protected ? '<div class="user-meta">Protected platform administrator</div>' : ''}</td>
            <td><div class="team-section-chips">${sections.map((key) => `<span>${escapeHtml(ADMIN_SECTION_LABELS[key])}</span>`).join('')}</div></td>
            <td>${manageable ? `<div class="row-actions"><button type="button" class="table-btn" data-team-action="edit" data-user-id="${escapeHtml(member.user_id)}">Edit</button><button type="button" class="table-btn danger" data-admin-delete="team" data-team-action="revoke" data-user-id="${escapeHtml(member.user_id)}">Revoke access</button></div>`
                : '<span class="user-meta">Access locked</span>'}</td></tr>`;
    }).join('') || '<tr><td colspan="4" class="table-empty">No team members found.</td></tr>';
    if (refs.teamSummary) refs.teamSummary.textContent = `${state.team.members.length} console member${state.team.members.length === 1 ? '' : 's'}`;
    applyAdminPermissions();
}

async function loadTeam() {
    if (!requireAdminPermission('team') || !await ensureAdminProtection({ silent: false })) return;
    setTeamError();
    state.team.loading = true;
    if (refs.teamTableBody) refs.teamTableBody.innerHTML = '<tr><td colspan="4" class="table-empty">Loading team…</td></tr>';
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/team`, { headers: buildAuthHeaders(), credentials: 'same-origin' });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) { setTeamError(normalizeErrorMessage(payload, 'Could not load team members.')); return; }
        // Keep only display/access metadata; credentials must never enter cached state.
        state.team.members = Array.isArray(payload.members) ? payload.members.map((member) => ({
            user_id: member.user_id, email: member.email, full_name: member.full_name,
            role: member.role, sections: member.sections, protected: Boolean(member.protected),
            can_manage: Boolean(member.can_manage), has_console_password: Boolean(member.has_console_password)
        })) : [];
        state.team.sections = Array.isArray(payload.sections) ? payload.sections : [];
        renderTeamMembers(); renderTeamSections(selectedTeamSections());
    } catch { setTeamError('Could not load team members. Please retry.'); }
    finally { state.team.loading = false; }
}

function editTeamMember(userId) {
    if (!requireAdminPermission('team', 'write') || state.team.saving) return;
    clearTeamPasswordFields();
    const member = state.team.members.find((item) => String(item.user_id) === String(userId));
    if (!member || member.protected || !member.can_manage) { setTeamError('This member’s access cannot be changed by your account.'); return; }
    state.team.editingId = member.user_id;
    refs.teamEmail.value = member.email; refs.teamEmail.disabled = true;
    refs.teamRole.value = member.role;
    refs.teamFormTitle.textContent = 'Edit team access';
    refs.teamSave.textContent = 'Save changes'; refs.teamCancel.textContent = 'Cancel edit';
    setTeamError(); renderTeamSections(member.sections); refs.teamRole.focus();
}

function teamMemberPayload() {
    const role = String(refs.teamRole?.value || '');
    const sections = selectedTeamSections().filter((key) => canAccessSection(key) && (key !== 'team' || role === 'admin'));
    if (!['admin', 'editor', 'viewer'].includes(role)) throw new Error('Choose an available role.');
    if (!sections.length) throw new Error('Select at least one section.');
    const payload = { role, sections: [...new Set(sections)] };
    const password = refs.teamPassword?.value || '';
    const confirmation = refs.teamPasswordConfirm?.value || '';
    if (password || confirmation) {
        if (!password.trim()) throw new Error('Enter a new console password or leave both password fields blank.');
        if (password !== confirmation) throw new Error('The console passwords do not match.');
        payload.console_password = password;
    }
    if (state.team.editingId === null) {
        payload.email = (refs.teamEmail?.value || '').trim();
        if (!payload.email) throw new Error('Enter an existing Rilono account email.');
    }
    return payload;
}

function setTeamSaving(saving) {
    state.team.saving = saving;
    refs.teamForm?.setAttribute('aria-busy', String(saving));
    refs.teamForm?.querySelectorAll('input, select, button').forEach((control) => { control.disabled = saving; });
    if (!saving) {
        if (refs.teamEmail) refs.teamEmail.disabled = state.team.editingId !== null;
        refs.teamSections?.querySelectorAll('input').forEach((input) => { input.disabled = input.value === 'team' && refs.teamRole?.value !== 'admin'; });
    }
    if (refs.teamSave) refs.teamSave.textContent = saving ? 'Saving…' : state.team.editingId === null ? 'Add member' : 'Save changes';
    refs.teamTableBody?.querySelectorAll('button').forEach((button) => { button.disabled = saving; });
    applyAdminPermissions();
}

async function saveTeamMember(event) {
    event?.preventDefault();
    if (!requireAdminPermission('team', 'write') || state.team.saving) return;
    setTeamError();
    let payload;
    try { payload = teamMemberPayload(); } catch (error) { setTeamError(error.message); return; }
    if (!await ensureAdminProtection({ silent: false })) return;
    const editingId = state.team.editingId;
    if (editingId !== null) {
        const member = state.team.members.find((item) => String(item.user_id) === String(editingId));
        if (!member || member.protected || !member.can_manage) { setTeamError('This member’s access cannot be changed.'); return; }
    }
    setTeamSaving(true);
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/team${editingId === null ? '' : `/${encodeURIComponent(editingId)}`}`, {
            method: editingId === null ? 'POST' : 'PATCH', headers: buildAuthHeaders({ 'Content-Type': 'application/json' }), credentials: 'same-origin', body: JSON.stringify(payload)
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) { setTeamError(normalizeErrorMessage(result, 'Could not save team access.')); return; }
        resetTeamForm();
        if (await refreshCurrentAdminUser({ silent: true })) {
            if (canAccessSection('team')) await loadTeam(); else await loadActiveTab();
        } else showAuth();
        showFlash(editingId === null ? 'Console access added for the existing account.' : 'Team access updated.', 'success');
    } catch { setTeamError('Could not save team access. Please retry.'); }
    finally { clearTeamPasswordFields(); setTeamSaving(false); }
}

async function revokeTeamMember(userId) {
    if (!requireAdminPermission('team', 'delete') || state.team.saving) return;
    const member = state.team.members.find((item) => String(item.user_id) === String(userId));
    if (!member || member.protected || !member.can_manage) { setTeamError('This member’s access cannot be revoked by your account.'); return; }
    if (!await confirmDialog(`${member.email} will lose admin console access. Their Rilono account and data remain available.`, { title: 'Revoke console access?', okText: 'Revoke access' })) return;
    if (!await ensureAdminProtection({ silent: false })) return;
    setTeamError(); setTeamSaving(true);
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/team/${encodeURIComponent(userId)}`, { method: 'DELETE', headers: buildAuthHeaders(), credentials: 'same-origin' });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) { setTeamError(normalizeErrorMessage(payload, 'Could not revoke console access.')); return; }
        resetTeamForm();
        if (await refreshCurrentAdminUser({ silent: true })) {
            if (canAccessSection('team')) await loadTeam(); else await loadActiveTab();
        } else showAuth();
        showFlash('Console access revoked. The Rilono account was not deleted.', 'success');
    } catch { setTeamError('Could not revoke access. Please retry.'); }
    finally { setTeamSaving(false); }
}

function handleTeamAction(event) {
    const button = event.target.closest('[data-team-action]');
    if (!button || button.disabled) return;
    if (button.dataset.teamAction === 'edit') editTeamMember(button.dataset.userId);
    if (button.dataset.teamAction === 'revoke') void revokeTeamMember(button.dataset.userId);
}

// ---------------------------------------------------------------------------
// Tasks — the team's own small task board (app/routers/admin_tasks.py).
// Every console member can hand work to a teammate; the server decides who sees what.
// ---------------------------------------------------------------------------

function readTaskPrefs() {
    try {
        const raw = JSON.parse(localStorage.getItem(TASK_PREFS_KEY) || '{}');
        return { scope: TASK_SCOPES.includes(raw.scope) ? raw.scope : 'mine', showClosed: raw.showClosed === true };
    } catch { return { scope: 'mine', showClosed: false }; }
}

function saveTaskPrefs() {
    try { localStorage.setItem(TASK_PREFS_KEY, JSON.stringify({ scope: state.tasks.scope, showClosed: state.tasks.showClosed })); } catch { /* per-viewer convenience only */ }
}

function freshTaskState() {
    const prefs = readTaskPrefs();
    return { items: [], members: [], me: null, canViewAll: false, closedTotal: 0, truncated: false,
        loaded: false, loading: false, requestId: 0, scope: prefs.scope, search: '', person: '', showClosed: prefs.showClosed,
        openId: null, detail: null, detailRequestId: 0, editing: false, saving: false, pendingOpenId: null, dragId: null };
}

function clearTaskState() {
    const previous = state.tasks;
    state.tasks = freshTaskState();
    state.tasks.requestId = (previous?.requestId || 0) + 1;
    state.tasks.detailRequestId = (previous?.detailRequestId || 0) + 1;
    state.taskBadgeRequestId += 1;
    if (refs.taskModal && !refs.taskModal.hidden) {
        refs.taskModal.hidden = true;
        if (!refs.couponModal || refs.couponModal.hidden) document.body?.classList?.remove('admin-modal-open');
    }
    if (refs.taskModalBody) refs.taskModalBody.innerHTML = '';
    if (refs.taskBoard) refs.taskBoard.innerHTML = '';
    if (refs.taskSearch) refs.taskSearch.value = '';
    if (refs.taskHint) refs.taskHint.hidden = true;
    if (refs.taskPerson) { refs.taskPerson.innerHTML = '<option value="">Everyone</option>'; refs.taskPerson.value = ''; }
    setTaskError();
    updateTaskScopeUi();  // counts back to 0 and the roster gone, not the last person's numbers
    renderTaskBadge(0);
}

function setTaskError(message = '') {
    if (!refs.taskError) return;
    refs.taskError.textContent = message;
    refs.taskError.hidden = !message;
}

function setTaskModalError(message = '') {
    const line = refs.taskModalBody?.querySelector?.('[data-task-error]');
    if (line) { line.textContent = message; line.hidden = !message; }
    else if (message) showFlash(message, 'error');
}

function taskMe() {
    return state.tasks.me ?? state.currentUser?.id ?? null;
}

function findTask(taskId) {
    return state.tasks.items.find((task) => Number(task.id) === Number(taskId)) || null;
}

function upsertTask(task) {
    if (!task?.id) return;
    const index = state.tasks.items.findIndex((item) => Number(item.id) === Number(task.id));
    if (index === -1) state.tasks.items.unshift(task); else state.tasks.items[index] = task;
}

function removeTask(taskId) {
    state.tasks.items = state.tasks.items.filter((item) => Number(item.id) !== Number(taskId));
}

function taskInScope(task, scope = state.tasks.scope) {
    const me = taskMe();
    const assigneeId = task.assignee?.id ?? null;
    if (scope === 'mine') return assigneeId === me;
    if (scope === 'created') return (task.created_by?.id ?? null) === me && assigneeId !== me;
    return true;
}

function taskMatchesFilters(task) {
    const query = state.tasks.search.trim().toLowerCase();
    if (query) {
        const haystack = [task.title, task.description, task.assignee?.name, task.created_by?.name, `#${task.id}`];
        if (!haystack.some((value) => String(value || '').toLowerCase().includes(query))) return false;
    }
    if (state.tasks.scope === 'all' && state.tasks.person) {
        if (state.tasks.person === 'none') return !task.assignee;
        return String(task.assignee?.id ?? '') === state.tasks.person;
    }
    return true;
}

function taskTime(value) {
    const time = Date.parse(value || '');
    return Number.isNaN(time) ? 0 : time;
}

function sortTasks(items, status) {
    const recent = (a, b) => taskTime(b.status_changed_at || b.updated_at) - taskTime(a.status_changed_at || a.updated_at);
    if (status === 'done' || status === 'closed') return [...items].sort(recent);
    return [...items].sort((a, b) => ((TASK_PRIORITY_RANK[a.priority] ?? 9) - (TASK_PRIORITY_RANK[b.priority] ?? 9))
        || String(a.due_date || '9999-12-31').localeCompare(String(b.due_date || '9999-12-31'))
        || (taskTime(b.updated_at) - taskTime(a.updated_at)));
}

function formatTaskDate(iso) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ''));
    if (!match) return '';
    const [year, month, day] = match.slice(1).map(Number);
    const options = { day: 'numeric', month: 'short', timeZone: 'UTC' };
    if (year !== new Date().getFullYear()) options.year = 'numeric';
    return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString(undefined, options);
}

function taskDueInfo(task) {
    if (!task.due_date) return null;
    const label = formatTaskDate(task.due_date);
    if (['done', 'closed'].includes(task.status)) return { text: `Due ${label}`, tone: '' };
    const today = localIsoDate();
    if (task.due_date < today) return { text: `Overdue · ${label}`, tone: 'is-overdue' };
    if (task.due_date === today) return { text: 'Due today', tone: 'is-today' };
    return { text: `Due ${label}`, tone: '' };
}

function formatRelativeTime(value) {
    const time = taskTime(value);
    if (!time) return '';
    const seconds = Math.round((Date.now() - time) / 1000);
    if (seconds < 45) return 'just now';
    if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))}m ago`;
    if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
    if (seconds < 7 * 86400) return `${Math.round(seconds / 86400)}d ago`;
    const date = new Date(time);
    const options = { day: 'numeric', month: 'short' };
    if (date.getFullYear() !== new Date().getFullYear()) options.year = 'numeric';
    return date.toLocaleDateString(undefined, options);
}

function taskPersonName(person, { you = 'You' } = {}) {
    if (!person) return 'Former member';
    return Number(person.id) === Number(taskMe()) ? you : (person.name || person.email || 'Teammate');
}

function taskInitials(person) {
    const name = String(person?.name || person?.email || '?').trim();
    const parts = name.split(/[\s._-]+/).filter(Boolean);
    return ((parts[0]?.[0] || '?') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
}

function taskAvatar(person) {
    if (!person) return '<span class="tasks-avatar is-empty" aria-hidden="true">?</span>';
    const hue = (Math.abs(Number(person.id) || 0) * 47) % 360;
    return `<span class="tasks-avatar" style="--tasks-avatar-hue:${hue}" aria-hidden="true">${escapeHtml(taskInitials(person))}</span>`;
}

function updateTaskScopeUi() {
    const counts = { mine: 0, created: 0, all: 0 };
    state.tasks.items.forEach((task) => {
        if (task.status === 'closed') return;
        TASK_SCOPES.forEach((scope) => { if (taskInScope(task, scope)) counts[scope] += 1; });
    });
    refs.taskScopes?.querySelectorAll?.('[data-task-scope]').forEach((button) => {
        const active = button.dataset.taskScope === state.tasks.scope;
        button.classList.toggle('is-active', active);
        button.setAttribute('aria-pressed', String(active));
        const count = button.querySelector?.('[data-scope-count]');
        if (count) count.textContent = String(counts[button.dataset.taskScope] ?? 0);
    });
    if (refs.taskScopeAllLabel) refs.taskScopeAllLabel.textContent = state.tasks.canViewAll ? 'All team tasks' : 'All my tasks';
    if (refs.taskPersonWrap) refs.taskPersonWrap.hidden = state.tasks.scope !== 'all';
    if (refs.taskShowClosed) refs.taskShowClosed.checked = state.tasks.showClosed;
}

function renderTaskPersonFilter() {
    if (!refs.taskPerson) return;
    const current = state.tasks.person;
    const options = ['<option value="">Everyone</option>', '<option value="none">Unassigned</option>']
        .concat(state.tasks.members.map((member) => `<option value="${escapeHtml(member.id)}">${escapeHtml(taskPersonName(member, { you: `${member.name} (you)` }))}</option>`));
    refs.taskPerson.innerHTML = options.join('');
    const stillValid = !current || current === 'none' || state.tasks.members.some((member) => String(member.id) === current);
    state.tasks.person = stillValid ? current : '';
    refs.taskPerson.value = state.tasks.person;
}

function renderTaskCard(task) {
    const due = taskDueInfo(task);
    const mine = state.tasks.scope === 'mine';
    const person = mine ? task.created_by : task.assignee;
    const personLabel = mine
        ? `From ${taskPersonName(task.created_by, { you: 'you' })}`
        : (task.assignee ? taskPersonName(task.assignee) : 'Unassigned');
    const priority = TASK_PRIORITY_LABELS[task.priority] || task.priority;
    const status = TASK_STATUS_LABELS[task.status] || task.status;
    const ready = taskReadyToClose(task);
    const label = `${task.title}. ${status}${ready ? ', ready for you to close' : ''}, ${priority} priority${due ? `, ${due.text}` : ''}. ${personLabel}.`;
    const draggable = task.can_edit && !(task.status === 'closed' && !task.can_close);
    return `<div class="tasks-card priority-${escapeHtml(task.priority)}" role="button" tabindex="0" data-task-id="${escapeHtml(task.id)}"
            draggable="${draggable ? 'true' : 'false'}" aria-label="${escapeHtml(label)}">
        <div class="tasks-card-top"><span class="tasks-card-id">#${escapeHtml(task.id)}</span><span class="tasks-card-tags">${ready ? '<span class="tasks-ready-chip">Ready to close</span>' : ''}<span class="tasks-priority priority-${escapeHtml(task.priority)}">${escapeHtml(priority)}</span></span></div>
        <p class="tasks-card-title">${escapeHtml(task.title)}</p>
        <div class="tasks-card-foot">
            <span class="tasks-card-person">${person || !mine ? taskAvatar(person) : ''}<span>${escapeHtml(personLabel)}</span></span>
            <span class="tasks-card-signals">${due ? `<span class="tasks-due ${due.tone}">${escapeHtml(due.text)}</span>` : ''}${task.note_count ? `<span class="tasks-note-count" title="${escapeHtml(task.note_count)} note${task.note_count === 1 ? '' : 's'}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z"/></svg>${escapeHtml(task.note_count)}</span>` : ''}</span>
        </div>
    </div>`;
}

function renderTaskBoard() {
    if (!refs.taskBoard) return;
    updateTaskScopeUi();
    if (!state.tasks.loaded) return;
    const visible = state.tasks.items.filter((task) => taskInScope(task) && taskMatchesFilters(task));
    const columns = TASK_STATUSES.filter((column) => column.key !== 'closed' || state.tasks.showClosed);
    refs.taskBoard.classList.toggle('show-closed', state.tasks.showClosed);
    refs.taskBoard.innerHTML = columns.map((column) => {
        const items = sortTasks(visible.filter((task) => task.status === column.key), column.key);
        const closedNote = column.key === 'closed' && state.tasks.closedTotal > state.tasks.items.filter((task) => task.status === 'closed').length
            ? `<p class="tasks-column-note">Showing the latest closed tasks.</p>` : '';
        return `<section class="tasks-column" data-status="${column.key}" aria-label="${escapeHtml(column.label)}">
            <header class="tasks-column-head"><span class="tasks-status-dot status-${column.key}" aria-hidden="true"></span><h3>${escapeHtml(column.label)}</h3><span class="tasks-column-count">${items.length}</span></header>
            <div class="tasks-column-body" data-drop-status="${column.key}">${items.map(renderTaskCard).join('') || '<p class="tasks-column-empty">No tasks</p>'}${closedNote}</div>
        </section>`;
    }).join('');
    renderTaskHint(visible);
}

function renderTaskHint(visible) {
    if (!refs.taskHint) return;
    let text = '';
    const filtered = Boolean(state.tasks.search.trim() || (state.tasks.scope === 'all' && state.tasks.person));
    const openVisible = visible.filter((task) => task.status !== 'closed').length;
    if (state.tasks.truncated) text = 'Showing the 500 most recently updated open tasks.';
    else if (!openVisible && filtered) text = 'No tasks match these filters.';
    else if (!openVisible && state.tasks.scope === 'mine') text = 'Nothing is assigned to you right now. Tasks a teammate gives you will appear under Pending.';
    else if (!openVisible && state.tasks.scope === 'created') text = 'You haven’t handed out any open tasks. Use New task to assign one to a teammate.';
    else if (!openVisible) text = 'No open tasks yet. Use New task to assign one to a teammate.';
    refs.taskHint.textContent = text;
    refs.taskHint.hidden = !text;
}

function renderTaskBadge(count) {
    const total = Math.max(0, Number(count) || 0);
    if (refs.tasksNavBadge) {
        refs.tasksNavBadge.hidden = total === 0;
        refs.tasksNavBadge.textContent = total > 99 ? '99+' : String(total);
    }
    refs.tasksTabBtn?.setAttribute('aria-label', total ? `Tasks, ${total} open assigned to you` : 'Tasks');
}

function updateTaskBadgeFromItems() {
    if (!state.tasks.loaded) return;
    const me = taskMe();
    renderTaskBadge(state.tasks.items.filter((task) => task.assignee?.id === me && TASK_OPEN_STATUSES.includes(task.status)).length);
}

async function refreshTaskBadge() {
    if (!canAccessSection('tasks') || !await ensureAdminProtection({ silent: true })) return;
    const requestId = ++state.taskBadgeRequestId;
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/tasks/summary`, { headers: buildAuthHeaders(), credentials: 'same-origin' });
        const payload = await response.json().catch(() => ({}));
        if (requestId !== state.taskBadgeRequestId || !response.ok) return;
        renderTaskBadge(payload.assigned_open);
    } catch { /* the badge is a hint; the board is the record */ }
}

async function loadTasks({ quiet = false } = {}) {
    if (!canAccessSection('tasks') || !await ensureAdminProtection({ silent: quiet })) return;
    const requestId = ++state.tasks.requestId;
    state.tasks.loading = true;
    if (!quiet) setTaskError();
    if (!state.tasks.loaded && refs.taskBoard) refs.taskBoard.innerHTML = '<p class="tasks-loading">Loading tasks…</p>';
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/tasks`, { headers: buildAuthHeaders(), credentials: 'same-origin' });
        const payload = await response.json().catch(() => ({}));
        if (requestId !== state.tasks.requestId) return;
        if (!response.ok) {
            setTaskError(normalizeErrorMessage(payload, 'Could not load tasks.'));
            if (!state.tasks.loaded && refs.taskBoard) refs.taskBoard.innerHTML = '';
            return;
        }
        state.tasks.items = Array.isArray(payload.tasks) ? payload.tasks : [];
        state.tasks.members = Array.isArray(payload.members) ? payload.members : [];
        state.tasks.me = payload.me ?? state.currentUser?.id ?? null;
        state.tasks.canViewAll = Boolean(payload.can_view_all);
        state.tasks.closedTotal = Number(payload.closed_total) || 0;
        state.tasks.truncated = Boolean(payload.truncated);
        state.tasks.loaded = true;
        setTaskError();
        renderTaskPersonFilter();
        renderTaskBoard();
        updateTaskBadgeFromItems();
        const pending = state.tasks.pendingOpenId;
        if (pending) { state.tasks.pendingOpenId = null; void openTaskDetail(pending); }
    } catch {
        if (requestId === state.tasks.requestId) setTaskError('Could not load tasks. Please retry.');
    } finally {
        if (requestId === state.tasks.requestId) state.tasks.loading = false;
    }
}

function setTaskScope(scope) {
    if (!TASK_SCOPES.includes(scope) || state.tasks.scope === scope) return;
    state.tasks.scope = scope;
    saveTaskPrefs();
    renderTaskBoard();
}

// ---- Task modal: create form and detail view --------------------------------

function taskOptions(items, selected, isDisabled = () => false) {
    return items.map((item) => `<option value="${escapeHtml(item.key)}" ${item.key === selected ? 'selected' : ''} ${isDisabled(item) ? 'disabled' : ''}>${escapeHtml(item.label)}</option>`).join('');
}

// The assignee takes a task up to Done; only whoever assigned it (or a team manager) can
// close it, or reopen it once closed. The server enforces this; the UI just doesn't offer it.
function taskStatusLocked(task, status) {
    return Boolean(task && !task.can_close && task.status !== status && (status === 'closed' || task.status === 'closed'));
}

function taskAssignerName(task) {
    return task?.created_by ? taskPersonName(task.created_by) : 'A team manager';
}

function taskCloseDeniedMessage(task, status) {
    return status === 'closed'
        ? `Only ${taskAssignerName(task)} can close this task. Mark it Done and they’ll review it.`
        : `This task is closed. Only ${taskAssignerName(task)} can reopen it.`;
}

function taskReadyToClose(task) {
    return task.status === 'done' && task.can_close && Boolean(task.assignee) && Number(task.assignee.id) !== Number(taskMe());
}

function taskAssigneeOptions(selectedId, current = null) {
    const selected = selectedId === null || selectedId === undefined ? '' : String(selectedId);
    const me = taskMe();
    const members = [...state.tasks.members].sort((a, b) => (Number(b.id) === Number(me)) - (Number(a.id) === Number(me)));
    const options = [`<option value="" ${selected === '' ? 'selected' : ''}>Unassigned</option>`];
    if (current && !members.some((member) => String(member.id) === String(current.id))) {
        // Keep showing who has it even after they lost console access, so it can be reassigned.
        options.push(`<option value="${escapeHtml(current.id)}" selected disabled>${escapeHtml(current.name)} (no console access)</option>`);
    }
    members.forEach((member) => {
        const label = Number(member.id) === Number(me) ? `Me (${member.name})` : member.name;
        options.push(`<option value="${escapeHtml(member.id)}" ${String(member.id) === selected ? 'selected' : ''}>${escapeHtml(label)}</option>`);
    });
    return options.join('');
}

function showTaskModal({ returnTaskId = null } = {}) {
    if (!refs.taskModal) return;
    if (refs.taskModal.hidden) {
        state.tasks.returnFocus = document.activeElement || null;
        state.tasks.returnTaskId = returnTaskId;
    }
    refs.taskModal.hidden = false;
    state.tasks.openedAt = Date.now();
    document.body?.classList?.add('admin-modal-open');
    // Keyboard and screen-reader focus stay in the dialog while it is open.
    const shell = document.querySelector?.('.admin-shell');
    if (shell) shell.inert = true;
}

function focusTaskDialog() {
    refs.taskModal?.querySelector?.('[role="dialog"]')?.focus?.({ preventScroll: true });
}

function closeTaskModal() {
    state.tasks.openId = null;
    state.tasks.detail = null;
    state.tasks.editing = false;
    state.tasks.detailRequestId += 1;
    clearTaskHash();
    if (!refs.taskModal || refs.taskModal.hidden) return;
    refs.taskModal.hidden = true;
    if (refs.taskModalBody) refs.taskModalBody.innerHTML = '';
    if (!refs.couponModal || refs.couponModal.hidden) document.body?.classList?.remove('admin-modal-open');
    const shell = document.querySelector?.('.admin-shell');
    if (shell) shell.inert = false;
    // The board re-renders while a task is open, so find the card again by id.
    const card = state.tasks.returnTaskId ? refs.taskBoard?.querySelector?.(`[data-task-id="${Number(state.tasks.returnTaskId)}"]`) : null;
    const focusTarget = card || (state.tasks.returnFocus?.isConnected ? state.tasks.returnFocus : refs.taskNewBtn);
    state.tasks.returnFocus = null; state.tasks.returnTaskId = null;
    focusTarget?.focus?.({ preventScroll: true });
}

// Which control had focus, so a re-render after saving can put the user back there.
function taskFocusKey(element) {
    if (!element || !refs.taskModalBody?.contains?.(element)) return null;
    if (element.dataset?.taskField) return `[data-task-field="${element.dataset.taskField}"]`;
    if (element.closest?.('[data-task-form="note"]')) return '[data-task-form="note"] textarea';
    if (element.dataset?.taskAction) return `[data-task-action="${element.dataset.taskAction}"]`;
    return null;
}

function taskModalHasDraft() {
    const body = refs.taskModalBody;
    if (!body?.querySelector) return false;
    const note = body.querySelector('[data-task-form="note"] textarea');
    if (note && note.value.trim()) return true;
    if (state.tasks.editing || body.querySelector('[data-task-typing]')) return true;
    const create = body.querySelector('[data-task-form="create"]');
    return Boolean(create && [...create.querySelectorAll('input[type="text"], textarea')].some((field) => field.value.trim()));
}

async function requestCloseTaskModal() {
    if (state.tasks.saving) return;
    if (taskModalHasDraft() && !(await confirmDialog('What you typed in this task hasn’t been saved.', { title: 'Discard your changes?', okText: 'Discard', cancelText: 'Keep editing' }))) return;
    closeTaskModal();
}

function setTaskSaving(saving) {
    state.tasks.saving = saving;
    refs.taskModal?.querySelector?.('[role="dialog"]')?.setAttribute('aria-busy', String(saving));
    refs.taskModalBody?.querySelectorAll?.('input, select, textarea, button').forEach((control) => {
        control.disabled = saving || Boolean(control.hasAttribute?.('data-task-locked'));
    });
}

async function openTaskCreate() {
    if (!canWriteSection('tasks') || state.tasks.saving) return;
    if (!state.tasks.loaded) { await loadTasks(); if (!state.tasks.loaded) return; }
    state.tasks.openId = null; state.tasks.detail = null; state.tasks.editing = false;
    state.tasks.detailRequestId += 1;
    const me = taskMe();
    const others = state.tasks.members.filter((member) => Number(member.id) !== Number(me));
    // With one teammate (today's two-founder team) the obvious assignee is preselected.
    const defaultAssignee = others.length === 1 ? others[0].id : '';
    if (refs.taskModalEyebrow) refs.taskModalEyebrow.textContent = 'New task';
    if (refs.taskModalTitle) refs.taskModalTitle.textContent = 'Assign a task';
    refs.taskModalBody.innerHTML = `<form class="tasks-form" data-task-form="create" novalidate>
        <label class="tasks-field"><span>Title</span><input type="text" name="title" maxlength="200" required placeholder="What needs to be done?" autocomplete="off"></label>
        <label class="tasks-field"><span>Details <span class="tasks-optional">(optional)</span></span><textarea name="description" rows="4" maxlength="5000" placeholder="Context, links, and what “done” looks like"></textarea></label>
        <div class="tasks-form-grid">
            <label class="tasks-field"><span>Assign to</span><select name="assignee_user_id">${taskAssigneeOptions(defaultAssignee)}</select></label>
            <label class="tasks-field"><span>Priority</span><select name="priority">${taskOptions(TASK_PRIORITIES, 'medium')}</select></label>
            <label class="tasks-field"><span>Due date <span class="tasks-optional">(optional)</span></span><input type="date" name="due_date" min="2000-01-01" max="2100-12-31"></label>
        </div>
        <p class="tasks-error" data-task-error role="alert" hidden></p>
        <div class="tasks-form-actions"><button type="button" class="ghost-btn small-btn" data-task-action="cancel">Cancel</button><button type="submit" class="primary-btn small-btn">Create task</button></div>
    </form>`;
    showTaskModal();
    refs.taskModalBody.querySelector?.('input[name="title"]')?.focus();
}

function readTaskCreateForm(form) {
    const field = (name) => form.querySelector(`[name="${name}"]`);
    const title = (field('title')?.value || '').trim();
    if (!title) throw new Error('Give the task a title.');
    const assignee = field('assignee_user_id')?.value || '';
    return {
        title,
        description: (field('description')?.value || '').trim() || null,
        assignee_user_id: assignee ? Number(assignee) : null,
        priority: TASK_PRIORITY_LABELS[field('priority')?.value] ? field('priority').value : 'medium',
        due_date: field('due_date')?.value || null
    };
}

async function submitTaskCreate(form) {
    if (state.tasks.saving || !canWriteSection('tasks')) return;
    let payload;
    try { payload = readTaskCreateForm(form); } catch (error) { setTaskModalError(error.message); form.querySelector('[name="title"]')?.focus(); return; }
    if (!await ensureAdminProtection({ silent: false })) return;
    setTaskModalError(); setTaskSaving(true);
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/tasks`, {
            method: 'POST', headers: buildAuthHeaders({ 'Content-Type': 'application/json' }), credentials: 'same-origin', body: JSON.stringify(payload)
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || !result.task) { setTaskModalError(normalizeErrorMessage(result, 'Could not create the task.')); return; }
        upsertTask(result.task);
        // Show the task where it now lives, so creating one never looks like nothing happened.
        if (!taskInScope(result.task)) { state.tasks.scope = taskInScope(result.task, 'mine') ? 'mine' : taskInScope(result.task, 'created') ? 'created' : 'all'; saveTaskPrefs(); }
        closeTaskModal();
        renderTaskBoard(); updateTaskBadgeFromItems();
        const assignee = result.task.assignee;
        showFlash(assignee && Number(assignee.id) !== Number(taskMe()) ? `Task assigned to ${assignee.name}. They’ll get an email.` : 'Task created.', 'success');
    } catch { setTaskModalError('Could not create the task. Please retry.'); }
    finally { setTaskSaving(false); }
}

async function openTaskDetail(taskId) {
    const id = Number(taskId);
    if (!id || !canAccessSection('tasks') || !await ensureAdminProtection({ silent: false })) return;
    state.tasks.openId = id; state.tasks.detail = null; state.tasks.editing = false;
    const requestId = ++state.tasks.detailRequestId;
    const cached = findTask(id);
    if (refs.taskModalEyebrow) refs.taskModalEyebrow.textContent = `Task #${id}`;
    if (refs.taskModalTitle) refs.taskModalTitle.textContent = cached?.title || 'Loading task…';
    if (refs.taskModalBody) refs.taskModalBody.innerHTML = '<p class="tasks-loading">Loading task…</p>';
    const wasOpen = refs.taskModal && !refs.taskModal.hidden;
    showTaskModal({ returnTaskId: id });
    if (!wasOpen) focusTaskDialog();
    setTaskHash(id);
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/tasks/${encodeURIComponent(id)}`, { headers: buildAuthHeaders(), credentials: 'same-origin' });
        const payload = await response.json().catch(() => ({}));
        if (requestId !== state.tasks.detailRequestId || state.tasks.openId !== id) return;
        if (!response.ok) {
            if (response.status === 404) { removeTask(id); renderTaskBoard(); updateTaskBadgeFromItems(); }
            if (refs.taskModalTitle) refs.taskModalTitle.textContent = 'Task unavailable';
            const message = response.status === 404 ? 'This task was deleted, or it isn’t shared with you.' : normalizeErrorMessage(payload, 'Could not load this task.');
            if (refs.taskModalBody) refs.taskModalBody.innerHTML = `<p class="tasks-error">${escapeHtml(message)}</p>`;
            return;
        }
        applyTaskDetail(payload);
    } catch {
        if (requestId === state.tasks.detailRequestId && refs.taskModalBody) refs.taskModalBody.innerHTML = '<p class="tasks-error">Could not load this task. Please retry.</p>';
    }
}

function applyTaskDetail(payload, { keepNote = true, endEdit = false } = {}) {
    if (!payload?.visible || !payload.task) {
        const id = state.tasks.openId;
        if (id) removeTask(id);
        closeTaskModal(); renderTaskBoard(); updateTaskBadgeFromItems();
        return false;
    }
    state.tasks.detail = { task: payload.task, timeline: Array.isArray(payload.timeline) ? payload.timeline : [] };
    if (endEdit) state.tasks.editing = false;
    upsertTask(payload.task);
    renderTaskBoard(); updateTaskBadgeFromItems();
    renderTaskDetail({ keepNote, keepEdit: !endEdit });
    return true;
}

function describeTaskEvent(entry) {
    const strong = (value) => `<strong>${escapeHtml(value || '—')}</strong>`;
    const meId = String(taskMe());
    switch (entry.kind) {
    case 'created':
        if (!entry.to) return 'created this task';
        return `created this task and assigned it to ${entry.to === meId ? strong('you') : strong(entry.to_label)}`;
    case 'status': return `moved it from ${strong(entry.from_label)} to ${strong(entry.to_label)}`;
    case 'assignee':
        if (!entry.to) return `unassigned ${strong(entry.from_label)}`;
        if (!entry.from) return `assigned it to ${entry.to === meId ? strong('you') : strong(entry.to_label)}`;
        return `reassigned it from ${strong(entry.from_label)} to ${entry.to === meId ? strong('you') : strong(entry.to_label)}`;
    case 'priority': return `changed the priority from ${strong(entry.from_label)} to ${strong(entry.to_label)}`;
    case 'due_date': return entry.to ? `set the due date to ${strong(entry.to_label)}` : 'removed the due date';
    case 'edited': {
        const fields = String(entry.to || '').split(',').filter(Boolean).map((field) => escapeHtml(field));
        return `edited the ${fields.join(' and ') || 'task'}`;
    }
    default: return 'updated this task';
    }
}

function renderTaskTimelineEntry(entry) {
    const who = taskPersonName(entry.author);
    const when = `<time datetime="${escapeHtml(entry.created_at || '')}" title="${escapeHtml(formatDateTime(entry.created_at))} UTC">${escapeHtml(formatRelativeTime(entry.created_at))}</time>`;
    if (entry.kind === 'note') {
        return `<li class="tasks-entry tasks-entry-note">${taskAvatar(entry.author)}<div class="tasks-entry-bubble">
            <div class="tasks-entry-head"><strong>${escapeHtml(who)}</strong>${when}${entry.can_delete ? `<button type="button" class="tasks-link-btn" data-task-action="delete-note" data-note-id="${escapeHtml(entry.id)}">Delete</button>` : ''}</div>
            <p>${escapeHtml(entry.body)}</p></div></li>`;
    }
    return `<li class="tasks-entry tasks-entry-event"><span class="tasks-entry-dot status-${escapeHtml(entry.kind === 'status' ? entry.to : 'event')}" aria-hidden="true"></span><p><strong>${escapeHtml(who)}</strong> ${describeTaskEvent(entry)} · ${when}</p></li>`;
}

function renderTaskDetail({ keepNote = true, keepEdit = true } = {}) {
    const detail = state.tasks.detail;
    if (!detail || !refs.taskModalBody) return;
    const { task, timeline } = detail;
    // A status change made while a note or an edit is half-written must not wipe it.
    const sameTask = refs.taskModalBody.dataset?.taskId === String(task.id);
    const draftNote = keepNote && sameTask ? refs.taskModalBody.querySelector?.('[data-task-form="note"] textarea')?.value || '' : '';
    const editForm = keepEdit && sameTask && state.tasks.editing ? refs.taskModalBody.querySelector?.('[data-task-form="edit"]') : null;
    const draftEdit = editForm ? { title: editForm.querySelector('[name="title"]')?.value, description: editForm.querySelector('[name="description"]')?.value } : null;
    const wasEditing = Boolean(refs.taskModalBody.querySelector?.('[data-task-form="edit"]'));
    const editable = Boolean(task.can_edit);
    const lock = editable ? '' : 'disabled data-task-locked';
    if (refs.taskModalEyebrow) refs.taskModalEyebrow.textContent = `Task #${task.id} · ${TASK_STATUS_LABELS[task.status] || task.status}`;
    if (refs.taskModalTitle) refs.taskModalTitle.textContent = task.title;
    const description = state.tasks.editing
        ? `<form class="tasks-form" data-task-form="edit" novalidate>
            <label class="tasks-field"><span>Title</span><input type="text" name="title" maxlength="200" required value="${escapeHtml(task.title)}" autocomplete="off"></label>
            <label class="tasks-field"><span>Details</span><textarea name="description" rows="5" maxlength="5000">${escapeHtml(task.description)}</textarea></label>
            <div class="tasks-form-actions"><button type="button" class="ghost-btn small-btn" data-task-action="cancel-edit">Cancel</button><button type="submit" class="primary-btn small-btn">Save</button></div>
        </form>`
        : (task.description ? `<p class="tasks-description">${escapeHtml(task.description)}</p>` : '<p class="tasks-muted">No details yet.</p>');
    const due = taskDueInfo(task);
    const assigneeGone = task.assignee && !task.assignee.has_access;
    let statusHint = '';
    if (!task.can_close && task.status === 'closed') statusHint = `Closed. Only ${taskAssignerName(task)} can reopen it.`;
    else if (!task.can_close) statusHint = `When it’s finished, mark it Done. ${taskAssignerName(task)} reviews it and closes it.`;
    else if (taskReadyToClose(task)) statusHint = `${taskPersonName(task.assignee)} marked this Done. Close it, or move it back if something’s missing.`;
    refs.taskModalBody.innerHTML = `<div class="tasks-detail">
        <div class="tasks-detail-main">
            <section class="tasks-detail-section">
                <div class="tasks-section-head"><h4>Details</h4>${editable && !state.tasks.editing ? '<button type="button" class="tasks-link-btn" data-task-action="edit">Edit</button>' : ''}</div>
                ${description}
            </section>
            <section class="tasks-detail-section">
                <div class="tasks-section-head"><h4>Notes &amp; activity</h4><span class="tasks-muted">${Number(task.note_count) || 0} note${Number(task.note_count) === 1 ? '' : 's'}</span></div>
                ${editable ? `<form class="tasks-note-form" data-task-form="note" novalidate>
                    <label class="tasks-sr-only" for="adminTaskNoteInput">Add a note</label>
                    <textarea id="adminTaskNoteInput" name="body" rows="3" maxlength="4000" placeholder="Add a note: progress, blockers, what’s left"></textarea>
                    <div class="tasks-note-actions"><span class="tasks-muted">Ctrl / ⌘ + Enter to post</span><button type="submit" class="primary-btn small-btn">Add note</button></div>
                </form>` : ''}
                <ol class="tasks-timeline">${timeline.map(renderTaskTimelineEntry).join('') || '<li class="tasks-muted">No activity yet.</li>'}</ol>
            </section>
        </div>
        <aside class="tasks-detail-side" aria-label="Task details">
            <label class="tasks-prop"><span>Status</span><select data-task-field="status" ${editable && !(task.status === 'closed' && !task.can_close) ? '' : 'disabled data-task-locked'}>${taskOptions(TASK_STATUSES, task.status, (item) => taskStatusLocked(task, item.key))}</select></label>
            ${statusHint ? `<p class="tasks-prop-hint">${escapeHtml(statusHint)}</p>` : ''}
            <label class="tasks-prop"><span>Assignee</span><select data-task-field="assignee_user_id" ${lock}>${taskAssigneeOptions(task.assignee?.id ?? '', task.assignee)}</select></label>
            ${assigneeGone ? '<p class="tasks-warn">This person no longer has console access. Reassign the task.</p>' : ''}
            <label class="tasks-prop"><span>Priority</span><select data-task-field="priority" ${lock}>${taskOptions(TASK_PRIORITIES, task.priority)}</select></label>
            <label class="tasks-prop"><span>Due date</span><input type="date" data-task-field="due_date" value="${escapeHtml(task.due_date || '')}" min="2000-01-01" max="2100-12-31" ${lock}></label>
            ${due?.tone ? `<p class="tasks-due ${due.tone}">${escapeHtml(due.text)}</p>` : ''}
            <dl class="tasks-facts">
                <div><dt>Created by</dt><dd>${escapeHtml(taskPersonName(task.created_by))}</dd></div>
                <div><dt>Created</dt><dd title="${escapeHtml(formatDateTime(task.created_at))} UTC">${escapeHtml(formatRelativeTime(task.created_at))}</dd></div>
                <div><dt>Last update</dt><dd title="${escapeHtml(formatDateTime(task.updated_at))} UTC">${escapeHtml(formatRelativeTime(task.updated_at))}</dd></div>
            </dl>
            <p class="tasks-error" data-task-error role="alert" hidden></p>
            ${task.can_delete ? '<button type="button" class="table-btn danger tasks-delete-btn" data-task-action="delete">Delete task</button>' : ''}
        </aside>
    </div>`;
    if (refs.taskModalBody.dataset) refs.taskModalBody.dataset.taskId = String(task.id);
    const noteField = refs.taskModalBody.querySelector?.('[data-task-form="note"] textarea');
    if (noteField && draftNote) noteField.value = draftNote;
    const edit = refs.taskModalBody.querySelector?.('[data-task-form="edit"]');
    if (edit && draftEdit) {
        if (typeof draftEdit.title === 'string') edit.querySelector('[name="title"]').value = draftEdit.title;
        if (typeof draftEdit.description === 'string') edit.querySelector('[name="description"]').value = draftEdit.description;
    }
    if (edit && !wasEditing) edit.querySelector('[name="title"]')?.focus();
    else if (state.tasks.focusKey) refs.taskModalBody.querySelector?.(state.tasks.focusKey)?.focus?.({ preventScroll: true });
    state.tasks.focusKey = null;
}

async function patchTask(taskId, body, { endEdit = false } = {}) {
    if (state.tasks.saving) return false;
    if (!await ensureAdminProtection({ silent: false })) return false;
    const id = Number(taskId);
    state.tasks.focusKey = taskFocusKey(document.activeElement);
    setTaskSaving(true); setTaskModalError(); setTaskError();
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/tasks/${encodeURIComponent(id)}`, {
            method: 'PATCH', headers: buildAuthHeaders({ 'Content-Type': 'application/json' }), credentials: 'same-origin', body: JSON.stringify(body)
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            const message = response.status === 404 ? 'This task was deleted, or it isn’t shared with you any more.' : normalizeErrorMessage(payload, 'Could not save the change.');
            if (response.status === 404) { removeTask(id); renderTaskBoard(); updateTaskBadgeFromItems(); }
            if (state.tasks.openId === id) setTaskModalError(message); else setTaskError(message);
            return false;
        }
        if (!payload.visible || !payload.task) {
            removeTask(id);
            if (state.tasks.openId === id) closeTaskModal();
            renderTaskBoard(); updateTaskBadgeFromItems();
            showFlash('Task handed off. It has left your board.', 'success');
            return true;
        }
        if (state.tasks.openId === id) applyTaskDetail(payload, { endEdit });
        else { upsertTask(payload.task); renderTaskBoard(); updateTaskBadgeFromItems(); }
        return true;
    } catch {
        if (state.tasks.openId === id) setTaskModalError('Could not save the change. Please retry.'); else setTaskError('Could not save the change. Please retry.');
        return false;
    } finally { setTaskSaving(false); }
}

async function askOnHoldNote() {
    const reason = await promptDialog('Add a short note so everyone knows what it’s waiting on.', {
        title: 'Put this task on hold?', okText: 'Put on hold', placeholder: 'Waiting on… (optional)'
    });
    return reason === null ? null : reason.trim();
}

// A pick with the mouse (or the date picker) saves at once. Typing a date, or arrowing
// through a select, fires `change` on every keystroke — those save on Enter or on leaving
// the field, so "15" is never saved as the 1st and no year is ever saved as 0002.
function handleTaskFieldChange(event) {
    const control = event.target.closest?.('[data-task-field]');
    if (!control || control.dataset.taskTyping) return;
    void commitTaskField(control);
}

function handleTaskFieldKeydown(event) {
    const control = event.target.closest?.('[data-task-field]');
    if (!control) return;
    if (event.key === 'Enter') { event.preventDefault(); delete control.dataset.taskTyping; void commitTaskField(control); return; }
    if (!['Tab', 'Escape', 'Shift', 'Control', 'Alt', 'Meta'].includes(event.key)) control.dataset.taskTyping = '1';
}

function handleTaskFieldBlur(event) {
    const control = event.target.closest?.('[data-task-field]');
    if (!control?.dataset.taskTyping) return;
    delete control.dataset.taskTyping;
    void commitTaskField(control);
}

async function commitTaskField(control) {
    const detail = state.tasks.detail;
    if (!control || !detail || state.tasks.saving) return;
    const task = detail.task;
    const field = control.dataset.taskField;
    const current = field === 'assignee_user_id' ? (task.assignee?.id ?? null) : (task[field] ?? null);
    let value = control.value;
    if (field === 'assignee_user_id') value = value ? Number(value) : null;
    if (field === 'due_date') value = value || null;
    const restore = () => { control.value = current === null ? '' : String(current); };
    if (value === current) return;
    if (field === 'due_date' && (control.validity?.badInput || (value && !/^(20\d\d|2100)-\d\d-\d\d$/.test(value)))) {
        restore();
        setTaskModalError('Enter a full due date between 2000 and 2100, or clear the field.');
        return;
    }
    const body = { [field]: value };
    if (field === 'status' && value === 'on_hold') {
        const reason = await askOnHoldNote();
        if (reason === null) { restore(); return; }
        if (reason) body.note = reason;
    }
    const me = Number(taskMe());
    if (field === 'assignee_user_id' && !state.tasks.canViewAll && Number(task.created_by?.id) !== me && value !== me) {
        const member = state.tasks.members.find((item) => Number(item.id) === value);
        const message = value ? `${member?.name || 'Your teammate'} will own this task, and it will leave your board.` : 'This task will be unassigned, and it will leave your board.';
        if (!(await confirmDialog(message, { title: 'Hand this task off?', okText: value ? 'Reassign' : 'Unassign', danger: false }))) { restore(); return; }
    }
    if (!(await patchTask(task.id, body))) restore();
}

async function moveTaskStatus(taskId, status) {
    const task = findTask(taskId);
    if (!task || !task.can_edit || task.status === status || !TASK_STATUS_LABELS[status] || state.tasks.saving) return;
    if (taskStatusLocked(task, status)) { setTaskError(taskCloseDeniedMessage(task, status)); return; }
    const body = { status };
    if (status === 'on_hold') {
        const reason = await askOnHoldNote();
        if (reason === null) return;
        if (reason) body.note = reason;
    }
    const previous = task.status;
    task.status = status;  // move the card now; the server's copy replaces it on success
    renderTaskBoard();
    if (!(await patchTask(task.id, body))) {
        const stale = findTask(task.id);
        if (stale && stale.status === status) { stale.status = previous; renderTaskBoard(); }
    }
}

async function submitTaskEdit(form) {
    const task = state.tasks.detail?.task;
    if (!task || state.tasks.saving) return;
    const title = (form.querySelector('[name="title"]')?.value || '').trim();
    const description = (form.querySelector('[name="description"]')?.value || '').trim();
    if (!title) { setTaskModalError('Give the task a title.'); return; }
    const body = {};
    if (title !== task.title) body.title = title;
    if (description !== (task.description || '')) body.description = description || null;
    if (!Object.keys(body).length) { state.tasks.editing = false; renderTaskDetail({ keepEdit: false }); return; }
    await patchTask(task.id, body, { endEdit: true });
}

async function submitTaskNote(form) {
    const task = state.tasks.detail?.task;
    const field = form.querySelector('textarea');
    const body = (field?.value || '').trim();
    if (!task || state.tasks.saving) return;
    if (!body) { field?.focus(); return; }
    if (!await ensureAdminProtection({ silent: false })) return;
    state.tasks.focusKey = '[data-task-form="note"] textarea';
    setTaskSaving(true); setTaskModalError();
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/tasks/${encodeURIComponent(task.id)}/notes`, {
            method: 'POST', headers: buildAuthHeaders({ 'Content-Type': 'application/json' }), credentials: 'same-origin', body: JSON.stringify({ body })
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) { setTaskModalError(normalizeErrorMessage(payload, 'Could not add the note.')); return; }
        if (state.tasks.openId === Number(task.id)) applyTaskDetail(payload, { keepNote: false });
    } catch { setTaskModalError('Could not add the note. Please retry.'); }
    finally { setTaskSaving(false); }
}

async function deleteTaskNote(noteId) {
    const task = state.tasks.detail?.task;
    if (!task || state.tasks.saving) return;
    if (!(await confirmDialog('This note will be removed from the task for everyone.', { title: 'Delete this note?', okText: 'Delete note' }))) return;
    if (!await ensureAdminProtection({ silent: false })) return;
    state.tasks.focusKey = '[data-task-form="note"] textarea';
    setTaskSaving(true); setTaskModalError();
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/tasks/${encodeURIComponent(task.id)}/notes/${encodeURIComponent(noteId)}`, {
            method: 'DELETE', headers: buildAuthHeaders(), credentials: 'same-origin'
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) { setTaskModalError(normalizeErrorMessage(payload, 'Could not delete the note.')); return; }
        if (state.tasks.openId === Number(task.id)) applyTaskDetail(payload);
    } catch { setTaskModalError('Could not delete the note. Please retry.'); }
    finally { setTaskSaving(false); }
}

async function deleteTask() {
    const task = state.tasks.detail?.task;
    if (!task?.can_delete || state.tasks.saving) return;
    if (!(await confirmDialog(`“${task.title}” and all of its notes will be deleted for everyone. If the work is finished, close the task instead. Closed tasks keep their history.`, { title: 'Delete this task?', okText: 'Delete task' }))) return;
    if (!await ensureAdminProtection({ silent: false })) return;
    setTaskSaving(true); setTaskModalError();
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/tasks/${encodeURIComponent(task.id)}`, {
            method: 'DELETE', headers: buildAuthHeaders(), credentials: 'same-origin'
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) { setTaskModalError(normalizeErrorMessage(payload, 'Could not delete the task.')); return; }
        removeTask(task.id);
        closeTaskModal(); renderTaskBoard(); updateTaskBadgeFromItems();
        showFlash('Task deleted.', 'success');
    } catch { setTaskModalError('Could not delete the task. Please retry.'); }
    finally { setTaskSaving(false); }
}

// ---- Deep links: /admin_console#task-42 (used by task emails) ---------------

function taskIdFromHash() {
    try {
        const match = /^#task-(\d{1,10})$/.exec(window.location?.hash || '');
        return match ? Number(match[1]) : null;
    } catch { return null; }
}

function setTaskHash(taskId) {
    try { if (window.history?.replaceState && window.location?.hash !== `#task-${taskId}`) window.history.replaceState(null, '', `#task-${taskId}`); } catch { /* cosmetic */ }
}

function clearTaskHash() {
    try {
        if (window.history?.replaceState && /^#task-\d+$/.test(window.location?.hash || '')) {
            window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
        }
    } catch { /* cosmetic */ }
}

function applyTaskDeepLink() {
    let hash = '';
    try { hash = window.location?.hash || ''; } catch { return false; }
    const taskId = taskIdFromHash();
    if ((!taskId && hash !== '#tasks') || !canAccessSection('tasks')) return false;
    state.activeTab = 'tasks';
    state.tasks.pendingOpenId = taskId;
    renderActiveTab();
    return true;
}

function handleTaskHashChange() {
    if (!state.currentUser || !canAccessSection('tasks')) return;
    const taskId = taskIdFromHash();
    if (!taskId || taskId === state.tasks.openId) return;
    if (state.activeTab !== 'tasks' || !state.tasks.loaded) {
        state.tasks.pendingOpenId = taskId;
        if (state.activeTab !== 'tasks') selectAdminTab('tasks'); else void loadTasks();
    } else void openTaskDetail(taskId);
}

// ---- Events -------------------------------------------------------------------

function clearTaskDropTargets() {
    refs.taskBoard?.querySelectorAll?.('.is-drop-target').forEach((zone) => zone.classList.remove('is-drop-target'));
}

function bindTaskEvents() {
    refs.tasksTabBtn?.addEventListener('click', () => selectAdminTab('tasks'));
    refs.taskNewBtn?.addEventListener('click', () => void openTaskCreate());
    refs.taskScopes?.addEventListener('click', (event) => {
        const button = event.target.closest('[data-task-scope]');
        if (button) setTaskScope(button.dataset.taskScope);
    });
    refs.taskSearch?.addEventListener('input', () => { state.tasks.search = refs.taskSearch.value || ''; renderTaskBoard(); });
    refs.taskPerson?.addEventListener('change', () => { state.tasks.person = refs.taskPerson.value || ''; renderTaskBoard(); });
    refs.taskShowClosed?.addEventListener('change', () => { state.tasks.showClosed = Boolean(refs.taskShowClosed.checked); saveTaskPrefs(); renderTaskBoard(); });
    refs.taskBoard?.addEventListener('click', (event) => {
        const card = event.target.closest('[data-task-id]');
        if (card) void openTaskDetail(card.dataset.taskId);
    });
    refs.taskBoard?.addEventListener('keydown', (event) => {
        const card = event.target.closest('[data-task-id]');
        if (card && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); void openTaskDetail(card.dataset.taskId); }
    });
    refs.taskBoard?.addEventListener('dragstart', (event) => {
        const card = event.target.closest?.('[data-task-id][draggable="true"]');
        if (!card || state.tasks.saving) { event.preventDefault(); return; }
        state.tasks.dragId = Number(card.dataset.taskId);
        card.classList.add('is-dragging');
        try { event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', String(state.tasks.dragId)); } catch { /* older browsers */ }
    });
    refs.taskBoard?.addEventListener('dragend', (event) => {
        event.target.closest?.('[data-task-id]')?.classList.remove('is-dragging');
        state.tasks.dragId = null;
        clearTaskDropTargets();
    });
    refs.taskBoard?.addEventListener('dragover', (event) => {
        const zone = event.target.closest?.('[data-drop-status]');
        if (!zone || !state.tasks.dragId) return;
        // Not a drop target: the browser shows "not allowed" over Closed for an assignee.
        if (taskStatusLocked(findTask(state.tasks.dragId), zone.dataset.dropStatus)) return;
        event.preventDefault();
        try { event.dataTransfer.dropEffect = 'move'; } catch { /* older browsers */ }
        if (!zone.classList.contains('is-drop-target')) { clearTaskDropTargets(); zone.classList.add('is-drop-target'); }
    });
    refs.taskBoard?.addEventListener('dragleave', (event) => {
        const zone = event.target.closest?.('[data-drop-status]');
        if (zone && !zone.contains(event.relatedTarget)) zone.classList.remove('is-drop-target');
    });
    refs.taskBoard?.addEventListener('drop', (event) => {
        const zone = event.target.closest?.('[data-drop-status]');
        const taskId = state.tasks.dragId;
        clearTaskDropTargets();
        if (!zone || !taskId) return;
        event.preventDefault();
        state.tasks.dragId = null;
        void moveTaskStatus(taskId, zone.dataset.dropStatus);
    });
    refs.taskModalClose?.addEventListener('click', () => void requestCloseTaskModal());
    // Backdrop closes only for a press that started on it, and not for the second click of
    // the double-click that opened the task.
    refs.taskModal?.addEventListener('mousedown', (event) => { state.tasks.backdropPress = event.target === refs.taskModal; });
    refs.taskModal?.addEventListener('click', (event) => {
        const pressed = state.tasks.backdropPress;
        state.tasks.backdropPress = false;
        if (event.target !== refs.taskModal || !pressed || Date.now() - (state.tasks.openedAt || 0) < 500) return;
        void requestCloseTaskModal();
    });
    refs.taskModalBody?.addEventListener('submit', (event) => {
        const form = event.target.closest('[data-task-form]');
        if (!form) return;
        event.preventDefault();
        if (form.dataset.taskForm === 'create') void submitTaskCreate(form);
        if (form.dataset.taskForm === 'edit') void submitTaskEdit(form);
        if (form.dataset.taskForm === 'note') void submitTaskNote(form);
    });
    refs.taskModalBody?.addEventListener('change', (event) => {
        if (event.target.closest('[data-task-field]')) handleTaskFieldChange(event);
    });
    refs.taskModalBody?.addEventListener('click', (event) => {
        const button = event.target.closest('[data-task-action]');
        if (!button || button.disabled) return;
        const action = button.dataset.taskAction;
        if (action === 'cancel') void requestCloseTaskModal();
        if (action === 'edit') { state.tasks.editing = true; renderTaskDetail(); }
        if (action === 'cancel-edit') { state.tasks.editing = false; renderTaskDetail({ keepEdit: false }); }
        if (action === 'delete') void deleteTask();
        if (action === 'delete-note') void deleteTaskNote(button.dataset.noteId);
    });
    refs.taskModalBody?.addEventListener('focusout', handleTaskFieldBlur);
    refs.taskModalBody?.addEventListener('keydown', (event) => {
        if (event.target.closest?.('[data-task-field]')) { handleTaskFieldKeydown(event); return; }
        if (event.key !== 'Enter' || !(event.metaKey || event.ctrlKey)) return;
        const form = event.target.closest?.('[data-task-form]');
        if (!form) return;
        event.preventDefault();
        if (typeof form.requestSubmit === 'function') form.requestSubmit();
        else form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    window.addEventListener?.('hashchange', handleTaskHashChange);
}

function setDateColumnTimeZoneLabels() {
    if (refs.createdHeader) refs.createdHeader.textContent = `Created (${ADMIN_TIME_ZONE_LABEL})`;
    if (refs.lastLoginHeader) refs.lastLoginHeader.textContent = `Last Login (${ADMIN_TIME_ZONE_LABEL})`;
    if (refs.enterpriseCreatedHeader) refs.enterpriseCreatedHeader.textContent = `Created (${ADMIN_TIME_ZONE_LABEL})`;
}

function bindEvents() {
    bindAdminNavigation();
    refs.teamTabBtn?.addEventListener('click', () => selectAdminTab('team'));
    refs.teamForm?.addEventListener('submit', saveTeamMember);
    refs.teamRole?.addEventListener('change', () => renderTeamSections(selectedTeamSections()));
    refs.teamCancel?.addEventListener('click', () => resetTeamForm());
    refs.teamTableBody?.addEventListener('click', handleTeamAction);
    bindTaskEvents();
    document.addEventListener('visibilitychange', async () => {
        if (document.visibilityState !== 'visible' || !state.currentUser || state.team.saving) return;
        const revision = state.accessRevision;
        const allowed = await refreshCurrentAdminUser({ silent: true });
        if (!allowed) showAuth();
        else if (revision !== state.accessRevision) await loadActiveTab();
        else if (state.activeTab === 'tasks') { if (!state.tasks.saving && !state.tasks.dragId) await loadTasks({ quiet: true }); }
        else void refreshTaskBadge();
    });
    // Dynamic account, refund, and ledger controls receive the same permission rules.
    if (typeof MutationObserver !== 'undefined') {
        const observer = new MutationObserver(() => applyAdminPermissions());
        observer.observe(refs.consolePanel, { childList: true, subtree: true });
        if (refs.couponModal) observer.observe(refs.couponModal, { childList: true, subtree: true });
        const detail = document.getElementById('adminAccountDetail');
        if (detail) observer.observe(detail, { childList: true, subtree: true });
    }
    refs.loginForm?.addEventListener('submit', handleLoginSubmit);
    refs.logoutBtn?.addEventListener('click', handleLogout);
    document.getElementById('adminGrowthRunBtn')?.addEventListener('click', runGrowthAnalysis);
    document.getElementById('adminInsightsRefreshBtn')?.addEventListener('click', loadGrowthInsights);
    document.getElementById('adminAccountBackBtn')?.addEventListener('click', closeAccountDetail);
    refs.verifyProtectionBtn?.addEventListener('click', handleProtectionVerifyClick);
    refs.usersTabBtn?.addEventListener('click', () => selectAdminTab('users'));
    refs.enterpriseTabBtn?.addEventListener('click', () => selectAdminTab('enterprise'));
    refs.analyticsTabBtn?.addEventListener('click', () => selectAdminTab('analytics'));
    refs.financeTabBtn?.addEventListener('click', () => selectAdminTab('finance'));
    refs.aiTabBtn?.addEventListener('click', () => selectAdminTab('ai'));
    refs.usersForm?.addEventListener('submit', handleUserFiltersSubmit);
    refs.usersResetBtn?.addEventListener('click', resetUserFilters);
    refs.usersExportCsvBtn?.addEventListener('click', () => exportUsers('csv'));
    refs.usersExportExcelBtn?.addEventListener('click', () => exportUsers('xlsx'));
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
    refs.financeLevelBtn?.addEventListener('click', levelFounderSpend);
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
    refs.aiProfilesForm?.addEventListener('submit', (event) => {
        event.preventDefault();
        state.aiProfiles.search = (refs.aiProfilesSearch?.value || '').trim();
        void loadAiProfiles({ resetPage: true });
    });
    refs.aiProfilesResetBtn?.addEventListener('click', () => {
        if (refs.aiProfilesSearch) refs.aiProfilesSearch.value = '';
        state.aiProfiles.search = '';
        void loadAiProfiles({ resetPage: true });
    });
    refs.aiProfilesPrevBtn?.addEventListener('click', () => changeAiProfilesPage(-1));
    refs.aiProfilesNextBtn?.addEventListener('click', () => changeAiProfilesPage(1));
    refs.aiProfilesExportBtn?.addEventListener('click', exportAiProfiles);
    refs.aiAccountsExportBtn?.addEventListener('click', exportAiAccounts);
    refs.aiProfilesTableBody?.addEventListener('click', (event) => {
        const button = event.target.closest('[data-ai-profile-id]');
        if (button) void loadAiProfileDetail(button.dataset.aiProfileId);
    });
    refs.aiProfileCloseBtn?.addEventListener('click', closeAiProfileDetail);
    refs.aiBillingSyncBtn?.addEventListener('click', syncAiBilling);
    initAiRangeInputs();
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && refs.couponModal && !refs.couponModal.hidden) closeCouponModal();
        if (event.key === 'Escape' && refs.taskModal && !refs.taskModal.hidden) void requestCloseTaskModal();
    });
}

function adminTabButtons() {
    return ADMIN_TABS.map((key) => refs[`${key}TabBtn`]).filter((button) => button && !button.hidden);
}

function updateSidebarAccessibility() {
    const isMobile = window.matchMedia('(max-width: 900px)').matches;
    const isOpen = document.body.classList.contains('sidebar-open');
    if (refs.sidebar) refs.sidebar.inert = isMobile && !isOpen;
    const workspace = document.querySelector('.admin-workspace');
    if (workspace) workspace.inert = isMobile && isOpen;
}

function setSidebarOpen(open, { restoreFocus = false } = {}) {
    const canOpen = open && !refs.sidebar?.hidden && window.matchMedia('(max-width: 900px)').matches;
    document.body.classList.toggle('sidebar-open', Boolean(canOpen));
    refs.menuToggle?.setAttribute('aria-expanded', String(Boolean(canOpen)));
    if (refs.sidebarBackdrop) refs.sidebarBackdrop.hidden = !canOpen;
    updateSidebarAccessibility();
    if (canOpen) {
        const buttons = adminTabButtons();
        buttons.forEach((button) => {
            button.tabIndex = button.getAttribute('aria-selected') === 'true' ? 0 : -1;
        });
        buttons.find((button) => button.tabIndex === 0)?.focus();
    } else if (restoreFocus && refs.menuToggle && !refs.menuToggle.hidden) {
        refs.menuToggle.focus();
    }
}

function selectAdminTab(tabName) {
    const wasDrawerOpen = document.body.classList.contains('sidebar-open');
    const isNewTab = state.activeTab !== tabName;
    setSidebarOpen(false);
    void handleTabSwitch(tabName);
    if (isNewTab) window.scrollTo({ top: 0, behavior: 'auto' });
    if (wasDrawerOpen) {
        const button = adminTabButtons().find((item) => item.dataset.tab === tabName);
        document.getElementById(button?.getAttribute('aria-controls'))?.focus({ preventScroll: true });
    }
}

function bindAdminNavigation() {
    // CSS can hide the focused control before a breakpoint change is delivered.
    let navigationHadFocus = false;
    document.addEventListener('focusin', (event) => {
        navigationHadFocus = Boolean(refs.sidebar?.contains(event.target) || event.target === refs.menuToggle);
    });
    refs.menuToggle?.addEventListener('click', () => setSidebarOpen(!document.body.classList.contains('sidebar-open')));
    refs.sidebarClose?.addEventListener('click', () => setSidebarOpen(false, { restoreFocus: true }));
    refs.sidebarBackdrop?.addEventListener('click', () => setSidebarOpen(false, { restoreFocus: true }));
    refs.sidebar?.addEventListener('keydown', (event) => {
        const buttons = adminTabButtons();
        const index = buttons.indexOf(document.activeElement);
        if (index === -1 || !['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
            : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
        buttons.forEach((button, buttonIndex) => { button.tabIndex = buttonIndex === next ? 0 : -1; });
        buttons[next].focus();
    });
    document.addEventListener('keydown', (event) => {
        if (!document.body.classList.contains('sidebar-open')) return;
        if (event.key === 'Escape') {
            event.preventDefault();
            setSidebarOpen(false, { restoreFocus: true });
        } else if (event.key === 'Tab') {
            const focusable = [...refs.sidebar.querySelectorAll('button:not([hidden]):not([tabindex="-1"])')];
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last?.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first?.focus();
            }
        }
    });
    window.matchMedia('(max-width: 900px)').addEventListener('change', (event) => {
        const focusedNavigation = navigationHadFocus || refs.sidebar?.contains(document.activeElement)
            || document.activeElement === refs.menuToggle || document.body.classList.contains('sidebar-open');
        setSidebarOpen(false);
        if (focusedNavigation && !refs.sidebar?.hidden) {
            const target = event.matches ? refs.menuToggle
                : adminTabButtons().find((button) => button.getAttribute('aria-selected') === 'true');
            target?.focus();
        }
    });
    updateSidebarAccessibility();
}

async function bootstrap() {
    await initializeTurnstile();
    const canAccess = await refreshCurrentAdminUser({ silent: true });
    if (canAccess) {
        applyTaskDeepLink();
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
    return { ...extraHeaders, 'X-Admin-Console-Session': 'required' };
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
        if (existing) { existing.dismiss?.(); existing.remove(); }
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
        overlay.dismiss = () => done(false);
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
        if (existing) { existing.dismiss?.(); existing.remove(); }
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
        overlay.dismiss = () => done(null);
        function onKey(e) { if (e.key === 'Escape') { e.stopPropagation(); done(null); } }
        overlay.querySelector('#adminPromptForm').onsubmit = (e) => { e.preventDefault(); done(overlay.querySelector('#adminPromptInput').value); };
        overlay.querySelector('#adminPromptCancel').onclick = () => done(null);
        overlay.addEventListener('click', (e) => { if (e.target === overlay) done(null); });
        document.addEventListener('keydown', onKey, true);
        const inp = overlay.querySelector('#adminPromptInput'); if (inp) inp.focus();
    });
}

function showAuth() {
    state.currentUser = null; state.access = null;
    clearPrivilegedState();
    setSidebarOpen(false);
    document.body.classList.remove('admin-authenticated');
    if (refs.sidebar) refs.sidebar.hidden = true;
    if (refs.menuToggle) refs.menuToggle.hidden = true;
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
    document.body.classList.add('admin-authenticated');
    if (refs.sidebar) refs.sidebar.hidden = false;
    if (refs.menuToggle) refs.menuToggle.hidden = false;
    updateSidebarAccessibility();
    refs.authPanel.hidden = true;
    refs.consolePanel.hidden = false;
    refs.logoutBtn.hidden = false;
    refs.sessionBadge.hidden = false;
    renderActiveTab();
    updateProtectionUi();
    updateSessionBadge();
}

function renderActiveTab() {
    if (!canAccessSection(state.activeTab)) state.activeTab = ADMIN_TABS.find(canAccessSection) || null;
    ADMIN_TABS.forEach((key) => {
        const allowed = canAccessSection(key);
        const selected = allowed && state.activeTab === key;
        const button = refs[`${key}TabBtn`];
        const panel = refs[`${key}TabPanel`];
        if (button) {
            button.hidden = !allowed;
            button.classList.toggle('active', selected);
            button.setAttribute('aria-selected', String(selected));
            button.tabIndex = selected ? 0 : -1;
        }
        if (panel) panel.hidden = !selected;
    });
    document.querySelectorAll?.('.nav-group-label[data-admin-group]').forEach((label) => {
        label.hidden = !label.dataset.adminGroup.split(' ').some(canAccessSection);
    });
    applyAdminPermissions();
}

async function handleTabSwitch(tabName) {
    const normalized = String(tabName || '').trim().toLowerCase();
    if (!ADMIN_TABS.includes(normalized) || !canAccessSection(normalized)) return;
    if (state.activeTab === normalized) return;

    state.activeTab = normalized;
    renderActiveTab();

    if (!state.currentUser) return;
    clearFlash();
    await loadActiveTab({ resetPage: false });
}

async function loadActiveTab({ resetPage = false } = {}) {
    if (!canAccessSection(state.activeTab)) return;
    if (state.activeTab === 'tasks') { await loadTasks(); return; }
    // The board keeps its own badge current; every other tab refreshes it on load.
    void refreshTaskBadge();
    if (state.activeTab === 'team') { await loadTeam(); return; }
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
    const role = state.access?.role ? state.access.role[0].toUpperCase() + state.access.role.slice(1) : 'Member';
    const label = user.full_name || user.username || user.email || 'Admin User';
    refs.sessionBadge.textContent = `${role}: ${label}`;
    refs.sessionBadge.hidden = false;
}

function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = String(value || '');
    // These strings are used in both text nodes and quoted data attributes.
    return div.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
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

let adminAccessRefreshPromise = null;
async function handleAdminAuthOrProtectionError(responseStatus, payload) {
    if (responseStatus !== 401 && responseStatus !== 403) return;
    const detail = String(payload?.detail || '').toLowerCase();
    if (detail.includes('cloudflare verification')) {
        state.adminProtectionVerified = false;
        updateProtectionUi();
        return;
    }
    const revision = state.accessRevision;
    if (!adminAccessRefreshPromise) {
        adminAccessRefreshPromise = refreshCurrentAdminUser({ silent: true })
            .finally(() => { adminAccessRefreshPromise = null; });
    }
    if (!await adminAccessRefreshPromise) {
        showAuth();
        showFlash(responseStatus === 401 ? 'Your session expired. Please sign in again.' : 'This account no longer has console access.', 'error');
    } else if (revision !== state.accessRevision) {
        await loadActiveTab();
    }
}

async function refreshCurrentAdminUser({ silent = false } = {}) {
    const requestId = ++state.accessRequestId;
    try {
        const response = await fetch(`${API_BASE}/api/admin/access`, {
            headers: buildAuthHeaders(), credentials: 'same-origin'
        });
        const payload = response.ok ? await response.json() : null;
        if (requestId !== state.accessRequestId) return Boolean(state.access);
        if (!response.ok || !applyAdminAccess(payload)) {
            state.currentUser = null; state.access = null;
            clearPrivilegedState(); renderActiveTab();
            if (!silent) showFlash(response.status === 403 ? 'This account does not have console access.' : 'Session expired. Please sign in again.', 'error');
            return false;
        }
        return true;
    } catch (error) {
        if (requestId !== state.accessRequestId) return Boolean(state.access);
        state.currentUser = null; state.access = null;
        clearPrivilegedState(); renderActiveTab();
        if (!silent) showFlash('Could not verify console access. Please retry.', 'error');
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
        const response = await fetch(`${API_BASE}/api/auth/turnstile-site-key`, { headers: buildAuthHeaders(), credentials: 'same-origin' });
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
        const loginPayload = { email, password };
        if (turnstileToken) loginPayload.cf_turnstile_token = turnstileToken;
        const response = await fetch(`${API_BASE}/api/admin-auth/login`, {
            method: 'POST',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(loginPayload),
            credentials: 'same-origin'
        });

        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            showFlash(normalizeErrorMessage(payload, 'Login failed.'), 'error');
            resetTurnstileWidget();
            return;
        }

        state.authToken = COOKIE_AUTH_SENTINEL;
        const canAccess = await refreshCurrentAdminUser({ silent: true });

        if (!canAccess) {
            showFlash('Logged in, but this account does not have admin access.', 'error');
            showAuth();
            return;
        }

        applyTaskDeepLink();
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
        showFlash('Could not sign in right now. Please try again.', 'error');
    } finally {
        if (refs.loginPassword) refs.loginPassword.value = '';
        refs.loginBtn.disabled = false;
        refs.loginBtn.textContent = 'Sign In to Admin Console';
    }
}

async function handleLogout() {
    const headers = buildAuthHeaders();
    const hadUser = Boolean(state.currentUser);
    state.accessRequestId += 1;
    state.authToken = null;
    showAuth();
    resetTurnstileWidget(); resetActionTurnstileWidget();
    if (hadUser) {
        try { await fetch(`${API_BASE}/api/admin/turnstile/clear`, { method: 'POST', headers, credentials: 'same-origin' }); } catch { /* session may already be gone */ }
    }
    try { await fetch(`${API_BASE}/api/admin-auth/logout`, { method: 'POST', headers, credentials: 'same-origin' }); } catch { /* clear local access regardless */ }
    showFlash('Logged out. Sign in to continue.', 'info');
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
    renderFinanceFounderBalance(null);
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
        // A settlement followed by a deleted/re-attributed expense can leave one founder
        // below 0 or above 100%: clamp only the bar, never the number printed beside it.
        const share = Number(item.percentage) || 0;
        const barWidth = Math.min(Math.max(share, 0), 100);
        const amount = Number(item.amount_usd) || 0;
        return `
            <div class="finance-breakdown-row contributor-row">
                <div class="finance-breakdown-top">
                    <strong>${escapeHtml(item.label || 'Unassigned')}</strong>
                    <span>${escapeHtml(formatUsd(amount))}</span>
                </div>
                <div class="finance-breakdown-track contributor-track">
                    <span style="width: ${barWidth.toFixed(2)}%"></span>
                </div>
                <div class="finance-breakdown-percent">${escapeHtml(formatPercent(share))} of founder spend</div>
            </div>
        `;
    }).join('');
}

// The day the Level button is clicked, in the clicker's own timezone (the server accepts
// any date within a day of UTC's today). toISOString() would be tomorrow for a US evening.
function localIsoDate(date = new Date()) {
    const pad = (n) => String(n).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

// founder_balance comes from the server (Decimal math): who owes whom to make the two
// founders' spend 50/50. The client only displays it and echoes it back on Level, so the
// server can refuse if the balance moved after the confirmation was shown.
function financeOtherContributorsNote(balance) {
    const others = Array.isArray(balance?.other_contributors) ? balance.other_contributors : [];
    if (!others.length) return '';
    const names = others.map((o) => `${o.label} ${formatUsd(o.amount_usd)}`).join(', ');
    return `Some investment is filed under other names (${names}). Set Paid by on those entries to Gaurav or Kushal, then level.`;
}

function renderFinanceFounderBalance(balance) {
    const btn = refs.financeLevelBtn;
    const status = refs.financeLevelStatus;
    const founders = Array.isArray(balance?.founders) ? balance.founders : [];
    const othersNote = financeOtherContributorsNote(balance);
    const hasSpend = Boolean(othersNote) || founders.some((f) => (Number(f.amount_usd) || 0) !== 0);
    const pending = Boolean(balance && !othersNote && !balance.is_level && balance.payer && balance.payee
        && (Number(balance.transfer_usd) || 0) > 0);
    if (btn) {
        btn.disabled = state.financeLeveling || !pending || !canWriteSection('finance');
        btn.textContent = state.financeLeveling ? 'Leveling…' : '⚖ Level 50/50';
        btn.title = othersNote ? 'Re-assign spend filed under other names first'
            : pending
                ? `Record that ${balance.payer} paid ${balance.payee} ${formatUsd(balance.transfer_usd)} so founder spend is 50/50`
                : (hasSpend ? 'Founder spend is already 50/50' : 'No founder spend to level yet');
    }
    if (!status) return;
    if (!balance || !hasSpend) {
        status.hidden = true;
        status.textContent = '';
        status.className = 'finance-level-status';
        return;
    }
    status.hidden = false;
    if (othersNote) {
        status.className = 'finance-level-status is-owed';
        status.textContent = othersNote;
    } else if (pending) {
        status.className = 'finance-level-status is-owed';
        status.textContent = `${balance.payer} owes ${balance.payee} ${formatUsd(balance.transfer_usd)} to make founder spend 50/50.`;
    } else {
        status.className = 'finance-level-status is-level';
        const split = founders.map((f) => `${f.label} ${formatUsd(f.amount_usd)}`).join(' · ');
        status.textContent = `✓ Founder spend is level (50/50): ${split}.`;
    }
}

async function levelFounderSpend() {
    if (state.financeLeveling) return;
    if (!requireAdminPermission('finance', 'write')) return;
    const balance = state.financeAnalytics?.founder_balance;
    if (!balance) {
        showFlash('Finance data has not loaded yet. Refresh and try again.', 'error');
        return;
    }
    const othersNote = financeOtherContributorsNote(balance);
    if (othersNote) {
        showFlash(othersNote, 'error');
        return;
    }
    if (balance.is_level || !balance.payer || !balance.payee || !(Number(balance.transfer_usd) > 0)) {
        showFlash('Founder spend is already 50/50.', 'success');
        return;
    }
    if (!await ensureAdminProtection({ silent: false })) return;

    const occurredOn = localIsoDate();
    const transfer = Number(balance.transfer_usd);
    const founders = Array.isArray(balance.founders) ? balance.founders : [];
    const after = founders.map((f) => `${f.label} ${formatUsd(f.after_usd)}`).join(' · ');
    const totalInvested = Number(state.financeAnalytics?.summary?.total_invested_usd ?? balance.total_usd) || 0;
    const confirmed = await confirmDialog(
        `This adds a settlement to the ledger dated ${occurredOn}: ${balance.payer} paid ${balance.payee} ${formatUsd(transfer)}.\n\n`
        + `Founder spend after leveling: ${after}.\n`
        + `Total invested stays ${formatUsd(totalInvested)} — only the split between founders changes.`,
        { title: 'Level founder spend 50/50?', okText: 'Level 50/50', danger: false }
    );
    if (!confirmed) return;

    const accessRevision = state.accessRevision;
    state.financeLeveling = true;
    renderFinanceFounderBalance(balance);
    let message = '';
    let level = 'error';
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/company-finance/level`, {
            method: 'POST',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            credentials: 'same-origin',
            body: JSON.stringify({
                occurred_on: occurredOn,
                expected_payer: balance.payer,
                expected_transfer_usd: transfer,
            }),
        });
        const payload = await response.json().catch(() => ({}));
        if (response.ok) {
            message = `Leveled: ${balance.payer} paid ${balance.payee} ${formatUsd(transfer)}. Founder spend is now 50/50.`;
            level = 'success';
        } else {
            message = normalizeErrorMessage(payload, 'Could not level founder spend.');
            // 409 = the balance moved or someone already leveled; reload so the card is current.
            if (response.status !== 409) return void showFlash(message, 'error');
        }
    } catch (error) {
        console.error('Level founder spend failed:', error);
        return void showFlash('Could not level founder spend. Please retry.', 'error');
    } finally {
        state.financeLeveling = false;
        renderFinanceFounderBalance(state.financeAnalytics?.founder_balance);
    }
    // Signed out / access changed mid-request: the page no longer belongs to that session.
    if (state.accessRevision !== accessRevision) return;
    // Reload first: loadFinanceAnalytics() clears the flash on success.
    await loadFinanceAnalytics();
    showFlash(message, level);
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
        // A settlement is founder → founder (Level 50/50), not company money: neither an
        // investment nor a return, and only deletable — editing one side would unbalance it.
        const isSettlement = String(item.kind || '').toLowerCase() === 'settlement';
        const isReturn = amount >= 0;
        const tone = isSettlement ? 'settlement' : (isReturn ? 'return' : 'investment');
        const fid = financeLedgerEntryId(item);
        const editBtn = isSettlement ? ''
            : `<button type="button" class="table-btn" data-admin-write="finance" data-finance-edit="${escapeHtml(fid)}">Edit</button>`;
        const actions = fid
            ? `${editBtn}
               <button type="button" class="table-btn danger" data-admin-delete="finance" data-finance-delete="${escapeHtml(fid)}">Delete</button>`
            : '<span class="finance-source">Auto</span>';
        const settlementNote = isSettlement
            ? `<div class="finance-source">${escapeHtml(item.paid_by || '-')} → ${escapeHtml(item.paid_to || item.vendor || '-')}</div>`
            : '';
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
                <td><span class="finance-kind ${tone}">${escapeHtml(item.kind || '-')}</span></td>
                <td><div class="user-name">${escapeHtml(item.vendor || '-')}</div></td>
                <td>${escapeHtml(item.category || '-')}</td>
                <td><span class="finance-source">${escapeHtml(item.paid_by || '-')}</span></td>
                <td>${escapeHtml(item.description || '-')}</td>
                <td class="finance-amount ${isSettlement ? 'settlement' : (isReturn ? 'positive' : 'negative')}">${escapeHtml(formatUsd(amount))}${settlementNote}${chargedNote}${estimatedNote}</td>
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
    applyAdminPermissions();
}

function filenameFromDisposition(header, fallback) {
    const match = /filename="?([^";]+)"?/i.exec(String(header || ''));
    return (match && match[1]) ? match[1].trim() : fallback;
}

async function exportFinanceLedger() {
    if (!requireAdminPermission('finance')) return;
    const btn = refs.financeExportBtn;
    if (!await ensureAdminProtection({ silent: false })) return;

    const originalLabel = btn ? btn.textContent : '';
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Preparing…';
    }

    try {
        const response = await adminFetch(`${API_BASE}/api/admin/company-finance/export?format=xlsx`, {
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });

        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            const message = normalizeErrorMessage(payload, 'Failed to export the finance ledger.');

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
    if (!requireAdminPermission('finance', 'write')) return;
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
    event.preventDefault();
    if (!requireAdminPermission('finance', 'write')) return;
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
        const response = await adminFetch(url, {
            method: isEdit ? 'PATCH' : 'POST',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            credentials: 'same-origin',
            body: JSON.stringify({ occurred_on, entry_type, vendor, category, paid_by, amount_usd, description }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {

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
    if (!requireAdminPermission('finance', 'delete')) return;
    if (!await ensureAdminProtection({ silent: false })) return;
    const item = financeLedgerItemByEntryId(fid);
    const isSettlement = String(item?.kind || '').toLowerCase() === 'settlement';
    const label = item ? `${item.vendor} · ${formatUsd(Number(item.amount_usd) || 0)}` : `entry #${fid}`;
    const message = isSettlement
        ? `This settlement (${item.paid_by} paid ${item.paid_to || item.vendor} ${formatUsd(Number(item.amount_usd) || 0)}) will be permanently removed, and founder spend goes back to the split before it was leveled.`
        : `This finance entry (${label}) will be permanently removed from the ledger and analytics.`;
    if (!(await confirmDialog(message, { title: isSettlement ? 'Delete settlement?' : 'Delete finance entry?', okText: 'Delete' }))) return;
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/company-finance/entries/${encodeURIComponent(fid)}`, {
            method: 'DELETE',
            headers: buildAuthHeaders(),
            credentials: 'same-origin',
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {

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
    renderFinanceFounderBalance(payload.founder_balance || null);
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
    renderUsersExportControls();
}

function renderUsersExportControls() {
    const exporting = Boolean(state.usersExportFormat);
    const disabled = state.loading || exporting || state.total <= 0;
    if (refs.usersExportActions) refs.usersExportActions.setAttribute('aria-busy', String(exporting));
    if (refs.usersExportCsvBtn) {
        refs.usersExportCsvBtn.disabled = disabled;
        refs.usersExportCsvBtn.textContent = state.usersExportFormat === 'csv' ? 'Preparing CSV…' : 'Export CSV';
    }
    if (refs.usersExportExcelBtn) {
        refs.usersExportExcelBtn.disabled = disabled;
        refs.usersExportExcelBtn.textContent = state.usersExportFormat === 'xlsx' ? 'Preparing Excel…' : 'Export Excel';
    }
}

async function exportUsers(format) {
    if (!requireAdminPermission('users')) return;
    if (!['csv', 'xlsx'].includes(format) || state.loading || state.usersExportFormat || state.total <= 0) return;

    // Export the filters used to load the table, including every matching page.
    const filters = { ...state.filters };
    state.usersExportFormat = format;
    renderUsersExportControls();

    try {
        if (!await ensureAdminProtection({ silent: false })) return;

        const params = new URLSearchParams({ format, plan: filters.plan, role: filters.role });
        if (filters.search) params.set('search', filters.search);
        const response = await adminFetch(`${API_BASE}/api/admin/users/export?${params.toString()}`, {
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });

        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            const message = normalizeErrorMessage(payload, 'Failed to export student accounts.');

            showFlash(message, 'error');
            return;
        }

        const blob = await response.blob();
        const filename = filenameFromDisposition(
            response.headers.get('Content-Disposition'),
            `rilono-student-accounts.${format}`
        );
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
        showFlash(`Downloaded ${filename}`, 'success');
    } catch (error) {
        console.error('Failed to export student accounts:', error);
        showFlash('Could not export student accounts. Please retry.', 'error');
    } finally {
        state.usersExportFormat = null;
        renderUsersExportControls();
    }
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
    event.preventDefault();
    if (!canAccessSection('enterprise')) return;
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
    applyAdminPermissions();
}

async function loadUsers({ resetPage = false } = {}) {
    if (!canAccessSection('users')) return;
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

        const response = await adminFetch(`${API_BASE}/api/admin/users?${params.toString()}`, {
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
    if (!canAccessSection('enterprise')) return;
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

        const response = await adminFetch(`${API_BASE}/api/admin/enterprise/accounts?${params.toString()}`, {
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
    if (!canAccessSection('finance')) return;
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
        const response = await adminFetch(`${API_BASE}/api/admin/company-finance/analytics`, {
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });
        const payload = await response.json().catch(() => ({}));

        if (!response.ok) {
            const message = normalizeErrorMessage(payload, 'Failed to load finance analytics.');
            state.financeAnalytics = null;
            renderFinanceEmptyState(message);

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
    return aiExactCount(value);
}

function aiUsageEmptyState(message) {
    state.aiUsageData = null;
    state.aiSeries = [];
    if (refs.aiCalculatedCost) refs.aiCalculatedCost.textContent = '$0.00';
    if (refs.aiCalculatedCostSub) refs.aiCalculatedCostSub.textContent = 'Cost data not loaded';
    if (refs.aiCalculatedCoverage) refs.aiCalculatedCoverage.textContent = 'Cost data not loaded.';
    [refs.aiTodayCost, refs.ai7Cost, refs.aiMonthCost, refs.aiAllCost, refs.aiRangeCost,
        refs.aiRangeAvg, refs.aiRangeTopDay, refs.aiRangeSaved, refs.aiRangeSearch,
        refs.aiDailyTotalCalls, refs.aiDailyTotalTokens, refs.aiDailyTotalCost].forEach((el) => {
        if (el) el.textContent = '0';
    });
    [refs.aiTodaySub, refs.ai7Sub, refs.aiMonthSub, refs.aiAllSub, refs.aiRangeSub,
        refs.aiRangeAvgSub, refs.aiRangeTopDaySub, refs.aiRangeSavedSub, refs.aiRangeSearchSub].forEach((el) => {
        if (el) el.textContent = 'Usage data not loaded';
    });
    if (refs.aiDailyTotalShare) refs.aiDailyTotalShare.textContent = '0%';
    if (refs.aiDailyCalculatedTotal) refs.aiDailyCalculatedTotal.textContent = '$0.00';
    const m = escapeHtml(message || 'No AI usage recorded yet.');
    [refs.aiTimelineChart, refs.aiSourceChart, refs.aiModelChart].forEach((el) => {
        if (el) el.innerHTML = `<div class="table-empty">${m}</div>`;
    });
    if (refs.aiDailyTableBody) refs.aiDailyTableBody.innerHTML = `<tr><td colspan="6" class="table-empty">${m}</td></tr>`;
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
    if (!canAccessSection('ai')) return;
    const requestId = ++state.aiUsageRequestId;
    invalidateAiAccounting();
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
        const response = await adminFetch(`${API_BASE}/api/admin/ai-usage/analytics${query ? `?${query}` : ''}`, {
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });
        const payload = await response.json().catch(() => ({}));
        if (requestId !== state.aiUsageRequestId) return;
        if (!response.ok) {
            const message = normalizeErrorMessage(payload, 'Failed to load AI usage.');
            aiUsageEmptyState(message);
            aiAccountingUnavailable(message);

            showFlash(message, 'error');
            return;
        }
        renderAiUsage(payload);
        clearFlash();
        await Promise.all([loadAiProfiles({ resetPage: true }), loadAiReconciliation(), loadAiAccounts()]);
    } catch (error) {
        if (requestId !== state.aiUsageRequestId) return;
        console.error('Failed to load AI usage:', error);
        aiUsageEmptyState('Could not load AI usage. Please retry.');
        aiAccountingUnavailable('Could not load AI usage. Apply the date range to retry.');
        showFlash('Could not load AI usage. Please retry.', 'error');
    } finally {
        if (requestId === state.aiUsageRequestId) setAiRefreshing(false);
    }
    if (requestId !== state.aiUsageRequestId) return;
    if (chartsOnly) return;
    await loadB2cRevenue();
}

async function loadB2cRevenue() {
    if (!canAccessSection('finance')) return;
    if (!refs.b2cRevenuePanel || refs.b2cRevenuePanel.hidden) return;
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/b2c/revenue`, { headers: buildAuthHeaders(), credentials: 'same-origin' });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) return;
        renderB2cRevenue(payload);
    } catch (error) { console.error('Failed to load B2C revenue:', error); }
}

async function loadAcquisitionBreakdown() {
    if (!canAccessSection('analytics')) return;
    const el = document.getElementById('adminAcquisitionBreakdown');
    const metaEl = document.getElementById('adminAcquisitionMeta');
    if (!el) return;
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/acquisition/analytics`, { headers: buildAuthHeaders(), credentials: 'same-origin' });
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
    if (!requireAdminPermission('analytics', 'write')) return;
    const btn = document.getElementById('adminGrowthRunBtn');
    const el = document.getElementById('adminGrowthResults');
    if (!el) return;
    if (btn) { btn.disabled = true; btn.textContent = 'Analyzing…'; }
    el.innerHTML = '<div class="table-empty">The agent is scoring accounts and drafting conversion plays… this can take a few seconds.</div>';
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/growth/conversion-analysis?limit=30`, {
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
    if (!canAccessSection('analytics')) return;
    const funnelEl = document.getElementById('adminFunnelBody');
    const outcomesEl = document.getElementById('adminOutcomesBody');
    if (!funnelEl && !outcomesEl) return;
    try {
        const [fRes, oRes] = await Promise.all([
            adminFetch(`${API_BASE}/api/admin/growth/funnel`, { headers: buildAuthHeaders(), credentials: 'same-origin' }),
            adminFetch(`${API_BASE}/api/admin/growth/outcomes`, { headers: buildAuthHeaders(), credentials: 'same-origin' }),
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
    if (!canAccessSection('users')) return;
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
        const response = await adminFetch(`${API_BASE}/api/admin/users/${userId}/detail`, {
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
        ? `<button class="table-btn" id="acctToggleBtn" data-admin-write="users">${active ? 'Deactivate' : 'Activate'}</button>
           <button class="table-btn danger" id="acctDeleteBtn" data-admin-delete="users">Delete</button>`
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

    // Resend bounce / spam-complaint / suppression flag (set by the deliverability webhook).
    // Nudges, digests and promos skip a flagged account; password reset + OTPs still try.
    const ed = a.email_delivery || {};
    const emailDeliveryChip = ed.undeliverable
        ? `<span class="acct-chip red">Undeliverable · ${escapeHtml(ed.reason_label || ed.reason || 'flagged')}</span>`
        : '<span class="acct-chip green">Deliverable</span>';
    const emailDeliveryAlert = ed.undeliverable ? `
          <div class="acct-alert" id="acctEmailDeliveryAlert">
            <div class="acct-alert-title">Emails to ${escapeHtml(a.email || 'this address')} are not arriving</div>
            <p>Resend reported <strong>${escapeHtml(ed.reason_label || ed.reason || 'a delivery failure')}</strong>${ed.flagged_at ? ` on ${escapeHtml(acctFmt(ed.flagged_at))}` : ''}.
              Password-reset and sign-in codes are still sent but will likely not arrive; daily nudges, digests and promotions are paused.</p>
            ${ed.detail ? `<p class="acct-alert-detail">${escapeHtml(ed.detail)}</p>` : ''}
            <p>Remove the address from the suppression list in Resend (or ask the student for another address), then clear this flag. If Resend still suppresses it, the next email flags it again.</p>
            <button type="button" class="table-btn" id="acctEmailDeliveryClearBtn" data-admin-write="users">Clear flag</button>
          </div>` : '';
    const emailDeliveryMeta = (!ed.undeliverable && ed.cleared_at)
        ? ` <span style="color:#94a3b8;font-size:12px">cleared ${escapeHtml(acctFmt(ed.cleared_at))}${ed.cleared_by ? ' · ' + escapeHtml(ed.cleared_by) : ''}</span>`
        : '';

    // Coupon codes issued FOR this account (per-account "conversion play" offers).
    const offers = data.coupon_offers || [];
    const offersHtml = offers.length
        ? offers.map((c) => `<div class="acct-line">
            <span><strong>${escapeHtml(c.code)}</strong> · ${c.percent_off}% off
              · used ${c.verified_uses}${c.max_uses_per_user != null ? ` / ${c.max_uses_per_user}` : ' (no cap)'}
            </span>
            <span style="display:inline-flex;align-items:center;gap:8px;color:#64748b">${c.created_at ? escapeHtml(acctFmt(c.created_at)) : ''}
              <button type="button" class="table-btn danger" data-admin-delete="users" data-coupon-delete="${escapeHtml(c.code)}">Delete</button></span>
          </div>`).join('')
        : '<div class="acct-empty">No coupon codes issued for this account yet.</div>';
    const suggestedCode = `${String((a.name || 'SAVE').split(' ')[0] || 'SAVE').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 12) || 'SAVE'}20`;

    document.getElementById('adminAccountBody').innerHTML = `
      <div class="acct-grid">
        <div style="display:grid;gap:16px">
          <div class="acct-card"><h3>Profile</h3>${emailDeliveryAlert}
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
              <dt>Email delivery</dt><dd>${emailDeliveryChip}${a.email_notifications_enabled === false ? ' <span class="acct-chip grey">Unsubscribed from notifications</span>' : ''}${emailDeliveryMeta}</dd>
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
              <button class="primary-btn small-btn" id="acctRecoBtn" data-admin-write="users">Get AI recommendation</button>
            </div>
          </div>
          <div class="acct-card"><h3>Coupon codes for this account</h3>
            <p style="font-size:12px;color:#94a3b8;margin:0 0 10px">Only this account can redeem these codes — at the
              Visa Success Pass checkout. Deleting a code stops future use; past payments keep their discount.</p>
            <div id="acctCouponList">${offersHtml}</div>
            <form id="acctCouponForm" data-admin-write="users" class="coupon-form" style="margin-top:12px">
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
                <button type="button" class="table-btn" data-admin-write="users" data-decision="approved">Approved</button>
                <button type="button" class="table-btn" data-admin-write="users" data-decision="refused">Refused</button>
                <button type="button" class="table-btn" data-admin-write="users" data-decision="withdrawn">Withdrawn</button>
                <button type="button" class="table-btn" data-admin-write="users" data-decision="deferred">Deferred</button>
                ${vd.decision ? '<button type="button" class="table-btn danger" data-admin-write="users" data-decision="clear">Clear</button>' : ''}
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
    const emailClearBtn = document.getElementById('acctEmailDeliveryClearBtn');
    if (emailClearBtn) emailClearBtn.addEventListener('click', () => clearAccountEmailUndeliverable(userId, emailClearBtn));
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
    applyAdminPermissions();
}

// Create a coupon code restricted to this account (the actionable half of the
// growth agent's "offer them a tailored coupon" recommendation).
async function createAccountCoupon(userId) {
    if (!requireAdminPermission('users', 'write')) return;
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
        const response = await adminFetch(`${API_BASE}/api/admin/coupons`, {
            method: 'POST',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            credentials: 'same-origin',
            body: JSON.stringify({ code, percent_off: pct, max_uses_per_user: maxUses, restricted_to_user_id: userId }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {

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
    if (!requireAdminPermission('users', 'delete')) return;
    if (!await ensureAdminProtection({ silent: false })) return;
    if (!(await confirmDialog(`Students will no longer be able to apply "${code}". Past payments keep their discount.`, { title: 'Delete coupon?', okText: 'Delete' }))) return;
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/coupons/${encodeURIComponent(code)}`, {
            method: 'DELETE',
            headers: buildAuthHeaders(),
            credentials: 'same-origin',
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {

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

async function clearAccountEmailUndeliverable(userId, button) {
    if (!requireAdminPermission('users', 'write')) return;
    if (!(await confirmDialog(
        'Daily nudges, digests and promotions will resume for this address. Only clear it after the address is off the suppression list in Resend.',
        { title: 'Clear the undeliverable flag?', okText: 'Clear flag', danger: false },
    ))) return;
    if (!await ensureAdminProtection({ silent: false })) return;
    if (button) { button.disabled = true; button.textContent = 'Clearing…'; }
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/users/${userId}/email-delivery/clear`, {
            method: 'POST', headers: buildAuthHeaders(), credentials: 'same-origin',
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            showFlash(normalizeErrorMessage(payload, 'Could not clear the flag.'), 'error');
            return;
        }
        showFlash('Email delivery flag cleared.', 'success');
        await openAccountDetail(userId);
    } catch (error) {
        console.error('Clear email-undeliverable flag failed:', error);
        showFlash('Could not clear the flag.', 'error');
    } finally {
        if (button && button.isConnected) { button.disabled = false; button.textContent = 'Clear flag'; }
    }
}

async function setAccountVisaDecision(userId, decision) {
    if (!requireAdminPermission('users', 'write')) return;
    const body = document.getElementById('acctDecisionBody');
    if (!body) return;
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/users/${userId}/visa-decision`, {
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
    if (!requireAdminPermission('users', 'write')) return;
    const body = document.getElementById('acctRecoBody');
    if (!body) return;
    body.innerHTML = '<div class="acct-empty">Rilono AI is analyzing this account and drafting a play…</div>';
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/users/${userId}/conversion-reco`, {
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
            <button class="ghost-btn small-btn" id="acctRecoRerun" data-admin-write="users" style="margin-left:auto">Re-run</button>
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
    // their INR settlement). The
    // zero fallbacks follow that currency instead of hardcoding a rupee sign.
    const bookCurrency = (data && data.currency) || 'INR';
    const setText = (el, v) => { if (el) el.textContent = v; };
    setText(refs.b2cRevenue, moneyOr(s.revenue_display, bookCurrency));
    // build_revenue_analytics EXCLUDES foreign passes with no INR settlement figure rather
    // than adding their cents as paise, so revenue is a known understatement while any
    // exist. Say so next to the number instead of letting it read as complete.
    const b2cUnsettled = Number(s.unsettled_payments || 0);
    setText(refs.b2cRevenueSub, `${(s.passes_sold || 0).toLocaleString()} passes sold`
        + (b2cUnsettled > 0 ? ` · ${b2cUnsettled} not counted (awaiting INR settlement)` : ''));
    setText(refs.b2cActive, (s.active_passes || 0).toLocaleString());
    setText(refs.b2cCost, moneyOr(null, bookCurrency));
    setText(refs.b2cCostSub, 'No B2C-level billed cost');
    setText(refs.b2cConversion, s.conversion_pct != null ? `${s.conversion_pct}%` : '0%');
    setText(refs.b2cConversionSub, `${(s.free_users || 0).toLocaleString()} free users`);
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
    const totals = data?.totals || {};
    const setMetric = (numberEl, subEl, stats = {}) => {
        if (numberEl) numberEl.textContent = formatTokens(stats.tokens);
        if (subEl) subEl.textContent = aiActivitySummary(stats);
    };
    setMetric(refs.aiTodayCost, refs.aiTodaySub, totals.today);
    setMetric(refs.ai7Cost, refs.ai7Sub, totals.last_7_days);
    setMetric(refs.aiMonthCost, refs.aiMonthSub, totals.this_month);
    setMetric(refs.aiAllCost, refs.aiAllSub, totals.all_time);
    const range = data?.range || {};
    if (refs.aiCalculatedCost) refs.aiCalculatedCost.textContent = aiRecordedCost(range);
    if (refs.aiCalculatedCostSub) refs.aiCalculatedCostSub.textContent = aiCalculatedStatus(range);
    if (refs.aiCalculatedCoverage) refs.aiCalculatedCoverage.innerHTML = aiPricingCoverage(range);
    const label = aiRangeLabel(range);
    if (range.start && range.end) {
        state.aiRange.start = range.start;
        state.aiRange.end = range.end;
        if (refs.aiRangeStart) refs.aiRangeStart.value = range.start;
        if (refs.aiRangeEnd) refs.aiRangeEnd.value = range.end;
    }
    if (refs.aiRangeStart && data?.earliest_event_date) refs.aiRangeStart.min = data.earliest_event_date;
    setMetric(refs.aiRangeCost, refs.aiRangeSub, range);
    if (refs.aiRangeCaption) refs.aiRangeCaption.textContent = `Showing ${label || 'the selected range'} · ${aiExactCount(range.days)} days (UTC). Lifetime totals include all available records.`;
    if (refs.aiRangeAvg) refs.aiRangeAvg.textContent = aiExactCount(range.calls);
    if (refs.aiRangeAvgSub) refs.aiRangeAvgSub.textContent = `${aiExactCount(range.active_days)} of ${aiExactCount(range.days)} days with recorded activity`;
    const top = (Array.isArray(data?.daily) ? data.daily : []).reduce((best, day) => Number(day.tokens) > Number(best?.tokens || 0) ? day : best, null);
    if (refs.aiRangeTopDay) refs.aiRangeTopDay.textContent = formatTokens(top?.tokens);
    if (refs.aiRangeTopDaySub) refs.aiRangeTopDaySub.textContent = top ? formatAiDate(top.date) : 'No recorded tokens';
    if (refs.aiRangeSaved) refs.aiRangeSaved.textContent = formatTokens(range.cached_tokens);
    if (refs.aiRangeSavedSub) refs.aiRangeSavedSub.textContent = 'Subset of recorded input tokens';
    if (refs.aiRangeSearch) refs.aiRangeSearch.textContent = aiExactCount(range.search_queries);
    if (refs.aiRangeSearchSub) refs.aiRangeSearchSub.textContent = 'Recorded provider search counter';
    const granularity = range.granularity || 'day';
    const word = granularity === 'month' ? 'month' : (granularity === 'week' ? 'week' : 'day');
    if (refs.aiTimelineTitle) refs.aiTimelineTitle.textContent = `Recorded tokens by ${word}`;
    if (refs.aiTimelineSub) refs.aiTimelineSub.textContent = `Recorded provider tokens per ${word} · ${label}. Voice characters are separate.`;
    if (refs.aiSourceSub) refs.aiSourceSub.textContent = `Recorded usage by feature · ${label}.`;
    if (refs.aiModelSub) refs.aiModelSub.textContent = `Recorded usage by provider model identifier · ${label}.`;
    if (refs.aiDailyCaption) refs.aiDailyCaption.textContent = `Recorded usage in ${label || 'the selected range'}, newest first.`;
    state.aiSeries = Array.isArray(data?.series) && data.series.length ? data.series : (Array.isArray(data?.daily) ? data.daily : []);
    state.aiGranularity = granularity;
    renderAiTimelineChart();
    renderAiBreakdown(refs.aiSourceChart, data?.by_source || [], (row) => row.label);
    renderAiBreakdown(refs.aiModelChart, data?.by_model || [], (row) => row.model || 'Unknown model');
    renderAiDailyTable();
}

// --- Profile accounting and Google billing ---------------------------------
function aiAccountingParams(range = state.aiRange) {
    const params = new URLSearchParams();
    if (range.start) params.set('start', range.start);
    if (range.end) params.set('end', range.end);
    return params;
}

function aiExactCount(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return '0';
    return Number(value).toLocaleString('en-US', { maximumFractionDigits: 0 });
}

function aiRecordedValue(stats, key) {
    return aiExactCount(stats?.[key]);
}

function aiRecordedCost(stats) {
    // Only the audited calculator can supply this value. Legacy estimated and
    // Google project-wide billed amounts are never used as a profile fallback.
    const known = stats?.calculated_cost_available === true
        && ['complete', 'partial'].includes(stats?.calculated_cost_status);
    return aiBillingMoney(known ? stats.calculated_cost_usd : '0', 'USD');
}

function aiCalculatedStatus(stats) {
    if (stats?.calculated_cost_status === 'no_usage' || !Number(stats?.calls)) return 'No recorded usage';
    if (stats?.calculated_cost_status === 'complete' && stats.calculated_cost_available) return 'Recorded usage × published rates';
    if (stats?.calculated_cost_status === 'partial' && stats.calculated_cost_available) return 'Partial cost · see pricing coverage';
    return 'Cost unavailable · missing usage or pricing';
}

function aiCalculatedCell(stats) {
    return `<strong>${escapeHtml(aiRecordedCost(stats))}</strong><div class="user-meta">${escapeHtml(aiCalculatedStatus(stats))}</div>`;
}

function aiPricingCoverage(stats = {}) {
    const reasonLabels = {
        input_modality_not_recorded: 'Input type was not recorded, so its price is unavailable.',
        grounding_fees_and_free_allowance: 'Search grounding fees and shared free allowances are excluded.',
        tool_or_unclassified_tokens: 'Tool or unclassified tokens could not be priced.',
        non_token_price_not_verified: 'Voice or other non-token pricing has not been verified.',
        historical_counters_retained_without_raw_provider_metadata: 'Older records retain token counters without the original provider metadata.',
        valued_at_standard_list_rates_service_tier_not_retained: 'The original service tier was not recorded; this value uses standard rates.',
        model_rate_not_verified: 'The model has no verified price in the rate catalog.',
        usage_not_measured: 'Some requests have no measured usage.',
        provider_usage_metadata_missing: 'Provider usage metadata is missing.',
        explicit_cache_storage: 'Cache storage charges are excluded.',
        explicit_cache_storage_duration_not_metered: 'Cache storage duration and charges are excluded.',
        region_not_retained_standard_global_rates_used: 'The original region was not recorded; this value uses the verified global rate.',
        historical_request_date_price_not_verified: 'The price on the original request date is not verified; this value uses the current catalog.',
        historical_provider_not_retained_shared_standard_rates_used: 'The original API provider was not recorded; only supported rates shared by both providers are used.',
        service_tier_not_retained_standard_rates_used: 'The original service tier was not recorded; this value uses standard rates.'
    };
    const reasons = [...new Set([...(stats.cost_exclusions || []), ...(stats.calculation_assumptions || []), ...(stats.rate_coverage_reasons || [])].map(reason => reasonLabels[reason] || String(reason).replace(/_/g, ' ')))];
    const verified = Array.isArray(stats.rates_verified_at) ? stats.rates_verified_at.join(', ') : String(stats.rates_verified_at || '');
    return `<div class="ai-pricing-coverage"><p><strong>${escapeHtml(aiCalculatedStatus(stats))}</strong> · ${escapeHtml(aiExactCount(stats.priced_calls))} fully priced calls · ${escapeHtml(aiExactCount(stats.partially_priced_calls))} partially priced · ${escapeHtml(aiExactCount(Math.max(0, Number(stats.unpriced_calls || 0) - Number(stats.partially_priced_calls || 0))))} unavailable.</p>
        <p>Calculated USD = (uncached input × input rate + cached input × cache rate + output (including thinking) × output rate) ÷ 1,000,000. Rates are per million tokens and selected for each request’s model and prompt size.</p>
        <p>Uses Google’s currently published standard rates${verified ? `, verified ${escapeHtml(verified)}` : ''}. Historical prices, discounts, credits, tax and currency conversion are not reconstructed. The imported Google bill is shown separately. Missing amounts display 0; they do not confirm zero cost.</p>
        ${reasons.length ? `<ul>${reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join('')}</ul>` : ''}
        <p><a href="https://ai.google.dev/gemini-api/docs/pricing" target="_blank" rel="noopener noreferrer">Gemini API rates</a> · <a href="https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing" target="_blank" rel="noopener noreferrer">Google Cloud rates</a></p></div>`;
}

function aiCoverageChips(stats) {
    if (!stats || !Number(stats.calls)) return '<span class="ai-coverage-chip">No records</span>';
    const chips = [];
    [['unknown_calls', 'missing usage'], ['legacy_calls', 'legacy']].forEach(([key, label]) => {
        if (Number(stats[key]) > 0) chips.push(`<span class="ai-coverage-chip warning">${escapeHtml(aiExactCount(stats[key]))} ${label}</span>`);
    });
    return chips.length ? chips.join('') : '<span class="ai-coverage-chip">Recorded usage</span>';
}

function closeAiProfileDetail() {
    state.aiProfileId = null;
    state.aiProfileRequestId += 1;
    if (refs.aiProfileDetail) refs.aiProfileDetail.hidden = true;
}

function invalidateAiAccounting() {
    state.aiProfiles.requestId += 1;
    state.aiProfiles.loading = true;
    state.aiProfiles.data = null;
    state.aiProfiles.total = 0;
    state.aiBilling.requestId += 1;
    state.aiBilling.loading = true;
    state.aiBilling.data = null;
    closeAiProfileDetail();
    if (refs.aiMonthHero) refs.aiMonthHero.textContent = '$0.00';
    if (refs.aiHeroLabel) refs.aiHeroLabel.textContent = 'Billing not loaded for these dates';
    if (refs.aiHeroNote) refs.aiHeroNote.textContent = '';
    if (refs.aiProfilesTableBody) refs.aiProfilesTableBody.innerHTML = '<tr><td colspan="6" class="table-empty">Loading profile usage…</td></tr>';
    if (refs.aiCoverage) refs.aiCoverage.textContent = 'Checking available records and coverage…';
    if (refs.aiReconciliation) refs.aiReconciliation.innerHTML = `${aiBillingMetrics()}<p class="ai-accounting-note">Loading imported billing…</p>`;
    state.aiAccounts.requestId += 1;
    state.aiAccounts.loading = true;
    state.aiAccounts.data = null;
    resetAiAccountsView('Loading usage by account…');
    renderAiProfilesControls();
    renderAiBillingControls();
    renderAiAccountsControls();
}

function aiAccountingUnavailable(message) {
    state.aiProfiles.loading = false;
    state.aiBilling.loading = false;
    if (refs.aiProfilesTableBody) refs.aiProfilesTableBody.innerHTML = `<tr><td colspan="6" class="table-empty">${escapeHtml(message)}</td></tr>`;
    if (refs.aiCoverage) refs.aiCoverage.textContent = 'Coverage could not be checked.';
    state.aiAccounts.loading = false;
    resetAiAccountsView(message);
    renderAiAccountsControls();
    if (refs.aiReconciliation) refs.aiReconciliation.innerHTML = `${aiBillingMetrics()}<p class="ai-accounting-note">${escapeHtml(message)} No imported amount is available for this view.</p>`;
    renderAiProfilesControls();
    renderAiBillingControls();
}

function renderAiProfilesControls() {
    const profiles = state.aiProfiles;
    const pages = Math.max(1, Math.ceil(profiles.total / profiles.pageSize));
    if (refs.aiProfilesPrevBtn) refs.aiProfilesPrevBtn.disabled = profiles.loading || profiles.page <= 1;
    if (refs.aiProfilesNextBtn) refs.aiProfilesNextBtn.disabled = profiles.loading || profiles.page >= pages;
    if (refs.aiProfilesApplyBtn) refs.aiProfilesApplyBtn.disabled = profiles.loading;
    if (refs.aiProfilesResetBtn) refs.aiProfilesResetBtn.disabled = profiles.loading;
    if (refs.aiProfilesPageInfo) refs.aiProfilesPageInfo.textContent = `Page ${profiles.page} of ${pages}`;
    if (refs.aiProfilesExportBtn) {
        refs.aiProfilesExportBtn.disabled = profiles.loading || profiles.exporting || !profiles.total;
        refs.aiProfilesExportBtn.textContent = profiles.exporting ? 'Preparing CSV…' : 'Export all matching profiles';
    }
}

function renderAiCoverage(coverage = {}, health = {}) {
    if (!refs.aiCoverage) return;
    const first = coverage.first_recorded_at ? `First available record: ${formatDateTime(coverage.first_recorded_at)} (UTC).` : 'No first record is available.';
    const counts = `${aiExactCount(coverage.measured_calls)} measured calls · ${aiExactCount(coverage.legacy_calls)} legacy calls · ${aiExactCount(coverage.unknown_calls)} calls missing usage in the selected range.`;
    const sharedLine = (name, stats) => `${name}: ${aiExactCount(stats?.calls)} calls, ${aiRecordedValue(stats, 'total_tokens')} recorded tokens.`;
    const healthNotes = [];
    if (Number(health.spooled_events) > 0) healthNotes.push(`${aiExactCount(health.spooled_events)} usage records are waiting to be saved to the database. Totals may be incomplete until they are replayed.`);
    if (Number(health.unrecoverable_writes) > 0) healthNotes.push(`${aiExactCount(health.unrecoverable_writes)} usage records could not be saved or recovered. Investigate before relying on complete totals.`);
    refs.aiCoverage.innerHTML = `<p><strong>Coverage and attribution</strong> · ${escapeHtml(first)}</p>
        <p>${escapeHtml(coverage.note || 'Lifetime means all available records. Usage before tracking began or without retained records cannot be reconstructed exactly.')}</p>
        <p>${escapeHtml(counts)}</p>
        <p>${escapeHtml(sharedLine('Shared AI operations', coverage.shared))} ${escapeHtml(sharedLine('Unclassified / unattributed AI operations', coverage.unattributed))} These records are separate from confirmed B2C profile totals. Missing counters show 0 and do not establish zero usage.</p>
        ${healthNotes.map((message) => `<p><strong>Tracking needs attention.</strong> ${escapeHtml(message)}</p>`).join('')}`;
}

function aiProfilesEmptyMessage() {
    // The table follows the date filter: a profile without recorded usage in the selected dates is not listed.
    return state.aiProfiles.search
        ? 'No profiles match this search with recorded AI usage in the selected dates. Try another name or email, or widen the dates.'
        : 'No profiles with recorded AI usage in the selected dates.';
}

function renderAiProfiles(data) {
    const profiles = Array.isArray(data.profiles) ? data.profiles : [];
    state.aiProfiles.data = data;
    state.aiProfiles.total = Number(data.total) || 0;
    state.aiProfiles.page = Number(data.page) || 1;
    state.aiProfiles.pageSize = Number(data.page_size) || 25;
    if (refs.aiProfilesTableBody) refs.aiProfilesTableBody.innerHTML = profiles.length ? profiles.map((profile) => {
        const selected = profile.range || {};
        const lifetime = profile.lifetime || {};
        const first = lifetime.first_event_at ? `Records from ${formatDateTime(lifetime.first_event_at)} (UTC)` : 'No retained usage records';
        return `<tr><td><button type="button" class="ai-profile-link" data-ai-profile-id="${escapeHtml(String(profile.user_id))}">${escapeHtml(profile.name || profile.email || 'Student')}</button><div class="user-meta">${escapeHtml(profile.email || '')}</div><div class="user-meta">${escapeHtml(first)}</div></td>
            <td><strong>${escapeHtml(aiRecordedValue(selected, 'total_tokens'))}</strong><div class="user-meta">${escapeHtml(aiExactCount(selected.calls))} calls${Number(selected.unknown_calls) > 0 ? ' · partial usage' : ''}</div></td>
            <td>${aiCalculatedCell(selected)}</td>
            <td><strong>${escapeHtml(aiRecordedValue(lifetime, 'total_tokens'))}</strong><div class="user-meta">${escapeHtml(aiExactCount(lifetime.calls))} calls</div></td>
            <td>${aiCalculatedCell(lifetime)}</td><td>${aiCoverageChips(selected)}</td></tr>`;
    }).join('') : `<tr><td colspan="6" class="table-empty">${escapeHtml(aiProfilesEmptyMessage())}</td></tr>`;
    if (refs.aiProfilesSummary) {
        const first = state.aiProfiles.total ? (state.aiProfiles.page - 1) * state.aiProfiles.pageSize + 1 : 0;
        refs.aiProfilesSummary.textContent = state.aiProfiles.total
            ? `Showing ${first}–${first + profiles.length - 1} of ${aiExactCount(state.aiProfiles.total)} profiles with recorded usage · ${aiRangeLabel(data.range)} (UTC) · ordered by recorded tokens in these dates`
            : aiProfilesEmptyMessage();
    }
    renderAiCoverage(data.coverage, data.metering_health);
    renderAiProfilesControls();
}

async function loadAiProfiles({ resetPage = false } = {}) {
    if (!canAccessSection('ai')) return;
    const profiles = state.aiProfiles;
    const requestId = ++profiles.requestId;
    if (resetPage) profiles.page = 1;
    const params = aiAccountingParams();
    params.set('page', String(profiles.page));
    params.set('page_size', String(profiles.pageSize));
    if (profiles.search) params.set('search', profiles.search);
    profiles.loading = true;
    closeAiProfileDetail();
    renderAiProfilesControls();
    if (refs.aiProfilesTableBody) refs.aiProfilesTableBody.innerHTML = '<tr><td colspan="6" class="table-empty">Loading profile usage…</td></tr>';
    try {
        if (!await ensureAdminProtection({ silent: false })) return;
        const response = await adminFetch(`${API_BASE}/api/admin/ai-usage/profiles?${params}`, { headers: buildAuthHeaders(), credentials: 'same-origin' });
        const payload = await response.json().catch(() => ({}));
        if (requestId !== profiles.requestId) return;
        if (!response.ok) {

            throw new Error(normalizeErrorMessage(payload, 'Could not load profile usage.'));
        }
        renderAiProfiles(payload);
    } catch (error) {
        if (requestId !== profiles.requestId) return;
        profiles.data = null;
        profiles.total = 0;
        if (refs.aiProfilesTableBody) refs.aiProfilesTableBody.innerHTML = `<tr><td colspan="6" class="table-empty">${escapeHtml(error.message || 'Could not load profile usage. Please retry.')}</td></tr>`;
        if (refs.aiProfilesSummary) refs.aiProfilesSummary.textContent = 'Profile usage could not be loaded.';
        if (refs.aiCoverage) refs.aiCoverage.textContent = 'Coverage could not be checked. Search again to retry.';
    } finally {
        if (requestId === profiles.requestId) { profiles.loading = false; renderAiProfilesControls(); }
    }
}

function changeAiProfilesPage(delta) {
    const profiles = state.aiProfiles;
    const pages = Math.max(1, Math.ceil(profiles.total / profiles.pageSize));
    if (profiles.loading || profiles.page + delta < 1 || profiles.page + delta > pages) return;
    profiles.page += delta;
    void loadAiProfiles();
}

function aiFeatureTable(features, period, totals) {
    const rows = features.map((feature) => ({ label: feature.label || feature.source || 'Other AI', stats: feature[period] || {} }));
    rows.push({ label: 'All recorded features', stats: totals || {}, total: true });
    return `<p class="ai-detail-help ai-scroll-hint">Scroll horizontally to view all token categories and coverage.</p><div class="table-wrap"><table class="users-table ai-feature-table"><thead><tr>
        <th scope="col">Feature</th><th scope="col">Total tokens</th><th scope="col">Calculated USD</th><th scope="col">Calls</th><th scope="col">Input</th><th scope="col">Output<br><span>Candidate</span></th><th scope="col">Thinking</th><th scope="col">Cached<br><span>Within input</span></th><th scope="col">Tool</th><th scope="col">TTS<br><span>Characters</span></th><th scope="col">Coverage</th></tr></thead><tbody>${rows.map(({ label, stats, total }) => `<tr${total ? ' class="ai-feature-total"' : ''}><td>${escapeHtml(label)}</td><td>${escapeHtml(aiRecordedValue(stats, 'total_tokens'))}</td><td>${aiCalculatedCell(stats)}</td><td>${escapeHtml(aiExactCount(stats.calls))}</td>${['input_tokens', 'output_tokens', 'thinking_tokens', 'cached_tokens', 'tool_tokens', 'tts_characters'].map((key) => `<td>${escapeHtml(aiRecordedValue(stats, key))}</td>`).join('')}<td>${aiCoverageChips(stats)}</td></tr>`).join('')}</tbody></table></div>`;
}

function aiProfileDailyTable(days) {
    const rows = Array.isArray(days) ? days.slice().reverse() : [];
    return `<div class="table-wrap"><table class="users-table ai-profile-daily-table"><thead><tr><th>Date (UTC)</th><th>Calls</th><th>Total tokens</th><th>TTS characters</th><th>Calculated USD</th></tr></thead><tbody>${rows.length ? rows.map((day) => `<tr><td>${escapeHtml(formatAiDate(day.date))}</td><td>${escapeHtml(aiExactCount(day.calls))}</td><td>${escapeHtml(aiRecordedValue(day, 'total_tokens'))}</td><td>${escapeHtml(aiRecordedValue(day, 'tts_characters'))}</td><td>${aiCalculatedCell(day)}</td></tr>`).join('') : '<tr><td colspan="5" class="table-empty">0 recorded usage and $0.00 calculated cost in this range.</td></tr>'}</tbody></table></div>`;
}

function renderAiProfileDetail(data) {
    const profile = data.profile || {};
    if (refs.aiProfileDetailTitle) refs.aiProfileDetailTitle.textContent = profile.name || profile.email || 'Student profile';
    if (refs.aiProfileDetailSubtitle) refs.aiProfileDetailSubtitle.textContent = profile.email || '';
    const features = Array.isArray(data.features) ? data.features : [];
    const first = data.lifetime_totals?.first_event_at ? `First retained record: ${formatDateTime(data.lifetime_totals.first_event_at)} (UTC).` : 'No retained usage records for this profile.';
    if (refs.aiProfileDetailBody) refs.aiProfileDetailBody.innerHTML = `<p class="ai-detail-help">${escapeHtml(data.coverage_note || 'Lifetime includes available records only. It does not establish complete usage since signup.')} ${escapeHtml(first)}</p>
        <details class="ai-pricing-details"><summary>Pricing coverage and calculation · lifetime</summary>${aiPricingCoverage(data.lifetime_totals)}</details>
        <h5>Selected range · ${escapeHtml(aiRangeLabel(data.range))} (UTC)</h5>${aiFeatureTable(features, 'range', data.range_totals)}
        <h5>Daily usage and cost · selected range (UTC)</h5>${aiProfileDailyTable(data.daily || [])}
        <h5>Lifetime recorded usage</h5>${aiFeatureTable(features, 'lifetime', data.lifetime_totals)}
        <p class="ai-detail-help">Input includes prompts, system instructions and conversation context. Cached tokens are a subset of input. Output shows candidate tokens; thinking is separate. Total tokens use the recorded provider total, so adding every column would double-count some tokens. Voice-synthesis characters are separate from tokens.</p>
        <p class="ai-detail-help">Missing usage is excluded from known token totals. Legacy output can include thinking; older records may not retain separate thinking or tool counters. A zero in those legacy columns does not establish zero usage. Calculated cost uses supported recorded components only. Google project charges are not allocated to profiles.</p>`;
}

async function loadAiProfileDetail(userId) {
    if (!canAccessSection('ai')) return;
    const requestId = ++state.aiProfileRequestId;
    state.aiProfileId = String(userId);
    const params = aiAccountingParams();
    if (refs.aiProfileDetail) { refs.aiProfileDetail.hidden = false; refs.aiProfileDetail.scrollIntoView?.({ behavior: 'smooth', block: 'start' }); }
    if (refs.aiProfileDetailTitle) refs.aiProfileDetailTitle.textContent = 'Loading profile…';
    if (refs.aiProfileDetailSubtitle) refs.aiProfileDetailSubtitle.textContent = '';
    if (refs.aiProfileDetailBody) refs.aiProfileDetailBody.innerHTML = '<p class="ai-accounting-note">Loading feature breakdown…</p>';
    try {
        if (!await ensureAdminProtection({ silent: false })) return;
        const response = await adminFetch(`${API_BASE}/api/admin/ai-usage/profiles/${encodeURIComponent(userId)}?${params}`, { headers: buildAuthHeaders(), credentials: 'same-origin' });
        const payload = await response.json().catch(() => ({}));
        if (requestId !== state.aiProfileRequestId) return;
        if (!response.ok) {

            throw new Error(normalizeErrorMessage(payload, 'Could not load this profile.'));
        }
        renderAiProfileDetail(payload);
        refs.aiProfileDetailTitle?.focus({ preventScroll: true });
    } catch (error) {
        if (requestId !== state.aiProfileRequestId) return;
        if (refs.aiProfileDetailTitle) refs.aiProfileDetailTitle.textContent = 'Profile usage unavailable';
        if (refs.aiProfileDetailBody) refs.aiProfileDetailBody.innerHTML = `<p class="ai-accounting-note">${escapeHtml(error.message || 'Could not load this profile. Please retry.')}</p>`;
    }
}

function resetAiAccountsView(message) {
    if (refs.aiAccountsSummary) refs.aiAccountsSummary.innerHTML = `<p class="ai-accounting-note">${escapeHtml(message)}</p>`;
    [refs.aiOrgsTableBody, refs.aiUnlistedTableBody, refs.aiSharedTableBody, refs.aiUnattributedTableBody].forEach((body) => {
        if (body) body.innerHTML = `<tr><td colspan="6" class="table-empty">${escapeHtml(message)}</td></tr>`;
    });
}

function renderAiAccountsControls() {
    const accounts = state.aiAccounts;
    if (!refs.aiAccountsExportBtn) return;
    const calls = Number(accounts.data?.ledger?.range?.calls || 0);
    refs.aiAccountsExportBtn.disabled = accounts.loading || accounts.exporting || !calls;
    refs.aiAccountsExportBtn.textContent = accounts.exporting ? 'Preparing CSV…' : 'Export usage by account';
}

function aiAccountRow(label, meta, row = {}) {
    const selected = row.range || {};
    const lifetime = row.lifetime || {};
    return `<tr><td><strong>${escapeHtml(label)}</strong>${meta ? `<div class="user-meta">${escapeHtml(meta)}</div>` : ''}</td>
        <td><strong>${escapeHtml(aiRecordedValue(selected, 'total_tokens'))}</strong><div class="user-meta">${escapeHtml(aiExactCount(selected.calls))} calls</div></td>
        <td>${aiCalculatedCell(selected)}</td>
        <td><strong>${escapeHtml(aiRecordedValue(lifetime, 'total_tokens'))}</strong><div class="user-meta">${escapeHtml(aiExactCount(lifetime.calls))} calls</div></td>
        <td>${aiCalculatedCell(lifetime)}</td><td>${aiCoverageChips(selected)}</td></tr>`;
}

function aiAccountsReconcileLine(data = {}) {
    // The ledger total (all four buckets) is the number to hold against Google's project-wide charge.
    const ledger = data.ledger?.range || {};
    const ledgerText = aiRecordedCost(ledger);
    const google = data.google || {};
    if (!google.available) {
        return `Ledger total ${ledgerText} across all four buckets for these dates. ${google.message || 'No imported Google charge is available for these dates.'}`;
    }
    const googleCost = Number(google.cost_before_credits_usd || 0);
    const gap = Number(ledger.calculated_cost_usd || 0) - googleCost;
    const gapText = Math.abs(gap) < 0.000001 ? 'they match'
        : `ledger ${gap > 0 ? 'higher' : 'lower'} by ${aiBillingMoney(Math.abs(gap).toFixed(6), 'USD')}`;
    const source = google.derived && google.source_range ? ` The Google figure is taken from the import covering ${aiRangeLabel(google.source_range)}.` : '';
    const firstDay = google.first_usage_date && data.range?.start && google.first_usage_date > data.range.start
        ? ` Google's import only has rows from ${formatAiDate(google.first_usage_date)}; ledger calls before that day are not in it.` : '';
    return `Ledger total ${ledgerText} across all four buckets vs Google cost before credits ${aiBillingMoney(String(google.cost_before_credits_usd ?? 0), 'USD')} for the same dates: ${gapText}.${source}${firstDay} Google bills the project as a whole; the split above comes from the app ledger.`;
}

function renderAiAccounts(data = {}) {
    const accounts = state.aiAccounts;
    accounts.data = data;
    accounts.loading = false;
    const buckets = Array.isArray(data.buckets) ? data.buckets : [];
    const ledgerCost = Number(data.ledger?.range?.calculated_cost_usd || 0);
    const share = (bucket) => {
        const value = Number(bucket.range?.calculated_cost_usd || 0);
        return ledgerCost > 0 ? `${(value / ledgerCost * 100).toFixed(1)}% of the ledger total` : 'no calculated cost in these dates';
    };
    const unlistedTotal = data.b2c_unlisted_total?.range || {};
    const unlistedNote = (bucket) => bucket.key === 'b2c' && Number(unlistedTotal.calls || 0)
        ? ` · includes ${aiRecordedCost(unlistedTotal)} (${aiExactCount(unlistedTotal.calls)} calls) not listed in the profile table` : '';
    const cards = buckets.map((bucket) => `<article class="metric-card ai-range-metric" title="${escapeHtml(bucket.description || '')}"><span>${escapeHtml(bucket.label || bucket.key || 'Bucket')}</span><strong>${escapeHtml(aiRecordedCost(bucket.range))}</strong><div class="metric-subtext">${escapeHtml(aiRecordedValue(bucket.range, 'total_tokens'))} tokens · ${escapeHtml(aiExactCount(bucket.range?.calls))} calls · ${escapeHtml(share(bucket))}${escapeHtml(unlistedNote(bucket))}</div></article>`).join('');
    if (refs.aiAccountsSummary) {
        refs.aiAccountsSummary.innerHTML = buckets.length
            ? `<div class="metrics-grid finance-metrics-grid ai-range-metrics">${cards}</div><p class="ai-accounting-note"><strong>${escapeHtml(aiAccountsReconcileLine(data))}</strong></p><p class="ai-detail-help">${escapeHtml(data.note || '')}</p>`
            : '<p class="ai-accounting-note">Usage by account is not available.</p>';
    }
    const empty = (message) => `<tr><td colspan="6" class="table-empty">${escapeHtml(message)}</td></tr>`;
    const organizations = Array.isArray(data.organizations) ? data.organizations : [];
    if (refs.aiOrgsTableBody) refs.aiOrgsTableBody.innerHTML = organizations.length
        ? organizations.map((org) => aiAccountRow(org.name || `Organisation ${org.organization_id}`,
            org.organization_id ? `${org.subdomain ? `${org.subdomain} · ` : ''}organisation id ${org.organization_id}` : 'organisation id not recorded on these calls', org)).join('')
        : empty('No enterprise organisation used AI in the selected dates.');
    const unlisted = Array.isArray(data.b2c_unlisted) ? data.b2c_unlisted : [];
    if (refs.aiUnlistedTableBody) refs.aiUnlistedTableBody.innerHTML = unlisted.length
        ? unlisted.map((row) => aiAccountRow(row.name || 'Profile', row.user_id
            ? `${row.email ? `${row.email} · ` : ''}enterprise-origin account, cannot sign in to the B2C app`
            : 'calls recorded without a profile id', row)).join('')
        : empty('Every B2C call in the selected dates belongs to a profile listed above.');
    const shared = Array.isArray(data.shared) ? data.shared : [];
    if (refs.aiSharedTableBody) refs.aiSharedTableBody.innerHTML = shared.length
        ? shared.map((row) => aiAccountRow(row.source || 'Unknown feature', 'Rilono background job', row)).join('')
        : empty('No shared platform AI work in the selected dates.');
    const unattributed = Array.isArray(data.unattributed) ? data.unattributed : [];
    if (refs.aiUnattributedTableBody) refs.aiUnattributedTableBody.innerHTML = unattributed.length
        ? unattributed.map((row) => aiAccountRow(row.source || 'Unknown feature', 'no account or product recorded', row)).join('')
        : empty('Every call in the selected dates is attributed.');
    renderAiAccountsControls();
}

async function loadAiAccounts() {
    if (typeof canAccessSection === 'function' && !canAccessSection('ai')) return;
    const accounts = state.aiAccounts;
    const requestId = ++accounts.requestId;
    const params = aiAccountingParams();
    accounts.loading = true;
    renderAiAccountsControls();
    const doFetch = typeof adminFetch === 'function' ? adminFetch : fetch;
    try {
        if (!await ensureAdminProtection({ silent: false })) return;
        const response = await doFetch(`${API_BASE}/api/admin/ai-usage/accounts?${params}`, { headers: buildAuthHeaders(), credentials: 'same-origin' });
        const payload = await response.json().catch(() => ({}));
        if (requestId !== accounts.requestId) return;
        if (!response.ok) {
            await handleAdminAuthOrProtectionError(response.status, payload);
            throw new Error(normalizeErrorMessage(payload, 'Could not load usage by account.'));
        }
        renderAiAccounts(payload);
    } catch (error) {
        if (requestId !== accounts.requestId) return;
        accounts.data = null;
        accounts.loading = false;
        resetAiAccountsView(error.message || 'Could not load usage by account. Please retry.');
        renderAiAccountsControls();
    }
}

async function exportAiAccounts() {
    if (typeof requireAdminPermission === 'function' && !requireAdminPermission('ai')) return;
    const accounts = state.aiAccounts;
    if (accounts.loading || accounts.exporting || !Number(accounts.data?.ledger?.range?.calls || 0)) return;
    const params = aiAccountingParams();
    accounts.exporting = true;
    renderAiAccountsControls();
    const doFetch = typeof adminFetch === 'function' ? adminFetch : fetch;
    try {
        if (!await ensureAdminProtection({ silent: false })) return;
        const response = await doFetch(`${API_BASE}/api/admin/ai-usage/accounts/export?${params}`, { headers: buildAuthHeaders(), credentials: 'same-origin' });
        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            throw new Error(normalizeErrorMessage(payload, 'Could not export usage by account.'));
        }
        const blob = await response.blob();
        const filename = (response.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/i)?.[1] || 'rilono-ai-usage-by-account.csv';
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
        showFlash(`Downloaded ${filename}`, 'success');
    } catch (error) {
        showFlash(error.message || 'Could not export usage by account. Please retry.', 'error');
    } finally {
        accounts.exporting = false;
        renderAiAccountsControls();
    }
}

async function exportAiProfiles() {
    if (!requireAdminPermission('ai')) return;
    const profiles = state.aiProfiles;
    if (profiles.loading || profiles.exporting || !profiles.total) return;
    const params = aiAccountingParams();
    if (profiles.search) params.set('search', profiles.search);
    profiles.exporting = true;
    renderAiProfilesControls();
    try {
        if (!await ensureAdminProtection({ silent: false })) return;
        const response = await adminFetch(`${API_BASE}/api/admin/ai-usage/profiles/export?${params}`, { headers: buildAuthHeaders(), credentials: 'same-origin' });
        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));

            throw new Error(normalizeErrorMessage(payload, 'Could not export profile usage.'));
        }
        const blob = await response.blob();
        const filename = (response.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/i)?.[1] || 'rilono-ai-profile-usage.csv';
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
        showFlash(`Downloaded ${filename}`, 'success');
    } catch (error) {
        showFlash(error.message || 'Could not export profile usage. Please retry.', 'error');
    } finally {
        profiles.exporting = false;
        renderAiProfilesControls();
    }
}

function renderAiBillingControls() {
    if (!refs.aiBillingSyncBtn) return;
    refs.aiBillingSyncBtn.disabled = state.aiBilling.loading || state.aiBilling.syncing || !state.aiBilling.data?.configured;
    refs.aiBillingSyncBtn.textContent = state.aiBilling.syncing ? 'Syncing billing…' : 'Sync billing';
}

function aiBillingMoney(value, currency) {
    // Billing decimals arrive as strings. Never round them through a JS Number.
    const match = String(value ?? '0').trim().match(/^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/);
    let integer = '0', fraction = '', negative = false;
    if (match) {
        const exponent = Number(match[4] || 0);
        if (Number.isInteger(exponent) && Math.abs(exponent) <= 1000) {
            const digits = match[2] + (match[3] || '');
            const point = match[2].length + exponent;
            integer = point <= 0 ? '0' : digits.slice(0, point).padEnd(point, '0');
            fraction = point <= 0 ? '0'.repeat(-point) + digits : digits.slice(point);
            integer = integer.replace(/^0+(?=\d)/, '');
            fraction = fraction.replace(/0+$/, '');
            negative = match[1] === '-' && /[1-9]/.test(integer + fraction);
        }
    }
    const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    const number = `${negative ? '-' : ''}${grouped}.${fraction.padEnd(2, '0')}`;
    return currency === 'USD' ? `$${number}` : `${currency || 'Unknown currency'} ${number}`;
}

function aiBillingMetrics(totals = []) {
    const rows = totals.length ? totals : [{ currency: 'USD', cost: 0, credits: 0, net_cost: 0 }];
    const value = (field) => rows.map((row) => `<strong>${escapeHtml(aiBillingMoney(row[field], row.currency))}</strong>`).join('');
    return `<div class="ai-billing-metrics"><div class="ai-billing-metric"><span>Imported Google cost before credits</span>${value('cost')}</div><div class="ai-billing-metric"><span>Imported Google credits</span>${value('credits')}</div><div class="ai-billing-metric"><span>Imported Google net cost</span>${value('net_cost')}</div></div>`;
}

function aiBillingCreditsApplied(data = {}, totals = []) {
    // Credits arrive as decimal strings; any nonzero digit in the totals or the breakdown means Google applied a credit.
    const nonZero = (value) => /[1-9]/.test(String(value ?? ''));
    return data.credits_applied === true || totals.some((row) => nonZero(row.credits))
        || (Array.isArray(data.credit_breakdown) && data.credit_breakdown.some((item) => nonZero(item.amount)));
}

function aiBillingCredits(data = {}, totals = [], awaitingExport = false) {
    if (!aiBillingCreditsApplied(data, totals)) return '';
    const items = Array.isArray(data.credit_breakdown) ? data.credit_breakdown : [];
    if (!items.length) {
        const reason = awaitingExport ? 'Credit names will be imported by the next successful sync.'
            : data.credit_breakdown_available ? 'Google returned no credit details for this range.'
            : 'Credit names are not part of this snapshot yet. Run Sync billing to load them.';
        return `<p class="ai-detail-help">${escapeHtml(reason)}</p>`;
    }
    const line = (item) => {
        const label = item.full_name || item.name || 'Credit';
        // Google's credit name is unique per grant; show it when the display name alone cannot tell grants apart.
        const grant = item.name && item.name !== label ? `<small>${escapeHtml(item.name)}</small>` : '';
        return `<li><span>${escapeHtml(label)}${item.type ? ` · ${escapeHtml(String(item.type).toLowerCase())}` : ''}${grant}</span><strong>${escapeHtml(aiBillingMoney(item.amount, item.currency))}</strong></li>`;
    };
    return `<div class="ai-billing-credits"><h5>Credits applied by Google</h5><ul>${items.map(line).join('')}</ul></div>`;
}

function renderAiReconciliation(data = {}) {
    state.aiBilling.data = data;
    renderAiBillingControls();
    if (!refs.aiReconciliation) return;
    const available = data.status === 'available' && Array.isArray(data.totals) && data.totals.length > 0;
    const totals = available ? data.totals : [];
    const note = data.scope_note || 'Billing covers the configured Google AI project, including B2B, shared and unattributed activity. Project charges cannot establish a profile-level billed cost.';
    const lastSync = data.last_synced_at ? formatDateTime(data.last_synced_at) + ' (UTC)' : 'Not synced yet';
    // Dates inside a wider import are served from it; say which import so the figures are traceable.
    const importedWindow = data.derived && data.source_range ? `<span>Imported window: ${escapeHtml(aiRangeLabel(data.source_range))} (UTC)</span>` : '';
    const meta = `<div class="ai-billing-meta"><span>Project: ${escapeHtml(data.project_id || 'Not configured')}</span><span>Last sync: ${escapeHtml(lastSync)}</span><span>${escapeHtml(aiRangeLabel(data.range))} (UTC)</span>${importedWindow}</div>`;
    const awaitingExport = data.sync_status === 'awaiting_export' || data.billing_status === 'awaiting_export' || data.status === 'awaiting_export';
    const status = awaitingExport ? (available ? 'Awaiting Google export · Previous import retained' : 'Awaiting Google billing export')
        : available ? 'Imported Google billing records'
        : !data.configured ? 'Google billing is not connected.' : 'No imported billing records for this range.';
    const zeroNote = available ? 'Amounts below are copied from Google billing records in their original currencies.'
        : 'Displayed amounts are 0 because no billed amount has been imported. This does not confirm that Google charged 0.';
    const creditNote = aiBillingCreditsApplied(data, totals)
        ? ' Google credits reduce the net amount. Track the cost before credits as the actual usage cost.' : '';
    // The tracked figure is the charge before credits: a promotion or free-trial credit can bring net to 0 while usage is real.
    if (refs.aiMonthHero) refs.aiMonthHero.textContent = totals.length ? totals.map((row) => aiBillingMoney(row.cost, row.currency)).join(' / ') : '$0.00';
    if (refs.aiHeroLabel) refs.aiHeroLabel.textContent = available ? 'Google cost before credits' : 'No imported billing amount';
    if (refs.aiHeroNote) refs.aiHeroNote.textContent = totals.length
        ? totals.map((row) => `Credits ${aiBillingMoney(row.credits, row.currency)} · Net ${aiBillingMoney(row.net_cost, row.currency)}`).join(' / ') : '';
    refs.aiReconciliation.innerHTML = `${aiBillingMetrics(totals)}${meta}
        <p class="ai-accounting-note"><strong>${status}</strong> ${escapeHtml(zeroNote)}${escapeHtml(creditNote)} ${escapeHtml(data.message || '')}</p>
        ${aiBillingCredits(data, totals, awaitingExport)}
        <p class="ai-detail-help">${escapeHtml(note)} Billing quantities can use different units and services; they are not combined into a single token total.</p>
        ${available && Array.isArray(data.usage_rows) && data.usage_rows.length ? `<details><summary class="ai-detail-help">Provider usage by service and billing item</summary><div class="table-wrap"><table class="users-table"><thead><tr><th>Service</th><th>Billing item</th><th>Usage</th><th>Unit</th><th>Cost</th></tr></thead><tbody>${data.usage_rows.map((row) => `<tr><td>${escapeHtml(row.service || 'Unknown')}</td><td>${escapeHtml(row.sku || 'Unknown')}</td><td>${escapeHtml(String(row.usage_amount ?? 0))}</td><td>${escapeHtml(row.unit || 'Unknown')}</td><td>${escapeHtml(aiBillingMoney(row.cost, row.currency))}</td></tr>`).join('')}</tbody></table></div></details>` : ''}`;
}

async function loadAiReconciliation() {
    if (!canAccessSection('ai')) return;
    const billing = state.aiBilling;
    const requestId = ++billing.requestId;
    const params = aiAccountingParams();
    billing.loading = true;
    renderAiBillingControls();
    try {
        if (!await ensureAdminProtection({ silent: false })) return;
        const response = await adminFetch(`${API_BASE}/api/admin/ai-usage/reconciliation?${params}`, { headers: buildAuthHeaders(), credentials: 'same-origin' });
        const payload = await response.json().catch(() => ({}));
        if (requestId !== billing.requestId) return;
        if (!response.ok) {

            throw new Error(normalizeErrorMessage(payload, 'Could not load imported billing.'));
        }
        renderAiReconciliation(payload);
    } catch (error) {
        if (requestId !== billing.requestId) return;
        billing.data = null;
        if (refs.aiMonthHero) refs.aiMonthHero.textContent = '$0.00';
        if (refs.aiHeroLabel) refs.aiHeroLabel.textContent = 'Billing could not be loaded';
        if (refs.aiHeroNote) refs.aiHeroNote.textContent = '';
        if (refs.aiReconciliation) refs.aiReconciliation.innerHTML = `${aiBillingMetrics()}<p class="ai-accounting-note">${escapeHtml(error.message || 'Could not load imported billing. Please retry.')} No imported amount is available for this view.</p>`;
    } finally {
        if (requestId === billing.requestId) { billing.loading = false; renderAiBillingControls(); }
    }
}

async function syncAiBilling() {
    if (!requireAdminPermission('ai', 'write')) return;
    const billing = state.aiBilling;
    if (billing.loading || billing.syncing || !billing.data?.configured) return;
    const range = { start: state.aiRange.start, end: state.aiRange.end };
    const requestId = ++billing.requestId;
    billing.syncing = true;
    renderAiBillingControls();
    try {
        if (!await ensureAdminProtection({ silent: false })) return;
        const response = await adminFetch(`${API_BASE}/api/admin/ai-usage/reconciliation/sync`, { method: 'POST', headers: buildAuthHeaders({ 'Content-Type': 'application/json' }), credentials: 'same-origin', body: JSON.stringify(range) });
        const payload = await response.json().catch(() => ({}));
        if (requestId !== billing.requestId) return;
        if (!response.ok) {

            throw new Error(normalizeErrorMessage(payload, 'Could not sync billing.'));
        }
        const awaitingExport = response.status === 202 || payload.sync_status === 'awaiting_export' || payload.status === 'awaiting_export';
        renderAiReconciliation(awaitingExport ? { ...payload, sync_status: 'awaiting_export' } : payload);
        if (awaitingExport) {
            showFlash(payload.message || 'Awaiting Google billing export. No new billing records have been imported.', 'info');
        } else {
            showFlash('Google billing import refreshed for the selected dates.', 'success');
        }
    } catch (error) {
        if (requestId === billing.requestId) showFlash(error.message || 'Could not sync billing. Please retry.', 'error');
    } finally {
        billing.syncing = false;
        renderAiBillingControls();
    }
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
    const sections = [];
    const costHeader = ['Calculated cost (USD)', 'Calculation status', 'Pricing basis', 'Excluded components'];
    const costValues = (row) => [row.calculated_cost_available ? row.calculated_cost_usd : '0', row.calculated_cost_status || 'unavailable', (row.rate_basis || []).join('; '), (row.cost_exclusions || []).join('; ')];
    if (kind === 'sources' || kind === 'all') sections.push({
        title: 'Usage by feature',
        header: ['Feature', 'Source key', 'Calls', 'Tokens', 'TTS characters', 'Searches', ...costHeader],
        rows: (data.by_source || []).map((row) => [row.label || row.source, row.source, row.calls || 0, row.tokens || 0, row.tts_characters || 0, row.search_queries || 0, ...costValues(row)])
    });
    if (kind === 'models' || kind === 'all') sections.push({
        title: 'Usage by model',
        header: ['Model', 'Calls', 'Tokens', 'TTS characters', ...costHeader],
        rows: (data.by_model || []).map((row) => [row.model, row.calls || 0, row.tokens || 0, row.tts_characters || 0, ...costValues(row)])
    });
    if (kind === 'daily' || kind === 'all') {
        const total = Number(data.range?.tokens) || 0;
        const hideEmpty = kind === 'daily' && (!refs.aiHideEmptyDays || refs.aiHideEmptyDays.checked);
        const days = hideEmpty ? (data.daily || []).filter((day) => (day.calls || 0) > 0) : (data.daily || []);
        sections.push({ title: 'Usage by date', header: ['Date (UTC)', 'Calls', 'Tokens', 'TTS characters', 'Share of recorded tokens (%)', ...costHeader],
            rows: days.map((day) => [day.date, day.calls || 0, day.tokens || 0, day.tts_characters || 0, total > 0 ? Number(((day.tokens || 0) / total * 100).toFixed(2)) : 0, ...costValues(day)]) });
    }
    return sections;
}

function exportAiCsv(kind, btn) {
    if (!requireAdminPermission('ai')) return;
    const data = state.aiUsageData;
    if (!data || !data.range) { showFlash('Load the AI usage data before exporting.', 'error'); return; }
    const range = data.range;
    const lines = [
        ['Rilono — Recorded AI usage and calculated costs'],
        ['Range (UTC)', range.start, 'to', range.end],
        ['Days in range', range.days || 0, 'Days with activity', range.active_days || 0],
        ['Recorded calls', range.calls || 0, 'Recorded tokens', range.tokens || 0, 'TTS characters', range.tts_characters || 0],
        ['Calculated cost (USD)', range.calculated_cost_available ? range.calculated_cost_usd : '0', 'Calculation status', range.calculated_cost_status || 'unavailable'],
        ['Pricing basis', 'Recorded usage at current published standard rates; excludes unverified components. Google billed charges are separate.'],
        ['Note', 'Only retained usage records are included. Missing counters display 0; this does not establish that no usage occurred.'],
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
    const rangeTotal = Number((data.range || {}).tokens) || 0;
    const hideEmpty = !refs.aiHideEmptyDays || refs.aiHideEmptyDays.checked;
    const rows = (hideEmpty ? daily.filter((d) => (d.calls || 0) > 0) : daily).slice().reverse();

    if (!rows.length) {
        const message = daily.length && hideEmpty
            ? 'No AI usage on any day in this range.'
            : 'No AI usage in the selected range.';
        refs.aiDailyTableBody.innerHTML = `<tr><td colspan="6" class="table-empty">${escapeHtml(message)}</td></tr>`;
    } else {
        refs.aiDailyTableBody.innerHTML = rows.map((d) => {
            const share = rangeTotal > 0 ? ((Number(d.tokens) || 0) / rangeTotal) * 100 : 0;
            return `
                <tr${(d.calls || 0) ? '' : ' class="ai-daily-empty-row"'}>
                    <td>${escapeHtml(formatAiDate(d.date))}</td>
                    <td>${escapeHtml((d.calls || 0).toLocaleString())}</td>
                    <td>${escapeHtml(formatTokens(d.tokens))}</td>
                    <td>${escapeHtml(formatTokens(d.tts_characters))}</td>
                    <td>${escapeHtml(share.toFixed(1))}%</td>
                    <td>${aiCalculatedCell(d)}</td>
                </tr>`;
        }).join('');
    }

    const put = (el, v) => { if (el) el.textContent = v; };
    const totalCalls = daily.reduce((sum, d) => sum + (d.calls || 0), 0);
    const totalTokens = daily.reduce((sum, d) => sum + (d.tokens || 0), 0);
    put(refs.aiDailyTotalCalls, totalCalls.toLocaleString());
    put(refs.aiDailyTotalTokens, formatTokens(totalTokens));
    put(refs.aiDailyTotalCost, formatTokens(daily.reduce((sum, day) => sum + (Number(day.tts_characters) || 0), 0)));
    put(refs.aiDailyTotalShare, totalTokens > 0 ? '100%' : '0%');
    put(refs.aiDailyCalculatedTotal, aiRecordedCost(data.range));
}

// --- Recorded token timeline (SVG column chart) -----------------------------------
// Single series, so no legend — the card title names what is plotted. One hue
// (#6366f1, validated against the white card surface), hairline solid gridlines,
// value axis, per-column hover/keyboard tooltip, and a direct label on the peak
// only. Every value is also in the "Usage by date" table below, so the tooltip
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

// Integer token gridlines use steps of 1/2/5 × 10ⁿ.
function niceAxis(max, targetCount = 4) {
    if (!(max > 0)) return { top: 1, step: 1, ticks: [0, 1] };
    const rawStep = max / targetCount;
    const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const normalized = rawStep / magnitude;
    const step = Math.max(1, (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) * magnitude);
    const top = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = 0; v <= top + step / 2; v += step) ticks.push(Number(v.toPrecision(12)));
    return { top, step, ticks };
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
    const values = series.map((d) => Number(d.tokens) || 0);
    if (!series.length || !values.some((v) => v > 0)) {
        host.innerHTML = '<div class="table-empty">0 recorded tokens in the selected range.</div>';
        return;
    }
    if (series.length < 2) {
        // A single bucket is a number, not a chart — "Recorded tokens" above already
        // states it, and a lone column would just be that number drawn badly.
        host.innerHTML = '<div class="table-empty">One day selected — see <strong>Recorded tokens</strong> above.'
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
        text.textContent = formatTokens(tick);
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
        const label = formatTokens(values[peakIndex]);
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
        `Recorded tokens per ${state.aiGranularity || 'day'}, ${series.length} points. Values are listed in the Usage by date table below.`);

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
        value.textContent = `${formatTokens(values[index])} tokens`;
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

function aiActivitySummary(row) {
    const parts = [`${aiExactCount(row.calls)} calls`];
    const isTts = String(row.model || '').startsWith('gcp-tts/') || row.source === 'mock_interview_tts';
    if (Number(row.tokens) > 0 || (!isTts && !Number(row.tts_characters))) parts.push(`${formatTokens(row.tokens)} tokens`);
    if (Number(row.tts_characters) > 0) parts.push(`${aiExactCount(row.tts_characters)} TTS characters`);
    else if (isTts) parts.push(row.tts_characters == null ? '0 TTS characters (not recorded)' : '0 TTS characters');
    return parts.join(' · ');
}

function renderAiBreakdown(el, rows, labelFn) {
    if (!el) return;
    const list = Array.isArray(rows) ? rows.slice() : [];
    if (!list.length) { el.innerHTML = '<div class="table-empty">0 recorded calls · 0 recorded tokens</div>'; return; }
    const totalTokens = list.reduce((sum, row) => sum + (Number(row.tokens) || 0), 0);
    el.innerHTML = list.map((row, index) => {
        const tokens = Number(row.tokens) || 0;
        const percent = totalTokens > 0 ? Math.min(Math.max(tokens / totalTokens * 100, 0), 100) : 0;
        return `<div class="finance-breakdown-row">
            <div class="finance-breakdown-top"><strong>${escapeHtml(labelFn(row, index) || 'Unknown')}</strong></div>
            ${tokens > 0 ? `<div class="finance-breakdown-track"><span style="width: ${percent.toFixed(2)}%"></span></div>` : ''}
            <div class="finance-breakdown-percent">${escapeHtml(aiActivitySummary(row))}</div>
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
    if (!canProvisionEnterprise()) { showFlash('Only platform administrators can provision enterprise credentials.', 'error'); return; }
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
        const response = await adminFetch(`${API_BASE}/api/admin/enterprise/credentials`, {
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
    if (!canAccessSection('enterprise')) return;
    state.couponOrg = { id: orgId, company };
    state.couponList = [];
    state.billingNotice = null;
    state.billingTab = 'payment';
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
    if (!canAccessSection('enterprise')) return;
    if (!state.couponOrg || !refs.accountDetails) return;
    if (!await ensureAdminProtection({ silent: true })) {
        refs.accountDetails.innerHTML = '<p class="account-details-status">Verify the security check above to load account details.</p>';
        return;
    }
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/enterprise/accounts/${state.couponOrg.id}/details`, {
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {

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

    // The plan is what this org pays for now. The infra fee below is history: it is only
    // rendered when this org actually paid it at some point, so live accounts show nothing.
    const subx = data.subscription || {};
    const capWord = (v) => (v === -1 || v == null ? '∞' : Number(v).toLocaleString());
    const planBits = [`<b>${escapeHtml(subx.plan_label || '—')}</b>`];
    if (subx.monthly_display && !subx.is_sandbox) {
        planBits.push(`${escapeHtml(subx.monthly_display)}/mo${subx.tax_label ? ' + ' + escapeHtml(subx.tax_label) : ''}`);
    }
    // Pricing v2 counts OPEN files only (closed/approved/rejected don't use the limit).
    planBits.push(`${Number(subx.open_files_used ?? subx.clients_used ?? 0).toLocaleString()} / ${capWord(subx.max_open_files ?? subx.max_clients)} open files`);
    planBits.push(`${Number(subx.seats_used || 0).toLocaleString()} / ${capWord(subx.max_seats)} seats`);
    if (subx.included_credits) planBits.push(`${Number(subx.included_credits).toLocaleString()} credits${subx.credits_recur ? '/mo' : ' once'}`);
    if (subx.grandfathered) planBits.push('<em>grandfathered</em>');
    else if (subx.trial_expired) planBits.push('<em>sandbox expired</em>');

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
        <p class="account-meta-line">Plan: ${planBits.join(' · ')}</p>
        ${buildBillingFactsLine(data)}
        ${Number(totals.infra_revenue_paise || 0) > 0 ? `<p class="account-meta-line">Infrastructure fee (retired): ${escapeHtml(moneyOr(totals.infra_revenue_display, totalsCurrency))} paid historically</p>` : ''}
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
    const planPaymentsBlock = buildPlanPaymentsBlock(data);
    const billingControlsBlock = buildBillingControlsBlock(data);

    refs.accountDetails.innerHTML =
        `<h4 class="account-section-title">Wallet &amp; billing</h4>` +
        `<p class="account-meta-line" style="margin-top:-0.2rem">${metaBits.join(' · ')}</p>` +
        metrics + planPaymentsBlock + billingControlsBlock + purchasesBlock + refundFormBlock + refundsBlock + activityBlock;

    wireRefundForm(data);
    wireBillingControls(data);
    applyAdminPermissions();
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
    if (!canDeleteSection('enterprise')) return '';
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
    if (!requireAdminPermission('enterprise', 'delete')) return;
    if (!state.couponOrg) return;
    if (!await ensureAdminProtection({ silent: false })) return;
    const originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = 'Processing…';
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/enterprise/accounts/${state.couponOrg.id}/refunds`, {
            method: 'POST',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            credentials: 'same-origin',
            body: JSON.stringify(body)
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {

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

// ---------------------------------------------------------------------------
// Billing controls (Admin role): record an offline plan payment, adjust credits / grant the
// demo-call bonus, edit Branch Packs, limit overrides and the trial end.
// Server: app/routers/admin.py "Billing controls". Every amount sent is an INTEGER IN THE
// MINOR UNIT of its currency, converted in ONE place (billingMajorToMinor) — the same rule
// as the refund form.
// ---------------------------------------------------------------------------

const BILLING_OVERRIDE_FIELDS = [
    // [request field, input id, label]
    ['max_seats', 'billingOvSeats', 'Staff seats'],
    ['max_clients', 'billingOvFiles', 'Open files'],
    ['included_credits', 'billingOvCredits', 'AI credits / period'],
    ['monthly_reads', 'billingOvReads', 'AI reads / period']
];

function billingInput(id) {
    return document.getElementById(id) || {};
}

// '4,718.82' (INR) → 471882. NaN for anything that is not a plain non-negative amount with
// at most the currency's decimals — a third decimal on a rupee figure is a typo, not paise.
function billingMajorToMinor(value, currency) {
    const raw = String(value ?? '').replace(/,/g, '').trim();
    if (!raw) return NaN;
    const exponent = currencyExponent(currency);
    const pattern = exponent === 0 ? /^\d+$/ : new RegExp(`^\\d+(?:\\.\\d{1,${exponent}})?$`);
    if (!pattern.test(raw)) return NaN;
    return Math.round(Number(raw) * Math.pow(10, exponent));
}

// '' → null (back to the plan default); a whole number ≥ 0 → that number; else NaN.
function billingOptionalCount(value) {
    const raw = String(value ?? '').trim();
    if (!raw) return null;
    return /^\d+$/.test(raw) ? Number(raw) : NaN;
}

function billingDateInputValue(iso) {
    if (!iso) return '';
    const match = String(iso).match(/^(\d{4}-\d{2}-\d{2})/);
    return match ? match[1] : '';
}

function billingListPrice(controls, plan, cycle, currency) {
    return (controls.price_list || []).find((row) => row.plan === plan && row.billing_cycle === cycle
        && row.currency === currencyCode(currency)) || null;
}

function buildBillingFactsLine(data) {
    const subx = data.subscription || {};
    const controls = data.billing_controls || {};
    const bits = [];
    const reads = subx.reads || {};
    if (reads.unlimited) {
        bits.push('AI reads unlimited');
    } else if (reads.granted != null) {
        bits.push(`${Number(reads.remaining ?? 0).toLocaleString()} / ${Number(reads.granted || 0).toLocaleString()} AI reads left`);
    }
    const packs = Number(controls.branch_packs || 0);
    if (packs > 0) {
        bits.push(`${packs} Branch Pack${packs === 1 ? '' : 's'}${controls.branch_packs_applied ? '' : ' (not applied — no paid plan)'}`);
    }
    const overrides = controls.overrides || {};
    const set = BILLING_OVERRIDE_FIELDS.filter(([key]) => overrides[key] != null)
        .map(([key, , label]) => `${label.toLowerCase()} ${Number(overrides[key]).toLocaleString()}`);
    if (set.length) {
        bits.push(`overrides: ${set.join(', ')}${controls.overrides_applied === false ? ' (not applied — plan lapsed)' : ''}`);
    }
    if (controls.demo_bonus_granted_at) bits.push(`demo bonus granted ${formatDateTime(controls.demo_bonus_granted_at)}`);
    if (subx.is_sandbox && controls.trial_ends_at) bits.push(`trial ends ${formatDateTime(controls.trial_ends_at)}`);
    if (controls.trial_domain_blocked) bits.push('company domain already used a trial');
    if (!bits.length && !subx.ai_paused) return '';
    const paused = subx.ai_paused ? ` · <em>AI paused${subx.ai_paused_reason ? ` (${escapeHtml(String(subx.ai_paused_reason).replace(/_/g, ' '))})` : ''}</em>` : '';
    return `<p class="account-meta-line">${bits.map(escapeHtml).join(' · ')}${paused}</p>`;
}

function buildPlanPaymentsBlock(data) {
    const rows = Array.isArray(data.plan_payments) ? data.plan_payments : [];
    if (!rows.length) return '';
    const body = rows.map((p) => {
        let statusCls = 'created';
        if (p.status === 'verified') statusCls = 'verified';
        // "superseded" = charged on a mandate the org had already replaced: money taken for
        // nothing, to be refunded — red, like a failure, so it is not read as a normal row.
        // "foreign_card_refund_due" (D-011) = a rupee price paid with a foreign card whose
        // automatic refund failed: refund it by hand, so it is red too.
        else if (p.status === 'failed' || p.status === 'superseded' || p.status === 'foreign_card_refund_due') statusCls = 'failed';
        else if (p.status === 'refunded' || p.status === 'partially_refunded' || p.status === 'foreign_card_refused') statusCls = 'refunded';
        const statusLabel = String(p.status || '').replace(/_/g, ' ');
        const offlineTag = p.is_offline ? ' <span class="account-coupon-tag">offline</span>' : '';
        const reference = p.reference ? `<div class="enterprise-meta">${escapeHtml(p.reference)}</div>` : '';
        const recordedBy = (p.is_offline && p.created_by_name)
            ? `<div class="enterprise-meta">recorded by ${escapeHtml(p.created_by_name)}</div>` : '';
        // The admin's note on an offline payment (deal terms, who confirmed the transfer). Free
        // text typed by staff, so always escaped; it exists nowhere else in the console.
        const note = p.note ? `<div class="enterprise-meta">${escapeHtml(p.note)}</div>` : '';
        // Tax is shown only when the row actually carries some — a 0% GST payment has no line.
        const tax = p.tax_display ? `<div class="enterprise-meta">incl. ${escapeHtml(p.tax_label || 'tax')} ${escapeHtml(p.tax_display)}</div>` : '';
        const settled = (currencyCode(p.currency) !== 'INR' && p.settled_inr_display)
            ? `<div class="enterprise-meta">settled ${escapeHtml(p.settled_inr_display)}</div>` : '';
        const list = p.original_amount_display ? `<div class="enterprise-meta">list ${escapeHtml(p.original_amount_display)}</div>` : '';
        return `<tr>
            <td>${escapeHtml(formatDateTime(p.verified_at || p.created_at))}</td>
            <td>${escapeHtml(p.plan_label || p.plan || '—')}<div class="enterprise-meta">${escapeHtml(p.billing_cycle || 'monthly')}</div></td>
            <td>${escapeHtml(moneyOr(p.amount_display, p.currency))}${tax}${settled}${list}</td>
            <td>${escapeHtml(p.provider_label || p.provider || '—')}${offlineTag}${reference}${recordedBy}${note}</td>
            <td><span class="account-status-chip ${statusCls}">${escapeHtml(statusLabel)}</span></td>
        </tr>`;
    }).join('');
    return `
        <h4 class="account-section-title">Plan payments</h4>
        <div class="coupon-list-wrap">
            <table class="users-table">
                <thead><tr><th>Date</th><th>Plan</th><th>Amount</th><th>Method</th><th>Status</th></tr></thead>
                <tbody>${body}</tbody>
            </table>
        </div>`;
}

function buildBillingNotice() {
    const notice = state.billingNotice;
    if (!notice || !state.couponOrg || notice.orgId !== state.couponOrg.id) return '';
    const warnings = (notice.warnings || []).map((w) => `<li>${escapeHtml(w)}</li>`).join('');
    return `<div id="billingNotice" class="billing-notice ${notice.tone === 'success' ? 'success' : 'info'}">
        <p>${escapeHtml(notice.text)}</p>${warnings ? `<ul>${warnings}</ul>` : ''}</div>`;
}

function buildBillingControlsBlock(data) {
    if (!canDeleteSection('enterprise')) return '';
    const c = data.billing_controls;
    if (!c) return '';
    const tab = ['payment', 'credits', 'overrides'].includes(state.billingTab) ? state.billingTab : 'payment';
    const option = (value, label, selected) => `<option value="${escapeHtml(value)}"${selected ? ' selected' : ''}>${escapeHtml(label)}</option>`;

    const subPlan = (data.subscription || {}).plan;
    const defaultPlan = (c.plans || []).some((p) => p.key === subPlan) ? subPlan : ((c.plans || [])[0] || {}).key;
    const defaultCurrency = currencyCode(c.default_currency || 'INR');
    const planOptions = (c.plans || []).map((p) => option(p.key, p.label, p.key === defaultPlan)).join('');
    const providerOptions = (c.providers || []).map((p) => option(p.key, p.label, p.key === 'bank_transfer')).join('');
    const currencyOptions = (c.currencies || ['INR']).map((code) => option(code, code, code === defaultCurrency)).join('');
    const days = c.period_days || {};
    const yearlyLabel = `Yearly (${Number(days.yearly || 365)} days${c.yearly_enabled ? '' : ' — invoice sale; self-serve yearly is off'})`;

    const paymentInner = c.billing_enabled === false
        ? '<p class="account-details-status">Billing is switched off (ENTERPRISE_FREE), so there is no plan to activate.</p>'
        : `
            <div class="refund-grid">
                <label class="coupon-field"><span>Plan</span><select id="billingPayPlan">${planOptions}</select></label>
                <label class="coupon-field"><span>Billing cycle</span><select id="billingPayCycle">
                    ${option('monthly', `Monthly (${Number(days.monthly || 30)} days)`, true)}${option('yearly', yearlyLabel, false)}</select></label>
                <label class="coupon-field"><span>Method</span><select id="billingPayProvider">${providerOptions}</select></label>
                <label class="coupon-field"><span>Currency</span><select id="billingPayCurrency">${currencyOptions}</select></label>
                <label class="coupon-field"><span id="billingPayAmountLabel">Amount received, incl. tax (${escapeHtml(currencyInputLabel(defaultCurrency))})</span>
                    <input type="text" inputmode="decimal" id="billingPayAmount" placeholder="0.00" autocomplete="off"></label>
                <label class="coupon-field"><span id="billingPayTaxLabel">Tax inside that amount (optional)</span>
                    <input type="text" inputmode="decimal" id="billingPayTax" placeholder="auto" autocomplete="off"></label>
                <label class="coupon-field" id="billingPaySettledField"${defaultCurrency === 'INR' ? ' hidden' : ''}><span>INR that settled (₹)</span>
                    <input type="text" inputmode="decimal" id="billingPaySettled" placeholder="from the bank credit advice" autocomplete="off"></label>
                <label class="coupon-field"><span>Reference (UTR / pay_… id / invoice no.)</span>
                    <input type="text" id="billingPayReference" maxlength="80" autocomplete="off"></label>
                <label class="coupon-field coupon-field-wide"><span>Note (optional)</span>
                    <input type="text" id="billingPayNote" maxlength="500" placeholder="e.g. NEFT after the demo call"></label>
                ${c.term_locked_until ? `<label class="coupon-field coupon-field-wide"><span><input type="checkbox" id="billingPayTierNow">
                    Change tier now: the prepaid ${escapeHtml(c.term_locked_plan_label || c.term_locked_plan || '')} term (to ${escapeHtml(formatDateTime(c.term_locked_until))}) is replaced from today. Prorate the invoice first — without this, a different plan is refused while the term runs.</span></label>` : ''}
            </div>
            <p id="billingPayHint" class="account-meta-line" style="margin:-0.3rem 0 0.6rem"></p>
            <button type="button" id="billingPayBtn" class="primary-btn small-btn">Record payment</button>
            <p class="account-meta-line" style="margin:0.4rem 0 0">Activates the plan, extends it from the current end date (or today, if it has lapsed) and grants this period's credits. Recording the same reference again changes nothing.</p>`;

    const bonus = Number(c.demo_bonus_credits || 0);
    let demoInner;
    if (c.demo_bonus_granted_at) {
        demoInner = `<p id="billingDemoStatus" class="account-meta-line" style="margin:0">Demo-call bonus granted ${escapeHtml(formatDateTime(c.demo_bonus_granted_at))} — it can be given once per account.</p>`;
    } else if (bonus > 0) {
        demoInner = `<button type="button" id="billingDemoBtn" class="primary-btn small-btn">Grant demo-call bonus (+${bonus.toLocaleString()} credits)</button>`;
    } else {
        demoInner = '<p id="billingDemoStatus" class="account-meta-line" style="margin:0">The demo-call bonus is switched off.</p>';
    }
    const caps = c.caps || {};
    const creditsInner = `
            <div class="refund-grid">
                <label class="coupon-field"><span>Credits (negative to deduct)</span>
                    <input type="number" id="billingAdjustCredits" step="1" placeholder="e.g. 50 or -20"></label>
                <label class="coupon-field coupon-field-wide"><span>Reason (shown in the customer's credit history)</span>
                    <input type="text" id="billingAdjustReason" maxlength="200" placeholder="e.g. Goodwill — Deep Scan failed twice"></label>
            </div>
            <button type="button" id="billingAdjustBtn" class="primary-btn small-btn">Apply adjustment</button>
            <p class="account-meta-line" style="margin:0.4rem 0 0.9rem">No money moves. A deduction stops at the current balance${caps.credit_adjust_max ? `; at most ${Number(caps.credit_adjust_max).toLocaleString()} credits per adjustment` : ''}.</p>
            ${demoInner}`;

    const defaults = c.plan_defaults || {};
    const overrides = c.overrides || {};
    const pack = c.branch_pack || {};
    const overrideInputs = BILLING_OVERRIDE_FIELDS.map(([key, id, label]) => `
                <label class="coupon-field"><span>${escapeHtml(label)}</span>
                    <input type="number" id="${id}" min="0" step="1" value="${overrides[key] != null ? escapeHtml(String(overrides[key])) : ''}"
                        placeholder="${defaults[key] != null ? `Plan default: ${escapeHtml(Number(defaults[key]).toLocaleString())}` : 'Plan default'}"></label>`).join('');
    const overridesInner = `
            <div class="refund-grid">
                <label class="coupon-field"><span>Branch Packs</span>
                    <input type="number" id="billingOvPacks" min="0" step="1" value="${escapeHtml(String(Number(c.branch_packs || 0)))}"></label>
                <label class="coupon-field"><span>Trial ends (UTC, end of day)</span>
                    <input type="date" id="billingOvTrial" value="${escapeHtml(billingDateInputValue(c.trial_ends_at))}"></label>
                ${overrideInputs}
            </div>
            <button type="button" id="billingOvBtn" class="primary-btn small-btn">Save limits</button>
            <p class="account-meta-line" style="margin:0.4rem 0 0">Each Branch Pack adds +${Number(pack.open_files || 0).toLocaleString()} open files, +${Number(pack.seats || 0).toLocaleString()} seats, +${Number(pack.credits || 0).toLocaleString()} credits and +${Number(pack.reads || 0).toLocaleString()} reads a month on a paid plan. Leave a limit empty for the plan default; an override replaces it and packs add on top. A raised allowance is granted now; a lower one applies from the next period.</p>`;

    const tabButton = (mode, label) => `<button type="button" class="billing-tab${tab === mode ? ' active' : ''}" data-billing-mode="${mode}">${label}</button>`;
    const pane = (mode, inner) => `<div class="billing-mode${tab === mode ? '' : ' hidden'}" data-mode="${mode}">${inner}</div>`;
    return `
        <h4 class="account-section-title">Billing controls</h4>
        ${buildBillingNotice()}
        <div class="billing-tabs">
            ${tabButton('payment', 'Record offline payment')}${tabButton('credits', 'Credits')}${tabButton('overrides', 'Limits &amp; trial')}
        </div>
        ${pane('payment', paymentInner)}${pane('credits', creditsInner)}${pane('overrides', overridesInner)}
        <p id="billingFormError" class="coupon-form-error" hidden></p>`;
}

function setBillingError(message) {
    const el = document.getElementById('billingFormError');
    if (!el) return;
    if (!message) { el.hidden = true; el.textContent = ''; return; }
    el.textContent = message;
    el.hidden = false;
}

function syncOfflinePaymentForm(controls) {
    const currency = currencyCode(billingInput('billingPayCurrency').value || 'INR');
    const label = document.getElementById('billingPayAmountLabel');
    if (label) label.textContent = `Amount received, incl. tax (${currencyInputLabel(currency)})`;
    const settledField = document.getElementById('billingPaySettledField');
    if (settledField) settledField.hidden = currency === 'INR';
    const hint = document.getElementById('billingPayHint');
    if (!hint) return;
    const price = billingListPrice(controls, billingInput('billingPayPlan').value, billingInput('billingPayCycle').value, currency);
    hint.textContent = price ? `List price: ${price.total_display}${price.tax_minor ? ' including tax' : ''}.` : '';
}

// Reads the offline-payment form into the request body, or { error } without sending.
function readOfflinePaymentForm(controls) {
    const plan = String(billingInput('billingPayPlan').value || '');
    const cycle = billingInput('billingPayCycle').value === 'yearly' ? 'yearly' : 'monthly';
    const provider = String(billingInput('billingPayProvider').value || '');
    const currency = currencyCode(billingInput('billingPayCurrency').value || 'INR');
    const reference = String(billingInput('billingPayReference').value || '').trim();
    const note = String(billingInput('billingPayNote').value || '').trim();
    if (!plan) return { error: 'Choose the plan that was paid for.' };
    const amountMinor = billingMajorToMinor(billingInput('billingPayAmount').value, currency);
    if (!Number.isFinite(amountMinor) || amountMinor <= 0) {
        return { error: `Enter the amount received in ${currency}, e.g. 4718.82.` };
    }
    const caps = controls.caps || {};
    if (caps.offline_payment_max_minor && amountMinor > Number(caps.offline_payment_max_minor)) {
        return { error: `That is more than ${formatMinor(caps.offline_payment_max_minor, currency)} — check the amount.` };
    }
    const body = { plan, billing_cycle: cycle, provider, currency, amount_minor: amountMinor, reference };
    const taxRaw = String(billingInput('billingPayTax').value || '').trim();
    if (taxRaw) {
        const taxMinor = billingMajorToMinor(taxRaw, currency);
        if (!Number.isFinite(taxMinor) || taxMinor >= amountMinor) {
            return { error: 'Tax must be a plain amount smaller than the amount received (or empty for automatic).' };
        }
        body.tax_minor = taxMinor;
    }
    if (currency !== 'INR') {
        const settled = billingMajorToMinor(billingInput('billingPaySettled').value, 'INR');
        if (!Number.isFinite(settled) || settled <= 0) {
            return { error: `Enter the INR amount that settled for this ${currency} payment.` };
        }
        body.settled_inr_minor = settled;
    }
    if (!/^[A-Za-z0-9][A-Za-z0-9._/#:-]{2,79}$/.test(reference)) {
        return { error: 'Enter the payment reference (UTR, pay_… id or invoice number) — 3 to 80 characters, no spaces.' };
    }
    if (note) body.note = note;
    // Only offered while a prepaid yearly term runs (the server 409s a different plan then).
    if (billingInput('billingPayTierNow').checked) body.change_tier_now = true;
    return { body };
}

// Reads the limits form and returns only what CHANGED, so saving never resets a value
// another admin set while this modal was open. { error } on bad input.
function readOverridesForm(controls) {
    const body = {};
    const lines = [];
    const overrides = controls.overrides || {};
    const defaults = controls.plan_defaults || {};
    const packs = billingOptionalCount(billingInput('billingOvPacks').value);
    if (Number.isNaN(packs)) return { error: 'Branch Packs must be a whole number (0 for none).' };
    const packsValue = packs == null ? 0 : packs;
    if (packsValue !== Number(controls.branch_packs || 0)) {
        body.branch_packs = packsValue;
        lines.push(`Branch Packs: ${Number(controls.branch_packs || 0)} → ${packsValue}`);
    }
    for (const [key, id, label] of BILLING_OVERRIDE_FIELDS) {
        const value = billingOptionalCount(billingInput(id).value);
        if (Number.isNaN(value)) return { error: `${label} must be a whole number, or empty for the plan default.` };
        const current = overrides[key] != null ? Number(overrides[key]) : null;
        if (value !== current) {
            body[key] = value;
            const shown = (v) => (v == null ? `plan default${defaults[key] != null ? ` (${Number(defaults[key]).toLocaleString()})` : ''}` : Number(v).toLocaleString());
            lines.push(`${label}: ${shown(current)} → ${shown(value)}`);
        }
    }
    const trial = String(billingInput('billingOvTrial').value || '').trim();
    const currentTrial = billingDateInputValue(controls.trial_ends_at);
    if (trial && trial !== currentTrial) {
        body.trial_ends_at = trial;
        lines.push(`Trial ends: ${currentTrial || 'not set'} → ${trial} (end of day, UTC)`);
    }
    if (!lines.length) return { error: 'Nothing changed.' };
    return { body, lines };
}

async function submitBillingControl(button, path, method, body, fallbackMessage) {
    if (!requireAdminPermission('enterprise', 'delete')) return null;
    if (!state.couponOrg) return null;
    if (!await ensureAdminProtection({ silent: false })) return null;
    const orgId = state.couponOrg.id;
    const originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = 'Saving…';
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/enterprise/accounts/${orgId}/${path}`, {
            method,
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            credentials: 'same-origin',
            body: JSON.stringify(body)
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            setBillingError(normalizeErrorMessage(payload, fallbackMessage));
            return null;
        }
        // A replay (duplicate payment / bonus already given) or any server warning is
        // information the admin must read, so it is not styled as a plain success.
        const warnings = Array.isArray(payload.warnings) ? payload.warnings.filter(Boolean) : [];
        const neutral = payload.duplicate || payload.already_granted || payload.changed === false || warnings.length;
        state.billingNotice = { orgId, tone: neutral ? 'info' : 'success', text: payload.message || 'Saved.', warnings };
        await loadAccountDetails();
        await loadEnterpriseAccounts({ silent: true }).catch(() => {});
        return payload;
    } catch (error) {
        console.error('Billing control failed:', error);
        setBillingError('Could not reach the server. Please retry.');
        return null;
    } finally {
        button.disabled = false;
        button.textContent = originalLabel;
    }
}

function wireBillingControls(data) {
    const controls = data.billing_controls;
    if (!controls || !canDeleteSection('enterprise')) return;
    const company = () => (state.couponOrg && state.couponOrg.company) || 'this account';

    document.querySelectorAll('.billing-tab').forEach((tab) => {
        tab.addEventListener('click', () => {
            const mode = tab.dataset.billingMode;
            state.billingTab = mode;
            document.querySelectorAll('.billing-tab').forEach((t) => t.classList.toggle('active', t === tab));
            document.querySelectorAll('.billing-mode').forEach((m) => m.classList.toggle('hidden', m.dataset.mode !== mode));
            setBillingError('');
        });
    });

    // --- offline payment ---
    ['billingPayPlan', 'billingPayCycle', 'billingPayCurrency'].forEach((id) => {
        document.getElementById(id)?.addEventListener('change', () => syncOfflinePaymentForm(controls));
    });
    if (document.getElementById('billingPayPlan')) syncOfflinePaymentForm(controls);
    const payBtn = document.getElementById('billingPayBtn');
    if (payBtn) payBtn.addEventListener('click', async () => {
        setBillingError('');
        const { body, error } = readOfflinePaymentForm(controls);
        if (error) { setBillingError(error); return; }
        const planLabel = ((controls.plans || []).find((p) => p.key === body.plan) || {}).label || body.plan;
        const providerLabel = ((controls.providers || []).find((p) => p.key === body.provider) || {}).label || body.provider;
        const days = (controls.period_days || {})[body.billing_cycle] || (body.billing_cycle === 'yearly' ? 365 : 30);
        const amountText = formatMinor(body.amount_minor, body.currency);
        const message = `Record ${amountText} (${body.currency}) received by ${providerLabel}, reference ${body.reference}, for ${company()}?\n`
            + `This activates ${planLabel} (${body.billing_cycle}) and extends it by ${days} days. It can't be undone from the console.`;
        if (!(await confirmDialog(message, { title: 'Record offline payment?', okText: `Record ${amountText}`, danger: false }))) return;
        await submitBillingControl(payBtn, 'offline-payment', 'POST', body, 'Could not record the payment.');
    });

    // --- credits ---
    const adjustBtn = document.getElementById('billingAdjustBtn');
    if (adjustBtn) adjustBtn.addEventListener('click', async () => {
        setBillingError('');
        const raw = String(billingInput('billingAdjustCredits').value ?? '').trim();
        const credits = /^-?\d+$/.test(raw) ? Number(raw) : NaN;
        const reason = String(billingInput('billingAdjustReason').value || '').trim();
        if (!Number.isFinite(credits) || credits === 0) { setBillingError('Enter a whole number of credits (negative to deduct).'); return; }
        const cap = Number((controls.caps || {}).credit_adjust_max || 0);
        if (cap && Math.abs(credits) > cap) { setBillingError(`At most ${cap.toLocaleString()} credits per adjustment.`); return; }
        if (reason.length < 3) { setBillingError('Give a reason — the customer sees it in their credit history.'); return; }
        const verb = credits > 0 ? `Add ${credits.toLocaleString()} credits to` : `Deduct ${Math.abs(credits).toLocaleString()} credits from`;
        const tail = credits > 0 ? '' : ' A deduction stops at the current balance.';
        if (!(await confirmDialog(`${verb} ${company()}?\nReason: ${reason}.${tail}`, { title: 'Adjust credits?', okText: credits > 0 ? 'Add credits' : 'Deduct credits', danger: credits < 0 }))) return;
        await submitBillingControl(adjustBtn, 'credits/adjust', 'POST', { kind: 'adjustment', credits, reason }, 'Could not adjust credits.');
    });
    const demoBtn = document.getElementById('billingDemoBtn');
    if (demoBtn) demoBtn.addEventListener('click', async () => {
        setBillingError('');
        const bonus = Number(controls.demo_bonus_credits || 0);
        if (!(await confirmDialog(`Grant the one-time ${bonus.toLocaleString()}-credit demo-call bonus to ${company()}? It can only be given once per account.`, { title: 'Grant demo-call bonus?', okText: 'Grant bonus', danger: false }))) return;
        const reason = String(billingInput('billingAdjustReason').value || '').trim();
        await submitBillingControl(demoBtn, 'credits/adjust', 'POST', { kind: 'demo_call_bonus', reason }, 'Could not grant the bonus.');
    });

    // --- limits & trial ---
    const ovBtn = document.getElementById('billingOvBtn');
    if (ovBtn) ovBtn.addEventListener('click', async () => {
        setBillingError('');
        const { body, lines, error } = readOverridesForm(controls);
        if (error) { setBillingError(error); return; }
        if (!(await confirmDialog(`Change limits for ${company()}?\n${lines.join('\n')}`, { title: 'Save limits?', okText: 'Save limits', danger: false }))) return;
        await submitBillingControl(ovBtn, 'overrides', 'PUT', body, 'Could not save the limits.');
    });
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
                <td>${c.above_cap && c.effective_percent_display
                    // A legacy code saved above ENTERPRISE_COUPON_MAX_PERCENT: checkout (and the
                    // promo email) give the cap, so lead with what the code really takes off.
                    ? `${escapeHtml(c.effective_percent_display)}<div class="enterprise-meta">saved as ${escapeHtml(c.percent_display || (c.percent_off + '%'))} · above cap</div>`
                    : escapeHtml(c.percent_display || (c.percent_off + '%'))}</td>
                <td>${escapeHtml(appliesLabel)}</td>
                <td>${escapeHtml(String(used))} / ${cap}</td>
                <td>${statusChip}</td>
                <td>
                    <button type="button" class="table-btn" data-admin-write="enterprise" data-coupon-action="email"
                        data-coupon-id="${escapeHtml(String(c.id))}" data-coupon-code="${escapeHtml(c.code)}">Email</button>
                    <button type="button" class="table-btn" data-admin-write="enterprise" data-coupon-action="toggle"
                        data-coupon-id="${escapeHtml(String(c.id))}" data-next-active="${c.is_active ? 'false' : 'true'}">${toggleLabel}</button>
                    <button type="button" class="table-btn danger" data-admin-delete="enterprise" data-coupon-action="delete"
                        data-coupon-id="${escapeHtml(String(c.id))}" data-coupon-code="${escapeHtml(c.code)}">Delete</button>
                </td>
            </tr>
        `;
    }).join('');
    applyAdminPermissions();
}

async function loadCoupons() {
    if (!canAccessSection('enterprise')) return;
    if (!state.couponOrg) return;
    if (!await ensureAdminProtection({ silent: false })) return;
    state.couponLoading = true;
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/enterprise/accounts/${state.couponOrg.id}/coupons`, {
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {

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
    if (!requireAdminPermission('enterprise', 'write')) return;
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
        const response = await adminFetch(`${API_BASE}/api/admin/enterprise/accounts/${state.couponOrg.id}/coupons`, {
            method: 'POST',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            credentials: 'same-origin',
            body: JSON.stringify(body)
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {

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
    if (!requireAdminPermission('enterprise', 'write')) return;
    if (!state.couponOrg) return;
    const company = state.couponOrg.company || 'this account';
    if (!(await confirmDialog(`The "${code}" discount will be emailed to ${company}'s team.`, { title: 'Send discount email?', okText: 'Send email', danger: false }))) return;
    if (!await ensureAdminProtection({ silent: false })) return;
    const original = button ? button.textContent : '';
    if (button) { button.disabled = true; button.textContent = 'Sending...'; }
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/enterprise/accounts/${state.couponOrg.id}/coupons/${couponId}/send-email`, {
            method: 'POST',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            credentials: 'same-origin',
            body: JSON.stringify({})
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {

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
    if (!requireAdminPermission('enterprise', 'write')) return;
    if (!state.couponOrg) return;
    if (!await ensureAdminProtection({ silent: false })) return;
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/enterprise/accounts/${state.couponOrg.id}/coupons/${couponId}`, {
            method: 'PATCH',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            credentials: 'same-origin',
            body: JSON.stringify(patch)
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {

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
    if (!requireAdminPermission('enterprise', 'delete')) return;
    if (!state.couponOrg) return;
    if (!await ensureAdminProtection({ silent: false })) return;
    try {
        const response = await adminFetch(`${API_BASE}/api/admin/enterprise/accounts/${state.couponOrg.id}/coupons/${couponId}`, {
            method: 'DELETE',
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {

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
    if (!requireAdminPermission('users', 'write')) return;
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
        const response = await adminFetch(`${API_BASE}/api/admin/users/${userId}/status`, {
            method: 'PATCH',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ is_active: Boolean(nextIsActive) }),
            credentials: 'same-origin'
        });

        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {

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
    if (!requireAdminPermission('users', 'delete')) return;
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
        const response = await adminFetch(`${API_BASE}/api/admin/users/${userId}`, {
            method: 'DELETE',
            headers: buildAuthHeaders(),
            credentials: 'same-origin'
        });

        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {

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
