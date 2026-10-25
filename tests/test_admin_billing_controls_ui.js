// Admin console billing controls on the enterprise account modal (pricing v2): record an
// offline plan payment, adjust credits / grant the demo-call bonus, edit Branch Packs, limit
// overrides and the trial end. vm harness in the style of test_admin_finance_level_ui.js — no
// DOM: static/admin_console.js runs in a vm context with stubbed document/fetch, and the
// helpers under test are exposed through a trailing `;globalThis.ui = {...}`.

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/admin_console.js'), 'utf8');
const sections = ['users', 'enterprise', 'analytics', 'finance', 'ai', 'team'];

const ORG_ID = 42;
const BASE = `/api/admin/enterprise/accounts/${ORG_ID}`;
const DETAILS_URL = `${BASE}/details`;

const jsonResponse = (payload, status = 200) => ({ ok: status < 400, status, headers: { get() {} }, json: async () => payload });
const plain = (value) => JSON.parse(JSON.stringify(value));

function access(role = 'admin', assigned = sections) {
    return {
        user: { id: 17, email: 'founder@example.test', full_name: 'Console Founder', is_admin: false, is_developer: false },
        role, sections: assigned, can_manage_team: role === 'admin' && assigned.includes('team'), can_provision_enterprise: false,
        can_write_sections: role === 'viewer' ? [] : assigned,
        can_delete_sections: role === 'admin' ? assigned : []
    };
}

// Shapes mirror app/routers/admin.py enterprise_account_details_admin + _billing_controls_state.
function controls(overrides = {}) {
    return {
        billing_enabled: true,
        stored_plan: 'growth', status: 'active', current_period_end: '2026-11-21T10:00:00',
        trial_ends_at: '2026-11-05T23:59:59', trial_domain_blocked: false, has_mandate: false,
        branch_packs: 1, branch_packs_applied: 1,
        branch_pack: { open_files: 100, seats: 10, credits: 200, reads: 200 },
        overrides: { max_seats: 35, max_clients: null, included_credits: null, monthly_reads: null },
        overrides_applied: true,
        plan_defaults: { max_seats: 25, max_clients: 150, included_credits: 450, monthly_reads: 500 },
        effective_limits: { max_seats: 45, max_clients: 250, included_credits: 650, monthly_reads: 700 },
        demo_bonus_credits: 50, demo_bonus_granted_at: null, demo_bonus_available: true,
        plans: [{ key: 'starter', label: 'Starter' }, { key: 'growth', label: 'Team' }, { key: 'scale', label: 'Multi-branch' }],
        providers: [{ key: 'payment_link', label: 'Payment Link' }, { key: 'bank_transfer', label: 'Bank transfer' }, { key: 'invoice', label: 'Invoice' }],
        currencies: ['INR', 'USD'], default_currency: 'INR', yearly_enabled: false,
        period_days: { monthly: 30, yearly: 365 },
        price_list: [
            { plan: 'growth', billing_cycle: 'monthly', currency: 'INR', list_minor: 399900, tax_minor: 71982, total_minor: 471882, total_display: '₹4,718.82' },
            { plan: 'growth', billing_cycle: 'yearly', currency: 'INR', list_minor: 3999000, tax_minor: 719820, total_minor: 4718820, total_display: '₹47,188.20' },
            { plan: 'growth', billing_cycle: 'monthly', currency: 'USD', list_minor: 8900, tax_minor: 0, total_minor: 8900, total_display: '$89' }
        ],
        caps: { offline_payment_max_minor: 100000000, credit_adjust_max: 100000, branch_packs_max: 100, override_max: 1000000, trial_days_max: 365 },
        ...overrides
    };
}

