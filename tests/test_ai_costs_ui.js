const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/admin_console.js'), 'utf8');

function stats(overrides = {}) {
    return { calls: 3, input_tokens: 1212, output_tokens: 310, thinking_tokens: 150,
        cached_tokens: 200, tool_tokens: 11, total_tokens: 1683, tts_characters: 400,
        estimated_cost_usd: 0.125, unknown_calls: 0, unpriced_calls: 0, legacy_calls: 0,
        first_event_at: '2026-07-01T00:00:00', last_event_at: '2026-09-01T00:00:00', ...overrides };
}

function profilePayload(name = 'Student') {
    return { range: { start: '2026-09-01', end: '2026-09-06' }, page: 1, page_size: 25, total: 30,
        profiles: [{ user_id: 9, name, email: 'student@example.test', range: stats(), lifetime: stats({ total_tokens: 9876543, calls: 60 }) }],
        coverage: { first_recorded_at: '2026-07-01T00:00:00', measured_calls: 3, legacy_calls: 1, unknown_calls: 2,
            unpriced_calls: 1, shared: stats(), unattributed: stats(), note: 'Lifetime includes retained records only.' },
        metering_health: { spooled_events: 2, unrecoverable_writes: 1 } };
}

function okJson(data) { return { ok: true, json: async () => data }; }
function deferred() { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; }

