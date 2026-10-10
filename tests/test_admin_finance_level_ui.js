// Admin console "⚖ Level 50/50" (Founder Spend card) — vm harness in the style of
// test_admin_team_ui.js / test_admin_users_export_ui.js. No DOM: static/admin_console.js is
// loaded into a vm context with stubbed document/fetch, and the helpers under test are
// exposed through a trailing `;globalThis.ui = {...}`.

// The Level entry is dated the click day in the clicker's own timezone. Pin a US evening
// where the local date (Oct 8) and the UTC date (Oct 9) differ, so a toISOString()-based
// date would be caught. node --test runs each file in its own process, so this is local.
process.env.TZ = 'America/Los_Angeles';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/admin_console.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../static/admin_console.html'), 'utf8');
const sections = ['users', 'enterprise', 'analytics', 'finance', 'ai', 'team'];

const RealDate = Date;
const FIXED_NOW = RealDate.parse('2026-10-09T03:30:00Z'); // 8:30pm Oct 8 in Los Angeles
class FixedDate extends RealDate {
    constructor(...args) { super(...(args.length ? args : [FIXED_NOW])); }
    static now() { return FIXED_NOW; }
}
const LOCAL_CLICK_DAY = '2026-10-08';
const UTC_CLICK_DAY = '2026-10-09';

const LEVEL_URL = '/api/admin/company-finance/level';
const ANALYTICS_URL = '/api/admin/company-finance/analytics';

// Shapes mirror _founder_balance() in app/routers/admin.py for the real numbers:
// Gaurav $871.33, Kushal $334.24 → Kushal pays half the gap, $268.55 (half-up).
const PENDING = {
    founders: [
        { label: 'Gaurav', amount_usd: 871.33, after_usd: 602.78 },
        { label: 'Kushal', amount_usd: 334.24, after_usd: 602.79 }
    ],
    total_usd: 1205.57, is_level: false, payer: 'Kushal', payee: 'Gaurav', transfer_usd: 268.55
};
const LEVEL = {
    founders: [
        { label: 'Gaurav', amount_usd: 602.78, after_usd: 602.78 },
        { label: 'Kushal', amount_usd: 602.79, after_usd: 602.79 }
    ],
    total_usd: 1205.57, is_level: true, payer: null, payee: null, transfer_usd: 0
};
const NO_SPEND = {
    founders: [
        { label: 'Gaurav', amount_usd: 0, after_usd: 0 },
        { label: 'Kushal', amount_usd: 0, after_usd: 0 }
    ],
    total_usd: 0, is_level: true, payer: null, payee: null, transfer_usd: 0
};

const SETTLEMENT_ROW = {
    id: 'finance-42', kind: 'Settlement', category: 'Founder Settlement', vendor: 'Gaurav',
    paid_by: 'Kushal', paid_to: 'Gaurav', amount_usd: 268.55, occurred_on: LOCAL_CLICK_DAY,
    description: 'Kushal paid Gaurav $268.55 to level founder spend 50/50', source: 'level'
};
const INVESTMENT_ROW = {
    id: 'finance-7', kind: 'Investment', category: 'Hosting', vendor: 'Render', paid_by: 'Gaurav',
    amount_usd: -25, occurred_on: '2026-09-01', description: 'Web service', source: 'manual'
};
const PAYMENT_ROW = {
    id: 'payment-3', kind: 'Return', category: 'Subscription', vendor: 'Visa Success Pass', paid_by: 'Customer',
    amount_usd: 12, occurred_on: '2026-09-02', description: 'Pass purchase', source: 'razorpay'
};

const jsonResponse = (payload, status = 200) => ({ ok: status < 400, status, headers: { get() {} }, json: async () => payload });
const plain = (value) => JSON.parse(JSON.stringify(value));
const settle = () => new Promise((resolve) => setImmediate(resolve));

function analytics(balance, ledger = [INVESTMENT_ROW]) {
    const payload = {
        summary: { total_invested_usd: 1205.57, total_returns_usd: 0, net_usd: -1205.57, roi_percent: -100 },
        monthly_series: [], expense_breakdown: [], contributor_breakdown: [], ledger
    };
    if (balance !== undefined) payload.founder_balance = balance;
    return payload;
}

