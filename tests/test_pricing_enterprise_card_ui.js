// The Enterprise plans on the public /pricing page (static/app.js refreshEnterprisePricingCard)
// and the students ↔ Enterprise toggle in front of them (setPricingAudience).
// Prices, limits, the tax note, the yearly offer and the US$ estimate must come from
// GET /api/enterprise/public/plans, in the currency the SERVER picks for this visitor's region —
// no hint, no selector, and no Enterprise price anywhere in app.js: a visitor is only ever shown
// their own region's prices (the INR and foreign ladders are not near-parity). Offline, the
// server-rendered cards stay as served. vm harness in the style of the other *_ui.js tests —
// no DOM: the declarations under test are sliced out of static/app.js (it is one 16k-line
// script that boots the whole SPA on load) and run against a stubbed document/fetch.

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
const moneySource = fs.readFileSync(path.join(__dirname, '../app/money.py'), 'utf8');
const stylesSource = fs.readFileSync(path.join(__dirname, '../static/styles.css'), 'utf8');
const pageSource = fs.readFileSync(path.join(__dirname, '../static/us_f1_visa.html'), 'utf8');

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
    'enterprisePublicPlansRequest', 'enterprisePricingInitialHtml', 'fetchEnterprisePublicPlans',
    'formatEnterpriseCount', 'setEnterprisePricingText', 'enterprisePlanField', 'enterprisePriceHtml',
    'enterprisePlanNote', 'renderEnterprisePlanCard', 'renderEnterprisePricingFromServer',
    'renderEnterprisePricingFallback', 'refreshEnterprisePricingCard'
];
const harnessSource = [
    "const API_BASE = '';",
    ...DECLARATIONS.map(extract),
    ';globalThis.ui = { refreshEnterprisePricingCard, formatMoneyMinor };'
].join('\n\n');

const INITIAL_CARD_HTML = '<!-- server-rendered INR price list -->';
const PLAN_KEYS = ['starter', 'growth', 'scale'];
const PLAN_FIELDS = ['label', 'purpose', 'price', 'note', 'seats', 'files', 'credits', 'reads'];
const jsonResponse = (payload, status = 200) => ({ ok: status < 400, status, json: async () => payload });
function deferred() { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; }

function element(id, attrs = {}) {
    const fields = new Map();
    return {
        id, innerHTML: '', textContent: '', style: { display: '' }, attrs, fields,
        getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null; },
        querySelector(selector) {
            const match = /^\[data-ent-field="([a-z]+)"\]$/.exec(selector);
            return match ? fields.get(match[1]) || null : null;
        }
    };
}

function planCard(key) {
    const card = element(`card-${key}`, { 'data-enterprise-plan': key });
    for (const field of PLAN_FIELDS) card.fields.set(field, element(`${key}-${field}`));
    card.fields.get('price').innerHTML = `SERVER-RENDERED ${key} PRICE`;
    card.fields.get('label').textContent = `SERVER-RENDERED ${key} LABEL`;
    return card;
}

function setup(fetchImpl) {
    const ids = ['pricingEnterpriseCard', 'pricingEnterpriseTrial', 'pricingEnterpriseTopupRow', 'pricingEnterpriseTopupFrom'];
    const elements = new Map(ids.map((id) => [id, element(id)]));
    elements.get('pricingEnterpriseCard').innerHTML = INITIAL_CARD_HTML;
    const cards = PLAN_KEYS.map(planCard);
    const requests = [];
    const context = vm.createContext({
        console: { warn() {}, log() {}, error() {} },
        Map, Number, String, Object, Array, Math, Intl, Promise, Error, encodeURIComponent,
        document: {
            getElementById: (id) => elements.get(id) || null,
            querySelectorAll: (selector) => (selector === '[data-enterprise-plan]' ? cards : [])
        },
        escapeHtml: (text) => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;'),
        fetch: async (url, init) => { requests.push({ url, init }); return fetchImpl(url, requests.length); }
    });
    vm.runInContext(harnessSource, context, { filename: 'static/app.js (enterprise pricing plans)' });
    const card = (key) => cards[PLAN_KEYS.indexOf(key)];
    const field = (key, name) => card(key).fields.get(name);
    return { ui: context.ui, el: (id) => elements.get(id), card, field, requests };
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
        currency: 'INR', currencies: ['INR'], show_usd_estimate: false, yearly_enabled: false,
        tax: { percent: 18, label: 'GST', note: '+ GST' },
        trial: { label: '14-day free trial', days: 14 },
        plans: [
            { key: 'sandbox', label: '14-day free trial', currency: 'INR', is_free: true, monthly_minor: 0, monthly_display: '₹0',
                price_note: 'Free for 14 days', max_seats: 3, max_open_files: 15, included_credits: 50, max_reads: 50 },
            plan('starter', 'Starter', 149900, '₹1,499', { purpose: 'Owner-led or 1–5 person offices', max_seats: 5,
                max_open_files: 40, included_credits: 150, max_reads: 150, yearly_display: '₹14,990', ...(planExtra.starter || {}) }),
            plan('growth', 'Team', 399900, '₹3,999', { purpose: 'Offices with 3–20 counsellors', max_seats: 25,
                max_open_files: 150, included_credits: 450, max_reads: 500, ...(planExtra.growth || {}) }),
            plan('scale', 'Multi-branch', 999900, '₹9,999', { purpose: 'Multi-branch firms with 10–40 counsellors', max_seats: 50,
                max_open_files: 500, included_credits: 1200, max_reads: 1000, ...(planExtra.scale || {}) })
        ],
        packages: [
            { key: 'pro', amount_minor: 299900, amount_display: '₹2,999' },
            { key: 'starter', amount_minor: 99900, amount_display: '₹999' }
        ],
        ...overrides
    };
}
const flush = () => new Promise((resolve) => setImmediate(resolve));