function details(extra = {}) {
    return {
        organization: { id: ORG_ID, company_name: 'Acme Visas', members_active: 3, admins: 1 },
        wallet: { balance_credits: 120, balance_display: '₹1,200', lifetime_purchased_credits: 0, lifetime_spent_credits: 30 },
        subscription: {
            plan: 'growth', plan_label: 'Team', is_sandbox: false, monthly_display: '₹3,999', tax_label: 'GST',
            open_files_used: 12, max_open_files: 250, clients_used: 12, max_clients: 250, seats_used: 4, max_seats: 45,
            included_credits: 650, credits_recur: true, reads: { granted: 700, used: 20, remaining: 680 }, ai_paused: false
        },
        totals: { currency: 'INR', total_paid_display: '₹4,718.82', verified_payment_count: 0, payment_currencies: ['INR'] },
        purchases: [], recent_activity: [], coupons: [], refunds: [], razorpay_enabled: false,
        plan_payments: [{
            id: 7, plan: 'growth', plan_label: 'Team', billing_cycle: 'monthly', provider: 'bank_transfer',
            provider_label: 'Bank transfer', is_offline: true, reference: 'UTR<img src=x onerror=alert(1)>',
            currency: 'INR', amount_minor: 471882, amount_display: '₹4,718.82', tax_display: '₹719.82', tax_label: 'GST',
            status: 'verified', created_by_name: 'Console Founder', verified_at: '2026-10-22T10:00:00'
        }],
        billing_controls: controls(),
        ...extra
    };
}

function classList() {
    const names = new Set();
    return {
        names,
        toggle(name, force) { const on = force === undefined ? !names.has(name) : Boolean(force); if (on) names.add(name); else names.delete(name); return on; },
        add(name) { names.add(name); }, remove(name) { names.delete(name); }, contains: (name) => names.has(name)
    };
}

function element(id = '') {
    let markup = '';
    let text = '';
    const listeners = {};
    return {
        id, value: '', hidden: false, disabled: false, className: '', title: '', tabIndex: 0,
        dataset: {}, attributes: {}, style: {}, listeners, removed: false, classList: classList(),
        setAttribute(name, value) { this.attributes[name] = String(value); },
        getAttribute(name) { return this.attributes[name]; },
        hasAttribute(name) { return name in this.attributes; },
        addEventListener(type, handler) { (listeners[type] ||= []).push(handler); },
        removeEventListener() {}, reset() {}, focus() {}, scrollIntoView() {},
        remove() { this.removed = true; },
        querySelector() { return element(); },
        querySelectorAll() { return []; },
        get textContent() { return text; },
        set textContent(value) { text = String(value); markup = ''; },
        get innerHTML() { return markup || text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); },
        set innerHTML(value) { markup = String(value); text = ''; }
    };
}

function setup({ fetchImpl, grant = access(), confirmAnswer = true } = {}) {
    let elements = new Map();
    const requests = [];
    const confirms = [];
    const get = (id) => {
        if (/Overlay$/.test(id)) return null;
        if (!elements.has(id)) elements.set(id, element(id));
        return elements.get(id);
    };
    sections.forEach((key) => { get(`admin${key[0].toUpperCase() + key.slice(1)}TabBtn`).dataset.tab = key; });
    // The billing tabs and panes, as querySelectorAll would find them in the rendered modal.
    const tabs = ['payment', 'credits', 'overrides'].map((mode) => Object.assign(element(), { dataset: { billingMode: mode } }));
    const panes = ['payment', 'credits', 'overrides'].map((mode) => Object.assign(element(), { dataset: { mode } }));
    const context = vm.createContext({
        document: {
            getElementById: get,
            createElement: () => element(),
            addEventListener() {}, removeEventListener() {},
            querySelectorAll(selector) {
                if (selector === '.billing-tab') return tabs;
                if (selector === '.billing-mode') return panes;
                return [];
            },
            querySelector() { return null; },
            body: Object.assign(element('body'), { appendChild() {} })
        },
        window: { matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {} }),
            addEventListener() {}, removeEventListener() {}, scrollTo() {} },
        URLSearchParams, Blob, URL, setTimeout, clearTimeout,
        console: { error() {}, warn() {}, log() {} },
        fetch: async (url, options = {}) => {
            requests.push({ url, method: String(options.method || 'GET').toUpperCase(), body: options.body ? JSON.parse(options.body) : undefined });
            return fetchImpl ? fetchImpl(url, options) : jsonResponse({});
        }
    });
    vm.runInContext(`${source}
;globalThis.ui = { state, refs, applyAdminAccess, adminFetch, renderAccountDetails, loadAccountDetails,
    billingMajorToMinor, readOfflinePaymentForm, readOverridesForm, buildBillingControlsBlock, buildPlanPaymentsBlock,
    renderCouponTable, renderEnterpriseTable, handleEnterpriseTableActionClick, openCouponModal,
    setAccountModalSection, handleCouponCreateSubmit };`, context);
    context.__confirm = async (message, opts) => {
        confirms.push({ message, opts: plain(opts || {}) });
        return confirmAnswer;
    };
    vm.runInContext('confirmDialog = (message, opts) => globalThis.__confirm(message, opts);', context);
    const app = context.ui;
    app.state.authToken = 'test-cookie-token';
    if (grant) app.applyAdminAccess(grant);
    app.state.couponOrg = { id: ORG_ID, company: 'Acme Visas' };
    return { ...app, context, get, requests, confirms, tabs, panes };
}