function access(role = 'admin', assigned = sections) {
    return {
        user: { id: 17, email: 'founder@example.test', full_name: 'Console Founder', is_admin: false, is_developer: false },
        role, sections: assigned, can_manage_team: role === 'admin' && assigned.includes('team'), can_provision_enterprise: false,
        can_write_sections: role === 'viewer' ? [] : assigned,
        can_delete_sections: role === 'admin' ? assigned : []
    };
}

function element(id = '') {
    let markup = '';
    let text = '';
    const listeners = {};
    const queried = new Map();
    return {
        id, value: '', hidden: false, disabled: false, className: '', title: '', tabIndex: 0,
        dataset: {}, attributes: {}, style: {}, listeners, removed: false,
        classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
        setAttribute(name, value) { this.attributes[name] = String(value); },
        getAttribute(name) { return this.attributes[name]; },
        hasAttribute(name) { return name in this.attributes; },
        addEventListener(type, handler) { (listeners[type] ||= []).push(handler); },
        removeEventListener() {},
        reset() {}, focus() {}, scrollIntoView() {},
        remove() { this.removed = true; },
        // confirmDialog() looks up its buttons with overlay.querySelector('#adminCfmOk').
        querySelector(selector) {
            if (!queried.has(selector)) queried.set(selector, element(selector.replace(/^#/, '')));
            return queried.get(selector);
        },
        querySelectorAll() { return []; },
        get textContent() { return text; },
        set textContent(value) { text = String(value); markup = ''; },
        // escapeHtml() round-trips through a div's textContent → innerHTML.
        get innerHTML() { return markup || text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); },
        set innerHTML(value) { markup = String(value); text = ''; }
    };
}

function setup({ fetchImpl, grant = access(), realConfirm = false, confirmAnswer = true } = {}) {
    const elements = new Map();
    const permissionElements = [];
    const appended = [];
    const requests = [];
    const confirms = [];
    const get = (id) => {
        const open = appended.find((node) => node.id === id && !node.removed);
        if (open) return open;
        if (/Overlay$/.test(id)) return null; // no dialog is open
        if (!elements.has(id)) elements.set(id, element(id));
        return elements.get(id);
    };
    sections.forEach((key) => { get(`admin${key[0].toUpperCase() + key.slice(1)}TabBtn`).dataset.tab = key; });
    // Mirror the shipped markup: the button starts disabled and is guarded as a finance write,
    // and the status line starts hidden.
    const levelBtn = get('adminFinanceLevelBtn');
    levelBtn.disabled = true;
    levelBtn.textContent = '⚖ Level 50/50';
    levelBtn.dataset.adminWrite = 'finance';
    levelBtn.setAttribute('data-admin-write', 'finance');
    permissionElements.push(levelBtn);
    const levelStatus = get('adminFinanceLevelStatus');
    levelStatus.hidden = true;
    levelStatus.className = 'finance-level-status';
    get('adminFlash').hidden = true;

    const context = vm.createContext({
        document: {
            getElementById: get,
            createElement: () => element(),
            addEventListener() {}, removeEventListener() {},
            querySelectorAll(selector) { return selector.startsWith('[data-admin-write]') ? permissionElements : []; },
            querySelector() { return null; },
            body: Object.assign(element('body'), { appendChild(node) { appended.push(node); } })
        },
        window: { matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {} }),
            addEventListener() {}, removeEventListener() {}, scrollTo() {} },
        Date: FixedDate,
        URLSearchParams, Blob, URL, setTimeout, clearTimeout,
        console: { error() {}, warn() {}, log() {} },
        fetch: async (url, options = {}) => {
            requests.push({ url, method: String(options.method || 'GET').toUpperCase(), options });
            return fetchImpl ? fetchImpl(url, options) : jsonResponse({});
        }
    });
    vm.runInContext(`${source}
;globalThis.ui = { state, refs, applyAdminAccess, bindEvents, localIsoDate, renderFinanceFounderBalance, levelFounderSpend,
    renderFinanceLedger, renderFinanceAnalytics, renderFinanceEmptyState, loadFinanceAnalytics, deleteFinanceEntry };`, context);
    if (!realConfirm) {
        context.__confirm = async (message, opts) => {
            confirms.push({ message, opts: plain(opts || {}) });
            return typeof confirmAnswer === 'function' ? confirmAnswer(message, opts) : confirmAnswer;
        };
        vm.runInContext('confirmDialog = (message, opts) => globalThis.__confirm(message, opts);', context);
    }
    const app = context.ui;
    app.state.authToken = 'test-cookie-token';
    if (grant) app.applyAdminAccess(grant);
    return { ...app, context, get, elements, appended, requests, confirms, permissionElements,
        levelBtn: app.refs.financeLevelBtn, levelStatus: app.refs.financeLevelStatus, flash: app.refs.flash };
}

