const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/admin_console.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../static/admin_console.html'), 'utf8');
const jsonResponse = (payload, status = 200) => ({ ok: status < 400, status, headers: { get() {} }, json: async () => payload });
const plain = (value) => JSON.parse(JSON.stringify(value));

function access(role = 'viewer', sections = ['ai']) {
    return { user: { id: 17, email: 'member@example.test', full_name: 'Console Member', is_admin: false, is_developer: false },
        role, sections, can_manage_team: false, can_provision_enterprise: false,
        can_write_sections: role === 'viewer' ? [] : sections, can_delete_sections: role === 'admin' ? sections : [] };
}

const me = { id: 17, name: 'Console Member', email: 'member@example.test', has_access: true };
const boss = { id: 5, name: 'Boss', email: 'boss@example.test', has_access: true };
const other = { id: 9, name: 'Other', email: 'other@example.test', has_access: true };

function task(id, overrides = {}) {
    return { id, title: `Task ${id}`, description: '', status: 'pending', priority: 'medium', due_date: null,
        assignee: me, created_by: boss, created_at: '2026-10-20T10:00:00+00:00', updated_at: '2026-10-20T10:00:00+00:00',
        status_changed_at: '2026-10-20T10:00:00+00:00', note_count: 0, can_edit: true, can_delete: false, ...overrides };
}

function element(id = '') {
    let html = '';
    let text = '';
    return { id, value: '', hidden: false, disabled: false, checked: false, dataset: {}, attributes: {}, children: [],
        classList: { toggle() {}, add() {}, remove() {}, contains: () => false }, style: {},
        setAttribute(name, value) { this.attributes[name] = String(value); },
        getAttribute(name) { return this.attributes[name]; },
        hasAttribute(name) { return name in this.attributes; },
        addEventListener() {}, reset() {}, focus() { this.focused = true; }, scrollIntoView() {},
        querySelector() { return null; },
        querySelectorAll() { return []; },
        get textContent() { return text; },
        set textContent(value) { text = String(value); html = ''; },
        get innerHTML() { return html || text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); },
        set innerHTML(value) { html = value; text = ''; } };
}

function setup(fetchImpl, initial = access()) {
    const elements = new Map();
    const requests = [];
    const get = (id) => { if (!elements.has(id)) elements.set(id, element(id)); return elements.get(id); };
    const context = vm.createContext({
        document: { getElementById: get, createElement: () => element(), addEventListener() {},
            querySelectorAll() { return []; }, querySelector() { return null; }, body: element('body') },
        window: { matchMedia: () => ({ matches: false }), scrollTo() {} },
        URLSearchParams, Blob, URL, setTimeout, clearTimeout, console: { error() {} },
        fetch: async (url, options) => { requests.push({ url, options }); return fetchImpl ? fetchImpl(url, options) : jsonResponse({}); }
    });
    vm.runInContext(`${source}\n;globalThis.ui = { state, refs, applyAdminAccess, renderActiveTab, handleTabSwitch, loadActiveTab,
        canAccessSection, canWriteSection, canDeleteSection, adminFetch, clearPrivilegedState, showAuth,
        loadTasks, renderTaskBoard, taskInScope, openTaskDetail, renderTaskDetail, applyTaskDetail, patchTask, moveTaskStatus,
        handleTaskFieldChange, handleTaskFieldKeydown, handleTaskFieldBlur, commitTaskField, readTaskCreateForm, refreshTaskBadge, renderTaskBadge, describeTaskEvent, renderTaskCard };
        confirmDialog = async () => true; promptDialog = async () => '';`, context);
    context.ui.state.authToken = 'test-cookie-token';
    if (initial) context.ui.applyAdminAccess(initial);
    return { ...context.ui, context, get, requests };
}

const board = (tasks, extra = {}) => ({ me: 17, can_view_all: false, members: [boss, me, other], tasks, closed_total: 0, truncated: false, ...extra });

