// The Enterprise card on the public /pricing page (static/app.js refreshEnterprisePricingCard).
// Prices, limits, the tax note, the yearly offer and the US$ estimate must come from
// GET /api/enterprise/public/plans, in the currency the SERVER answers with (its region rule
// wins over the selected currency); ENTERPRISE_PLAN_LADDER_FALLBACK is only an offline
// fallback and must match app/money.py. vm harness in the style of the other *_ui.js tests —
// no DOM: the declarations under test are sliced out of static/app.js (it is one 16k-line
// script that boots the whole SPA on load) and run against a stubbed document/fetch.

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
const moneySource = fs.readFileSync(path.join(__dirname, '../app/money.py'), 'utf8');

// A top-level declaration of app.js, from its first line to the first column-0 line that
// closes it (`}`, `});`, `};` …) — or just that line for a one-line `const x = …;`.
function extract(name) {
    const lines = source.split('\n');
    const head = new RegExp(`^(?:async\\s+)?function\\s+${name}\\s*\\(|^(?:const|let)\\s+${name}\\s*=`);
    const start = lines.findIndex((line) => head.test(line));
    assert.ok(start >= 0, `static/app.js no longer declares ${name}`);
    const first = lines[start];
    if (/;\s*$/.test(first) && !/[{([]\s*$/.test(first)) return first;
    for (let i = start + 1; i < lines.length; i += 1) {
        if (/^[}\])]/.test(lines[i])) return lines.slice(start, i + 1).join('\n');
    }
    throw new Error(`could not find the end of ${name}`);
}

const DECLARATIONS = [
    'CURRENCY_MINOR_UNIT_EXPONENT', 'CURRENCY_SYMBOL_OVERRIDES', 'formatCurrencyAmount', 'formatMoneyMinor',
    'ENTERPRISE_PLAN_LADDER_FALLBACK', 'enterprisePublicPlansCache', 'enterprisePricingRenderSeq',
    'enterprisePricingInitialHtml', 'ENTERPRISE_TIER_PRICE_IDS', 'fetchEnterprisePublicPlans',
    'formatEnterpriseCount', 'setEnterprisePricingNote', 'enterpriseTierRowHtml',
    'renderEnterprisePricingFromServer', 'renderEnterprisePricingFallback', 'refreshEnterprisePricingCard'
];
const harnessSource = [
    "const API_BASE = '';",
    ...DECLARATIONS.map(extract),
    ';globalThis.ui = { refreshEnterprisePricingCard, ENTERPRISE_PLAN_LADDER_FALLBACK, formatMoneyMinor };'
].join('\n\n');

const INITIAL_CARD_HTML = '<!-- server-rendered INR card -->';
const jsonResponse = (payload, status = 200) => ({ ok: status < 400, status, json: async () => payload });
function deferred() { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; }

function element(id, attrs = {}) {
    return {
        id, innerHTML: '', textContent: '', style: { display: '' }, attrs,
        getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null; }
    };
}

function setup(fetchImpl) {
    const ids = ['pricingEnterpriseCard', 'pricingEnterprisePrice', 'pricingEnterpriseNote', 'pricingEnterpriseTrial',
        'pricingEnterpriseTopupRow', 'pricingEnterpriseTopupFrom',
        'pricingEnterpriseTierStarter', 'pricingEnterpriseTierGrowth', 'pricingEnterpriseTierScale'];
    const elements = new Map(ids.map((id) => [id, element(id)]));
    elements.get('pricingEnterpriseCard').innerHTML = INITIAL_CARD_HTML;
    elements.get('pricingEnterprisePrice').innerHTML = 'SERVER-RENDERED PRICE';
    const rows = ['starter', 'growth', 'scale'].map((key) => element(`row-${key}`, { 'data-enterprise-plan': key }));
    const requests = [];
    const context = vm.createContext({
        console: { warn() {}, log() {}, error() {} },
        Map, Number, String, Object, Array, Math, Intl, Promise, Error, encodeURIComponent,
        document: {
            getElementById: (id) => elements.get(id) || null,
            querySelectorAll: (selector) => (selector === '[data-enterprise-plan]' ? rows : [])
        },
        escapeHtml: (text) => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;'),
        fetch: async (url, init) => { requests.push({ url, init }); return fetchImpl(url, requests.length); }
    });
    vm.runInContext(harnessSource, context, { filename: 'static/app.js (enterprise pricing card)' });
    return { ui: context.ui, el: (id) => elements.get(id), rows, requests };
}