// Every billing POST/PUT answers with `answer`; the details reload returns `reloaded`.
function server({ answer = () => jsonResponse({ message: 'Saved.', warnings: [] }), reloaded = details() } = {}) {
    return (url, options = {}) => {
        if (url === DETAILS_URL) return jsonResponse(typeof reloaded === 'function' ? reloaded() : reloaded);
        if (url.startsWith(BASE + '/') && ['POST', 'PUT'].includes(String(options.method || '').toUpperCase())) return answer(url, options);
        return jsonResponse({});
    };
}

// The stub hands back the SAME element for an id across re-renders, so every render adds one
// more listener to it; a real re-render replaces the element. Fire only the latest render's
// handler — iterating the live list would also fire the handlers each save's reload adds.
async function click(app, id) {
    const handlers = app.get(id).listeners.click || [];
    assert.ok(handlers.length, `no click handler wired on #${id}`);
    await handlers[handlers.length - 1]({ preventDefault() {} });
}

function fill(app, values) {
    Object.entries(values).forEach(([id, value]) => { app.get(id).value = value; });
}

const writes = (app) => app.requests.filter((r) => r.method !== 'GET');

// ---------------------------------------------------------------------------

test('enterprise accounts expose a direct Discount codes action with the account identity', () => {
    const app = setup();
    app.state.enterpriseAccounts = [{ organization_id: ORG_ID, company_name: 'Acme <Visas>' }];
    app.renderEnterpriseTable();
    assert.match(app.refs.enterpriseTableBody.innerHTML,
        /data-action="discount-codes"\s+data-org-id="42"\s+data-company="Acme &lt;Visas&gt;">Discount codes<\/button>/);
});

test('Discount codes opens its own section while account details are still loading', async () => {
    let finishDetails;
    const app = setup({ fetchImpl: (url) => {
        if (url === DETAILS_URL) return new Promise((resolve) => { finishDetails = () => resolve(jsonResponse(details())); });
        return jsonResponse({ coupons: [] });
    } });
    const loading = app.handleEnterpriseTableActionClick({ target: { closest: () => ({
        disabled: false, dataset: { action: 'discount-codes', orgId: String(ORG_ID), company: 'Acme Visas' }
    }) } });
    assert.equal(app.refs.couponModal.hidden, false);
    assert.equal(app.refs.accountDiscountPane.hidden, false);
    assert.equal(app.refs.accountDetailsPane.hidden, true);
    assert.equal(app.refs.accountDiscountTab.getAttribute('aria-pressed'), 'true');
    assert.match(app.refs.accountDetails.innerHTML, /Loading account details/);
    // Let the protection check finish, then complete the unrelated details request.
    await new Promise((resolve) => setImmediate(resolve));
    finishDetails();
    await loading;
    assert.equal(app.refs.accountDiscountPane.hidden, false, 'loading details must not displace the discount form');
    app.refs.accountModalBody.scrollTop = 500;
    app.setAccountModalSection('details');
    assert.equal(app.refs.accountModalBody.scrollTop, 0, 'switching sections starts at its first field');
    assert.equal(app.refs.accountDetailsPane.hidden, false);
    assert.equal(app.refs.accountDiscountPane.hidden, true);
    assert.equal(app.refs.accountDetailsTab.getAttribute('aria-pressed'), 'true');
});