// POST /level answers with `levelResponse`; every analytics reload returns `reloaded`.
function levelServer({ levelResponse = () => jsonResponse({ entry: { id: 42 }, founder_balance: LEVEL }), reloaded = analytics(LEVEL, [SETTLEMENT_ROW, INVESTMENT_ROW]) } = {}) {
    return (url, options = {}) => {
        if (url === LEVEL_URL && options.method === 'POST') return levelResponse(url, options);
        if (url === ANALYTICS_URL) return jsonResponse(typeof reloaded === 'function' ? reloaded() : reloaded);
        if (url === '/api/admin/access') return jsonResponse(access());
        return jsonResponse({});
    };
}

function showPending(app, balance = PENDING) {
    app.state.financeAnalytics = analytics(balance);
    app.renderFinanceAnalytics();
}

function ledgerRows(markup) {
    return markup.split(/<tr>/).slice(1);
}

// ---------------------------------------------------------------------------------------
// Markup + wiring
// ---------------------------------------------------------------------------------------

test('Founder Spend card ships a disabled finance-write Level button and a hidden live status line', () => {
    const button = /<button[^>]+id="adminFinanceLevelBtn"[^>]*>([^<]*)<\/button>/.exec(html);
    assert.ok(button, 'Level button is in admin_console.html');
    assert.match(button[0], /data-admin-write="finance"/);
    assert.match(button[0], /\sdisabled(?:\s|>)/);
    assert.equal(button[1], '⚖ Level 50/50');
    const status = /<p[^>]+id="adminFinanceLevelStatus"[^>]*>/.exec(html);
    assert.ok(status, 'status line is in admin_console.html');
    assert.match(status[0], /aria-live="polite"/);
    assert.match(status[0], /\shidden(?:\s|>)/);
});

test('bindEvents wires the Level button click to levelFounderSpend', () => {
    const app = setup();
    app.bindEvents();
    assert.ok(app.levelBtn.listeners.click, 'click listener registered');
    assert.ok(app.levelBtn.listeners.click.includes(app.levelFounderSpend));
});

// ---------------------------------------------------------------------------------------
// renderFinanceFounderBalance
// ---------------------------------------------------------------------------------------

test('pending balance shows "<payer> owes <payee> $X" and enables the Level button', () => {
    const app = setup();
    app.renderFinanceFounderBalance(PENDING);
    assert.equal(app.levelStatus.hidden, false);
    assert.equal(app.levelStatus.className, 'finance-level-status is-owed');
    assert.equal(app.levelStatus.textContent, 'Kushal owes Gaurav $268.55 to make founder spend 50/50.');
    assert.equal(app.levelBtn.disabled, false);
    assert.equal(app.levelBtn.textContent, '⚖ Level 50/50');
    assert.equal(app.levelBtn.title, 'Record that Kushal paid Gaurav $268.55 so founder spend is 50/50');
});

test('level balance shows the ✓ split and disables the Level button', () => {
    const app = setup();
    app.renderFinanceFounderBalance(PENDING);
    app.renderFinanceFounderBalance(LEVEL);
    assert.equal(app.levelStatus.hidden, false);
    assert.equal(app.levelStatus.className, 'finance-level-status is-level');
    assert.equal(app.levelStatus.textContent, '✓ Founder spend is level (50/50): Gaurav $602.78 · Kushal $602.79.');
    assert.equal(app.levelBtn.disabled, true);
    assert.equal(app.levelBtn.title, 'Founder spend is already 50/50');
});

for (const [name, balance] of [['null', null], ['undefined', undefined], ['an empty object', {}], ['an all-zero balance', NO_SPEND]]) {
    test(`${name} founder balance hides the status line and disables the button`, () => {
        const app = setup();
        app.renderFinanceFounderBalance(PENDING); // start from a visible, enabled card
        app.renderFinanceFounderBalance(balance);
        assert.equal(app.levelStatus.hidden, true);
        assert.equal(app.levelStatus.textContent, '');
        assert.equal(app.levelStatus.className, 'finance-level-status');
        assert.equal(app.levelBtn.disabled, true);
        assert.equal(app.levelBtn.title, 'No founder spend to level yet');
    });
}