test('renders the server price list into every plan card: prices, limits and the server tax note', async () => {
    const { ui, el, field, requests } = setup(async () => jsonResponse(priceList()));
    await ui.refreshEnterprisePricingCard();
    assert.equal(requests.length, 1);
    // No currency hint: the server alone decides, from the visitor's region.
    assert.equal(requests[0].url, '/api/enterprise/public/plans');
    assert.equal(field('starter', 'price').innerHTML, '₹1,499<span>&nbsp;/month + GST</span>');
    assert.equal(field('growth', 'price').innerHTML, '₹3,999<span>&nbsp;/month + GST</span>');
    assert.equal(field('scale', 'price').innerHTML, '₹9,999<span>&nbsp;/month + GST</span>');
    assert.equal(field('starter', 'label').textContent, 'Starter');
    assert.equal(field('growth', 'label').textContent, 'Team');
    assert.equal(field('scale', 'purpose').textContent, 'Multi-branch firms with 10–40 counsellors');
    assert.deepEqual(
        ['seats', 'files', 'credits', 'reads'].map((name) => field('scale', name).textContent),
        ['50', '500', '1,200', '1,000']
    );
    assert.deepEqual(
        ['seats', 'files', 'credits', 'reads'].map((name) => field('starter', name).textContent),
        ['5', '40', '150', '150']
    );
    assert.equal(el('pricingEnterpriseTopupFrom').textContent, '₹999');   // the cheapest pack, not the first
    assert.equal(el('pricingEnterpriseTopupRow').style.display, '');
    assert.equal(el('pricingEnterpriseTrial').textContent, '14-day free trial · no card required');
    // Yearly is not on sale: nothing promotes it, even though the plan carries the price.
    for (const key of PLAN_KEYS) {
        assert.equal(field(key, 'note').textContent, '');
        assert.equal(field(key, 'note').style.display, 'none');
    }
});

test('no "+ GST" anywhere when the server reports no tax', async () => {
    const noTax = { price_note: '' };
    const { ui, field } = setup(async () => jsonResponse(priceList(
        { tax: { percent: 0, label: null, note: '' } }, { starter: noTax, growth: noTax, scale: noTax })));
    await ui.refreshEnterprisePricingCard();
    assert.equal(field('starter', 'price').innerHTML, '₹1,499<span>&nbsp;/month</span>');
    assert.ok(PLAN_KEYS.every((key) => !field(key, 'price').innerHTML.includes('GST')));
});

test('an INR-region visitor outside India gets the INR price with a US$ estimate line', async () => {
    const estimate = { currency: 'USD', monthly_minor: 2100, monthly_display: '≈ US$21' };
    const { ui, field } = setup(async () => jsonResponse(priceList(
        { currency: 'INR', show_usd_estimate: true }, { starter: { usd_estimate: estimate } })));
    await ui.refreshEnterprisePricingCard();
    assert.equal(field('starter', 'price').innerHTML, '₹1,499<span>&nbsp;/month + GST</span>');
    assert.equal(field('starter', 'note').textContent, 'Billed in INR · ≈ US$21 a month in total');
    assert.equal(field('starter', 'note').style.display, '');
    // A plan without an estimate says nothing; the estimate line already explains the currency.
    assert.equal(field('growth', 'note').style.display, 'none');
});