test('every console member gets the Tasks tab, even a Viewer whose only section is AI Costs', () => {
    const app = setup(null, access('viewer', ['ai']));
    assert.equal(app.canAccessSection('tasks'), true);
    assert.equal(app.canWriteSection('tasks'), true);
    assert.equal(app.canDeleteSection('tasks'), true);
    assert.equal(app.canWriteSection('ai'), false, 'data sections keep their role rules');
    assert.equal(app.refs.tasksTabBtn.hidden, false);
    assert.equal(app.state.activeTab, 'ai', 'landing tab is still the first data section');
    app.showAuth();
    assert.equal(app.canAccessSection('tasks'), false);
});

test('task requests are classified as the tasks section and still need console access', async () => {
    const app = setup(() => jsonResponse({}));
    assert.equal((await app.adminFetch('/api/admin/tasks/3', { method: 'DELETE' })).ok, true);
    assert.equal((await app.adminFetch('/api/admin/tasks', { method: 'POST' })).ok, true);
    assert.equal(app.requests.length, 2);
    app.showAuth();
    assert.equal((await app.adminFetch('/api/admin/tasks')).status, 403);
    assert.equal(app.requests.length, 2);
});

test('the tab is not offered as a grantable Team section', () => {
    assert.doesNotMatch(source.match(/const ADMIN_SECTIONS = \[[^\]]+\]/)[0], /tasks/);
    assert.match(html, /data-admin-group="tasks team"/);
    assert.match(html, /id="adminTasksTabBtn"[^>]+data-tab="tasks"/);
});

test('board loads, scopes split work assigned to me from work I handed out, and the badge counts open work', async () => {
    const tasks = [task(1), task(2, { status: 'done' }), task(3, { assignee: other, created_by: me }), task(4, { status: 'closed' }),
        task(5, { assignee: me, created_by: me, status: 'on_hold' })];
    const app = setup(() => jsonResponse(board(tasks)));
    await app.loadTasks();
    assert.equal(app.state.tasks.loaded, true);
    assert.deepEqual(app.state.tasks.items.filter((item) => app.taskInScope(item, 'mine')).map((item) => item.id), [1, 2, 4, 5]);
    assert.deepEqual(app.state.tasks.items.filter((item) => app.taskInScope(item, 'created')).map((item) => item.id), [3]);
    assert.equal(app.refs.tasksNavBadge.textContent, '2');
    assert.equal(app.refs.tasksNavBadge.hidden, false);
    assert.equal(app.refs.tasksTabBtn.attributes['aria-label'], 'Tasks, 2 open assigned to you');
    assert.equal(app.refs.taskScopeAllLabel.textContent, 'All my tasks');
    assert.match(app.refs.taskBoard.innerHTML, /data-drop-status="on_hold"/);
    assert.doesNotMatch(app.refs.taskBoard.innerHTML, /data-drop-status="closed"/, 'Closed column is opt-in');
});

test('task text is escaped on cards and in the timeline', () => {
    const app = setup();
    app.state.tasks.me = 17;
    const card = app.renderTaskCard(task(7, { title: '<img src=x onerror=alert(1)>', created_by: { ...boss, name: '<b>Boss</b>' } }));
    assert.doesNotMatch(card, /<img|<b>/);
    assert.match(card, /&lt;img/);
    const line = app.describeTaskEvent({ kind: 'status', from_label: '<i>a</i>', to_label: 'On hold' });
    assert.doesNotMatch(line, /<i>/);
    assert.equal(app.describeTaskEvent({ kind: 'assignee', from: '5', to: '17', from_label: 'Boss', to_label: 'Console Member' }),
        'reassigned it from <strong>Boss</strong> to <strong>you</strong>');
});

test('the create form sends only the task fields, trimmed, with an explicit unassigned null', () => {
    const app = setup();
    const fields = { title: { value: '  Ship it  ' }, description: { value: '   ' }, assignee_user_id: { value: '' },
        priority: { value: 'p0' }, due_date: { value: '' } };
    const form = { querySelector: (selector) => fields[/name="([^"]+)"/.exec(selector)[1]] };
    assert.deepEqual(plain(app.readTaskCreateForm(form)),
        { title: 'Ship it', description: null, assignee_user_id: null, priority: 'medium', due_date: null });
    fields.title.value = '   ';
    assert.throws(() => app.readTaskCreateForm(form), /title/);
});

