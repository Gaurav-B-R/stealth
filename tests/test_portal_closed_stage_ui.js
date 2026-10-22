// The client portal (static/portal.html) with the Closed stage (pricing v2, 2026-10-22): Closed
// arrives in the server's stage list as a terminal, not-open stage. It must sit OFF the journey
// track like Rejected (never as a node after Approved), and a closed file gets its own banner —
// not the refusal one.
//
// The page's inline <script> runs in a vm with stub elements keyed by id (no real DOM).

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/portal.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
const source = scripts[scripts.length - 1];
assert.ok(source && source.includes('/api/enterprise/public/portal'), 'portal script not found');

const TOKEN = 'portal-token-1';
const API = '/api/enterprise/public/portal';
const jsonResponse = (payload, status = 200) => ({ ok: status < 400, status, json: async () => payload });
const settle = async () => { for (let i = 0; i < 8; i += 1) await new Promise((r) => setImmediate(r)); };

const STAGES = [
  { key: 'new_lead', label: 'New Lead', order: 1, color: '#64748b', is_open: true, is_terminal: false },
  { key: 'decision', label: 'Decision', order: 8, color: '#f59e0b', is_open: true, is_terminal: false },
  { key: 'approved', label: 'Approved', order: 9, color: '#10b981', is_open: false, is_terminal: true },
  { key: 'rejected', label: 'Rejected', order: 10, color: '#ef4444', is_open: false, is_terminal: true },
  { key: 'closed', label: 'Closed', order: 11, color: '#6b7280', is_open: false, is_terminal: true },
  { key: 'on_hold', label: 'On Hold', order: 12, color: '#9ca3af', is_open: false, is_terminal: false },
];

function element(id) {
  let markup = '';
  let text = '';
  const names = new Set();
  return {
    id, value: '', disabled: false, style: {},
    classList: { add: (n) => names.add(n), remove: (n) => names.delete(n), toggle(n, f) { if (f === undefined ? !names.has(n) : f) names.add(n); else names.delete(n); }, contains: (n) => names.has(n) },
    get innerHTML() { return markup; }, set innerHTML(v) { markup = String(v); },
    get textContent() { return text; }, set textContent(v) { text = String(v); },
    addEventListener() {}, querySelectorAll() { return []; }, focus() {},
  };
}

async function renderFor(stages, status) {
  const els = new Map();
  const get = (id) => { if (!els.has(id)) els.set(id, element(id)); return els.get(id); };
  const fetch = async (url, options = {}) => {
    if (url === `${API}/${TOKEN}`) return jsonResponse({ organization_name: 'Acme', client_first_name: 'Asha' });
    if (url === `${API}/${TOKEN}/verify`) return jsonResponse({ session_token: 'sess' });
    if (url === `${API}/data`) {
      return jsonResponse({
        status, stage: stages.find((s) => s.key === status), stages, stages_skipped: [], stage_records: {},
        client: { full_name: 'Asha Rao', destination_country_code: 'UK' }, organization: { name: 'Acme' },
        documents: [], universities: [], payments: [],
      });
    }
    return jsonResponse({}, 404);
  };
  const store = new Map();
  const context = vm.createContext({
    document: { getElementById: get }, location: { pathname: `/portal/${TOKEN}` }, fetch, console,
    sessionStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, v), removeItem: (k) => store.delete(k) },
  });
  vm.runInContext(source, context);
  await settle();
  get('codeInput').value = '123456';
  const verify = get('verifyBtn');
  verify.onclick.call(verify);
  await settle();
  return get('portalView').innerHTML;
}

test('a closed file: Closed is off the journey track and gets its own banner, not the refusal one', async () => {
  const view = await renderFor(STAGES, 'closed');
  const track = /<div class="jt">([\s\S]*?)<\/div><div class="p-banner/.exec(view);
  assert.ok(track, 'journey track with a banner rendered');
  assert.ok(!/jt-label">Closed</.test(track[1]), 'Closed is not a node on the track');
  assert.ok(/jt-label">Approved</.test(track[1]));
  assert.ok(view.includes('Your consultancy has closed this file.'));
  assert.ok(!view.includes('This application was refused.'));
});

test('a payload without the stage flags still keeps Closed off the track', async () => {
  const bare = STAGES.map(({ is_open, is_terminal, ...rest }) => rest);
  const view = await renderFor(bare, 'closed');
  assert.ok(!/jt-label">Closed</.test(view.split('p-banner')[0]));
  assert.ok(view.includes('Your consultancy has closed this file.'));
});

test('a refused file still reads as refused', async () => {
  const view = await renderFor(STAGES, 'rejected');
  assert.ok(view.includes('This application was refused.'));
  assert.ok(!view.includes('closed this file'));
});