// Shapes mirror app/routers/enterprise.py enterprise_public_plans + billing.public_plans_payload.
function plan(key, label, minor, display, extra = {}) {
    return {
        key, label, currency: 'INR', is_free: false, monthly_minor: minor, monthly_display: display,
        price_note: '+ GST', yearly_display: null, yearly_months_free: 2, usd_estimate: null, ...extra
    };
}
function priceList(overrides = {}, planExtra = {}) {
    return {
        currency: 'INR', show_usd_estimate: false, yearly_enabled: false, tax: { percent: 18, label: 'GST', note: '+ GST' },
        trial: { label: '14-day free trial', days: 14 },
        plans: [
            { key: 'sandbox', label: '14-day free trial', currency: 'INR', is_free: true, monthly_minor: 0, monthly_display: '₹0',
                price_note: 'Free for 14 days', max_seats: 3, max_open_files: 15, included_credits: 50 },
            plan('starter', 'Starter', 149900, '₹1,499', { max_seats: 5, max_open_files: 40, included_credits: 150,
                yearly_display: '₹14,990', ...(planExtra.starter || {}) }),
            plan('growth', 'Team', 399900, '₹3,999', { max_seats: 25, max_open_files: 150, included_credits: 450, ...(planExtra.growth || {}) }),
            plan('scale', 'Multi-branch', 999900, '₹9,999', { max_seats: 50, max_open_files: 500, included_credits: 1200, ...(planExtra.scale || {}) })
        ],
        packages: [
            { key: 'pro', amount_minor: 299900, amount_display: '₹2,999' },
            { key: 'starter', amount_minor: 99900, amount_display: '₹999' }
        ],
        ...overrides
    };
}
const flush = () => new Promise((resolve) => setImmediate(resolve));

test('renders the server price list: prices, limits and the server tax note', async () => {
    const { ui, el, rows, requests } = setup(async () => jsonResponse(priceList()));
    await ui.refreshEnterprisePricingCard('INR');
    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, '/api/enterprise/public/plans?currency=INR');
    assert.equal(el('pricingEnterprisePrice').innerHTML, '₹1,499<span>&nbsp;/month + GST</span>');
    assert.equal(rows[0].innerHTML, 'Starter <span id="pricingEnterpriseTierStarter">₹1,499</span>/mo — 5 staff, 40 open files, 150 AI credits/mo');
    assert.equal(rows[1].innerHTML, 'Team <span id="pricingEnterpriseTierGrowth">₹3,999</span>/mo — 25 staff, 150 open files, 450 AI credits/mo');
    assert.equal(rows[2].innerHTML, 'Multi-branch <span id="pricingEnterpriseTierScale">₹9,999</span>/mo — 50 staff, 500 open files, 1,200 AI credits/mo');
    assert.equal(el('pricingEnterpriseTopupFrom').textContent, '₹999');   // the cheapest pack, not the first
    assert.equal(el('pricingEnterpriseTopupRow').style.display, '');
    assert.equal(el('pricingEnterpriseTrial').textContent, '14-day free trial · no card required');
    // Yearly is not on sale: nothing promotes it, even though the card carries the price.
    assert.equal(el('pricingEnterpriseNote').textContent, '');
    assert.equal(el('pricingEnterpriseNote').style.display, 'none');
});

test('no "+ GST" anywhere when the server reports no tax', async () => {
    const noTax = { price_note: '' };
    const { ui, el, rows } = setup(async () => jsonResponse(priceList(
        { tax: { percent: 0, label: null, note: '' } }, { starter: noTax, growth: noTax, scale: noTax })));
    await ui.refreshEnterprisePricingCard('INR');
    assert.equal(el('pricingEnterprisePrice').innerHTML, '₹1,499<span>&nbsp;/month</span>');
    assert.ok(rows.every((row) => !row.innerHTML.includes('GST')));
});

test('the server region rule wins: a USD request from the INR region is quoted INR with a US$ estimate', async () => {
    const estimate = { currency: 'USD', monthly_minor: 2100, monthly_display: '≈ US$21' };
    const { ui, el, requests } = setup(async () => jsonResponse(priceList(
        { currency: 'INR', show_usd_estimate: true, requested_currency: 'USD' }, { starter: { usd_estimate: estimate } })));
    await ui.refreshEnterprisePricingCard('USD');
    assert.equal(requests[0].url, '/api/enterprise/public/plans?currency=USD');
    assert.equal(el('pricingEnterprisePrice').innerHTML, '₹1,499<span>&nbsp;/month + GST</span>');
    assert.equal(el('pricingEnterpriseNote').textContent, 'Billed in INR · ≈ US$21 a month in total');
    assert.equal(el('pricingEnterpriseNote').style.display, 'block');
});

test('a ladder currency answer renders as-is with no tax note', async () => {
    const gbp = (minor, display) => ({ currency: 'GBP', monthly_minor: minor, monthly_display: display, price_note: '' });
    const { ui, el, rows } = setup(async () => jsonResponse(priceList(
        { currency: 'GBP', packages: [{ key: 'starter', amount_minor: 999, amount_display: '£9.99' }] },
        { starter: gbp(2900, '£29'), growth: gbp(6900, '£69'), scale: gbp(14500, '£145') })));
    await ui.refreshEnterprisePricingCard('GBP');
    assert.equal(el('pricingEnterprisePrice').innerHTML, '£29<span>&nbsp;/month</span>');
    assert.match(rows[2].innerHTML, /<span id="pricingEnterpriseTierScale">£145<\/span>\/mo/);
    assert.equal(el('pricingEnterpriseTopupFrom').textContent, '£9.99');
});