test('dragging to On hold asks why; cancelling leaves the task where it was and sends nothing', async () => {
    const app = setup(() => jsonResponse(board([task(1)])));
    await app.loadTasks();
    const before = app.requests.length;
    vm.runInContext('promptDialog = async () => null;', app.context);
    await app.moveTaskStatus(1, 'on_hold');
    assert.equal(app.requests.length, before);
    assert.equal(app.state.tasks.items[0].status, 'pending');
});

test('a status move sends the reason with it, and a failed save puts the card back', async () => {
    let fail = false;
    const app = setup((url, options) => {
        if (options?.method === 'PATCH') return fail ? jsonResponse({ detail: 'Nope' }, 422)
            : jsonResponse({ visible: true, task: task(1, { status: 'on_hold', note_count: 1 }), timeline: [] });
        return jsonResponse(board([task(1)]));
    });
    await app.loadTasks();
    vm.runInContext('promptDialog = async () => "  Waiting on the bank  ";', app.context);
    await app.moveTaskStatus(1, 'on_hold');
    const patch = app.requests.find((request) => request.options?.method === 'PATCH');
    assert.equal(patch.url, '/api/admin/tasks/1');
    assert.deepEqual(JSON.parse(patch.options.body), { status: 'on_hold', note: 'Waiting on the bank' });
    assert.equal(app.state.tasks.items[0].status, 'on_hold');
    fail = true;
    await app.moveTaskStatus(1, 'done');
    assert.equal(app.state.tasks.items[0].status, 'on_hold');
    assert.equal(app.refs.taskError.textContent, 'Nope');
    assert.equal(app.state.tasks.saving, false);
});

test('handing a task you did not create to someone else asks first, then drops it from your board', async () => {
    const app = setup((url, options) => options?.method === 'PATCH'
        ? jsonResponse({ visible: false, task: null, timeline: [] })
        : jsonResponse(board([task(1)])));
    await app.loadTasks();
    app.state.tasks.openId = 1;
    app.state.tasks.detail = { task: task(1), timeline: [] };
    let asked = 0;
    vm.runInContext('confirmDialog = async () => { globalThis.asked = (globalThis.asked || 0) + 1; return false; };', app.context);
    const control = { dataset: { taskField: 'assignee_user_id' }, value: '9' };
    await app.commitTaskField(control);
    asked = app.context.asked;
    assert.equal(asked, 1);
    assert.equal(control.value, '17', 'a declined hand-off restores the select');
    assert.equal(app.requests.some((request) => request.options?.method === 'PATCH'), false);
    vm.runInContext('confirmDialog = async () => true;', app.context);
    control.value = '9';
    await app.commitTaskField(control);
    assert.deepEqual(JSON.parse(app.requests.find((request) => request.options?.method === 'PATCH').options.body), { assignee_user_id: 9 });
    assert.equal(app.state.tasks.items.length, 0);
    assert.equal(app.state.tasks.openId, null);
});

test('signing out or an access change wipes task data and in-flight results', async () => {
    let resolve;
    const app = setup(() => new Promise((done) => { resolve = done; }));
    const pending = app.loadTasks();
    await Promise.resolve(); await Promise.resolve();
    app.applyAdminAccess(access('editor', ['users']));
    resolve(jsonResponse(board([task(1)])));
    await pending;
    assert.equal(app.state.tasks.items.length, 0);
    assert.equal(app.state.tasks.loaded, false);
    app.state.tasks.items = [task(2)];
    app.refs.tasksNavBadge.textContent = '3';
    app.showAuth();
    assert.equal(app.state.tasks.items.length, 0);
    assert.equal(app.refs.tasksNavBadge.hidden, true);
});

