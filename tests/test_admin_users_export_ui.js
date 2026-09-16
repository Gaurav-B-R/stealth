const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/admin_console.js'), 'utf8');

function makeElement() {
    return {
        disabled: false,
        hidden: true,
        textContent: '',
        value: '',
        attributes: {},
        setAttribute(name, value) { this.attributes[name] = value; }
    };
}

function successResponse(filename = 'student-accounts.csv') {
    return {
        ok: true,
        headers: { get: (name) => name === 'Content-Disposition' && filename
            ? `attachment; filename="${filename}"` : null },
        blob: async () => new Blob(['exported accounts'])
    };
}

function setup(fetchImpl = async () => successResponse()) {
    const elements = new Map([
        'adminFlash', 'adminUsersExportActions', 'adminUsersExportCsvBtn',
        'adminUsersExportExcelBtn', 'adminUsersSearchInput',
        'adminUsersPlanFilter', 'adminUsersRoleFilter'
    ].map((id) => [id, makeElement()]));
    const requests = [];
    const downloads = [];
    const objectUrls = [];
    const revokedUrls = [];
    const timers = [];
    const context = vm.createContext({
        document: {
            getElementById: (id) => elements.get(id) || null,
            // The tests invoke export behavior directly without bootstrapping the console.
            addEventListener() {},
            createElement(tag) {
                assert.equal(tag, 'a');
                const link = {
                    attached: false,
                    removed: false,
                    click() {
                        assert.equal(this.attached, true);
                        downloads.push({ href: this.href, filename: this.download, link: this });
                    },
                    remove() { this.removed = true; this.attached = false; }
                };
                return link;
            },
            body: { appendChild(link) { link.attached = true; } }
        },
        URLSearchParams,
        URL: {
            createObjectURL(blob) {
                const url = `blob:test-${objectUrls.length}`;
                objectUrls.push({ blob, url });
                return url;
            },
            revokeObjectURL: (url) => revokedUrls.push(url)
        },
        setTimeout(callback, delay) { timers.push({ callback, delay }); },
        fetch: async (url, options) => {
            requests.push({ url, options });
            return fetchImpl(url, options);
        },
        console: { error() {} }
    });
    vm.runInContext(`${source}\n;globalThis.exportTest = { state, refs, exportUsers, renderUsersExportControls };`, context);
    const api = context.exportTest;
    api.state.total = 47;
    api.state.authToken = 'test-admin-token';
    api.state.access = {
        role: 'admin', sections: ['users', 'enterprise', 'analytics', 'finance', 'ai', 'team'],
        can_manage_team: true, can_provision_enterprise: true,
        can_write_sections: ['users', 'enterprise', 'analytics', 'finance', 'ai', 'team'],
        can_delete_sections: ['users', 'enterprise', 'analytics', 'finance', 'ai', 'team']
    };
    api.renderUsersExportControls();
    return { ...api, requests, downloads, objectUrls, revokedUrls, timers };
}

function assertControlsReady(app) {
    assert.equal(app.state.usersExportFormat, null);
    assert.equal(app.refs.usersExportCsvBtn.disabled, false);
    assert.equal(app.refs.usersExportExcelBtn.disabled, false);
    assert.equal(app.refs.usersExportCsvBtn.textContent, 'Export CSV');
    assert.equal(app.refs.usersExportExcelBtn.textContent, 'Export Excel');
    assert.equal(app.refs.usersExportActions.attributes['aria-busy'], 'false');
}

for (const format of ['csv', 'xlsx']) {
    test(`${format} export downloads every matching page using applied filters and admin authentication`, async () => {
        const filename = `rilono-student-accounts-2026-09-06.${format}`;
        const app = setup(async () => successResponse(filename));
        app.state.filters = { search: 'A & B university', plan: 'visa_pass', role: 'student' };
        app.state.page = 3;
        app.state.pageSize = 20;
        app.refs.usersSearch.value = 'unsaved search';
        app.refs.usersPlan.value = 'free';
        app.refs.usersRole.value = 'admin';

        const exporting = app.exportUsers(format);
        // Changing the table while protection is checked cannot change this export's scope.
        app.state.filters.search = 'newer applied search';
        await exporting;

        assert.equal(app.requests.length, 1);
        const request = app.requests[0];
        const url = new URL(request.url, 'https://example.test');
        assert.equal(url.pathname, '/api/admin/users/export');
        assert.deepEqual(Object.fromEntries(url.searchParams), {
            format, plan: 'visa_pass', role: 'student', search: 'A & B university'
        });
        assert.equal(request.options.headers.Authorization, undefined);
        assert.equal(request.options.headers['X-Admin-Console-Session'], 'required');
        assert.equal(request.options.credentials, 'same-origin');
        assert.equal(app.downloads.length, 1);
        assert.equal(app.downloads[0].filename, filename);
        assert.equal(app.downloads[0].href, app.objectUrls[0].url);
        assert.equal(await app.objectUrls[0].blob.text(), 'exported accounts');
        assert.equal(app.downloads[0].link.removed, true);
        assert.equal(app.refs.flash.className, 'flash success');
        assert.equal(app.refs.flash.textContent, `Downloaded ${filename}`);
        assertControlsReady(app);
        assert.equal(app.revokedUrls.length, 0);
        assert.equal(app.timers.length, 1);
        app.timers[0].callback();
        assert.deepEqual(app.revokedUrls, [app.objectUrls[0].url]);
    });
}

