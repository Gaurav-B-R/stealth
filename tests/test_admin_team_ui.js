const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/admin_console.js'), 'utf8');
const sections = ['users', 'enterprise', 'analytics', 'finance', 'ai', 'team'];
const jsonResponse = (payload, status = 200) => ({ ok: status < 400, status, headers: { get() {} }, json: async () => payload });
const plain = (value) => JSON.parse(JSON.stringify(value));

function access(role = 'admin', assigned = sections, overrides = {}) {
    return { user: { id: 17, email: 'member@example.test', full_name: 'Console Member', is_admin: false, is_developer: false },
        role, sections: assigned, can_manage_team: role === 'admin' && assigned.includes('team'), can_provision_enterprise: false,
        can_write_sections: role === 'viewer' ? [] : assigned,
        can_delete_sections: role === 'admin' ? assigned : [], ...overrides };
}

function element(id = '') {
    let html = '';
    let text = '';
    const node = { id, value: '', hidden: false, disabled: false, dataset: {}, attributes: {}, children: [],
        classList: { toggle() {}, add() {}, remove() {}, contains: () => false }, style: {},
        setAttribute(name, value) { this.attributes[name] = String(value); },
        getAttribute(name) { return this.attributes[name]; },
        hasAttribute(name) { return name in this.attributes; },
        addEventListener() {}, reset() {}, focus() { this.focused = true; }, scrollIntoView() {},
        querySelectorAll(selector) {
            if (selector === 'input:checked') return this.children.filter((child) => child.checked);
            return this.children;
        },
        get textContent() { return text; },
        set textContent(value) { text = String(value); html = ''; this.children = []; },
        get innerHTML() { return html || text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); },
        set innerHTML(value) {
            html = value; text = '';
            if (id === 'adminTeamSections') {
                this.children = [...value.matchAll(/<input\s([^>]+)>/g)].map((match) => ({ value: /value="([^"]+)"/.exec(match[1])[1], checked: /\schecked(?:\s|$)/.test(match[1]), disabled: /\sdisabled(?:\s|$)/.test(match[1]) }));
            }
        }
    };
    return node;
}

function setup(fetchImpl, initial = access()) {
    const elements = new Map();
    const permissionElements = [];
    const requests = [];
    const get = (id) => { if (!elements.has(id)) elements.set(id, element(id)); return elements.get(id); };
    sections.forEach((key) => { get(`admin${key[0].toUpperCase() + key.slice(1)}TabBtn`).dataset.tab = key; });
    const context = vm.createContext({
        document: { getElementById: get, createElement: () => element(), addEventListener() {},
            querySelectorAll(selector) { return selector.startsWith('[data-admin-write]') ? permissionElements : []; },
            querySelector() { return null; }, body: element('body') },
        window: { matchMedia: () => ({ matches: false }), scrollTo() {} },
        URLSearchParams, Blob, URL, setTimeout, clearTimeout,
        console: { error() {} },
        fetch: async (url, options) => {
            requests.push({ url, options });
            return fetchImpl ? fetchImpl(url, options) : jsonResponse({});
        }
    });
    vm.runInContext(`${source}\n;globalThis.ui = { state, refs, applyAdminAccess, refreshCurrentAdminUser, renderActiveTab, handleTabSwitch, loadActiveTab,
        canAccessSection, canWriteSection, canDeleteSection, canProvisionEnterprise, applyAdminPermissions, adminFetch, clearPrivilegedState,
        loadUsers, loadEnterpriseAccounts, loadFinanceAnalytics, loadAiUsage, loadAcquisitionBreakdown, loadB2cRevenue,
        updateUserStatus, deleteUser, createAccountCoupon, deleteAccountCoupon, runAccountReco, setAccountVisaDecision,
        openFinanceEntryForm, submitFinanceEntry, deleteFinanceEntry, runGrowthAnalysis, syncAiBilling,
        handleEnterpriseCredentialSubmit, issueRefund, sendCouponEmail, updateCoupon, deleteCoupon,
        renderTeamSections, renderTeamMembers, loadTeam, editTeamMember, resetTeamForm, teamMemberPayload, saveTeamMember, revokeTeamMember, showAuth,
        handleLoginSubmit, handleLogout, buildAuthHeaders, clearTeamPasswordFields };
        confirmDialog = async () => true;`, context);
    context.ui.state.authToken = 'test-cookie-token';
    if (initial) context.ui.applyAdminAccess(initial);
    return { ...context.ui, context, elements, get, permissionElements, requests };
}