test('other tabs refresh the badge from the summary endpoint without loading the board', async () => {
    const app = setup((url) => jsonResponse(url.endsWith('/summary') ? { assigned_open: 120, assigned_overdue: 1 } : {}), access('viewer', ['ai']));
    vm.runInContext('loadAiUsage = async () => {};', app.context);
    await app.loadActiveTab();
    await new Promise((done) => setTimeout(done, 0));
    assert.deepEqual(app.requests.map((request) => request.url), ['/api/admin/tasks/summary']);
    assert.equal(app.refs.tasksNavBadge.textContent, '99+');
});

test('typing a due date saves once, on Enter or leaving the field, never per keystroke', async () => {
    const app = setup((url, options) => options?.method === 'PATCH'
        ? jsonResponse({ visible: true, task: task(1, { due_date: JSON.parse(options.body).due_date }), timeline: [] })
        : jsonResponse(board([task(1, { due_date: '2026-11-02' })])));
    await app.loadTasks();
    app.state.tasks.openId = 1;
    app.state.tasks.detail = { task: task(1, { due_date: '2026-11-02' }), timeline: [] };
    const control = { dataset: { taskField: 'due_date' }, value: '2026-11-02', validity: { badInput: false } };
    const event = (key) => ({ key, preventDefault() {}, target: { closest: () => control } });
    const patches = () => app.requests.filter((request) => request.options?.method === 'PATCH');
    // Chrome fires `change` with a "complete" value after every digit: 2026-01-02, 0002-12-25 ...
    for (const [key, value] of [['1', '2026-01-02'], ['2', '2026-12-02'], ['2', '0002-12-25'], ['7', '2027-12-25']]) {
        app.handleTaskFieldKeydown(event(key));
        control.value = value;
        app.handleTaskFieldChange(event());
    }
    await new Promise((done) => setTimeout(done, 0));
    assert.equal(patches().length, 0, 'nothing is saved while typing');
    app.handleTaskFieldBlur(event());
    await new Promise((done) => setTimeout(done, 0));
    assert.equal(patches().length, 1);
    assert.deepEqual(JSON.parse(patches()[0].options.body), { due_date: '2027-12-25' });
    // A half-typed year is refused locally rather than sent.
    app.state.tasks.detail = { task: task(1, { due_date: '2027-12-25' }), timeline: [] };
    control.value = '0202-12-25';
    app.handleTaskFieldKeydown(event('2'));
    app.handleTaskFieldKeydown(event('Enter'));
    await new Promise((done) => setTimeout(done, 0));
    assert.equal(patches().length, 1);
    assert.equal(control.value, '2027-12-25');
});

test('a mouse pick on a select still saves immediately', async () => {
    const app = setup((url, options) => options?.method === 'PATCH'
        ? jsonResponse({ visible: true, task: task(1, { priority: 'high' }), timeline: [] })
        : jsonResponse(board([task(1)])));
    await app.loadTasks();
    app.state.tasks.openId = 1;
    app.state.tasks.detail = { task: task(1), timeline: [] };
    const control = { dataset: { taskField: 'priority' }, value: 'high' };
    app.handleTaskFieldChange({ target: { closest: () => control } });
    await new Promise((done) => setTimeout(done, 0));
    const patch = app.requests.find((request) => request.options?.method === 'PATCH');
    assert.deepEqual(JSON.parse(patch.options.body), { priority: 'high' });
});

test('signing out resets the toolbar roster, not just the board', async () => {
    const app = setup(() => jsonResponse(board([task(1)])));
    await app.loadTasks();
    assert.match(app.refs.taskPerson.innerHTML, /Boss/);
    app.showAuth();
    assert.doesNotMatch(app.refs.taskPerson.innerHTML, /Boss/);
    assert.equal(app.refs.taskScopeAllLabel.textContent, 'All my tasks');
});

test('the dialog is focusable and its close button is not confused with closing the task', () => {
    assert.match(html, /class="admin-modal tasks-modal" role="dialog"[^>]+tabindex="-1"/);
    assert.match(html, /id="adminTaskModalClose"[^>]+aria-label="Close"/);
});