test('cookie sessions use credentials without exposing the sentinel and missing filenames get a format-specific fallback', async () => {
    const app = setup(async () => successResponse(null));
    app.state.authToken = '__cookie_session__';

    await app.exportUsers('xlsx');

    assert.equal(app.requests.length, 1);
    assert.deepEqual(Object.keys(app.requests[0].options.headers), ['X-Admin-Console-Session']);
    assert.equal(app.requests[0].options.headers['X-Admin-Console-Session'], 'required');
    assert.equal(app.requests[0].options.credentials, 'same-origin');
    const params = new URL(app.requests[0].url, 'https://example.test').searchParams;
    assert.deepEqual(Object.fromEntries(params), { format: 'xlsx', plan: 'all', role: 'all' });
    assert.equal(app.downloads[0].filename, 'rilono-student-accounts.xlsx');
    assertControlsReady(app);
});

test('both controls remain disabled during export and repeated clicks do not send another request', async () => {
    let resolveResponse;
    const response = new Promise((resolve) => { resolveResponse = resolve; });
    const app = setup(() => response);
    const exporting = app.exportUsers('csv');
    await Promise.resolve();

    assert.equal(app.requests.length, 1);
    assert.equal(app.state.usersExportFormat, 'csv');
    assert.equal(app.refs.usersExportCsvBtn.disabled, true);
    assert.equal(app.refs.usersExportExcelBtn.disabled, true);
    assert.equal(app.refs.usersExportCsvBtn.textContent, 'Preparing CSV…');
    assert.equal(app.refs.usersExportExcelBtn.textContent, 'Export Excel');
    assert.equal(app.refs.usersExportActions.attributes['aria-busy'], 'true');
    await app.exportUsers('xlsx');
    await app.exportUsers('csv');
    assert.equal(app.requests.length, 1);

    resolveResponse(successResponse());
    await exporting;
    assert.equal(app.downloads.length, 1);
    assertControlsReady(app);
});

for (const [name, initialState] of [
    ['the table is loading', { loading: true }],
    ['no accounts match', { total: 0 }]
]) {
    test(`exports are disabled and ignored when ${name}`, async () => {
        const app = setup();
        Object.assign(app.state, initialState);
        app.renderUsersExportControls();

        await app.exportUsers('csv');
        await app.exportUsers('xlsx');

        assert.equal(app.refs.usersExportCsvBtn.disabled, true);
        assert.equal(app.refs.usersExportExcelBtn.disabled, true);
        assert.equal(app.state.usersExportFormat, null);
        assert.equal(app.requests.length, 0);
        assert.equal(app.downloads.length, 0);
    });
}

test('unsupported formats are ignored', async () => {
    const app = setup();
    await app.exportUsers('pdf');
    assert.equal(app.requests.length, 0);
    assert.equal(app.downloads.length, 0);
    assertControlsReady(app);
});

test('rejected admin protection prevents the request and restores both controls', async () => {
    const app = setup();
    app.state.turnstileSiteKey = 'protection-enabled';
    app.state.adminProtectionVerified = false;

    await app.exportUsers('xlsx');

    assert.equal(app.requests.length, 0);
    assert.equal(app.downloads.length, 0);
    assert.equal(app.refs.flash.className, 'flash error');
    assert.match(app.refs.flash.textContent, /Cloudflare verification required/);
    assertControlsReady(app);
});

for (const [name, fetchImpl, message] of [
    ['a server error', async () => ({
        ok: false, status: 500, json: async () => ({ detail: 'Export is temporarily unavailable.' })
    }), 'Export is temporarily unavailable.'],
    ['a non-JSON error', async () => ({
        ok: false, status: 502, json: async () => { throw new SyntaxError('Unexpected HTML'); }
    }), 'Failed to export student accounts.'],
    ['a network failure', async () => { throw new Error('Network unavailable'); },
        'Could not export student accounts. Please retry.'],
    ['an unreadable download', async () => ({
        ...successResponse(), blob: async () => { throw new Error('Body read failed'); }
    }), 'Could not export student accounts. Please retry.']
]) {
    test(`${name} displays an error and makes both controls available for retry`, async () => {
        const app = setup(fetchImpl);

        await app.exportUsers('xlsx');

        assert.equal(app.requests.length, 1);
        assert.equal(app.downloads.length, 0);
        assert.equal(app.objectUrls.length, 0);
        assert.equal(app.refs.flash.hidden, false);
        assert.equal(app.refs.flash.className, 'flash error');
        assert.equal(app.refs.flash.textContent, message);
        assertControlsReady(app);
    });
}