test('opening Manage returns to account details after viewing discounts', async () => {
    const app = setup({ fetchImpl: server() });
    app.setAccountModalSection('discounts');
    await app.openCouponModal(ORG_ID, 'Acme Visas');
    assert.equal(app.refs.accountDetailsPane.hidden, false);
    assert.equal(app.refs.accountDiscountPane.hidden, true);
});

test('the account discount form sends 100% unchanged and refreshes its code list', async () => {
    const app = setup({ fetchImpl: (url, options = {}) => {
        if (options.method === 'POST') return jsonResponse({ coupon: { code: 'FREE100', percent_off: 100 } });
        return jsonResponse({ coupons: [{ id: 1, code: 'FREE100', percent_off: 100, is_active: true }] });
    } });
    fill(app, { adminCouponCodeInput: 'FREE100', adminCouponPercentInput: '100',
        adminCouponAppliesInput: 'billing', adminCouponMaxInput: '1', adminCouponNoteInput: '' });
    await app.handleCouponCreateSubmit({ preventDefault() {} });
    assert.deepEqual(writes(app), [{ url: `${BASE}/coupons`, method: 'POST', body: {
        code: 'FREE100', percent_off: 100, applies_to: 'billing', is_active: true, max_redemptions: 1, note: null
    } }]);
    assert.match(app.refs.couponTableBody.innerHTML, /FREE100/);
    assert.match(app.refs.couponTableBody.innerHTML, /100%/);
});

test('billingMajorToMinor converts once, in the currency\'s own minor unit, and refuses typos', () => {
    const app = setup();
    assert.equal(app.billingMajorToMinor('4,718.82', 'INR'), 471882);
    assert.equal(app.billingMajorToMinor('12', 'USD'), 1200);
    assert.equal(app.billingMajorToMinor('0.1', 'USD'), 10);
    assert.ok(Number.isNaN(app.billingMajorToMinor('1.005', 'USD')));
    assert.ok(Number.isNaN(app.billingMajorToMinor('-5', 'INR')));
    assert.ok(Number.isNaN(app.billingMajorToMinor('abc', 'INR')));
    assert.ok(Number.isNaN(app.billingMajorToMinor('', 'INR')));
});

test('an Editor is refused client-side for every billing control, before any request is sent', async () => {
    const app = setup({ grant: access('editor', ['enterprise']) });
    for (const [suffix, method] of [['offline-payment', 'POST'], ['credits/adjust', 'POST'], ['overrides', 'PUT'], ['refunds', 'POST']]) {
        const response = await app.adminFetch(`${BASE}/${suffix}`, { method, body: '{}' });
        assert.equal(response.ok, false, suffix);
        assert.equal(response.status, 403, suffix);
    }
    assert.equal(app.requests.length, 0);
    // Coupons stay Editor-level.
    const coupon = await app.adminFetch(`${BASE}/coupons`, { method: 'POST', body: '{}' });
    assert.equal(coupon.ok, true);
    assert.equal(app.requests.length, 1);
});

