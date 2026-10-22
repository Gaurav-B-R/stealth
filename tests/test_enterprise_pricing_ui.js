// Enterprise portal (static/enterprise.js) against the pricing-v2 API (2026-10-22): plan cards
// and tax notes from the server, the yearly toggle, region-filtered currencies, open-file grace
// and AI-paused banners, wallet price labels, document reading ("Read now"), the server-side
// staff mock-interview session, plan-gated Team editors and the Closed stage.
//
// vm harness in the style of the admin console tests — no real DOM. enterprise.js is one IIFE,
// so the test (and only the test) splices a `globalThis.__entTest = {...}` export in front of
// its `window.__ent = {` line and a guard in front of its INIT block. Elements are stubs keyed
// by id; `$$(".class", root)` is answered by scanning the root's rendered markup for that class
// (with its data-* attributes), which is enough to fire the real click handlers.

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/enterprise.js'), 'utf8');
const HOOK = '  window.__ent = {';
const INIT = '  setupAuth();\n  wireInfoTips();\n  boot()';
assert.equal(source.split(HOOK).length, 2, 'enterprise.js must contain exactly one `window.__ent = {` line');
assert.equal(source.split(INIT).length, 2, 'enterprise.js INIT block moved — update the harness');

const EXPORTS = [
  'state', 'teamUi', 'creditsUi', 'trialBanner', 'renderBilling', 'checkout', 'applyBillingCoupon',
  'renderCredits', 'openCreditCheckout', 'renderClientPage', 'tmDrawRoles', 'tmPaintBranches',
  'branchFilterHtml', 'docReadBadge', 'planFeature', 'aiPausedMessage', 'isAiPausedError',
  'priceLabelFor', 'creditCostFor', 'billingStartPrice', 'setStatus', 'applyAiMeta', 'sendAi',
  'renderAiThread', 'updatePlanChip', 'notOpenStageLabels', 'planAllowanceSummary',
];
const patched = source
  .replace(HOOK, `  globalThis.__entTest = { ${EXPORTS.join(', ')} };\n${HOOK}`)
  .replace(INIT, `  if (globalThis.__ENT_SKIP_INIT__) return;\n${INIT}`);

const plain = (value) => JSON.parse(JSON.stringify(value));
const jsonResponse = (payload, status = 200) => ({
  ok: status < 400, status, headers: { get() { return null; } }, json: async () => payload,
});
const flush = () => new Promise((resolve) => setImmediate(resolve));
async function settle(times = 6) { for (let i = 0; i < times; i += 1) await flush(); }

function classList() {
  const names = new Set();
  return {
    names,
    add(...n) { n.forEach((x) => names.add(x)); },
    remove(...n) { n.forEach((x) => names.delete(x)); },
    toggle(name, force) { const on = force === undefined ? !names.has(name) : !!force; if (on) names.add(name); else names.delete(name); return on; },
    contains(name) { return names.has(name); },
  };
}

function makeDom() {
  const elements = new Map();
  const found = {};
  const dom = { elements, found };
  function element(id = '') {
    let html = '';
    let text = '';
    const el = {
      id, value: '', checked: false, disabled: false, hidden: false, files: null, className: '',
      dataset: {}, style: {}, attributes: {}, listeners: {}, classList: classList(),
      isConnected: true, scrollTop: 0, scrollHeight: 0, tagName: 'DIV',
      get innerHTML() { return html; },
      set innerHTML(v) { html = String(v); text = ''; },
      get textContent() { return text || html.replace(/<[^>]*>/g, ''); },
      set textContent(v) { text = String(v); html = ''; },
      get outerHTML() { return html; },
      set outerHTML(v) { html = String(v); },
      setAttribute(k, v) { this.attributes[k] = String(v); },
      getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; },
      hasAttribute(k) { return k in this.attributes; },
      removeAttribute(k) { delete this.attributes[k]; },
      addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); },
      removeEventListener() {},
      querySelector(sel) { return dom.query(sel); },
      querySelectorAll(sel) { return dom.queryAll(sel, this); },
      appendChild(c) { return c; }, removeChild() {}, remove() {}, focus() {}, blur() {}, select() {},
      click() { if (this.onclick) return this.onclick({ preventDefault() {}, target: this }); return undefined; },
      scrollIntoView() {}, closest() { return null; }, contains() { return false; },
      getBoundingClientRect() { return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }; },
      insertAdjacentHTML(_, h) { html += h; }, cloneNode() { return element(); },
      setCustomValidity() {}, reportValidity() { return true; }, checkValidity() { return true; },
    };
    return el;
  }
  dom.element = element;
  dom.get = (id) => { if (!elements.has(id)) elements.set(id, element(id)); return elements.get(id); };
  dom.query = (sel) => {
    const m = /^#([\w-]+)$/.exec(String(sel || '').trim());
    return m ? dom.get(m[1]) : null;
  };
  // `.class` → one stub per matching start tag in the root's markup, data-* parsed into dataset.
  // The same tag text answers with the same stub, so a handler wired by one query (`$$(…)
  // .forEach(b => b.onclick = …)`) is the one a later query in the test fires.
  const stubCache = new Map();
  dom.queryAll = (sel, root) => {
    const m = /^\.([\w-]+)$/.exec(String(sel || '').trim());
    if (!m) return [];
    const roots = root ? [root] : [...elements.values()];
    const out = [];
    roots.forEach((r) => {
      const re = /<([a-z]+)\b([^>]*)>/gi;
      let t;
      const html = r.innerHTML || '';
      while ((t = re.exec(html))) {
        const cm = /class="([^"]*)"/.exec(t[2]);
        if (!cm || !cm[1].split(/\s+/).includes(m[1])) continue;
        const key = `${sel}|${t[0]}`;
        if (!stubCache.has(key)) {
          const el = element('');
          el.className = cm[1];
          t[2].replace(/data-([\w-]+)="([^"]*)"/g, (_, k, v) => { el.dataset[k.replace(/-([a-z])/g, (__, c) => c.toUpperCase())] = v; return ''; });
          stubCache.set(key, el);
        }
        out.push(stubCache.get(key));
      }
    });
    found[sel] = out;
    return out;
  };
  return dom;
}