test('yearly is promoted only while the server says it can be bought', async () => {
    const { ui, el } = setup(async () => jsonResponse(priceList({ yearly_enabled: true })));
    await ui.refreshEnterprisePricingCard('INR');
    assert.equal(el('pricingEnterpriseNote').textContent, 'or ₹14,990 a year (2 months free)');
});

test('offline: a ladder currency repaints from the fallback ladder, without a tax note or guessed extras', async () => {
    let fail = false;
    const { ui, el } = setup(async () => { if (fail) throw new Error('offline'); return jsonResponse(priceList()); });
    await ui.refreshEnterprisePricingCard('INR');          // first call snapshots the server markup
    el('pricingEnterpriseCard').innerHTML = 'MUTATED BY THAT RENDER';
    fail = true;
    await ui.refreshEnterprisePricingCard('USD');
    // Restored to the server-rendered markup first, then only the ladder prices repainted.
    assert.equal(el('pricingEnterpriseCard').innerHTML, INITIAL_CARD_HTML);
    assert.equal(el('pricingEnterprisePrice').innerHTML, '$39<span>&nbsp;/month</span>');
    assert.equal(el('pricingEnterpriseTierStarter').textContent, '$39');
    assert.equal(el('pricingEnterpriseTierGrowth').textContent, '$89');
    assert.equal(el('pricingEnterpriseTierScale').textContent, '$195');
    assert.equal(el('pricingEnterpriseTopupRow').style.display, 'none');   // its price is INR-only here
    assert.equal(el('pricingEnterpriseNote').style.display, 'none');
});

test('offline: INR restores the server-rendered card (its own tax note) and touches nothing else', async () => {
    let fail = false;
    const { ui, el } = setup(async () => { if (fail) throw new Error('offline'); return jsonResponse(priceList()); });
    await ui.refreshEnterprisePricingCard('EUR');          // snapshot the initial markup, then render
    fail = true;
    el('pricingEnterprisePrice').innerHTML = 'UNCHANGED';
    await ui.refreshEnterprisePricingCard('INR');
    assert.equal(el('pricingEnterpriseCard').innerHTML, INITIAL_CARD_HTML);
    assert.equal(el('pricingEnterprisePrice').innerHTML, 'UNCHANGED');
});

test('an empty price list (billing switched off) falls back instead of blanking the card', async () => {
    const { ui, el } = setup(async () => jsonResponse(priceList({ plans: [] })));
    await ui.refreshEnterprisePricingCard('USD');
    assert.equal(el('pricingEnterprisePrice').innerHTML, '$39<span>&nbsp;/month</span>');
});

test('a slow response for a currency the visitor already left is dropped', async () => {
    const slow = deferred();
    const { ui, el } = setup(async (url) => {
        if (url.endsWith('USD')) return slow.promise;
        return jsonResponse(priceList({ currency: 'GBP' }, { starter: { monthly_display: '£29', price_note: '' } }));
    });
    const first = ui.refreshEnterprisePricingCard('USD');
    await ui.refreshEnterprisePricingCard('GBP');
    slow.resolve(jsonResponse(priceList({ currency: 'USD' }, { starter: { monthly_display: '$39', price_note: '' } })));
    await first;
    await flush();
    assert.equal(el('pricingEnterprisePrice').innerHTML, '£29<span>&nbsp;/month</span>');
});

test('responses are cached per requested currency; failures are not', async () => {
    let calls = 0;
    const { ui, requests } = setup(async () => {
        calls += 1;
        if (calls === 1) throw new Error('blip');
        return jsonResponse(priceList());
    });
    await ui.refreshEnterprisePricingCard('EUR');   // fails, not cached
    await ui.refreshEnterprisePricingCard('EUR');   // fetches again, succeeds, cached
    await ui.refreshEnterprisePricingCard('EUR');   // served from cache
    assert.equal(requests.length, 2);
});

test('the offline ladder matches app/money.py PRICE_BOOK (INR re-cut 2026-10-22, other ladders unchanged)', () => {
    const { ui } = setup(async () => jsonResponse(priceList()));
    const ladder = ui.ENTERPRISE_PLAN_LADDER_FALLBACK;
    for (const product of ['plan_starter', 'plan_growth', 'plan_scale']) {
        const block = moneySource.slice(moneySource.indexOf(`"${product}": {`));
        const body = block.slice(0, block.indexOf('},'));
        const book = {};
        for (const match of body.matchAll(/"([A-Z]{3})":\s*_env_minor\("[A-Z_]+",\s*([\d_]+)\)/g)) {
            book[match[1]] = Number(match[2].replace(/_/g, ''));
        }
        assert.ok(Object.keys(book).length >= 8, `could not parse ${product} from app/money.py`);
        for (const [currency, minor] of Object.entries(book)) {
            assert.equal(ladder[currency] && ladder[currency][product], minor, `${product} ${currency}`);
        }
    }
    assert.deepEqual({ ...ladder.INR }, { plan_starter: 149900, plan_growth: 399900, plan_scale: 999900 });
});