test('a balance that claims to be pending without payer/payee or a positive transfer never enables the button', () => {
    const app = setup();
    for (const broken of [
        { ...PENDING, payer: null },
        { ...PENDING, payee: '' },
        { ...PENDING, transfer_usd: 0 },
        { ...PENDING, transfer_usd: -5 },
        { ...PENDING, transfer_usd: 'abc' }
    ]) {
        app.renderFinanceFounderBalance(PENDING);
        app.renderFinanceFounderBalance(broken);
        assert.equal(app.levelBtn.disabled, true, JSON.stringify(broken));
        assert.equal(app.levelStatus.className, 'finance-level-status is-level');
    }
});

test('renderFinanceAnalytics drives the card from payload.founder_balance; the loading state resets it', () => {
    const app = setup();
    showPending(app);
    assert.equal(app.levelBtn.disabled, false);
    assert.match(app.levelStatus.textContent, /^Kushal owes Gaurav \$268\.55/);

    app.renderFinanceEmptyState('Loading finance analytics...');
    assert.equal(app.levelBtn.disabled, true);
    assert.equal(app.levelStatus.hidden, true);
    assert.equal(app.levelStatus.textContent, '');

    // An analytics payload from a server without founder_balance leaves the card inert.
    app.state.financeAnalytics = analytics(undefined);
    app.renderFinanceAnalytics();
    assert.equal(app.levelBtn.disabled, true);
    assert.equal(app.levelStatus.hidden, true);
});

test('localIsoDate is the clicker\'s local calendar day, not the UTC day', () => {
    const app = setup();
    assert.equal(app.localIsoDate(), LOCAL_CLICK_DAY);
    assert.equal(new FixedDate().toISOString().slice(0, 10), UTC_CLICK_DAY); // the trap this avoids
    assert.equal(app.localIsoDate(new FixedDate(2026, 0, 5, 9, 0)), '2026-01-05'); // zero-padded
});

// ---------------------------------------------------------------------------------------
// levelFounderSpend
// ---------------------------------------------------------------------------------------

test('Level posts expected payer/transfer and the local click day only after the confirmation resolves true', async () => {
    let resolveConfirm;
    const app = setup({ fetchImpl: levelServer(), confirmAnswer: () => new Promise((resolve) => { resolveConfirm = resolve; }) });
    showPending(app);

    const leveling = app.levelFounderSpend();
    await settle();
    assert.equal(app.confirms.length, 1);
    assert.equal(app.requests.length, 0, 'nothing is sent while the confirmation is open');

    const { message, opts } = app.confirms[0];
    assert.deepEqual(opts, { title: 'Level founder spend 50/50?', okText: 'Level 50/50', danger: false });
    assert.match(message, new RegExp(`dated ${LOCAL_CLICK_DAY}: Kushal paid Gaurav \\$268\\.55\\.`));
    assert.match(message, /Founder spend after leveling: Gaurav \$602\.78 · Kushal \$602\.79\./);
    assert.match(message, /Total invested stays \$1,205\.57/);

    resolveConfirm(true);
    await leveling;

    const post = app.requests[0];
    assert.equal(post.url, LEVEL_URL);
    assert.equal(post.method, 'POST');
    assert.equal(post.options.credentials, 'same-origin');
    assert.equal(post.options.headers['Content-Type'], 'application/json');
    assert.equal(post.options.headers['X-Admin-Console-Session'], 'required');
    assert.equal(post.options.headers.Authorization, undefined);
    const body = JSON.parse(post.options.body);
    assert.deepEqual(body, { occurred_on: LOCAL_CLICK_DAY, expected_payer: 'Kushal', expected_transfer_usd: 268.55 });
    assert.match(body.occurred_on, /^\d{4}-\d{2}-\d{2}$/);
    assert.notEqual(body.occurred_on, UTC_CLICK_DAY);
    assert.equal(typeof body.expected_transfer_usd, 'number');
});