test('delegated member uses /admin/access despite having no legacy admin flags and selects first permitted section', async () => {
    const grant = access('viewer', ['finance']);
    const app = setup(() => jsonResponse(grant), null);
    assert.equal(await app.refreshCurrentAdminUser(), true);
    assert.equal(app.requests[0].url, '/api/admin/access');
    assert.equal(app.state.currentUser.is_admin, false);
    assert.equal(app.state.activeTab, 'finance');
    assert.equal(app.refs.financeTabBtn.hidden, false);
    assert.equal(app.refs.financeTabPanel.hidden, false);
    assert.equal(app.refs.usersTabBtn.hidden, true);
    assert.equal(app.refs.aiTabPanel.hidden, true);
    assert.equal(app.refs.teamTabBtn.hidden, true);
});

test('denied sections cannot be selected or eagerly loaded', async () => {
    const app = setup(null, access('viewer', ['team', 'finance']));
    assert.equal(app.canAccessSection('team'), false);
    await app.handleTabSwitch('users');
    await app.loadUsers(); await app.loadEnterpriseAccounts(); await app.loadAiUsage(); await app.loadAcquisitionBreakdown();
    assert.equal(app.state.activeTab, 'finance');
    assert.equal(app.requests.length, 0);
    vm.runInContext('globalThis.loaded = []; loadFinanceAnalytics = async () => loaded.push("finance"); loadUsers = async () => loaded.push("users");', app.context);
    await app.loadActiveTab();
    assert.deepEqual(plain(app.context.loaded), ['finance']);
});

test('Viewer direct mutation calls never reach fetch or destructive confirmations', async () => {
    const app = setup(null, access('viewer'));
    vm.runInContext('confirmDialog = async () => { throw new Error("No unauthorized confirmation"); };', app.context);
    const event = { preventDefault() {} };
    await app.updateUserStatus(5, false); await app.deleteUser(5, 'x@example.test', 'Name');
    await app.createAccountCoupon(5); await app.deleteAccountCoupon(5, 'X'); await app.runAccountReco(5); await app.setAccountVisaDecision(5, 'approved');
    app.openFinanceEntryForm(null); await app.submitFinanceEntry(event); await app.deleteFinanceEntry(5);
    await app.runGrowthAnalysis(); await app.syncAiBilling(); await app.handleEnterpriseCredentialSubmit(event);
    await app.issueRefund(null, {}); await app.sendCouponEmail(5, 'X', null); await app.updateCoupon(5, {}); await app.deleteCoupon(5, 'X');
    await app.saveTeamMember(event); await app.revokeTeamMember(5);
    assert.equal(app.requests.length, 0);
});

test('permission UI hides write and delete actions while leaving read filters and exports alone', () => {
    const app = setup(null, access('viewer', ['finance']));
    const write = element(), remove = element(), exportButton = element();
    write.dataset.adminWrite = 'finance'; remove.dataset.adminDelete = 'finance';
    app.permissionElements.push(write, remove);
    app.applyAdminPermissions();
    assert.equal(write.hidden, true); assert.equal(write.disabled, true);
    assert.equal(remove.hidden, true); assert.equal(exportButton.hidden, false); assert.equal(exportButton.disabled, false);
    app.applyAdminAccess(access('editor', ['finance']));
    assert.equal(write.hidden, false); assert.equal(write.disabled, false);
    assert.equal(remove.hidden, true);
});

test('Editor permits writes and exports but refuses DELETE, refunds, provisioning and Team', async () => {
    const app = setup(() => jsonResponse({}), access('editor'));
    assert.equal((await app.adminFetch('/api/admin/company-finance/entries', { method: 'POST' })).ok, true);
    assert.equal((await app.adminFetch('/api/admin/company-finance/export?format=xlsx')).ok, true);
    for (const [url, method] of [['/api/admin/users/7', 'DELETE'], ['/api/admin/enterprise/accounts/1/refunds', 'POST'], ['/api/admin/enterprise/credentials', 'POST'], ['/api/admin/team', 'GET']]) {
        assert.equal((await app.adminFetch(url, { method })).status, 403);
    }
    assert.equal(app.requests.length, 2);
});