test('the Admin sees the billing controls; an Editor sees the plan payments but no controls', () => {
    const admin = setup();
    admin.renderAccountDetails(details());
    const html = admin.refs.accountDetails.innerHTML;
    assert.match(html, /Billing controls/);
    assert.match(html, /id="billingPayBtn"/);
    assert.match(html, /id="billingAdjustBtn"/);
    assert.match(html, /id="billingDemoBtn"/);
    assert.match(html, /Grant demo-call bonus \(\+50 credits\)/);
    assert.match(html, /id="billingOvBtn"/);
    assert.match(html, /invoice sale; self-serve yearly is off/);
    assert.match(html, /Plan default: 150/);                       // empty override shows the plan number
    assert.match(html, /id="billingOvSeats"[^>]*value="35"/);       // a set override is prefilled
    assert.match(html, /id="billingOvTrial"[^>]*value="2026-11-05"/);
    // Plan payments: the offline row, its reference ESCAPED, and who recorded it.
    assert.match(html, /Plan payments/);
    assert.match(html, /Bank transfer <span class="account-coupon-tag">offline<\/span>/);
    assert.match(html, /UTR&lt;img src=x onerror=alert\(1\)&gt;/);
    assert.doesNotMatch(html, /<img src=x/);
    assert.match(html, /recorded by Console Founder/);
    assert.match(html, /680 \/ 700 AI reads left/);
    assert.match(html, /1 Branch Pack/);
    assert.match(html, /overrides: staff seats 35/);
    assert.match(html, /12 \/ 250 open files/);

    const editor = setup({ grant: access('editor', ['enterprise']) });
    editor.renderAccountDetails(details());
    const editorHtml = editor.refs.accountDetails.innerHTML;
    assert.doesNotMatch(editorHtml, /Billing controls/);
    assert.match(editorHtml, /Plan payments/);
});