test('on success Level reloads analytics, the card turns level, and the success flash is still visible afterwards', async () => {
    const app = setup({ fetchImpl: levelServer() });
    showPending(app);

    await app.levelFounderSpend();

    assert.deepEqual(app.requests.map((r) => `${r.method} ${r.url}`), [`POST ${LEVEL_URL}`, `GET ${ANALYTICS_URL}`]);
    assert.equal(app.flash.hidden, false, 'loadFinanceAnalytics() clears the flash; Level must re-show it after');
    assert.equal(app.flash.className, 'flash success');
    assert.equal(app.flash.textContent, 'Leveled: Kushal paid Gaurav $268.55. Founder spend is now 50/50.');
    assert.equal(app.state.financeLeveling, false);
    assert.equal(app.state.financeAnalytics.founder_balance.is_level, true);
    assert.equal(app.levelStatus.textContent, '✓ Founder spend is level (50/50): Gaurav $602.78 · Kushal $602.79.');
    assert.equal(app.levelBtn.disabled, true);
    assert.equal(app.levelBtn.textContent, '⚖ Level 50/50');
    // The reloaded ledger shows the new settlement row.
    assert.match(app.refs.financeTableBody.innerHTML, /finance-kind settlement/);
});

test('cancelling the confirmation sends nothing and leaves the card as it was', async () => {
    const app = setup({ fetchImpl: levelServer(), confirmAnswer: false });
    showPending(app);

    await app.levelFounderSpend();

    assert.equal(app.confirms.length, 1);
    assert.equal(app.requests.length, 0);
    assert.equal(app.state.financeLeveling, false);
    assert.equal(app.levelBtn.disabled, false);
    assert.equal(app.levelBtn.textContent, '⚖ Level 50/50');
    assert.equal(app.flash.hidden, true);
    assert.match(app.levelStatus.textContent, /^Kushal owes Gaurav \$268\.55/);
});

test('a second click while the Level request is in flight is ignored and the button shows Leveling…', { timeout: 5000 }, async () => {
    const pendingPosts = [];
    const app = setup({ fetchImpl: levelServer({ levelResponse: () => new Promise((resolve) => { pendingPosts.push(resolve); }) }) });
    showPending(app);

    const first = app.levelFounderSpend();
    await settle();
    assert.equal(app.requests.length, 1);
    assert.equal(app.state.financeLeveling, true);
    assert.equal(app.levelBtn.disabled, true);
    assert.equal(app.levelBtn.textContent, 'Leveling…');

    // Not awaited one by one: an unguarded click would block on its own pending POST.
    const repeats = [app.levelFounderSpend(), app.levelFounderSpend()];
    await settle();
    const confirmsDuringFlight = app.confirms.length;
    const requestsDuringFlight = app.requests.filter((r) => r.method === 'POST').length;

    pendingPosts.forEach((resolve) => resolve(jsonResponse({ entry: { id: 42 }, founder_balance: LEVEL })));
    await Promise.all([first, ...repeats]);

    assert.equal(confirmsDuringFlight, 1, 'no second confirmation');
    assert.equal(requestsDuringFlight, 1, 'no second POST');
    assert.deepEqual(app.requests.map((r) => r.method), ['POST', 'GET']);
    assert.equal(app.state.financeLeveling, false);
    assert.equal(app.levelBtn.textContent, '⚖ Level 50/50');
});

for (const [name, detail, reloadedBalance, expectStatus, expectEnabled] of [
    ['the balance moved', 'Founder spend changed since this page loaded. Refresh and try again.',
        { ...PENDING, founders: [{ label: 'Gaurav', amount_usd: 891.33, after_usd: 612.79 }, PENDING.founders[1]], total_usd: 1225.57, transfer_usd: 278.55 },
        'Kushal owes Gaurav $278.55 to make founder spend 50/50.', true],
    ['someone already leveled', 'Founder spend is already 50/50 — nothing to settle.', LEVEL,
        '✓ Founder spend is level (50/50): Gaurav $602.78 · Kushal $602.79.', false]
]) {
    test(`409 when ${name} reloads analytics and shows the server's reason`, async () => {
        const app = setup({ fetchImpl: levelServer({ levelResponse: () => jsonResponse({ detail }, 409), reloaded: analytics(reloadedBalance) }) });
        showPending(app);

        await app.levelFounderSpend();

        assert.deepEqual(app.requests.map((r) => `${r.method} ${r.url}`), [`POST ${LEVEL_URL}`, `GET ${ANALYTICS_URL}`]);
        assert.equal(app.flash.hidden, false);
        assert.equal(app.flash.className, 'flash error');
        assert.equal(app.flash.textContent, detail);
        assert.equal(app.state.financeLeveling, false);
        assert.equal(app.levelStatus.textContent, expectStatus);
        assert.equal(app.levelBtn.disabled, !expectEnabled);
        assert.equal(app.levelBtn.textContent, '⚖ Level 50/50');
    });
}