test('enterprise credential provisioning remains a distinct platform-admin capability', async () => {
    const app = setup(() => jsonResponse({}), access('admin', ['enterprise']));
    assert.equal(app.canProvisionEnterprise(), false);
    await app.handleEnterpriseCredentialSubmit({ preventDefault() {} });
    assert.equal(app.requests.length, 0);
    app.applyAdminAccess(access('admin', ['enterprise'], { can_provision_enterprise: true }));
    assert.equal(app.canProvisionEnterprise(), true);
    assert.equal((await app.adminFetch('/api/admin/enterprise/credentials', { method: 'POST' })).ok, true);
});

test('section and role updates discard privileged state, modal contents and inflight responses', async () => {
    let resolve;
    const response = new Promise((done) => { resolve = done; });
    const app = setup(() => response);
    app.state.users = [{ email: 'sensitive@example.test' }];
    app.state.accountDetails = { private: 'data' };
    app.state.aiUsageData = { bill: 8 };
    app.get('adminAccountBody').innerHTML = '<p>Private account</p>';
    app.get('adminAccountDetail').hidden = false;
    const pending = app.adminFetch('/api/admin/users');
    app.applyAdminAccess(access('viewer', ['ai']));
    resolve(jsonResponse({ users: [{ email: 'old-response@example.test' }] }));
    const stale = await pending;
    assert.equal(stale.ok, false); assert.equal(stale.status, 409);
    assert.equal(app.state.users.length, 0); assert.equal(app.state.accountDetails, null); assert.equal(app.state.aiUsageData, null);
    assert.equal(app.get('adminAccountBody').innerHTML, ''); assert.equal(app.get('adminAccountDetail').hidden, true);
    assert.equal(app.state.activeTab, 'ai');
});

test('revoked access 403 refreshes once, clears cached identity, and shows login without redirect loops', async () => {
    const app = setup(() => jsonResponse({ detail: 'Console access required.' }, 403));
    app.state.users = [{ id: 2 }];
    const response = await app.adminFetch('/api/admin/users');
    assert.equal(response.status, 403);
    assert.deepEqual(app.requests.map((request) => request.url), ['/api/admin/users', '/api/admin/access']);
    assert.equal(app.state.access, null); assert.equal(app.state.currentUser, null); assert.equal(app.state.users.length, 0);
    assert.equal(app.refs.authPanel.hidden, false); assert.equal(app.refs.consolePanel.hidden, true);
});

test('Cloudflare verification 403 retains membership and asks for existing shield instead of access refresh', async () => {
    const app = setup(() => jsonResponse({ detail: 'Cloudflare verification required.' }, 403));
    app.state.adminProtectionVerified = true;
    await app.adminFetch('/api/admin/users');
    assert.equal(app.requests.length, 1);
    assert.equal(app.state.adminProtectionVerified, false);
    assert.equal(app.state.access.role, 'admin');
});

test('Team choices are limited to assigned sections and Team is only selectable for Admin', () => {
    const app = setup(null, access('admin', ['users', 'team']));
    app.refs.teamRole.value = 'viewer';
    app.renderTeamSections(['users', 'team', 'finance']);
    assert.deepEqual(app.refs.teamSections.children.map((item) => item.value), ['users', 'team']);
    assert.equal(app.refs.teamSections.children[1].disabled, true);
    assert.equal(app.refs.teamSections.children[1].checked, false);
    app.refs.teamEmail.value = 'existing@example.test';
    assert.deepEqual(plain(app.teamMemberPayload()), { email: 'existing@example.test', role: 'viewer', sections: ['users'] });
    app.refs.teamRole.value = 'admin'; app.renderTeamSections(['team']);
    assert.deepEqual(plain(app.teamMemberPayload()).sections, ['team']);
});

test('protected and unmanageable team members expose no edit/revoke controls or callable mutation', async () => {
    const app = setup();
    app.state.team.members = [{ user_id: 7, email: '<admin>@example.test', full_name: '<img onerror=bad>', role: 'admin', sections, protected: true, can_manage: true }];
    app.renderTeamMembers();
    assert.doesNotMatch(app.refs.teamTableBody.innerHTML, /data-team-action|<img/);
    assert.match(app.refs.teamTableBody.innerHTML, /Protected platform administrator/);
    app.editTeamMember(7); await app.revokeTeamMember(7);
    assert.equal(app.requests.length, 0); assert.equal(app.state.team.editingId, null);
});