function setup({ routes = {}, caps = ['*'], subscription = null, credits = null, catalog = null, confirmAnswer = true } = {}) {
  const dom = makeDom();
  const requests = [];
  const toasts = [];
  const confirms = [];
  const fetchImpl = async (url, options = {}) => {
    const method = String(options.method || 'GET').toUpperCase();
    let body;
    try { body = options.body ? JSON.parse(options.body) : undefined; } catch (e) { body = options.body; }
    requests.push({ url, method, body });
    const key = `${method} ${String(url).replace(/^\/api\/enterprise/, '').split('?')[0]}`;
    const handler = routes[key];
    if (!handler) return jsonResponse({ detail: 'not stubbed' }, 404);
    return typeof handler === 'function' ? handler({ url, method, body }) : jsonResponse(handler);
  };
  const document = {
    getElementById: (id) => dom.get(id),
    querySelector: (sel) => dom.query(sel),
    querySelectorAll: (sel) => dom.queryAll(sel, null),
    createElement: () => dom.element(),
    addEventListener() {}, removeEventListener() {},
    body: Object.assign(dom.element('body'), { appendChild() {} }),
    documentElement: dom.element('html'),
    activeElement: null, fullscreenElement: null,
  };
  const storage = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) }; };
  const location = { pathname: '/enterprise', search: '', hash: '', origin: 'http://acme.lvh.me', href: 'http://acme.lvh.me/enterprise', hostname: 'acme.lvh.me', host: 'acme.lvh.me', protocol: 'http:', assign() {}, reload() {} };
  const window = {
    addEventListener() {}, removeEventListener() {}, scrollTo() {}, innerWidth: 1280, innerHeight: 800,
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {} }),
    location, setTimeout, clearTimeout,
  };
  const context = vm.createContext({
    document, window, location, navigator: { platform: 'node', userAgent: 'node', clipboard: { writeText: async () => {} } },
    history: { replaceState() {}, pushState() {} }, localStorage: storage(), sessionStorage: storage(),
    fetch: fetchImpl, URL, URLSearchParams, AbortController, FormData: class FormData { append() {} },
    setTimeout: (fn, ms) => setTimeout(fn, Math.min(Number(ms) || 0, 0)), clearTimeout, setInterval: () => 0, clearInterval() {},
    console: { error() {}, warn() {}, log() {} }, __ENT_SKIP_INIT__: true,
  });
  vm.runInContext(patched, context);
  const app = context.__entTest;
  // Toasts and confirmations are observable instead of DOM-only.
  dom.get('toast');
  app.toasts = toasts;
  app.state.me = { user: { id: 1, email: 'owner@acme.test' }, organization: { company_name: 'Acme' } };
  app.state.caps = caps.includes('*') ? null : new Set(caps);
  app.state.access = { is_owner: caps.includes('*'), data_scope: 'org' };
  app.state.subscription = subscription;
  app.state.credits = credits;
  app.state.catalog = catalog || CATALOG;
  return { ...app, dom, requests, toasts, confirms, context };
}

const STAGES = [
  { key: 'new_lead', label: 'New Lead', order: 1, color: '#64748b', is_open: true, is_terminal: false },
  { key: 'documents', label: 'Documents', order: 5, color: '#6366f1', is_open: true, is_terminal: false },
  { key: 'decision', label: 'Decision', order: 8, color: '#f59e0b', is_open: true, is_terminal: false },
  { key: 'approved', label: 'Approved', order: 9, color: '#10b981', is_open: false, is_terminal: true },
  { key: 'rejected', label: 'Rejected', order: 10, color: '#ef4444', is_open: false, is_terminal: true },
  { key: 'closed', label: 'Closed', order: 11, color: '#6b7280', is_open: false, is_terminal: true,
    description: "File closed without a visa outcome — doesn't count toward your plan's open files." },
  { key: 'on_hold', label: 'On Hold', order: 12, color: '#9ca3af', is_open: false, is_terminal: false },
];
const CATALOG = { countries: [], categories: [], stages: STAGES, stages_by_country: {}, priorities: [], document_types: [] };