for (const [name, respond, message] of [
    ['a 400 validation error', () => jsonResponse({ detail: 'Enter a valid amount.' }, 400), 'Enter a valid amount.'],
    ['a 422 with a detail list', () => jsonResponse({ detail: [{ msg: 'occurred_on is invalid' }] }, 422), 'occurred_on is invalid'],
    ['a non-JSON 502', () => ({ ok: false, status: 502, headers: { get() {} }, json: async () => { throw new SyntaxError('Unexpected <'); } }),
        'Could not level founder spend.'],
    ['a network failure', () => { throw new Error('Network unavailable'); }, 'Could not level founder spend. Please retry.']
]) {
    test(`${name} shows an error without reloading and leaves the button ready to retry`, async () => {
        const app = setup({ fetchImpl: levelServer({ levelResponse: respond }) });
        showPending(app);

        await app.levelFounderSpend();

        assert.equal(app.requests.length, 1, 'no analytics reload');
        assert.equal(app.flash.className, 'flash error');
        assert.equal(app.flash.textContent, message);
        assert.equal(app.state.financeLeveling, false);
        assert.equal(app.levelBtn.disabled, false);
        assert.equal(app.levelBtn.textContent, '⚖ Level 50/50');
        assert.match(app.levelStatus.textContent, /^Kushal owes Gaurav \$268\.55/);
    });
}

test('Level is a no-op with an "already 50/50" note when the balance is already level', async () => {
    const app = setup({ fetchImpl: levelServer() });
    app.state.financeAnalytics = analytics(LEVEL);

    await app.levelFounderSpend();

    assert.equal(app.confirms.length, 0);
    assert.equal(app.requests.length, 0);
    assert.equal(app.flash.className, 'flash success');
    assert.equal(app.flash.textContent, 'Founder spend is already 50/50.');
});

for (const [name, payload] of [['not loaded', null], ['missing founder_balance', analytics(undefined)]]) {
    test(`Level is a no-op that says finance data is not loaded when the balance is ${name}`, async () => {
        const app = setup({ fetchImpl: levelServer() });
        app.state.financeAnalytics = payload;

        await app.levelFounderSpend();

        assert.equal(app.confirms.length, 0);
        assert.equal(app.requests.length, 0);
        assert.equal(app.flash.className, 'flash error');
        assert.equal(app.flash.textContent, 'Finance data has not loaded yet. Refresh and try again.');
    });
}

// Spend filed under any other paid_by name is outside the 50/50 math: the card says so, the
// button stays disabled, and a direct call never confirms or posts.
const WITH_OTHERS = { ...PENDING, other_contributors: [{ label: 'Both', amount_usd: 100, percentage: 0 }] };
const OTHERS_NOTE = 'Some investment is filed under other names (Both $100.00). Set Paid by on those entries to Gaurav or Kushal, then level.';

test('spend under other names blocks Level with an explanation instead of a 50/50 claim', async () => {
    const app = setup({ fetchImpl: levelServer() });
    showPending(app, WITH_OTHERS);
    assert.equal(app.levelStatus.hidden, false);
    assert.equal(app.levelStatus.className, 'finance-level-status is-owed');
    assert.equal(app.levelStatus.textContent, OTHERS_NOTE);
    assert.equal(app.levelBtn.disabled, true);
    assert.equal(app.levelBtn.title, 'Re-assign spend filed under other names first');

    // Even an otherwise-level founder pair never claims ✓ 50/50 while others hold spend.
    app.renderFinanceFounderBalance({ ...LEVEL, other_contributors: WITH_OTHERS.other_contributors });
    assert.equal(app.levelStatus.textContent, OTHERS_NOTE);

    await app.levelFounderSpend();
    assert.equal(app.confirms.length, 0);
    assert.equal(app.requests.length, 0);
    assert.equal(app.flash.className, 'flash error');
    assert.equal(app.flash.textContent, OTHERS_NOTE);
});

test('the confirmation quotes total invested from the summary, not the founders-only sum', async () => {
    const app = setup({ fetchImpl: levelServer(), confirmAnswer: false });
    app.state.financeAnalytics = analytics(PENDING);
    app.state.financeAnalytics.summary.total_invested_usd = 1255.57;
    app.renderFinanceAnalytics();

    await app.levelFounderSpend();

    assert.equal(app.confirms.length, 1);
    assert.match(app.confirms[0].message, /Total invested stays \$1,255\.57 — only the split between founders changes\.$/);
});