function setup(fetchImpl = async () => okJson(profilePayload())) {
    const elements = new Map();
    const requests = [];
    const downloads = [];
    const urls = [];
    const revoked = [];
    const timers = [];
    const context = vm.createContext({
        document: {
            getElementById(id) {
                if (!elements.has(id)) elements.set(id, {
                    value: '', hidden: false, disabled: false, textContent: '', innerHTML: '', attributes: {},
                    classList: { toggle() {} }, setAttribute(k, v) { this.attributes[k] = v; },
                    focus() { this.focused = true; }, scrollIntoView() {}, querySelectorAll() { return []; }
                });
                return elements.get(id);
            },
            addEventListener() {},
            createElement(tag) {
                if (tag === 'div') return {
                    textContent: '',
                    get innerHTML() { return String(this.textContent).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
                };
                return { click() { downloads.push({ filename: this.download, href: this.href }); }, remove() {} };
            },
            body: { appendChild() {} }
        },
        URLSearchParams, Blob,
        URL: { createObjectURL(blob) { const url = `blob:${urls.length}`; urls.push({ blob, url }); return url; }, revokeObjectURL(url) { revoked.push(url); } },
        setTimeout(callback) { timers.push(callback); },
        fetch: async (url, options) => { requests.push({ url, options }); return fetchImpl(url, options); },
        console: { error() {} }
    });
    vm.runInContext(`${source}\n;globalThis.ui = { state, refs, renderAiProfiles, renderAiProfileDetail, renderAiReconciliation, loadAiProfiles, loadAiProfileDetail, closeAiProfileDetail, invalidateAiAccounting, loadAiReconciliation, syncAiBilling, exportAiProfiles, renderAiProfilesControls, aiRecordedValue, aiRecordedCost, formatTokens, aiActivitySummary, renderAiBreakdown, aiExportSections, renderAiUsage, renderB2cRevenue, exportAiCsv, aiUsageEmptyState, loadB2cRevenue, aiBillingMoney };`, context);
    const ui = context.ui;
    ui.state.authToken = 'test-admin-token';
    ui.state.aiRange = { start: '2026-09-01', end: '2026-09-06', preset: 'custom' };
    return { ...ui, elements, requests, downloads, urls, revoked, timers };
}

test('profiles preserve exact token counts, separate selected and lifetime, and escape profile data', () => {
    const app = setup();
    app.renderAiProfiles(profilePayload('<img src=x onerror=alert(1)>'));
    const html = app.refs.aiProfilesTableBody.innerHTML;
    assert.match(html, /1,683/);
    assert.match(html, /9,876,543/);
    assert.doesNotMatch(html, /9\.88M|<img/);
    assert.match(html, /&lt;img/);
    assert.match(html, /data-ai-profile-id="9"/);
    assert.match(app.refs.aiCoverage.innerHTML, /2 usage records are waiting/);
    assert.match(app.refs.aiCoverage.innerHTML, /1 usage records could not be saved/);
    assert.match(app.refs.aiCoverage.innerHTML, /Shared AI operations/);
    assert.match(app.refs.aiCoverage.innerHTML, /Unclassified \/ unattributed AI operations/);
    assert.match(app.refs.aiCoverage.innerHTML, /2 calls missing usage/);
    assert.doesNotMatch(app.refs.aiCoverage.innerHTML, /estimated|unpriced|\$/i);
    assert.equal(app.refs.aiProfilesNextBtn.disabled, false);
});

test('quoted dynamic data cannot break out of profile attributes', () => {
    const app = setup();
    const data = profilePayload();
    data.profiles[0].user_id = '9" onclick="alert(1)';
    app.renderAiProfiles(data);
    assert.match(app.refs.aiProfilesTableBody.innerHTML, /9&quot; onclick=&quot;alert\(1\)/);
    assert.doesNotMatch(app.refs.aiProfilesTableBody.innerHTML, /" onclick="/);
});

test('missing records display numeric zero with explicit coverage and calculation availability', () => {
    const app = setup();
    const data = profilePayload();
    data.profiles[0].range = stats({ calls: 0, total_tokens: 0 });
    data.profiles[0].lifetime = stats({ calls: 1, unknown_calls: 1, total_tokens: 0 });
    app.renderAiProfiles(data);
    const html = app.refs.aiProfilesTableBody.innerHTML;
    assert.match(html, /<strong>0<\/strong>/);
    assert.match(html, /\$0\.00/);
    assert.match(html, /Cost unavailable/);
    assert.match(html, /1 missing usage/);
    assert.doesNotMatch(html, /<strong>—<\/strong>|Unpriced|Partial estimate/);
    assert.equal(app.aiRecordedValue(null, 'total_tokens'), '0');
    assert.equal(app.aiRecordedCost(null), '$0.00');
});

test('profile estimated prices are ignored even if an older server includes them', () => {
    const app = setup();
    const data = profilePayload();
    data.profiles[0].range = stats({ calls: 1, estimated_cost_usd: 913.55 });
    app.renderAiProfiles(data);
    const html = app.refs.aiProfilesTableBody.innerHTML;
    assert.doesNotMatch(html, /913|0\.125|estimate|unpriced/i);
    assert.match(html, /Cost unavailable/);
    assert.equal(app.aiRecordedCost(stats({ estimated_cost_usd: 100 })), '$0.00');
});

test('feature detail displays separate token categories and TTS characters for both periods', () => {
    const app = setup();
    app.renderAiProfileDetail({ profile: { name: '<script>x</script>', email: 'a@example.test' },
        range: { start: '2026-09-01', end: '2026-09-06' },
        features: [{ source: 'student_mock_interview', label: 'Mock interview <x>', range: stats(), lifetime: stats({ tts_characters: 7654 }) }],
        range_totals: stats(), lifetime_totals: stats({ tts_characters: 7654 }), coverage_note: 'Older usage can be missing.' });
    assert.equal(app.refs.aiProfileDetailTitle.textContent, '<script>x</script>');
    const html = app.refs.aiProfileDetailBody.innerHTML;
    assert.match(html, /Selected range/);
    assert.match(html, /Lifetime recorded usage/);
    for (const column of ['Input', 'Candidate', 'Thinking', 'Within input', 'Tool', 'Total tokens', 'Characters']) assert.match(html, new RegExp(column));
    assert.match(html, /7,654/);
    assert.match(html, /Mock interview &lt;x&gt;/);
    assert.match(html, /Older usage can be missing/);
    assert.match(html, /double-count/);
    assert.match(html, /Feature<\/th><th scope="col">Total tokens<\/th><th scope="col">Calculated USD/);
    assert.match(html, /Scroll horizontally/);
});

test('all AI token displays use exact counts and TTS activity retains its character units', () => {
    const app = setup();
    assert.equal(app.formatTokens(2740561), '2,740,561');
    assert.equal(app.formatTokens(1019), '1,019');
    assert.equal(app.aiActivitySummary({ calls: 10, tokens: 2740561, tts_characters: 13294 }), '10 calls · 2,740,561 tokens · 13,294 TTS characters');
    assert.equal(app.aiActivitySummary({ model: 'gcp-tts/en-US-Neural2-D', calls: 5, tokens: 0, tts_characters: 13294 }), '5 calls · 13,294 TTS characters');
    assert.equal(app.aiActivitySummary({ source: 'mock_interview_tts', calls: 5, tokens: 0 }), '5 calls · 0 TTS characters (not recorded)');
});

test('model breakdown exposes real model IDs and CSV keeps separate TTS character columns', () => {
    const app = setup();
    const rows = [{ model: 'gemini-2.5-flash', calls: 1, tokens: 1234567, tts_characters: 0, cost_usd: 1 },
        { model: 'gcp-tts/en-US-Neural2-D', calls: 2, tokens: 0, tts_characters: 9321, cost_usd: 0.2 }];
    app.renderAiBreakdown(app.refs.aiModelChart, rows, (row) => row.model);
    assert.match(app.refs.aiModelChart.innerHTML, /gemini-2\.5-flash/);
    assert.match(app.refs.aiModelChart.innerHTML, /1,234,567 tokens/);
    assert.match(app.refs.aiModelChart.innerHTML, /9,321 TTS characters/);
    assert.doesNotMatch(app.refs.aiModelChart.innerHTML, /AI Model 1|0 tokens/);
    const sections = app.aiExportSections('models', { by_model: rows });
    assert.equal(sections[0].header[3], 'TTS characters');
    assert.equal(sections[0].rows[1][3], 9321);
});

test('profile requests use selected dates, applied search, pagination and admin authentication', async () => {
    const app = setup();
    app.state.aiProfiles.search = 'A & B';
    app.state.aiProfiles.page = 2;
    await app.loadAiProfiles();
    const req = app.requests[0];
    const url = new URL(req.url, 'https://example.test');
    assert.equal(url.pathname, '/api/admin/ai-usage/profiles');
    assert.deepEqual(Object.fromEntries(url.searchParams), { start: '2026-09-01', end: '2026-09-06', page: '2', page_size: '25', search: 'A & B' });
    assert.equal(req.options.headers.Authorization, 'Bearer test-admin-token');
    assert.equal(req.options.credentials, 'same-origin');
    assert.equal(app.state.aiProfiles.loading, false);
});

test('a stale profile response cannot overwrite a later search', async () => {
    const first = deferred();
    const app = setup((url) => new URL(url, 'https://example.test').searchParams.get('search') === 'old' ? first.promise : okJson(profilePayload('Newest')));
    app.state.aiProfiles.search = 'old';
    const old = app.loadAiProfiles();
    await Promise.resolve();
    app.state.aiProfiles.search = 'new';
    await app.loadAiProfiles();
    first.resolve(okJson(profilePayload('Stale')));
    await old;
    assert.match(app.refs.aiProfilesTableBody.innerHTML, /Newest/);
    assert.doesNotMatch(app.refs.aiProfilesTableBody.innerHTML, /Stale/);
});

test('closing a profile or changing dates invalidates an in-flight detail response', async () => {
    const pending = deferred();
    const app = setup(() => pending.promise);
    const loading = app.loadAiProfileDetail('9');
    await Promise.resolve();
    app.closeAiProfileDetail();
    pending.resolve(okJson({ profile: { name: 'Stale detail' }, features: [] }));
    await loading;
    assert.equal(app.refs.aiProfileDetail.hidden, true);
    assert.notEqual(app.refs.aiProfileDetailTitle.textContent, 'Stale detail');
});

test('CSV exports all matching profiles with applied filters, never a single table page', async () => {
    const app = setup(async () => ({ ok: true, headers: { get: () => 'attachment; filename="all-profiles.csv"' }, blob: async () => new Blob(['all rows']) }));
    app.state.aiProfiles.total = 100;
    app.state.aiProfiles.page = 3;
    app.state.aiProfiles.search = 'Applied search';
    app.refs.aiProfilesSearch.value = 'Unsaved search';
    const exporting = app.exportAiProfiles();
    app.state.aiProfiles.search = 'New search';
    await exporting;
    const url = new URL(app.requests[0].url, 'https://example.test');
    assert.equal(url.pathname, '/api/admin/ai-usage/profiles/export');
    assert.deepEqual(Object.fromEntries(url.searchParams), { start: '2026-09-01', end: '2026-09-06', search: 'Applied search' });
    assert.equal(app.requests[0].options.headers.Authorization, 'Bearer test-admin-token');
    assert.equal(app.downloads[0].filename, 'all-profiles.csv');
    assert.equal(await app.urls[0].blob.text(), 'all rows');
    assert.equal(app.state.aiProfiles.exporting, false);
    app.timers[0]();
    assert.deepEqual(app.revoked, ['blob:0']);
});

test('duplicate exports are suppressed and failure restores controls', async () => {
    const pending = deferred();
    const app = setup(() => pending.promise);
    app.state.aiProfiles.total = 10;
    const exporting = app.exportAiProfiles();
    await Promise.resolve();
    await app.exportAiProfiles();
    assert.equal(app.requests.length, 1);
    assert.equal(app.refs.aiProfilesExportBtn.disabled, true);
    pending.resolve({ ok: false, status: 500, json: async () => ({ detail: 'Export unavailable' }) });
    await exporting;
    assert.equal(app.downloads.length, 0);
    assert.equal(app.refs.aiProfilesExportBtn.disabled, false);
    assert.equal(app.refs.flash.textContent, 'Export unavailable');
});

test('unconnected billing shows zeros and explicitly identifies that no charges were imported', () => {
    const app = setup();
    app.renderAiReconciliation({ configured: false, status: 'not_configured', range: {}, totals: [], app_estimated_cost_usd: 0 });
    const html = app.refs.aiReconciliation.innerHTML;
    assert.match(html, /not connected/);
    assert.match(html, /\$0\.00/);
    assert.match(html, /does not confirm that Google charged 0/);
    assert.doesNotMatch(html, /Within rounding tolerance|estimate|difference/i);
    assert.equal(app.refs.aiBillingSyncBtn.disabled, true);
});

test('billing preserves native currencies and exposes project scope and original service units', () => {
    const app = setup();
    app.renderAiReconciliation({ configured: true, status: 'available', project_id: '<project>', last_synced_at: '2026-09-06T12:00:00',
        range: { start: '2026-09-01', end: '2026-09-06' }, totals: [{ currency: 'INR', cost: 1200, credits: -100, net_cost: 1100 }],
        app_estimated_cost_usd: 12, difference_usd: null, comparison_status: 'incomplete',
        usage_rows: [{ service: 'Text to speech', sku: '<sku>', unit: 'characters', usage_amount: 7500, cost: 1.2, currency: 'USD' }] });
    const html = app.refs.aiReconciliation.innerHTML;
    assert.match(html, /INR 1,100\.00/);
    assert.doesNotMatch(html, /estimate|difference|comparison/i);
    assert.match(html, /including B2B, shared and unattributed/);
    assert.match(html, /characters/);
    assert.match(html, /&lt;project&gt;/);
    assert.match(html, /&lt;sku&gt;/);
    assert.doesNotMatch(html, /<sku>|<project>/);
});

test('headline uses only imported native-currency gross, credits and net, never app rates', () => {
    const app = setup();
    app.renderAiReconciliation({ configured: true, status: 'available', range: {},
        google_cost_usd: 15, app_estimated_cost_usd: 12, difference_usd: 3,
        totals: [{ currency: 'INR', cost: 1200, credits: -100, net_cost: 1100 }] });
    const headline = app.refs.aiReconciliation.innerHTML.split('ai-billing-meta')[0];
    assert.match(headline, /Imported Google cost before credits/);
    assert.match(headline, /INR 1,200\.00/);
    assert.match(headline, /INR -100\.00/);
    assert.match(headline, /INR 1,100\.00/);
    assert.doesNotMatch(headline, /\$15|\$12|\$3|estimate|difference/i);
    assert.equal(app.refs.aiMonthHero.textContent, 'INR 1,100.00');
});

test('an actual zero billing record remains distinguishable from missing imports', () => {
    const app = setup();
    app.renderAiReconciliation({ configured: true, status: 'available', totals: [{ currency: 'USD', cost: 0, credits: 0, net_cost: 0 }] });
    assert.equal(app.refs.aiMonthHero.textContent, '$0.00');
    assert.equal(app.refs.aiHeroLabel.textContent, 'Imported Google net cost');
    assert.match(app.refs.aiReconciliation.innerHTML, /Imported Google billing records/);
    assert.doesNotMatch(app.refs.aiReconciliation.innerHTML, /no billed amount has been imported/);
    app.renderAiReconciliation({ configured: true, status: 'no_data', totals: [] });
    assert.equal(app.refs.aiMonthHero.textContent, '$0.00');
    assert.equal(app.refs.aiHeroLabel.textContent, 'No imported billing amount');
});

test('billing sync snapshots selected dates and requires admin protection', async () => {
    const app = setup(async () => okJson({ configured: true, status: 'no_data', range: {} }));
    app.state.aiBilling.data = { configured: true };
    const syncing = app.syncAiBilling();
    app.state.aiRange.start = '2026-08-01';
    await syncing;
    const req = app.requests[0];
    assert.equal(req.url, '/api/admin/ai-usage/reconciliation/sync');
    assert.equal(req.options.method, 'POST');
    assert.equal(req.options.credentials, 'same-origin');
    assert.equal(req.options.headers.Authorization, 'Bearer test-admin-token');
    assert.equal(req.options.headers['Content-Type'], 'application/json');
    assert.deepEqual(JSON.parse(req.options.body), { start: '2026-09-01', end: '2026-09-06' });
    assert.equal(app.state.aiBilling.syncing, false);

    app.state.turnstileSiteKey = 'security-check';
    app.state.adminProtectionVerified = false;
    await app.syncAiBilling();
    assert.equal(app.requests.length, 1);
    assert.equal(app.state.aiBilling.syncing, false);
});

test('date changes invalidate old billing results and profile data immediately', async () => {
    const pending = deferred();
    const app = setup(() => pending.promise);
    const loading = app.loadAiReconciliation();
    await Promise.resolve();
    app.invalidateAiAccounting();
    pending.resolve(okJson({ configured: true, status: 'available', project_id: 'stale-project', totals: [] }));
    await loading;
    assert.equal(app.state.aiBilling.data, null);
    assert.doesNotMatch(app.refs.aiReconciliation.innerHTML, /stale-project/);
    assert.equal(app.refs.aiProfilesExportBtn.disabled, true);
});


test('usage cards, daily rows, feature bars and CSV ignore all legacy estimated money', async () => {
    const app = setup();
    const row = { date: '2026-09-01', calls: 2, tokens: 3456789, tts_characters: 45, cost_usd: 987.65 };
    const data = { totals: { today: row, all_time: row },
        range: { ...row, start: row.date, end: row.date, days: 1, active_days: 1, cached_tokens: 111, search_queries: 2, avg_per_day_usd: 987.65, cache_saved_usd: 500 },
        daily: [row], by_source: [{ ...row, source: 'student_ai_chat', label: 'AI Chat' }], by_model: [] };
    app.renderAiUsage(data);
    assert.equal(app.refs.aiRangeCost.textContent, '3,456,789');
    assert.equal(app.refs.aiTodayCost.textContent, '3,456,789');
    assert.equal(app.refs.aiRangeAvg.textContent, '2');
    assert.equal(app.refs.aiRangeSaved.textContent, '111');
    assert.equal(app.refs.aiRangeSearch.textContent, '2');
    assert.equal(app.refs.aiDailyTotalCost.textContent, '45');
    assert.doesNotMatch(app.refs.aiDailyTableBody.innerHTML + app.refs.aiSourceChart.innerHTML, /987|estimate/i);
    app.exportAiCsv('all');
    const csv = await app.urls[0].blob.text();
    assert.match(csv, /3456789/);
    assert.doesNotMatch(csv, /987\.65|500|estimate/i);
    app.renderAiUsage({ totals: {}, range: {}, daily: [] });
    assert.equal(app.refs.aiRangeCost.textContent, '0');
    assert.equal(app.refs.aiDailyTotalShare.textContent, '0%');
});

test('B2C revenue does not display an inferred AI cost, profit or FX conversion', () => {
    const app = setup();
    app.renderB2cRevenue({ currency: 'INR', summary: { revenue_display: '₹999', gemini_cost_display: '₹123.45', gross_margin_display: '₹875.55', avg_cost_per_pass_display: '₹2.34' } });
    assert.equal(app.refs.b2cRevenue.textContent, '₹999');
    assert.equal(app.refs.b2cCost.textContent, '₹0');
    assert.equal(app.refs.b2cCostSub.textContent, 'No B2C-level billed cost');
});

test('AI Costs markup contains no illustrative metrics, estimated prices, margins or savings', () => {
    const html = fs.readFileSync(path.join(__dirname, '../static/admin_console.html'), 'utf8');
    const panel = html.slice(html.indexOf('<section id="adminAiTabPanel"'), html.indexOf('<div id="adminCouponModal"'));
    assert.doesNotMatch(panel, /Estimated|Est\.|Cost Saved|Tokens Saved|Gross Margin|Enterprise Revenue|Sample Student|demo/i);
    assert.match(panel, /Actual Google billing/);
    assert.match(panel, /No imported billing amount/);
    assert.match(panel, /Calculated USD/);
});


test('a failed or pending reload clears old numbers instead of implying they belong to new dates', () => {
    const app = setup();
    app.refs.aiRangeCost.textContent = '123';
    app.state.aiUsageData = { range: { tokens: 123 } };
    app.aiUsageEmptyState('Could not load usage.');
    assert.equal(app.refs.aiRangeCost.textContent, '0');
    assert.equal(app.refs.aiRangeSub.textContent, 'Usage data not loaded');
    assert.equal(app.state.aiUsageData, null);
    assert.match(app.refs.aiDailyTableBody.innerHTML, /Could not load usage/);
});

test('tiny imported charges retain their recorded decimal precision', () => {
    const app = setup();
    app.renderAiReconciliation({ configured: true, status: 'available', totals: [{ currency: 'USD', cost: 0.000012345, credits: 0, net_cost: 0.000012345 }] });
    assert.equal(app.refs.aiMonthHero.textContent, '$0.000012345');
});


test('removed or hidden B2C revenue panels skip revenue requests', async () => {
    const app = setup();
    app.refs.b2cRevenuePanel.hidden = true;
    await app.loadB2cRevenue();
    assert.equal(app.requests.length, 0);
    app.refs.b2cRevenuePanel = null;
    await app.loadB2cRevenue();
    assert.equal(app.requests.length, 0);
    const html = fs.readFileSync(path.join(__dirname, '../static/admin_console.html'), 'utf8');
    assert.doesNotMatch(html, /adminB2cRevenuePanel|B2C Revenue Model/);
});


test('202 awaiting export shows an informational pending state without claiming an import', async () => {
    const app = setup(async () => ({ ok: true, status: 202, json: async () => ({ configured: true, status: 'awaiting_export', sync_status: 'awaiting_export', totals: [], last_synced_at: null, message: 'Google has not created the export table yet.' }) }));
    app.state.aiBilling.data = { configured: true };
    await app.syncAiBilling();
    assert.equal(app.refs.flash.textContent, 'Google has not created the export table yet.');
    assert.equal(app.refs.flash.className, 'flash info');
    assert.doesNotMatch(app.refs.flash.textContent, /refreshed|success/i);
    assert.match(app.refs.aiReconciliation.innerHTML, /Awaiting Google billing export/);
    assert.match(app.refs.aiReconciliation.innerHTML, /Not synced yet/);
    assert.equal(app.refs.aiMonthHero.textContent, '$0.00');
    assert.equal(app.state.aiBilling.syncing, false);
});

test('pending export retains the prior import and timestamp without claiming a fresh sync', async () => {
    const oldTimestamp = '2026-09-01T12:00:00';
    const app = setup(async () => ({ ok: true, status: 202, json: async () => ({ configured: true, status: 'available', sync_status: 'awaiting_export', totals: [{ currency: 'USD', cost: '1.123456789', credits: '-0.10', net_cost: '1.023456789' }], last_synced_at: oldTimestamp }) }));
    app.state.aiBilling.data = { configured: true };
    await app.syncAiBilling();
    assert.match(app.refs.aiReconciliation.innerHTML, /Previous import retained/);
    assert.match(app.refs.flash.textContent, /Awaiting Google billing export/);
    assert.equal(app.refs.flash.className, 'flash info');
    assert.equal(app.state.aiBilling.data.last_synced_at, oldTimestamp);
    assert.equal(app.refs.aiMonthHero.textContent, '$1.023456789');
});

test('billing string formatting preserves all significant digits without floating-point conversion', () => {
    const app = setup();
    assert.equal(app.aiBillingMoney('12345678901234567890.123456789012345678901', 'INR'), 'INR 12,345,678,901,234,567,890.123456789012345678901');
    assert.equal(app.aiBillingMoney('0.000000000000000000000001', 'USD'), '$0.000000000000000000000001');
    assert.equal(app.aiBillingMoney('1.23456789E-10', 'USD'), '$0.000000000123456789');
    assert.equal(app.aiBillingMoney('-1234.5600', 'USD'), '$-1,234.56');
    assert.equal(app.aiBillingMoney('-0E-9', 'USD'), '$0.00');
});


test('profile calculated costs preserve precise positive amounts and label incomplete coverage', () => {
    const app = setup();
    const data = profilePayload();
    data.profiles[0].range = stats({ calculated_cost_usd: '0.00000012345', calculated_cost_available: true, calculated_cost_status: 'complete', priced_calls: 3 });
    data.profiles[0].lifetime = stats({ calculated_cost_usd: '12.123456789', calculated_cost_available: true, calculated_cost_status: 'partial', partially_priced_calls: 2, unpriced_calls: 2 });
    app.renderAiProfiles(data);
    const html = app.refs.aiProfilesTableBody.innerHTML;
    assert.match(html, /\$0\.00000012345/);
    assert.match(html, /\$12\.123456789/);
    assert.match(html, /Recorded usage × published rates/);
    assert.match(html, /Partial cost/);
    assert.doesNotMatch(html, /0\.125|No profile-level billed/);
    assert.equal(app.aiRecordedCost(stats({ calculated_cost_usd: '999', calculated_cost_available: false, calculated_cost_status: 'unavailable' })), '$0.00');
});

test('profile daily costs and pricing coverage explain exactly which values are available', () => {
    const app = setup();
    const calculated = stats({ calculated_cost_usd: '0.002025', calculated_cost_available: true, calculated_cost_status: 'partial',
        priced_calls: 1, partially_priced_calls: 1, unpriced_calls: 2, rates_verified_at: '2026-09-07',
        cost_exclusions: ['input_modality_not_recorded', '<script>unsafe</script>'], rate_coverage_reasons: ['historical_request_date_price_not_verified'] });
    app.renderAiProfileDetail({ profile: { name: 'Student' }, features: [], daily: [{ date: '2026-09-02', ...calculated }], lifetime_totals: calculated });
    const html = app.refs.aiProfileDetailBody.innerHTML;
    assert.match(html, /Daily usage and cost/);
    assert.match(html, /Sep 2, 2026/);
    assert.match(html, /\$0\.002025/);
    assert.match(html, /1 fully priced calls · 1 partially priced · 1 unavailable/);
    assert.match(html, /verified 2026-09-07/);
    assert.match(html, /currently published standard rates/);
    assert.match(html, /Input type was not recorded/);
    assert.match(html, /original request date is not verified/);
    assert.match(html, /&lt;script&gt;/);
    assert.doesNotMatch(html, /<script>/);
});

test('global cards daily rows and CSV show calculated money while Google billing remains separate', async () => {
    const app = setup();
    const row = { date: '2026-09-02', calls: 1, tokens: 1000, tts_characters: 0,
        calculated_cost_usd: '0.00123456789', calculated_cost_available: true, calculated_cost_status: 'partial', rate_basis: ['current_standard_list_rates'], cost_usd: 98765 };
    app.renderAiUsage({ totals: {}, range: { ...row, start: row.date, end: row.date, days: 1 }, daily: [row], by_model: [{ ...row, model: 'gemini-2.5-pro' }] });
    assert.equal(app.refs.aiCalculatedCost.textContent, '$0.00123456789');
    assert.equal(app.refs.aiDailyCalculatedTotal.textContent, '$0.00123456789');
    assert.match(app.refs.aiDailyTableBody.innerHTML, /\$0\.00123456789/);
    app.exportAiCsv('all');
    const csv = await app.urls[0].blob.text();
    assert.match(csv, /Calculated cost \(USD\)/);
    assert.match(csv, /0\.00123456789/);
    assert.match(csv, /current_standard_list_rates/);
    assert.doesNotMatch(csv, /98765/);
    app.renderAiReconciliation({ configured: true, status: 'available', totals: [{ currency: 'INR', cost: '12', credits: '-2', net_cost: '10' }] });
    assert.equal(app.refs.aiMonthHero.textContent, 'INR 10.00');
    assert.equal(app.refs.aiCalculatedCost.textContent, '$0.00123456789');
    app.aiUsageEmptyState('Offline');
    assert.equal(app.refs.aiCalculatedCost.textContent, '$0.00');
    assert.equal(app.refs.aiDailyCalculatedTotal.textContent, '$0.00');
});