test('Team add and edit send only account email / role / chosen sections, with no invitation or account creation', async () => {
    const member = { user_id: 5, email: 'existing@example.test', role: 'viewer', sections: ['users'], can_manage: true, protected: false };
    const app = setup((url) => jsonResponse(url === '/api/admin/access' ? access() : url === '/api/admin/team' ? { members: [member], sections: [] } : {}));
    app.refs.teamEmail.value = 'existing@example.test'; app.refs.teamRole.value = 'viewer'; app.renderTeamSections(['users']);
    await app.saveTeamMember({ preventDefault() {} });
    const create = app.requests.find((request) => request.options.method === 'POST');
    assert.equal(create.url, '/api/admin/team');
    assert.deepEqual(JSON.parse(create.options.body), { email: member.email, role: 'viewer', sections: ['users'] });
    assert.equal(app.state.team.saving, false); assert.equal(app.refs.teamForm.attributes['aria-busy'], 'false');
    app.editTeamMember(5);
    assert.equal(app.refs.teamEmail.disabled, true);
    app.refs.teamRole.value = 'editor'; app.renderTeamSections(['users', 'finance']);
    await app.saveTeamMember({ preventDefault() {} });
    const patch = app.requests.find((request) => request.options.method === 'PATCH');
    assert.equal(patch.url, '/api/admin/team/5');
    assert.deepEqual(JSON.parse(patch.options.body), { role: 'editor', sections: ['users', 'finance'] });
    assert.equal(app.requests.some((request) => /invite|send-email|auth\/register/.test(request.url)), false);
});