test('a founder pushed below 0 by a later delete shows the real percentage, with only the bar clamped', () => {
    const app = setup();
    app.state.financeAnalytics = analytics(PENDING);
    app.state.financeAnalytics.contributor_breakdown = [
        { label: 'Kushal', amount_usd: 602.79, percentage: 148.63 },
        { label: 'Gaurav', amount_usd: -197.22, percentage: -48.63 }
    ];
    app.renderFinanceAnalytics();
    const markup = app.refs.financeContributorChart.innerHTML;
    assert.match(markup, /width: 100\.00%/);
    assert.match(markup, /width: 0\.00%/);
    assert.match(markup, /148\.63% of founder spend/);
    assert.match(markup, /-48\.63% of founder spend/);
});

test('without finance write access the Level button stays disabled even when a transfer is pending', () => {
    const app = setup({ grant: access('viewer', ['finance']) });
    app.renderFinanceFounderBalance(PENDING);
    assert.equal(app.levelBtn.disabled, true);
    assert.equal(app.levelStatus.textContent, 'Kushal owes Gaurav $268.55 to make founder spend 50/50.');
});

test('viewers get a hidden button and direct Level calls never confirm or fetch', async () => {
    const app = setup({ fetchImpl: levelServer(), grant: access('viewer', ['finance']) });
    showPending(app);
    assert.equal(app.levelBtn.hidden, true);

    await app.levelFounderSpend();

    assert.equal(app.confirms.length, 0);
    assert.equal(app.requests.length, 0);
    assert.equal(app.flash.className, 'flash error');
    assert.equal(app.flash.textContent, 'Your role does not allow this action.');
});

test('editors (write without delete) can level', async () => {
    const app = setup({ fetchImpl: levelServer(), grant: access('editor', ['finance']) });
    showPending(app);
    assert.equal(app.levelBtn.hidden, false);

    await app.levelFounderSpend();

    assert.deepEqual(app.requests.map((r) => r.method), ['POST', 'GET']);
    assert.equal(app.flash.className, 'flash success');
});

test('an unverified Cloudflare shield blocks Level before the confirmation', async () => {
    const app = setup({ fetchImpl: levelServer() });
    showPending(app);
    app.state.turnstileSiteKey = 'protection-enabled';
    app.state.adminProtectionVerified = false;

    await app.levelFounderSpend();

    assert.equal(app.confirms.length, 0);
    assert.equal(app.requests.length, 0);
    assert.equal(app.flash.className, 'flash error');
    assert.match(app.flash.textContent, /Cloudflare verification required/);
});