// Shapes mirror app/enterprise_billing.build_subscription_state via _serialize_subscription_state.
function sub(overrides = {}) {
  return {
    plan: 'starter', plan_label: 'Starter', status: 'active', is_trial: false, is_sandbox: false,
    trial_expired: false, trial_days_left: null, trial_ends_at: null, current_period_end: '2026-11-21T10:00:00',
    max_clients: 40, max_seats: 5, clients_used: 12, seats_used: 2, can_add_client: true, can_add_seat: true,
    grandfathered: false, plan_lapsed: false, auto_renews: false, currency: 'INR',
    monthly_minor: 149900, monthly_display: '₹1,499', tax_label: 'GST', tax_percent: 18,
    total_minor: 176882, total_display: '₹1,768.82', price_note: '+ GST', billing_cycle: 'monthly',
    open_files_used: 12, max_open_files: 40, clients_total: 20, files_over_limit: false,
    files_over_limit_since: null, files_grace_ends_at: null, files_in_grace: false, files_grace_days: 14,
    monthly_reads: 150, reads: { granted: 150, used: 30, remaining: 120, period_ends_at: '2026-11-21T10:00:00', monthly_allowance: 150, unlimited: false },
    features: { branches: false, custom_roles: false, branch_reporting: false }, features_tier: 'starter',
    ai_paused: false, ai_paused_reason: null, ai_paused_message: null,
    yearly_enabled: false, yearly_minor: 1499000, yearly_display: '₹14,990',
    inr_region: true, show_usd_estimate: false, usd_estimate: null, included_credits: 150, credits_recur: true,
    ...overrides,
  };
}