test('a ladder currency answer renders as-is with no tax note', async () => {
    const gbp = (minor, display) => ({ currency: 'GBP', monthly_minor: minor, monthly_display: display, price_note: '' });
    const { ui, el, field } = setup(async () => jsonResponse(priceList(
        { currency: 'GBP', currencies: ['USD', 'GBP'], packages: [{ key: 'starter', amount_minor: 999, amount_display: '£9.99' }] },
        { starter: gbp(2900, '£29'), growth: gbp(6900, '£69'), scale: gbp(14500, '£145') })));
    await ui.refreshEnterprisePricingCard();
    assert.equal(field('starter', 'price').innerHTML, '£29<span>&nbsp;/month</span>');
    assert.equal(field('scale', 'price').innerHTML, '£145<span>&nbsp;/month</span>');
    assert.equal(el('pricingEnterpriseTopupFrom').textContent, '£9.99');
});

test('yearly is promoted only while the server says it can be bought', async () => {
    const { ui, field } = setup(async () => jsonResponse(priceList({ yearly_enabled: true })));
    await ui.refreshEnterprisePricingCard();
    assert.equal(field('starter', 'note').textContent, 'or ₹14,990 a year (2 months free)');
    assert.equal(field('growth', 'note').style.display, 'none');   // no yearly price on that plan
});

test('a tier the server no longer sells is hidden, never left up at a stale price', async () => {
    const { ui, card } = setup(async () => {
        const list = priceList();
        list.plans = list.plans.filter((p) => p.key !== 'scale');
        return jsonResponse(list);
    });
    await ui.refreshEnterprisePricingCard();
    assert.equal(card('scale').style.display, 'none');
    assert.equal(card('starter').style.display, '');
    assert.equal(card('growth').style.display, '');
});

test('a price list that matches none of the cards keeps the server-rendered cards instead of hiding every tier', async () => {
    const { ui, el, card, field } = setup(async () => {
        const list = priceList();
        list.plans = [plan('enterprise_custom', 'Custom', 5000000, '₹50,000')];
        return jsonResponse(list);
    });
    await ui.refreshEnterprisePricingCard();
    assert.ok(PLAN_KEYS.every((key) => card(key).style.display === ''));
    assert.equal(el('pricingEnterpriseCard').innerHTML, INITIAL_CARD_HTML);
    assert.equal(field('starter', 'price').innerHTML, 'SERVER-RENDERED starter PRICE');
});

test('offline: the server-rendered price list (already this visitor\'s region) stays, nothing is guessed', async () => {
    const { ui, el, field } = setup(async () => { throw new Error('offline'); });
    await ui.refreshEnterprisePricingCard();
    assert.equal(el('pricingEnterpriseCard').innerHTML, INITIAL_CARD_HTML);
    assert.equal(field('starter', 'price').innerHTML, 'SERVER-RENDERED starter PRICE');
    assert.equal(el('pricingEnterpriseTopupRow').style.display, '');
});

test('an empty price list (billing switched off) keeps the server-rendered plans', async () => {
    const { ui, el, field } = setup(async () => jsonResponse(priceList({ plans: [] })));
    await ui.refreshEnterprisePricingCard();
    assert.equal(el('pricingEnterpriseCard').innerHTML, INITIAL_CARD_HTML);
    assert.equal(field('starter', 'price').innerHTML, 'SERVER-RENDERED starter PRICE');
});

test('the price list is fetched once per page; a failure is not cached', async () => {
    let calls = 0;
    const { ui, requests } = setup(async () => {
        calls += 1;
        if (calls === 1) throw new Error('blip');
        return jsonResponse(priceList());
    });
    await ui.refreshEnterprisePricingCard();   // fails, not cached
    await ui.refreshEnterprisePricingCard();   // fetches again, succeeds, cached
    await ui.refreshEnterprisePricingCard();   // served from the same request
    assert.equal(requests.length, 2);
});