test('plan payments show the offline note (escaped), only when there is one, and flag a superseded charge', () => {
    const app = setup();
    const base = details().plan_payments[0];
    const html = app.buildPlanPaymentsBlock({ plan_payments: [
        { ...base, note: 'NEFT <b>after</b> demo; 10% negotiated' },
        { ...base, id: 8, is_offline: false, provider: 'razorpay', provider_label: 'Razorpay checkout', reference: 'pay_X1',
          created_by_name: null, note: null, status: 'superseded' },
    ] });
    assert.match(html, /NEFT &lt;b&gt;after&lt;\/b&gt; demo; 10% negotiated/);
    assert.doesNotMatch(html, /<b>after/);
    const rows = html.split('<tr>').slice(2);       // [header, offline row, checkout row]
    assert.equal(rows.length, 2);
    // The checkout row carries no note, so no extra meta line beyond its reference.
    assert.equal((rows[1].match(/enterprise-meta/g) || []).length, 3, 'cycle, tax, reference only');
    assert.match(rows[1], /account-status-chip failed">superseded/);
});

test('a legacy coupon above the cap is listed at the percent checkout really gives', () => {
    const app = setup();
    app.state.couponList = [
        { id: 1, code: 'LAUNCH50', percent_off: 50, percent_display: '50%', effective_percent_display: '15%', above_cap: true,
          is_active: true, applies_to: 'all', redemptions_used: 0, max_redemptions: null },
        { id: 2, code: 'TEN', percent_off: 10, percent_display: '10%', effective_percent_display: '10%', above_cap: false,
          is_active: true, applies_to: 'all', redemptions_used: 0, max_redemptions: null },
    ];
    app.renderCouponTable();
    const html = app.get('adminCouponTableBody').innerHTML;
    assert.match(html, /<td>15%<div class="enterprise-meta">saved as 50% · above cap<\/div><\/td>/);
    assert.match(html, /<td>10%<\/td>/);
});

test('inside a prepaid term the payment form offers an explicit tier change, and sends it only when ticked', () => {
    const app = setup();
    app.renderAccountDetails(details());
    assert.doesNotMatch(app.refs.accountDetails.innerHTML, /billingPayTierNow/, 'no option without a running term');

    app.renderAccountDetails(details({ billing_controls: controls({
        term_locked_until: '2027-08-01T00:00:00', term_locked_plan: 'starter', term_locked_plan_label: 'Starter' }) }));
    assert.match(app.refs.accountDetails.innerHTML, /id="billingPayTierNow"[\s\S]*prepaid Starter term/);
    fill(app, { billingPayPlan: 'scale', billingPayCycle: 'monthly', billingPayProvider: 'invoice',
        billingPayCurrency: 'INR', billingPayAmount: '11,798.82', billingPayReference: 'INV-9' });
    assert.equal(app.readOfflinePaymentForm(controls()).body.change_tier_now, undefined);
    app.get('billingPayTierNow').checked = true;
    assert.equal(app.readOfflinePaymentForm(controls()).body.change_tier_now, true);
});

test('a granted demo bonus shows its date instead of the button', () => {
    const app = setup();
    app.renderAccountDetails(details({ billing_controls: controls({ demo_bonus_granted_at: '2026-10-01T09:00:00', demo_bonus_available: false }) }));
    const html = app.refs.accountDetails.innerHTML;
    assert.doesNotMatch(html, /id="billingDemoBtn"/);
    assert.match(html, /Demo-call bonus granted/);
});

test('recording an offline payment confirms the amount and sends minor units, then reloads the account', async () => {
    const app = setup({ fetchImpl: server({ answer: () => jsonResponse({
        duplicate: false, message: 'Recorded ₹47,188.20 (Invoice, INV-2026/014). Team is active until 2027-11-21.',
        warnings: ['The amount differs from the list price for Team (yearly): ₹47,188.20 including tax.']
    }) }) });
    app.renderAccountDetails(details());
    fill(app, {
        billingPayPlan: 'growth', billingPayCycle: 'yearly', billingPayProvider: 'invoice', billingPayCurrency: 'INR',
        billingPayAmount: '47,188.20', billingPayTax: '', billingPayReference: 'INV-2026/014', billingPayNote: 'Signed deal'
    });
    await click(app, 'billingPayBtn');

    assert.equal(app.confirms.length, 1);
    assert.match(app.confirms[0].message, /Record ₹47,188\.20 \(INR\) received by Invoice, reference INV-2026\/014, for Acme Visas/);
    assert.match(app.confirms[0].message, /activates Team \(yearly\) and extends it by 365 days/);
    const [write] = writes(app);
    assert.equal(write.url, `${BASE}/offline-payment`);
    assert.equal(write.method, 'POST');
    assert.deepEqual(write.body, {
        plan: 'growth', billing_cycle: 'yearly', provider: 'invoice', currency: 'INR',
        amount_minor: 4718820, reference: 'INV-2026/014', note: 'Signed deal'
    });
    // Reloaded, and the result — with the server's warning — is shown above the forms.
    assert.ok(app.requests.some((r) => r.url === DETAILS_URL));
    assert.equal(app.state.billingNotice.tone, 'info');
    const html = app.refs.accountDetails.innerHTML;
    assert.match(html, /Team is active until 2027-11-21/);
    assert.match(html, /differs from the list price/);
    assert.equal(app.get('billingFormError').hidden, true);
});

test('a non-INR payment needs its INR settlement and an optional tax is converted too', async () => {
    const app = setup({ fetchImpl: server() });
    app.renderAccountDetails(details());
    fill(app, { billingPayPlan: 'growth', billingPayCycle: 'monthly', billingPayProvider: 'bank_transfer',
        billingPayCurrency: 'USD', billingPayAmount: '89', billingPayReference: 'WIRE-77', billingPaySettled: '' });
    await click(app, 'billingPayBtn');
    assert.match(app.get('billingFormError').textContent, /INR amount that settled for this USD payment/);
    assert.equal(writes(app).length, 0);

    fill(app, { billingPaySettled: '8,010.50', billingPayTax: '4.50' });
    await click(app, 'billingPayBtn');
    assert.deepEqual(writes(app)[0].body, {
        plan: 'growth', billing_cycle: 'monthly', provider: 'bank_transfer', currency: 'USD',
        amount_minor: 8900, tax_minor: 450, settled_inr_minor: 801050, reference: 'WIRE-77'
    });
});

test('offline payment input errors are shown in the modal and nothing is sent', async () => {
    const cases = [
        [{ billingPayAmount: '' }, /Enter the amount received in INR/],
        [{ billingPayAmount: '4718.825' }, /Enter the amount received in INR/],
        [{ billingPayAmount: '2000000' }, /check the amount/],
        [{ billingPayTax: '5000' }, /Tax must be a plain amount smaller/],
        [{ billingPayReference: 'UTR 001' }, /no spaces/],
        [{ billingPayReference: '' }, /payment reference/]
    ];
    for (const [values, error] of cases) {
        const app = setup({ fetchImpl: server() });
        app.renderAccountDetails(details());
        fill(app, { billingPayPlan: 'growth', billingPayCycle: 'monthly', billingPayProvider: 'bank_transfer',
            billingPayCurrency: 'INR', billingPayAmount: '4718.82', billingPayReference: 'UTR001', ...values });
        await click(app, 'billingPayBtn');
        assert.match(app.get('billingFormError').textContent, error, JSON.stringify(values));
        assert.equal(app.get('billingFormError').hidden, false);
        assert.equal(app.confirms.length, 0);
        assert.equal(writes(app).length, 0);
    }
});

test('a cancelled confirm sends nothing; a server refusal is shown and the account is not reloaded', async () => {
    const cancelled = setup({ fetchImpl: server(), confirmAnswer: false });
    cancelled.renderAccountDetails(details());
    fill(cancelled, { billingPayPlan: 'growth', billingPayCycle: 'monthly', billingPayProvider: 'bank_transfer',
        billingPayCurrency: 'INR', billingPayAmount: '4718.82', billingPayReference: 'UTR001' });
    await click(cancelled, 'billingPayBtn');
    assert.equal(writes(cancelled).length, 0);

    const refused = setup({ fetchImpl: server({ answer: () => jsonResponse({ detail: 'Reference UTR001 is already recorded (payment #3, account #9).' }, 409) }) });
    refused.renderAccountDetails(details());
    fill(refused, { billingPayPlan: 'growth', billingPayCycle: 'monthly', billingPayProvider: 'bank_transfer',
        billingPayCurrency: 'INR', billingPayAmount: '4718.82', billingPayReference: 'UTR001' });
    await click(refused, 'billingPayBtn');
    assert.match(refused.get('billingFormError').textContent, /already recorded/);
    assert.equal(refused.requests.filter((r) => r.url === DETAILS_URL).length, 0);
    assert.equal(refused.get('billingPayBtn').disabled, false);
    assert.equal(refused.state.billingNotice, null);
});

test('a credit deduction is confirmed as destructive and sends a signed whole number with its reason', async () => {
    const app = setup({ fetchImpl: server({ answer: () => jsonResponse({ message: 'Deducted 20 credits.', applied: -20, warnings: [] }) }) });
    app.renderAccountDetails(details());
    fill(app, { billingAdjustCredits: '-20', billingAdjustReason: 'Duplicate goodwill grant' });
    await click(app, 'billingAdjustBtn');
    assert.match(app.confirms[0].message, /Deduct 20 credits from Acme Visas/);
    assert.equal(app.confirms[0].opts.danger, true);
    assert.deepEqual(writes(app)[0], { url: `${BASE}/credits/adjust`, method: 'POST',
        body: { kind: 'adjustment', credits: -20, reason: 'Duplicate goodwill grant' } });
    assert.equal(app.state.billingNotice.tone, 'success');

    for (const [values, error] of [
        [{ billingAdjustCredits: '0', billingAdjustReason: 'zero' }, /whole number of credits/],
        [{ billingAdjustCredits: '2.5', billingAdjustReason: 'fraction' }, /whole number of credits/],
        [{ billingAdjustCredits: '100001', billingAdjustReason: 'typo' }, /At most 100,000/],
        [{ billingAdjustCredits: '10', billingAdjustReason: '' }, /Give a reason/]
    ]) {
        const bad = setup({ fetchImpl: server() });
        bad.renderAccountDetails(details());
        fill(bad, values);
        await click(bad, 'billingAdjustBtn');
        assert.match(bad.get('billingFormError').textContent, error);
        assert.equal(writes(bad).length, 0);
    }
});

test('the demo-call bonus posts its kind, and an already-granted answer is shown as information', async () => {
    const app = setup({ fetchImpl: server({ answer: () => jsonResponse({
        kind: 'demo_call_bonus', granted: 0, already_granted: true,
        message: 'The demo-call bonus was already granted on 2026-10-01 — it can be given once per account.'
    }) }) });
    app.renderAccountDetails(details());
    await click(app, 'billingDemoBtn');
    assert.match(app.confirms[0].message, /one-time 50-credit demo-call bonus to Acme Visas/);
    assert.deepEqual(writes(app)[0].body, { kind: 'demo_call_bonus', reason: '' });
    assert.equal(app.state.billingNotice.tone, 'info');
    assert.match(app.refs.accountDetails.innerHTML, /already granted on 2026-10-01/);
});

test('saving limits sends only what changed — blank means plan default, an unchanged trial is left alone', async () => {
    const app = setup({ fetchImpl: server() });
    app.renderAccountDetails(details());
    fill(app, { billingOvPacks: '2', billingOvSeats: '', billingOvFiles: '', billingOvCredits: '600', billingOvReads: '', billingOvTrial: '2026-11-05' });
    await click(app, 'billingOvBtn');
    const [write] = writes(app);
    assert.equal(write.method, 'PUT');
    assert.equal(write.url, `${BASE}/overrides`);
    assert.deepEqual(write.body, { branch_packs: 2, max_seats: null, included_credits: 600 });
    assert.match(app.confirms[0].message, /Branch Packs: 1 → 2/);
    assert.match(app.confirms[0].message, /Staff seats: 35 → plan default \(25\)/);
    assert.match(app.confirms[0].message, /AI credits \/ period: plan default \(450\) → 600/);

    const trial = setup({ fetchImpl: server() });
    trial.renderAccountDetails(details());
    fill(trial, { billingOvPacks: '1', billingOvSeats: '35', billingOvTrial: '2026-12-01' });
    await click(trial, 'billingOvBtn');
    assert.deepEqual(writes(trial)[0].body, { trial_ends_at: '2026-12-01' });

    const unchanged = setup({ fetchImpl: server() });
    unchanged.renderAccountDetails(details());
    fill(unchanged, { billingOvPacks: '1', billingOvSeats: '35', billingOvTrial: '2026-11-05' });
    await click(unchanged, 'billingOvBtn');
    assert.equal(unchanged.get('billingFormError').textContent, 'Nothing changed.');
    assert.equal(writes(unchanged).length, 0);

    const bad = setup({ fetchImpl: server() });
    bad.renderAccountDetails(details());
    fill(bad, { billingOvPacks: '1', billingOvSeats: '-3' });
    await click(bad, 'billingOvBtn');
    assert.match(bad.get('billingFormError').textContent, /Staff seats must be a whole number/);
    assert.equal(writes(bad).length, 0);
});

test('switching billing tabs is remembered across the re-render that follows a save', () => {
    const app = setup();
    app.renderAccountDetails(details());
    const creditsTab = app.tabs.find((t) => t.dataset.billingMode === 'credits');
    creditsTab.listeners.click[creditsTab.listeners.click.length - 1]();
    assert.equal(app.state.billingTab, 'credits');
    assert.equal(creditsTab.classList.contains('active'), true);
    assert.equal(app.panes.find((p) => p.dataset.mode === 'payment').classList.contains('hidden'), true);
    assert.equal(app.panes.find((p) => p.dataset.mode === 'credits').classList.contains('hidden'), false);
    app.renderAccountDetails(details());
    assert.match(app.refs.accountDetails.innerHTML, /class="billing-tab active" data-billing-mode="credits"/);
    assert.match(app.refs.accountDetails.innerHTML, /class="billing-mode hidden" data-mode="payment"/);
});

test('a notice from one account is never shown on another', () => {
    const app = setup();
    app.state.billingNotice = { orgId: 999, tone: 'success', text: 'Recorded for a different org.', warnings: [] };
    app.renderAccountDetails(details());
    assert.doesNotMatch(app.refs.accountDetails.innerHTML, /different org/);
});