test('with the real confirm dialog, Cancel sends nothing and OK posts once', async () => {
    const app = setup({ fetchImpl: levelServer(), realConfirm: true });
    showPending(app);

    const cancelled = app.levelFounderSpend();
    await settle();
    const firstOverlay = app.appended.at(-1);
    assert.equal(firstOverlay.id, 'adminConfirmOverlay');
    assert.match(firstOverlay.innerHTML, /Level founder spend 50\/50\?/);
    assert.match(firstOverlay.innerHTML, />Level 50\/50</);
    assert.match(firstOverlay.innerHTML, /#4f46e5/, 'non-destructive (indigo) OK button');
    assert.doesNotMatch(firstOverlay.innerHTML, /#ef4444/);
    assert.match(firstOverlay.innerHTML, /Kushal paid Gaurav \$268\.55\.<br><br>Founder spend after leveling/);
    firstOverlay.querySelector('#adminCfmCancel').onclick();
    await cancelled;
    assert.equal(firstOverlay.removed, true);
    assert.equal(app.requests.length, 0);

    const confirmed = app.levelFounderSpend();
    await settle();
    const secondOverlay = app.appended.at(-1);
    assert.notEqual(secondOverlay, firstOverlay);
    secondOverlay.querySelector('#adminCfmOk').onclick();
    await confirmed;
    assert.equal(secondOverlay.removed, true);
    assert.deepEqual(app.requests.map((r) => `${r.method} ${r.url}`), [`POST ${LEVEL_URL}`, `GET ${ANALYTICS_URL}`]);
});

// ---------------------------------------------------------------------------------------
// Ledger rendering + undo
// ---------------------------------------------------------------------------------------

test('a Settlement ledger row has the settlement badge, "Kushal → Gaurav", Delete and no Edit; an investment keeps Edit', () => {
    const app = setup();
    app.renderFinanceLedger([SETTLEMENT_ROW, INVESTMENT_ROW, PAYMENT_ROW]);
    const [settlement, investment, payment] = ledgerRows(app.refs.financeTableBody.innerHTML);

    assert.match(settlement, /<span class="finance-kind settlement">Settlement<\/span>/);
    assert.match(settlement, /class="finance-amount settlement">\$268\.55/);
    assert.match(settlement, /<div class="finance-source">Kushal → Gaurav<\/div>/);
    assert.match(settlement, /data-finance-delete="42"/);
    assert.match(settlement, /data-admin-delete="finance"/);
    assert.doesNotMatch(settlement, /data-finance-edit/);
    assert.doesNotMatch(settlement, />Edit</);
    assert.match(settlement, /<td>Founder Settlement<\/td>/);
    assert.match(settlement, /<span class="finance-source">level<\/span>/);

    assert.match(investment, /<span class="finance-kind investment">Investment<\/span>/);
    assert.match(investment, /class="finance-amount negative">/);
    assert.match(investment, /data-finance-edit="7"[^>]*>Edit</);
    assert.match(investment, /data-finance-delete="7"/);
    assert.doesNotMatch(investment, /→/);

    assert.match(payment, /<span class="finance-kind return">Return<\/span>/);
    assert.match(payment, />Auto</);
    assert.doesNotMatch(payment, /data-finance-(?:edit|delete)/);
});

test('settlement note falls back to vendor when paid_to is absent, matches kind case-insensitively, and escapes names', () => {
    const app = setup();
    const { paid_to: _omit, ...withoutPaidTo } = SETTLEMENT_ROW;
    app.renderFinanceLedger([
        { ...withoutPaidTo, kind: 'settlement' },
        { ...SETTLEMENT_ROW, id: 'finance-43', paid_by: '<img src=x onerror=alert(1)>', paid_to: 'A&B' }
    ]);
    const [fallback, hostile] = ledgerRows(app.refs.financeTableBody.innerHTML);
    assert.match(fallback, /finance-kind settlement/);
    assert.match(fallback, /<div class="finance-source">Kushal → Gaurav<\/div>/);
    assert.doesNotMatch(fallback, /data-finance-edit/);
    assert.doesNotMatch(hostile, /<img/);
    assert.match(hostile, /&lt;img src=x onerror=alert\(1\)&gt; → A&amp;B/);
});

test('deleting a settlement explains the undo, DELETEs only that entry, and the reloaded card can be leveled again', async () => {
    const app = setup({
        fetchImpl: (url, options) => {
            if (options.method === 'DELETE') return jsonResponse({ ok: true });
            if (url === ANALYTICS_URL) return jsonResponse(analytics(PENDING));
            return jsonResponse({});
        }
    });
    app.state.financeAnalytics = analytics(LEVEL, [SETTLEMENT_ROW, INVESTMENT_ROW]);
    app.renderFinanceAnalytics();
    assert.equal(app.levelBtn.disabled, true);

    await app.deleteFinanceEntry('42');

    assert.equal(app.confirms.length, 1);
    assert.equal(app.confirms[0].opts.title, 'Delete settlement?');
    assert.equal(app.confirms[0].message,
        'This settlement (Kushal paid Gaurav $268.55) will be permanently removed, and founder spend goes back to the split before it was leveled.');
    assert.deepEqual(app.requests.map((r) => `${r.method} ${r.url}`),
        ['DELETE /api/admin/company-finance/entries/42', `GET ${ANALYTICS_URL}`]);
    assert.equal(app.levelBtn.disabled, false);
    assert.equal(app.levelStatus.textContent, 'Kushal owes Gaurav $268.55 to make founder spend 50/50.');
});

// ---------------------------------------------------------------------------------------
// Session changes
// ---------------------------------------------------------------------------------------

test('access changes clear the founder balance line like the other cached finance figures', () => {
    // clearPrivilegedState() must reset the status line and button with the other cached
    // finance figures, or "Kushal owes Gaurav $268.55 …" outlives the session it belongs to.
    const app = setup();
    showPending(app);
    assert.match(app.levelStatus.textContent, /Kushal owes Gaurav/);

    app.applyAdminAccess(access('viewer', ['ai']));

    assert.equal(app.refs.financeContributorChart.textContent, '', 'sibling founder chart is cleared');
    assert.equal(app.levelStatus.textContent, '');
    assert.equal(app.levelStatus.hidden, true);
});