test('app.js carries no Enterprise price of its own and never asks for another currency', () => {
    // A client-side ladder shipped every region's prices — the rupee column included — to every
    // visitor's browser. The server's answer is the only Enterprise price the page may show.
    assert.ok(!source.includes('ENTERPRISE_PLAN_LADDER'), 'an Enterprise price ladder is back in app.js');
    for (const product of ['plan_starter', 'plan_growth', 'plan_scale']) {
        const block = moneySource.slice(moneySource.indexOf(`"${product}": {`));
        const body = block.slice(0, block.indexOf('},'));
        const inr = /"INR":\s*_env_minor\("[A-Z_]+",\s*([\d_]+)\)/.exec(body);
        assert.ok(inr, `could not parse ${product} INR from app/money.py`);
        assert.ok(!source.includes(inr[1].replace(/_/g, '')), `app.js holds the INR ${product} price`);
    }
    assert.ok(!/public\/plans\?currency=/.test(source), 'the Enterprise price list must not be asked for a currency');
    assert.ok(!extract('updatePricingByCurrency').includes('refreshEnterprisePricingCard'),
        'the Pass currency selector must not drive the Enterprise prices');
});

test('the page carries one card per ladder plan, each with every field the renderer fills', () => {
    const section = pageSource.slice(pageSource.indexOf('id="pricingEnterprisePanel"'), pageSource.indexOf('class="pricing-disclaimer"'));
    assert.ok(section.length > 0, 'us_f1_visa.html lost #pricingEnterprisePanel');
    assert.ok(section.includes('id="pricingEnterpriseCard"'), 'the snapshot/restore container must wrap the plans');
    // Every tier's CTA starts the same small trial workspace, so the trial's own limits must be on the panel.
    for (const token of ['{{ENT_TRIAL_SEATS}}', '{{ENT_TRIAL_OPEN_FILES}}', '{{ENT_TRIAL_CREDITS_NOTE}}']) {
        assert.ok(section.includes(token), `the Enterprise panel no longer states the trial's ${token}`);
    }
    assert.ok(!pageSource.includes('pricingEnterpriseRegionNote'), 'no "billed in another currency" note: there is no selector');
    // The currency selector is the Pass's: hidden for the Enterprise audience, and the CSS
    // must let `hidden` win over the controls' display:flex.
    assert.match(pageSource, /<div class="pricing-controls" data-pricing-only="students">/);
    assert.match(pageSource, /<span data-pricing-only="students">Every currency has its own price/);
    assert.match(stylesSource, /\[data-pricing-only\]\[hidden\]\s*\{\s*display:\s*none !important;/);
    const cards = section.split('data-enterprise-plan="').slice(1);
    assert.deepEqual(cards.map((chunk) => chunk.slice(0, chunk.indexOf('"'))), PLAN_KEYS);
    for (const chunk of cards) {
        const body = chunk.slice(0, chunk.indexOf('</article>'));
        for (const name of PLAN_FIELDS) assert.ok(body.includes(`data-ent-field="${name}"`), `${chunk.slice(0, 8)} lacks ${name}`);
    }
});

// ---------------------------------------------------------------------------
// The students ↔ Enterprise toggle
// ---------------------------------------------------------------------------

const toggleSource = [
    ...['PRICING_AUDIENCE_SUBTITLES', 'pricingAudience', 'pricingAudienceFromUrl', 'setPricingAudience',
        'handlePricingAudienceKeydown'].map(extract),
    ';globalThis.ui = { setPricingAudience, pricingAudienceFromUrl, handlePricingAudienceKeydown };'
].join('\n\n');

function toggleSetup(href = 'https://rilono.com/pricing') {
    let current = new URL(href);
    const replaced = [];
    const tab = (audience) => ({
        audience, tabIndex: audience === 'students' ? 0 : -1, focused: 0, classes: new Set(audience === 'students' ? ['is-active'] : []),
        attrs: { 'data-pricing-audience': audience, 'aria-selected': audience === 'students' ? 'true' : 'false' },
        getAttribute(name) { return this.attrs[name] ?? null; },
        setAttribute(name, value) { this.attrs[name] = String(value); },
        classList: null,
        focus() { this.focused += 1; }
    });
    const tabs = [tab('students'), tab('enterprise')];
    for (const t of tabs) {
        t.classList = { toggle: (name, on) => { if (on) t.classes.add(name); else t.classes.delete(name); } };
    }
    const toggle = { attrs: { 'data-active': 'students' }, scrolled: 0,
        setAttribute(name, value) { this.attrs[name] = String(value); }, scrollIntoView() { this.scrolled += 1; } };
    const onlyFor = (audience) => ({ hidden: false, getAttribute: (name) => (name === 'data-pricing-only' ? audience : null) });
    const studentsOnly = [onlyFor('students'), onlyFor('students')];
    const elements = new Map([
        ['pricingAudienceToggle', toggle],
        ['pricingStudentsPanel', { hidden: false }],
        ['pricingEnterprisePanel', { hidden: true }],
        ['pricingSubtitle', { textContent: '' }]
    ]);
    const location = {
        get href() { return current.href; }, get pathname() { return current.pathname; },
        get search() { return current.search; }, get hash() { return current.hash; }
    };
    const context = vm.createContext({
        String, Object, URL, URLSearchParams,
        document: {
            getElementById: (id) => elements.get(id) || null,
            querySelectorAll: (selector) => {
                if (selector === '[data-pricing-audience]') return tabs;
                if (selector === '[data-pricing-only]') return studentsOnly;
                return [];
            }
        },
        window: {
            location,
            history: { state: { path: '/pricing' }, replaceState(state, _title, url) { replaced.push(url); current = new URL(url, current); } }
        }
    });
    vm.runInContext(toggleSource, context, { filename: 'static/app.js (pricing audience toggle)' });
    return { ui: context.ui, tabs, toggle, el: (id) => elements.get(id), replaced, url: () => current, studentsOnly };
}

test('the toggle flips panels, tabs and the subtitle, and keeps ?for=enterprise in the address', () => {
    const { ui, tabs, toggle, el, replaced, url } = toggleSetup('https://rilono.com/pricing?utm_source=x#top');
    ui.setPricingAudience('enterprise');
    assert.equal(toggle.attrs['data-active'], 'enterprise');
    assert.equal(el('pricingStudentsPanel').hidden, true);
    assert.equal(el('pricingEnterprisePanel').hidden, false);
    assert.match(el('pricingSubtitle').textContent, /every AI feature/);
    assert.deepEqual(tabs.map((t) => [t.attrs['aria-selected'], t.tabIndex, t.classes.has('is-active')]),
        [['false', -1, false], ['true', 0, true]]);
    // Only `for` is touched: utm_* and the hash survive.
    assert.equal(url().search, '?utm_source=x&for=enterprise');
    assert.equal(url().hash, '#top');

    ui.setPricingAudience('students');
    assert.equal(el('pricingStudentsPanel').hidden, false);
    assert.equal(el('pricingEnterprisePanel').hidden, true);
    assert.equal(el('pricingSubtitle').textContent, 'Simple plans for every stage of your study-abroad journey.');
    assert.equal(url().search, '?utm_source=x');
    assert.equal(replaced.length, 2);
    ui.setPricingAudience('students');          // already there: no extra history write
    assert.equal(replaced.length, 2);
});

test('the Pass currency selector is hidden for the Enterprise audience and back for students', () => {
    const { ui, studentsOnly } = toggleSetup();
    ui.setPricingAudience('enterprise');
    assert.ok(studentsOnly.every((el) => el.hidden === true));
    ui.setPricingAudience('students');
    assert.ok(studentsOnly.every((el) => el.hidden === false));
});

test('the toggle never rewrites the address off /pricing, and unknown audiences mean students', () => {
    const { ui, el, replaced } = toggleSetup('https://rilono.com/about-us');
    ui.setPricingAudience('enterprise');
    assert.equal(replaced.length, 0);
    ui.setPricingAudience('nonsense');
    assert.equal(el('pricingStudentsPanel').hidden, false);
});

test('?for= deep links pick the audience; anything else is no preference', () => {
    assert.equal(toggleSetup('https://rilono.com/pricing?for=enterprise').ui.pricingAudienceFromUrl(), 'enterprise');
    assert.equal(toggleSetup('https://rilono.com/pricing?for=Teams').ui.pricingAudienceFromUrl(), 'enterprise');
    assert.equal(toggleSetup('https://rilono.com/pricing?for=students').ui.pricingAudienceFromUrl(), 'students');
    assert.equal(toggleSetup('https://rilono.com/pricing?for=pizza').ui.pricingAudienceFromUrl(), null);
    assert.equal(toggleSetup('https://rilono.com/pricing').ui.pricingAudienceFromUrl(), null);
});

test('arrow keys, Home and End move between the tabs and focus the new one', () => {
    const { ui, tabs, el } = toggleSetup();
    const press = (key) => { let prevented = false; ui.handlePricingAudienceKeydown({ key, preventDefault() { prevented = true; } }); return prevented; };
    assert.equal(press('ArrowRight'), true);
    assert.equal(el('pricingEnterprisePanel').hidden, false);
    assert.equal(tabs[1].focused, 1);
    press('ArrowLeft');
    assert.equal(el('pricingStudentsPanel').hidden, false);
    press('End');
    assert.equal(el('pricingEnterprisePanel').hidden, false);
    press('Home');
    assert.equal(el('pricingStudentsPanel').hidden, false);
    assert.equal(press('Tab'), false);          // everything else is left to the browser
});