test('Team revoke calls only console membership DELETE and form errors clear on cancel', async () => {
    const app = setup((url) => jsonResponse(url === '/api/admin/access' ? access() : { members: [], sections: [] }));
    app.state.team.members = [{ user_id: 5, email: 'existing@example.test', role: 'viewer', sections: ['users'], can_manage: true, protected: false }];
    await app.revokeTeamMember(5);
    const deletion = app.requests.find((request) => request.options.method === 'DELETE');
    assert.equal(deletion.url, '/api/admin/team/5');
    assert.equal(app.requests.some((request) => /\/users\//.test(request.url)), false);
    app.refs.teamError.textContent = 'An old error'; app.refs.teamError.hidden = false;
    app.resetTeamForm();
    assert.equal(app.refs.teamError.textContent, ''); assert.equal(app.refs.teamError.hidden, true);
});

test('Team duplicate saves are blocked while the first request is pending and failures preserve the form', async () => {
    let resolve;
    const app = setup(() => new Promise((done) => { resolve = done; }));
    app.refs.teamEmail.value = 'existing@example.test'; app.refs.teamRole.value = 'viewer'; app.renderTeamSections(['users']);
    const first = app.saveTeamMember({ preventDefault() {} });
    await Promise.resolve();
    await app.saveTeamMember({ preventDefault() {} });
    assert.equal(app.requests.length, 1); assert.equal(app.state.team.saving, true);
    resolve(jsonResponse({ detail: 'Account email not found.' }, 404)); await first;
    assert.equal(app.state.team.saving, false); assert.equal(app.refs.teamError.textContent, 'Account email not found.');
    assert.equal(app.refs.teamEmail.value, 'existing@example.test');
});

function fillTeamPassword(app, password = 'Synthetic-Console-9!', confirmation = password) {
    app.refs.teamPassword.value = password;
    app.refs.teamPasswordConfirm.value = confirmation;
}

function assertPasswordFieldsEmpty(app) {
    assert.equal(app.refs.teamPassword.value, '');
    assert.equal(app.refs.teamPasswordConfirm.value, '');
}

test('password fields are masked, use new-password autocomplete, and explain the personal-password boundary', () => {
    const html = fs.readFileSync(path.join(__dirname, '../static/admin_console.html'), 'utf8');
    for (const id of ['adminTeamPassword', 'adminTeamPasswordConfirm']) {
        const tag = new RegExp(`<input id="${id}"[^>]+>`).exec(html)[0];
        assert.match(tag, /type="password"/);
        assert.match(tag, /autocomplete="new-password"/);
        assert.doesNotMatch(tag, /\svalue=/);
    }
    assert.match(html, /personal Rilono password stays the same/);
    assert.match(html, /Leave both fields blank to keep their current sign-in method/);
});

test('blank Team password leaves existing sign-in unchanged, mismatch prevents network, and confirmation is never serialized', async () => {
    const app = setup();
    app.refs.teamEmail.value = 'existing@example.test'; app.refs.teamRole.value = 'viewer'; app.renderTeamSections(['users']);
    assert.equal('console_password' in app.teamMemberPayload(), false);
    fillTeamPassword(app, 'Synthetic-Console-9!', 'Does-not-match');
    await app.saveTeamMember({ preventDefault() {} });
    assert.equal(app.requests.length, 0);
    assert.match(app.refs.teamError.textContent, /do not match/);
    fillTeamPassword(app);
    const payload = plain(app.teamMemberPayload());
    assert.equal(payload.console_password, 'Synthetic-Console-9!');
    assert.deepEqual(Object.keys(payload).sort(), ['console_password', 'email', 'role', 'sections']);
    assert.doesNotMatch(JSON.stringify(app.state), /Synthetic-Console-9!/);
});

test('Team add and password reset send the separate credential without changing user-account routes', async () => {
    const member = { user_id: 5, email: 'existing@example.test', role: 'viewer', sections: ['users'], can_manage: true, protected: false, has_console_password: true };
    const app = setup((url) => jsonResponse(url === '/api/admin/access' ? access() : url === '/api/admin/team' ? { members: [member], sections: [] } : {}));
    app.refs.teamEmail.value = member.email; app.refs.teamRole.value = 'viewer'; app.renderTeamSections(['users']);
    fillTeamPassword(app);
    await app.saveTeamMember({ preventDefault() {} });
    const post = app.requests.find((request) => request.options.method === 'POST');
    assert.equal(JSON.parse(post.options.body).console_password, 'Synthetic-Console-9!');
    assertPasswordFieldsEmpty(app);
    app.editTeamMember(5);
    fillTeamPassword(app, 'Second-Synthetic-7!');
    await app.saveTeamMember({ preventDefault() {} });
    const patch = app.requests.find((request) => request.options.method === 'PATCH');
    assert.equal(patch.url, '/api/admin/team/5');
    assert.equal(JSON.parse(patch.options.body).console_password, 'Second-Synthetic-7!');
    assert.equal('email' in JSON.parse(patch.options.body), false);
    assertPasswordFieldsEmpty(app);
    assert.equal(app.requests.some((request) => /\/api\/(?:auth|users)\//.test(request.url)), false);
    assert.doesNotMatch(JSON.stringify(app.state), /Synthetic/);
});

test('all password request failures clear sensitive fields but retain email and grant choices for retry', async () => {
    for (const networkFailure of [false, true]) {
        const app = setup(() => {
            if (networkFailure) throw new Error('Simulated transport error');
            return jsonResponse({ detail: 'Choose a stronger password.' }, 422);
        });
        app.refs.teamEmail.value = 'existing@example.test'; app.refs.teamRole.value = 'editor'; app.renderTeamSections(['users']);
        fillTeamPassword(app);
        await app.saveTeamMember({ preventDefault() {} });
        assertPasswordFieldsEmpty(app);
        assert.equal(app.refs.teamEmail.value, 'existing@example.test');
        assert.equal(app.refs.teamRole.value, 'editor');
        assert.deepEqual(plain(app.teamMemberPayload()).sections, ['users']);
        assert.equal(app.state.team.saving, false);
    }
});

test('member switches, protected targets, reset, logout UI and access changes clear unsubmitted passwords', () => {
    const app = setup();
    app.state.team.members = [
        { user_id: 5, email: 'existing@example.test', role: 'viewer', sections: ['users'], can_manage: true, protected: false },
        { user_id: 6, email: 'owner@example.test', role: 'admin', sections, can_manage: false, protected: true }
    ];
    fillTeamPassword(app); app.editTeamMember(5); assertPasswordFieldsEmpty(app);
    fillTeamPassword(app); app.editTeamMember(6); assertPasswordFieldsEmpty(app);
    fillTeamPassword(app); app.resetTeamForm(); assertPasswordFieldsEmpty(app);
    fillTeamPassword(app); app.applyAdminAccess(access('viewer', ['ai'])); assertPasswordFieldsEmpty(app);
    fillTeamPassword(app); app.showAuth(); assertPasswordFieldsEmpty(app);
});

test('Team list stores only credential presence metadata and never credentials', async () => {
    const app = setup(() => jsonResponse({ members: [
        { user_id: 5, email: 'one@example.test', role: 'viewer', sections: ['users'], has_console_password: true, console_password: 'Should-Never-Be-Cached-5!' },
        { user_id: 6, email: 'two@example.test', role: 'viewer', sections: ['users'], has_console_password: false }
    ] }));
    await app.loadTeam();
    assert.match(app.refs.teamTableBody.innerHTML, /Console password set/);
    assert.match(app.refs.teamTableBody.innerHTML, /Existing Rilono password/);
    assert.doesNotMatch(app.refs.teamTableBody.innerHTML, /Should-Never/);
    assert.doesNotMatch(JSON.stringify(app.state), /Should-Never|"console_password"/);
});

test('console login uses JSON and the dedicated cookie route with no token fallback', async () => {
    const grant = access('viewer', ['ai']);
    const app = setup((url) => jsonResponse(url === '/api/admin/access' ? grant : {}), null);
    vm.runInContext('loadActiveTab = async () => {};', app.context);
    app.refs.loginEmail.value = ' member@example.test ';
    app.refs.loginPassword.value = 'Synthetic-Login-8!';
    await app.handleLoginSubmit({ preventDefault() {} });
    assert.deepEqual(app.requests.map((request) => request.url), ['/api/admin-auth/login', '/api/admin/access']);
    assert.deepEqual(JSON.parse(app.requests[0].options.body), { email: 'member@example.test', password: 'Synthetic-Login-8!' });
    assert.equal(app.requests[0].options.headers['Content-Type'], 'application/json');
    for (const request of app.requests) {
        assert.equal(request.options.headers['X-Admin-Console-Session'], 'required');
        assert.equal(request.options.credentials, 'same-origin');
        assert.equal(request.options.headers.Authorization, undefined);
    }
    assert.equal(app.state.currentUser.id, 17);
    assert.equal(app.refs.loginPassword.value, '');
    assert.doesNotMatch(JSON.stringify(app.state), /Synthetic-Login-8!/);
});

test('a login response token cannot bypass failure to establish a dedicated console cookie', async () => {
    const app = setup((url) => url === '/api/admin-auth/login' ? jsonResponse({ access_token: 'must-not-use-this-token' }) : jsonResponse({ detail: 'Console session required' }, 401), null);
    app.refs.loginEmail.value = 'member@example.test'; app.refs.loginPassword.value = 'Synthetic-Login-8!';
    await app.handleLoginSubmit({ preventDefault() {} });
    assert.equal(app.requests.length, 2);
    assert.equal(app.state.currentUser, null);
    assert.doesNotMatch(JSON.stringify(app.state), /must-not-use/);
    assert.equal(app.refs.loginPassword.value, '');
});

test('failed login clears password and never signs in through the main Rilono endpoint', async () => {
    for (const networkFailure of [false, true]) {
        const app = setup(() => {
            if (networkFailure) throw new Error('Transport failed');
            return jsonResponse({ detail: 'Invalid credentials' }, 401);
        }, null);
        app.refs.loginEmail.value = 'member@example.test'; app.refs.loginPassword.value = 'Synthetic-Login-8!';
        await app.handleLoginSubmit({ preventDefault() {} });
        assert.equal(app.refs.loginPassword.value, '');
        assert.deepEqual(app.requests.map((request) => request.url), ['/api/admin-auth/login']);
    }
});

test('logout clears console and shield sessions without touching the main Rilono logout', async () => {
    const app = setup(() => jsonResponse({}));
    fillTeamPassword(app); app.refs.loginPassword.value = 'Synthetic-Login-8!';
    await app.handleLogout();
    assert.deepEqual(app.requests.map((request) => request.url), ['/api/admin/turnstile/clear', '/api/admin-auth/logout']);
    assertPasswordFieldsEmpty(app); assert.equal(app.refs.loginPassword.value, '');
    assert.equal(app.state.currentUser, null); assert.equal(app.state.access, null);
    app.requests.forEach((request) => {
        assert.equal(request.options.headers['X-Admin-Console-Session'], 'required');
        assert.equal(request.options.headers.Authorization, undefined);
    });
});

test('every privileged request requires the console cookie even when called without prebuilt headers', async () => {
    const app = setup(() => jsonResponse({}));
    await app.adminFetch('/api/admin/users');
    assert.deepEqual(plain(app.requests[0].options.headers), { 'X-Admin-Console-Session': 'required' });
    assert.equal(app.buildAuthHeaders().Authorization, undefined);
});