// Shapes mirror app/enterprise_billing.public_plans_payload.
function card(key, overrides = {}) {
  const base = {
    sandbox: { label: '14-day free trial', monthly: 0, seats: 3, files: 15, credits: 50, reads: 50, recur: false },
    starter: { label: 'Starter', monthly: 149900, seats: 5, files: 40, credits: 150, reads: 150, recur: true },
    growth: { label: 'Team', monthly: 399900, seats: 25, files: 150, credits: 450, reads: 500, recur: true, popular: true },
    scale: { label: 'Multi-branch', monthly: 999900, seats: 50, files: 500, credits: 1200, reads: 1000, recur: true },
  }[key];
  const inr = (minor) => `₹${(minor / 100).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
  const tax = Math.round(base.monthly * 0.18);
  return {
    key, label: base.label, tagline: `${base.label} tagline`, currency: 'INR', is_free: base.monthly === 0,
    monthly_paise: base.monthly, monthly_minor: base.monthly, monthly_display: inr(base.monthly),
    tax_label: base.monthly ? 'GST' : null, tax_percent: base.monthly ? 18 : 0, tax_minor: base.monthly ? tax : 0,
    total_minor: base.monthly + (base.monthly ? tax : 0), total_display: inr(base.monthly + (base.monthly ? tax : 0)),
    price_note: base.monthly ? '+ GST' : 'Free for 14 days',
    yearly_enabled: false, yearly_minor: base.monthly * 10, yearly_display: base.monthly ? inr(base.monthly * 10) : null,
    yearly_total_minor: base.monthly ? base.monthly * 10 + tax * 10 : 0, yearly_total_display: base.monthly ? inr(base.monthly * 10 + tax * 10) : null,
    yearly_months_free: base.monthly ? 2 : 0,
    max_clients: base.files, max_open_files: base.files, files_note: "Approved, Rejected, Closed and On Hold files don't count.",
    max_seats: base.seats, included_credits: base.credits, credits_recur: base.recur, max_reads: base.reads, monthly_reads: base.reads,
    is_popular: !!base.popular, features: [`${base.seats} staff seats`, `${base.files} open student files`],
    price_options: base.monthly ? [
      { currency: 'INR', amount_minor: base.monthly, display: inr(base.monthly) },
      { currency: 'USD', amount_minor: { starter: 3900, growth: 8900, scale: 19500 }[key], display: `$${{ starter: 39, growth: 89, scale: 195 }[key]}` },
    ] : [],
    usd_estimate: null,
    ...overrides,
  };
}
const PLANS = () => ['sandbox', 'starter', 'growth', 'scale'].map((k) => card(k));
function billingPayload(overrides = {}) {
  return {
    plans: PLANS(), currency: 'INR', charge_currencies: ['INR'], gst_percent: 18,
    tax: { percent: 18, label: 'GST', note: '+ GST' }, yearly_enabled: false, subscription: sub(),
    ...overrides,
  };
}

// Shapes mirror app/enterprise_credits.actions_payload / wallet_state.
const ACTIONS = [
  { key: 'document_scan', label: 'Document check', credits: 4, price_inr: 40, unit: 'block', unit_label: 'per 15 pages', price_label: '4 credits per 15 pages', pages_per_unit: 15 },
  { key: 'deep_scan', label: 'Deep Scan', credits: 40, price_inr: 400, unit: 'scan', unit_label: 'per scan', price_label: '40 credits per scan', max_documents: 20 },
  { key: 'mock_interview', label: 'Mock interview', credits: 20, price_inr: 200, unit: 'session', unit_label: 'per interview', price_label: '20 credits per interview', max_questions: 12 },
  { key: 'ai_copilot', label: 'AI assistant', credits: 1, price_inr: 10, unit: 'bundle', unit_label: 'per 2 messages', price_label: '1 credit per 2 messages', messages_per_unit: 2 },
  { key: 'copilot_client', label: 'Client copilot', credits: 30, price_inr: 300, unit: 'client', unit_label: 'per client link', price_label: '30 credits per client link', messages_included: 5, valid_days: 30 },
  { key: 'writing_studio', label: 'SOP / LOR draft', credits: 5, price_inr: 50, unit: 'draft', unit_label: 'per draft or refinement', price_label: '5 credits per draft or refinement' },
];
function wallet(overrides = {}) {
  return {
    balance_credits: 120, balance_value_inr: 1200, credit_value_inr: 10, currency: 'INR', enforced: true,
    low_balance: false, low_balance_threshold: 40, ai_paused: false, ai_paused_reason: null, ai_paused_message: null,
    lifetime_purchased_credits: 0, lifetime_spent_credits: 30, actions: ACTIONS,
    reads: { granted: 150, used: 30, remaining: 120, period_ends_at: '2026-11-21T10:00:00', monthly_allowance: 150, recurring: true, unlimited: false, pages_per_read: 15 },
    plan_credits: { plan_label: 'Starter', included_credits: 150, remaining_this_period: 100, recurring: true, renews_at: '2026-11-21T10:00:00' },
    staff_interview_previews: { free: 2, remaining: 0 },
    free_tier: { deep_scans_per_client: 0, deep_scans_monthly_cap: 0, interview_previews: 2, interview_previews_left: 0, copilot_msgs_daily: 5, copilot_msgs_left_today: 5, copilot_msgs_per_credit: 2, reads_allowance: 150, reads_left: 120, pages_per_read: 15 },
    ...overrides,
  };
}
const PACKAGES = [{ key: 'pack_100', label: 'Starter pack', tagline: '', amount_paise: 99900, amount_display: '₹999', currency: 'INR', credits: 100, bonus_credits: 0, total_credits: 100, value_inr: 1000, is_popular: false,
  price_options: [{ currency: 'INR', amount_minor: 99900, display: '₹999' }, { currency: 'USD', amount_minor: 1299, display: '$12.99' }] }];

const content = (app) => app.dom.get('content').innerHTML;
// The portal formats dates in the reader's locale (fmtDate); expect exactly that.
const day = (iso) => new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });

// ---------------------------------------------------------------------------
// Plans & Billing
// ---------------------------------------------------------------------------

test('plan cards render the server labels, open files, seats, credits, reads and its price_note', async () => {
  const app = setup({ caps: ['*'], routes: { 'GET /billing/subscription': billingPayload() } });
  await app.renderBilling();
  const html = content(app);
  for (const label of ['Starter', 'Team', 'Multi-branch', '14-day free trial']) assert.ok(html.includes(label), label);
  assert.ok(html.includes('open files') && html.includes('staff seats') && html.includes('AI document reads'));
  assert.ok(html.includes('Approved, Rejected, Closed and On Hold files don&#39;t count.'), 'files_note from the server (escaped)');
  assert.ok(html.includes('+ GST · ₹4,718.82/mo charged'), 'Team card: server price_note + server total');
  assert.ok(html.includes('Prices are in INR, per month, exclusive of GST.'));
  assert.ok(!html.includes('active clients'), 'old "active clients" wording is gone');
  // The current-plan line uses the subscription's own price_note.
  assert.ok(html.includes('₹1,499/mo + GST'));
});

test('GST at 0% stays 0: no "+ GST", no tax line, no "exclusive of GST" anywhere on Plans & Billing', async () => {
  const zero = (c) => ({ ...c, tax_label: null, tax_percent: 0, tax_minor: 0, total_minor: c.monthly_minor, total_display: c.monthly_display, price_note: c.is_free ? c.price_note : '' });
  const payload = billingPayload({
    plans: PLANS().map(zero), gst_percent: 0, tax: { percent: 0, label: null, note: '' },
    subscription: sub({ tax_label: null, tax_percent: 0, price_note: '', total_display: '₹1,499' }),
  });
  const app = setup({ routes: { 'GET /billing/subscription': payload } });
  await app.renderBilling();
  const html = content(app);
  assert.ok(!/GST/.test(html), 'no GST copy at a 0% rate');
  assert.ok(!html.includes('charged</div>'), 'no tax/charged line');
  assert.equal(app.state.billingGstPercent, 0, 'the old `|| 18` fallback must not turn 0 into 18');
  assert.ok(html.includes('Prices are in INR, per month.'));
});

test('the yearly toggle exists only while the server sells yearly, and checkout sends the cycle it showed', async () => {
  const off = setup({ routes: { 'GET /billing/subscription': billingPayload() } });
  await off.renderBilling();
  assert.ok(!content(off).includes('cycle-toggle'), 'no toggle while yearly_enabled is false');
  off.state.billingCycle = 'yearly';               // a stale choice must never leak into a request
  await off.renderBilling();
  let sent;
  off.context.Razorpay = undefined;
  const offRoutes = off.requests;
  await off.checkout('growth', null);
  sent = offRoutes.find((r) => r.url.endsWith('/billing/checkout'));
  assert.equal(sent.body.billing_cycle, 'monthly');

  const yearlyPlans = PLANS().map((c) => ({ ...c, yearly_enabled: true }));
  const on = setup({ routes: {
    'GET /billing/subscription': billingPayload({ yearly_enabled: true, plans: yearlyPlans }),
    'POST /billing/checkout': ({ body }) => jsonResponse({ action: 'contact_sales', message: 'x', echo: body }),
  } });
  await on.renderBilling();
  assert.ok(content(on).includes('cycle-toggle') && content(on).includes('2 months free'));
  on.state.billingCycle = 'yearly';
  await on.renderBilling();
  const html = content(on);
  assert.ok(html.includes('₹39,990<small>/yr</small>'), 'Team yearly list price from the card');
  assert.ok(html.includes("doesn't renew automatically"));
  await on.checkout('growth', null);
  sent = on.requests.find((r) => r.url.endsWith('/billing/checkout'));
  assert.equal(sent.body.billing_cycle, 'yearly');
});

test('the currency picker offers only charge_currencies (region rule) and the USD estimate shows for INR-region orgs', async () => {
  // INR region: the ladder carries USD, but the org can only be charged INR → no picker at all.
  const inr = setup({ routes: { 'GET /billing/subscription': billingPayload() } });
  await inr.renderBilling();
  assert.ok(!content(inr).includes('billingCurrencySel'));
  // Unknown country: both are chargeable → picker with both.
  const both = setup({ routes: { 'GET /billing/subscription': billingPayload({ charge_currencies: ['INR', 'USD'] }) } });
  await both.renderBilling();
  assert.ok(content(both).includes('billingCurrencySel') && content(both).includes('USD · from $39/mo'));
  // Nepal org: INR cards carry a US$ estimate of the charged total.
  const est = (c) => (c.is_free ? c : { ...c, usd_estimate: { currency: 'USD', monthly_minor: 5700, monthly_display: '≈ US$57' } });
  const np = setup({ routes: { 'GET /billing/subscription': billingPayload({ plans: PLANS().map(est), subscription: sub({ show_usd_estimate: true, usd_estimate: { monthly_display: '≈ US$21' } }) }) } });
  await np.renderBilling();
  assert.ok(content(np).includes('≈ US$57/mo · charged in INR'));
  assert.ok(content(np).includes('(≈ US$21)'));
});

test('usage panel: open files with the grace deadline, team seats and the reads allowance', async () => {
  const s = sub({ files_over_limit: true, files_in_grace: true, files_over_limit_since: '2026-10-20T00:00:00', files_grace_ends_at: '2026-11-03T00:00:00', open_files_used: 42, clients_used: 42 });
  const app = setup({ routes: { 'GET /billing/subscription': billingPayload({ subscription: s }) } });
  await app.renderBilling();
  const html = content(app);
  assert.ok(html.includes('Open files</span><b>42 / 40'));
  assert.ok(html.includes(`you can keep adding until ${day('2026-11-03T00:00:00')}`));
  assert.ok(html.includes('AI document reads</span><b>30 / 150'));
  assert.ok(html.includes('120 left'));
});

// ---------------------------------------------------------------------------
// Banners
// ---------------------------------------------------------------------------

test('the banner quotes the server for AI paused, open-file grace (in grace / ended) and never a hardcoded price', () => {
  const app = setup({});
  app.state.subscription = sub({ is_sandbox: true, trial_expired: true, ai_paused: true, ai_paused_reason: 'trial_expired',
    ai_paused_message: 'Your free trial has ended — AI features are paused. Choose a plan to turn them back on. Everything in your workspace is still here.',
    can_add_client: false, can_add_seat: false });
  let html = app.trialBanner();
  assert.ok(html.includes('Your free trial has ended — AI features are paused.'));
  assert.ok(html.includes('Adding new files and teammates is paused too.'));
  assert.ok(html.includes('Choose a plan'));

  app.state.subscription = sub({ files_over_limit: true, files_in_grace: true, files_over_limit_since: '2026-10-20', files_grace_ends_at: '2026-11-03T00:00:00', open_files_used: 41 });
  html = app.trialBanner();
  assert.ok(/over your plan's 40 open files/.test(html) && html.includes(day('2026-11-03T00:00:00')));
  assert.ok(html.includes("Approved, Rejected, Closed and On Hold files don't count."), 'labels from the catalog flags');

  app.state.subscription = sub({ files_over_limit: true, files_in_grace: false, files_over_limit_since: '2026-10-01', files_grace_ends_at: '2026-10-15T00:00:00', can_add_client: false, open_files_used: 45 });
  html = app.trialBanner();
  assert.ok(html.includes('Adding files is paused.') && html.includes('trial-banner-danger'));

  // Trial countdown without loaded plan cards: no price at all (and no ₹2,999 / 1,000 credits).
  app.state.subscription = sub({ is_sandbox: true, trial_days_left: 3, plan: 'sandbox' });
  app.state.billingPlans = null;
  html = app.trialBanner();
  assert.ok(html.includes('3 days left in your free trial.'));
  assert.ok(!/₹|1,000|2,999|GST/.test(html));
  // …and with them, the cheapest paid card + its own price_note.
  app.state.billingPlans = PLANS();
  html = app.trialBanner();
  assert.ok(html.includes('Plans start at ₹1,499/month + GST and include 150 AI credits a month.'));
});

test('a member without billing.manage gets the fact and who can act, never a button into a denied page', () => {
  const app = setup({ caps: ['clients.view'] });
  app.state.subscription = sub({ ai_paused: true, ai_paused_message: 'Your Team plan has expired — AI features are paused. Renew to turn them back on. Everything in your workspace is still here.', plan_lapsed: true, max_seats: 3, max_open_files: 15 });
  const html = app.trialBanner();
  assert.ok(html.includes('Ask a workspace admin to choose a plan.'));
  assert.ok(!html.includes("__ent.go('billing')"));
  assert.ok(html.includes('Until you renew, your limits are 3 seats and 15 open files.'));
});

// ---------------------------------------------------------------------------
// Credits
// ---------------------------------------------------------------------------

test('wallet: per-unit price_label rows, server low-balance threshold, reads, and no First-Deep-Scan-free copy at 0', async () => {
  const w = wallet({ low_balance: true, balance_credits: 12 });
  const app = setup({ routes: { 'GET /credits/wallet': { wallet: w, usage: {}, packages: PACKAGES, charge_currencies: ['INR'], topup_allowed: true } } });
  app.state.view = 'credits';
  await app.renderCredits();
  const html = content(app) + app.dom.get('crPanel').innerHTML;
  assert.ok(html.includes('4 credits per 15 pages') && html.includes('1 credit per 2 messages') && html.includes('30 credits per client link'));
  assert.ok(html.includes('under 40 credits'), 'threshold from the server');
  assert.ok(html.includes('120</b> of 150 AI document reads left'));
  assert.ok(!html.includes('First Deep Scan'), 'deep_scans_per_client = 0 → no free-scan promise');
  assert.ok(!/first Deep Scan on each client/.test(html));
  assert.ok(!html.includes('1,000 / 3,500 / 10,000'));
});

test('top-ups while AI is paused: disabled with the server message, and a 402 at checkout repaints the wallet', async () => {
  const paused = 'Your free trial has ended — AI features are paused. Choose a plan to turn them back on. Everything in your workspace is still here.';
  const w = wallet({ ai_paused: true, ai_paused_reason: 'trial_expired', ai_paused_message: paused });
  const app = setup({ routes: { 'GET /credits/wallet': { wallet: w, usage: {}, packages: PACKAGES, charge_currencies: ['INR'], topup_allowed: false } } });
  app.state.view = 'credits';
  await app.renderCredits();
  const html = content(app) + app.dom.get('crPanel').innerHTML;
  assert.ok(html.includes(paused));
  assert.ok(!html.includes("__ent.topup('pack_100')"), 'no live Buy button while paused');
  app.openCreditCheckout('pack_100');
  assert.ok(!app.requests.some((r) => r.url.includes('/credits/topup/checkout')), 'the modal never opens');
});

// ---------------------------------------------------------------------------
// Documents, interviews (client page)
// ---------------------------------------------------------------------------

function clientData(docs) {
  return {
    client: {
      id: 7, full_name: 'Asha Rao', email: 'asha@example.test', status: 'documents', version: 1,
      destination_country_code: 'UK', destination_country_name: 'United Kingdom', visa_type: 'Student',
      country: { code: 'UK', gradient_from: '#000', gradient_to: '#111', flag_emoji: '🇬🇧' }, stage: STAGES[1],
    },
    notes: [], emails: [], documents: docs,
  };
}

test('documents: read badges, Read now posts to /read, and its 402 detail is shown word for word', async () => {
  const docs = [
    { id: 11, original_filename: 'passport.pdf', document_type: 'Passport', read_status: 'not_read', can_read_now: true, download_url: '#' },
    { id: 12, original_filename: 'bank.pdf', document_type: 'Bank statement', read_status: 'pending', can_read_now: false, download_url: '#' },
    { id: 13, original_filename: 'offer.pdf', document_type: 'Offer', read_status: 'failed', can_read_now: true, download_url: '#' },
  ];
  const detail = "You've used this month's 150 AI document reads. They refresh on 21 Nov 2026, or run a paid document check (4 credits per 15 pages).";
  const app = setup({ credits: wallet(), routes: {
    'GET /clients/7/documents': { documents: docs, scan_pricing: { cost_credits: 4, price_label: '4 credits per 15 pages', can_afford: true, ai_available: true }, reads: wallet().reads },
    'POST /clients/7/documents/11/read': () => jsonResponse({ detail }, 402),
  } });
  assert.deepEqual(plain(app.docReadBadge('not_read')), { cls: 'muted', txt: 'Not read yet' });
  assert.deepEqual(plain(app.docReadBadge('pending')), { cls: 'pending', txt: 'Reading…' });
  assert.deepEqual(plain(app.docReadBadge('failed')), { cls: 'warn', txt: 'Read failed' });
  assert.equal(app.docReadBadge('read'), null);
  assert.equal(app.docReadBadge(null), null);

  app.state.activeClient = 7;
  app.renderClientPage(clientData(docs));
  // Open the Documents tab through its own handler.
  const tabs = app.dom.queryAll('.cp-tab', app.dom.get('content'));
  const docTab = tabs.find((t) => t.dataset.tab === 'documents');
  assert.ok(docTab, 'documents tab rendered');
  await docTab.onclick({ preventDefault() {} });
  await settle();
  // The stub DOM has no `.cp-tab.active`, so repaint the tab once the list has loaded.
  await docTab.onclick({ preventDefault() {} });
  let html = app.dom.get('cpBody').innerHTML;
  assert.ok(html.includes('Not read yet') && html.includes('Reading…') && html.includes('Read failed'));
  assert.ok(html.includes('Scan &amp; validate with Rilono AI · 4 credits per 15 pages'), 'scan priced with price_label');
  assert.ok(html.includes('120 AI document reads left'));
  const readBtns = app.dom.queryAll('.doc-read-now', app.dom.get('cpBody'));
  assert.equal(readBtns.length, 2, 'Read now only where can_read_now');
  await readBtns.find((b) => b.dataset.id === '11').onclick();
  await settle();
  assert.ok(app.requests.some((r) => r.method === 'POST' && r.url.endsWith('/clients/7/documents/11/read')));
  html = app.dom.get('cpBody').innerHTML;
  assert.ok(html.includes(detail.replace(/'/g, '&#39;')), '402 detail shown verbatim on the card');
});

test('staff mock interview: server session — start keeps session_id, turns send {message, session_id} only, 409 → report', async () => {
  const turns = [];
  const app = setup({ credits: wallet(), routes: {
    'GET /clients/7/interview/sessions': { sessions: [] },
    'GET /clients/7/interview/invite': { invite: null },
    'POST /clients/7/interview/chat': ({ body }) => {
      turns.push(body);
      if (body.start) return jsonResponse({ reply: 'Why the UK?', finished: false, session_id: 55, questions_asked: 1, max_questions: 12, credits_charged: 20, was_preview: false });
      if (turns.length === 2) return jsonResponse({ reply: 'And funding?', finished: false, session_id: 55, questions_asked: 2, max_questions: 12 });
      return jsonResponse({ detail: 'The officer has already ended this interview — generate the feedback report.' }, 409);
    },
    'POST /clients/7/interview/feedback': ({ body }) => jsonResponse({ feedback: '**Verdict:** Likely approved', verdict: 'Likely approved', session: { id: 55, status: 'completed' }, echo: body }),
  } });
  app.state.activeClient = 7;
  app.renderClientPage(clientData([]));
  const tabs = app.dom.queryAll('.cp-tab', app.dom.get('content'));
  await tabs.find((t) => t.dataset.tab === 'interview').onclick({ preventDefault() {} });
  await settle();
  await app.dom.get('ivStartBtn').onclick();
  await settle();
  assert.deepEqual(plain(turns[0]), { start: true, mode: 'chat' });
  assert.ok(app.dom.get('ivWrap').innerHTML.includes('1 of 12 questions'));

  app.dom.get('ivInput').value = 'To study AI.';
  await app.dom.get('ivSend').onclick();
  await settle();
  assert.deepEqual(plain(turns[1]), { message: 'To study AI.', session_id: 55, mode: 'chat' });
  assert.ok(!('history' in turns[1]), 'the browser transcript is never sent');

  app.dom.get('ivInput').value = 'My parents.';
  await app.dom.get('ivSend').onclick();
  await settle();
  const fb = app.requests.find((r) => r.url.endsWith('/interview/feedback'));
  assert.ok(fb, '409 on a turn asks for the session report');
  assert.deepEqual(plain(fb.body), { session_id: 55, mode: 'chat' });
  assert.ok(app.dom.get('ivWrap').innerHTML.includes('Interview feedback'));
});

// ---------------------------------------------------------------------------
// Team plan gates, Closed stage
// ---------------------------------------------------------------------------

function teamMeta(features) {
  return {
    role_presets: [{ key: 'admin', label: 'Admin', capabilities: ['clients.view'], data_scope: 'org' }],
    custom_roles: [{ id: 3, name: 'Senior counsellor', capabilities: ['clients.view'], data_scope: 'org', is_active: true }],
    branches: [
      { id: 1, name: 'Head office', is_default: true, is_active: true, member_count: 2, client_count: 9 },
      { id: 2, name: 'Pune', is_default: false, is_active: true, member_count: 1, client_count: 4 },
    ],
    limits: { max_custom_roles: 20, max_branches: 50 }, capabilities: [], scopes: [],
    plan_features: features,
    plan_upgrade_messages: {
      branches: 'Adding or editing offices is part of the Team plan. Upgrade to Team to manage offices — your existing offices and their clients keep working.',
      custom_roles: 'Custom roles are part of the Team plan. Upgrade to Team to create or edit roles — everyone keeps the access they have today.',
      branch_reporting: 'Per-branch reporting is part of the Team plan. Upgrade to Team to filter and report by office.',
    },
  };
}

test('Starter: role and office editors step aside with the server upgrade message; reads stay', () => {
  const app = setup({ caps: ['*'] });
  app.teamUi.meta = teamMeta({ branches: false, custom_roles: false, branch_reporting: false });
  app.teamUi.tab = 'roles';
  app.tmDrawRoles();
  let html = app.dom.get('tmPanel').innerHTML;
  assert.ok(html.includes('Custom roles are part of the Team plan.'));
  assert.ok(!html.includes('id="rlCreate"') && !html.includes('data-rledit') && !html.includes('data-rlduppreset'));
  assert.ok(html.includes('Senior counsellor') && html.includes('View permissions'), 'existing roles still listed');

  app.tmPaintBranches();
  html = app.dom.get('tmPanel').innerHTML;
  assert.ok(html.includes('Adding or editing offices is part of the Team plan.'));
  assert.ok(!html.includes('id="brCreate"'), 'no second office on Starter');
  assert.ok(html.includes('data-bract="edit" data-bid="1"'), 'the default office stays editable');
  assert.ok(!html.includes('data-bract="edit" data-bid="2"') && !html.includes('data-bract="archive"'));
  assert.ok(html.includes('data-bract="assign"'), 'assigning people is a use, not an edit');
  assert.ok(!html.includes('data-drill="clients"'), 'no per-office client report without branch_reporting');

  app.state.branches = [{ id: 1, name: 'Head office' }, { id: 2, name: 'Pune' }];
  app.state.subscription = sub();
  assert.equal(app.branchFilterHtml('x'), '', 'no office filter without branch_reporting');

  app.teamUi.meta = teamMeta({ branches: true, custom_roles: true, branch_reporting: true });
  app.tmDrawRoles();
  assert.ok(app.dom.get('tmPanel').innerHTML.includes('id="rlCreate"'));
  app.state.subscription = sub({ features: { branches: true, custom_roles: true, branch_reporting: true } });
  assert.ok(app.branchFilterHtml('x').includes('All offices'));
});

test('reopening past the limit: the 402 is shown in full with a way to the plans', async () => {
  const msg = "Your Starter plan covers 40 open files and you have 40. Your 14-day grace period for going over has ended. Close files you've finished (Approved, Rejected, Closed and On Hold files don't count) or upgrade to add more.";
  const app = setup({ caps: ['*'], routes: { 'PATCH /clients/7/status': () => jsonResponse({ detail: msg }, 402) } });
  await app.setStatus(7, 'documents', 'closed');
  await settle();
  const modal = app.dom.get('modal').innerHTML;
  assert.ok(modal.includes(msg.replace(/'/g, '&#39;')));
  assert.ok(modal.includes('See plans'));
});

test('Closed comes from the catalog: off the journey track like Rejected, never after Approved', () => {
  const app = setup({ caps: ['*'] });
  app.state.activeClient = 7;
  const data = clientData([]);
  data.client.status = 'closed';
  data.client.stage = STAGES[5];
  app.renderClientPage(data);
  const html = app.dom.get('cpBody').innerHTML + app.dom.get('content').innerHTML;
  const track = /<div class="jtrack[^"]*">([\s\S]*?)<\/div>\s*<div class="jtrack-alt">/.exec(html);
  assert.ok(track, 'journey tracker rendered');
  assert.ok(!track[1].includes('>Closed<'), 'Closed is not a node on the track');
  assert.ok(/jtrack-alt-pill jtrack-alt-closed active/.test(html), 'Closed is an off-track pill, marked current');
  assert.equal(app.notOpenStageLabels(), 'Approved, Rejected, Closed and On Hold');
});

// ---------------------------------------------------------------------------
// Assistant + helpers
// ---------------------------------------------------------------------------

test('assistant: AI paused locks the composer with the server message; a plan bought unlocks it', () => {
  const app = setup({});
  const ta = app.dom.element('t');
  app.context.document.querySelectorAll = (sel) => (sel === '[data-ai-input]' ? [ta] : []);
  app.state.aiMeta = { enabled: true, suggestions: ['x'], ai_paused: true, ai_paused_message: 'Your free trial has ended — AI features are paused.' };
  app.applyAiMeta();
  assert.equal(ta.disabled, true);
  assert.ok(/paused/i.test(ta.placeholder));
  app.state.subscription = sub({ ai_paused: false });
  app.updatePlanChip();
  assert.equal(app.state.aiMeta.ai_paused, false);
  assert.equal(ta.disabled, false);
});

test('price helpers read the server and never invent a default', () => {
  const app = setup({ credits: wallet() });
  assert.equal(app.priceLabelFor('deep_scan'), '40 credits per scan');
  assert.equal(app.priceLabelFor('deep_scan', { price_label: 'promo label' }), 'promo label');
  assert.equal(app.creditCostFor('writing_studio'), 5);
  assert.equal(app.creditCostFor('copilot_client', { cost_credits: 0 }), 0, '0 is a real price (free unlock)');
  app.state.credits = null;
  assert.equal(app.creditCostFor('deep_scan'), null, 'no payload → unquoted, not 20');
  assert.equal(app.priceLabelFor('deep_scan'), '');
  assert.equal(app.isAiPausedError({ status: 402, message: 'Your free trial has ended — AI features are paused. Choose a plan…' }), true);
  assert.equal(app.isAiPausedError({ status: 402, message: 'Not enough Rilono Credits.' }), false);
  app.state.billingPlans = PLANS();
  assert.equal(app.planAllowanceSummary(), 'Starter, Team and Multi-branch include 150 / 450 / 1,200 AI credits every month.');
});
