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
        URLSearchParams, Blob, File, FormData, URL, setTimeout, clearTimeout, console: { error() {} },
        fetch: async (url, options) => { requests.push({ url, options }); return fetchImpl ? fetchImpl(url, options) : jsonResponse({}); }
    });
    vm.runInContext(`${source}\n;globalThis.ui = { state, refs, applyAdminAccess, renderActiveTab, handleTabSwitch, loadActiveTab,
        canAccessSection, canWriteSection, canDeleteSection, adminFetch, clearPrivilegedState, showAuth,
        loadTasks, renderTaskBoard, taskInScope, openTaskDetail, renderTaskDetail, applyTaskDetail, patchTask, moveTaskStatus,
        handleTaskFieldChange, handleTaskFieldKeydown, handleTaskFieldBlur, commitTaskField, readTaskCreateForm, refreshTaskBadge, renderTaskBadge, describeTaskEvent, renderTaskCard,
        submitTaskCreate, queueTaskFiles, uploadToOpenTask, handleTaskPaste, closeTaskModal, removeTaskFile };
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

test('the assignee cannot close a task: Closed is disabled, explained, and refused on drop', async () => {
    const app = setup(() => jsonResponse(board([task(1, { status: 'done', can_close: false })])));
    await app.loadTasks();
    const before = app.requests.length;
    await app.moveTaskStatus(1, 'closed');
    assert.equal(app.requests.length, before, 'nothing is sent');
    assert.match(app.refs.taskError.textContent, /Only Boss can close this task\. Mark it Done/);
    assert.equal(app.state.tasks.items[0].status, 'done');
    app.state.tasks.openId = 1;
    app.state.tasks.detail = { task: task(1, { status: 'done', can_close: false }), timeline: [] };
    app.renderTaskDetail();
    const body = app.refs.taskModalBody.innerHTML;
    assert.match(body, /<option value="closed"\s+disabled>/);
    assert.match(body, /<option value="in_progress"\s+>/, 'everything short of Closed stays available');
    assert.match(body, /When it’s finished, mark it Done\. Boss reviews it and closes it\./);
});

test('a closed task is locked for the assignee but reopenable by the assigner', () => {
    const app = setup();
    app.state.tasks.me = 17;
    app.state.tasks.detail = { task: task(1, { status: 'closed', can_close: false }), timeline: [] };
    app.renderTaskDetail();
    assert.match(app.refs.taskModalBody.innerHTML, /data-task-field="status" disabled data-task-locked/);
    assert.match(app.refs.taskModalBody.innerHTML, /Only Boss can reopen it/);
    app.state.tasks.detail = { task: task(1, { status: 'closed', can_close: true, assignee: other, created_by: me }), timeline: [] };
    app.renderTaskDetail();
    assert.doesNotMatch(app.refs.taskModalBody.innerHTML, /data-task-field="status" disabled/);
});

test('work handed back as Done is flagged "Ready to close" for the assigner only', () => {
    const app = setup();
    app.state.tasks.me = 17;
    const handedBack = task(3, { status: 'done', can_close: true, assignee: other, created_by: me });
    assert.match(app.renderTaskCard(handedBack), /Ready to close/);
    assert.doesNotMatch(app.renderTaskCard(task(4, { status: 'done', can_close: false })), /Ready to close/);
    app.state.tasks.detail = { task: handedBack, timeline: [] };
    app.renderTaskDetail();
    assert.match(app.refs.taskModalBody.innerHTML, /Other marked this Done\. Close it, or move it back/);
});

// ---- Attachments ----------------------------------------------------------------

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3, 4]);
const fileOf = (name, bytes = PNG, type = 'image/png') => new File([bytes], name, { type });
const blobResponse = (blob) => ({ ok: true, status: 200, headers: { get() {} }, json: async () => ({}), blob: async () => blob });
const tick = () => new Promise((done) => setTimeout(done, 0));
const detailOf = (item, attachments = []) => ({ visible: true, task: item, attachments, timeline: [] });

function createForm(title = 'Fix the export') {
    const fields = { title: { value: title }, description: { value: '' }, assignee_user_id: { value: '5' },
        priority: { value: 'medium' }, due_date: { value: '' } };
    const submit = { textContent: 'Create task', isConnected: true };
    return { submit, querySelector: (selector) => (selector.includes('submit') ? submit : fields[/name="([^"]+)"/.exec(selector)?.[1]] || null) };
}

function attachment(id, overrides = {}) {
    return { id, filename: `file-${id}.png`, ext: 'png', is_image: true, size: PNG.length, size_label: '12 B',
        url: `/api/admin/tasks/5/attachments/${id}`, uploaded_by: boss, created_at: '2026-10-24T09:00:00+00:00', can_delete: false, ...overrides };
}

test('cards show how many files a task has, and the timeline names them safely', () => {
    const app = setup();
    app.state.tasks.me = 17;
    const card = app.renderTaskCard(task(8, { attachment_count: 3 }));
    assert.match(card, /title="3 files"/);
    assert.match(card, /3 files attached\./);
    assert.doesNotMatch(app.renderTaskCard(task(9)), /files? attached/);
    assert.equal(app.describeTaskEvent({ kind: 'attachment', to: 'a.png', to_label: '<b>a.png</b>' }), 'attached <strong>&lt;b&gt;a.png&lt;/b&gt;</strong>');
    assert.equal(app.describeTaskEvent({ kind: 'attachment_removed', from: 'old.pdf', from_label: 'old.pdf' }), 'removed the file <strong>old.pdf</strong>');
});

test('the create form only queues files the server will accept, using the board’s limits', async () => {
    const app = setup(() => jsonResponse(board([], { attachment_limits: { max_files: 2, max_file_bytes: 64, max_total_bytes: 100, extensions: ['png', 'pdf'] } })));
    await app.loadTasks();
    app.queueTaskFiles([fileOf('one.png'), fileOf('tool.exe'), fileOf('huge.pdf', new Uint8Array(65), 'application/pdf'),
        fileOf('empty.png', new Uint8Array(0)), fileOf('two.pdf', new Uint8Array(40), 'application/pdf'), fileOf('three.png')]);
    assert.deepEqual(plain(app.state.tasks.createFiles.map((item) => item.file.name)), ['one.png', 'two.pdf']);
    assert.match(app.state.tasks.createFiles[0].preview, /^blob:/, 'images get a local preview');
    assert.equal(app.state.tasks.createFiles[1].preview, '', 'other files do not');
    app.closeTaskModal();
    assert.equal(app.state.tasks.createFiles.length, 0, 'closing the dialog lets the queued files go');
});

test('a new task’s files upload one by one right after it is created', async () => {
    const created = task(41, { assignee: boss, created_by: me });
    const order = [];
    const app = setup((url, options) => {
        if (url === '/api/admin/tasks' && options?.method === 'POST') { order.push('task'); return jsonResponse(detailOf(created), 201); }
        if (url === '/api/admin/tasks/41/attachments') {
            const file = options.body.get('file');
            order.push(file.name);
            return jsonResponse(detailOf({ ...created, attachment_count: order.length - 1 }), 201);
        }
        return jsonResponse(board([]));
    });
    await app.loadTasks();
    app.queueTaskFiles([fileOf('before.png'), fileOf('notes.txt', new Uint8Array([104, 105]), 'text/plain')]);
    const form = createForm();
    await app.submitTaskCreate(form);
    assert.deepEqual(order, ['task', 'before.png', 'notes.txt']);
    const upload = app.requests.find((request) => request.url.endsWith('/attachments'));
    assert.equal(upload.options.method, 'POST');
    assert.equal(upload.options.headers['Content-Type'], undefined, 'the browser sets the multipart boundary');
    assert.equal(upload.options.headers['X-Admin-Console-Session'], 'required');
    assert.equal(app.state.tasks.items.find((item) => item.id === 41).attachment_count, 2);
    assert.equal(app.state.tasks.createFiles.length, 0);
    assert.equal(app.state.tasks.saving, false);
    assert.equal(app.refs.flash.textContent, 'Task assigned to Boss with 2 files. They’ll get an email.');
});

test('when a file fails after the task exists, the dialog moves to that task instead of offering Create again', async () => {
    const created = task(42, { assignee: boss, created_by: me });
    const app = setup((url, options) => {
        if (url === '/api/admin/tasks' && options?.method === 'POST') return jsonResponse(detailOf(created), 201);
        if (url.endsWith('/attachments')) return jsonResponse({ detail: 'Each file can be up to 25 MB.' }, 400);
        if (url === '/api/admin/tasks/42') return jsonResponse(detailOf(created));
        return jsonResponse(board([]));
    });
    await app.loadTasks();
    app.queueTaskFiles([fileOf('screen.png')]);
    const fileError = element('fileError');
    app.refs.taskModalBody.querySelector = (selector) => (selector === '[data-task-file-error]' ? fileError : null);
    await app.submitTaskCreate(createForm());
    assert.equal(app.requests.filter((request) => request.url === '/api/admin/tasks' && request.options?.method === 'POST').length, 1);
    assert.equal(app.state.tasks.openId, 42);
    assert.match(app.refs.taskModalBody.innerHTML, /<h4 id="adminTaskFilesHeading">Attachments<\/h4>/);
    assert.equal(fileError.textContent, 'Task created, but “screen.png” couldn’t be attached: Each file can be up to 25 MB. Add it again here.');
    assert.equal(app.state.tasks.saving, false);
});

test('the detail view escapes file names, offers Remove only where allowed, and loads thumbnails through the console', async () => {
    const blob = new Blob([PNG], { type: 'image/png' });
    const app = setup((url) => (url.includes('/attachments/') ? blobResponse(blob) : jsonResponse({})));
    app.state.tasks.me = 17;
    app.state.tasks.openId = 5;
    app.state.tasks.detail = { task: task(5), timeline: [], attachments: [
        attachment(3, { filename: '<img src=x onerror=alert(1)>.png' }),
        attachment(4, { filename: 'payouts.csv', ext: 'csv', is_image: false, uploaded_by: me, can_delete: true })] };
    app.renderTaskDetail();
    const body = app.refs.taskModalBody.innerHTML;
    assert.doesNotMatch(body, /<img src=x/);
    assert.match(body, /&lt;img src=x onerror=alert\(1\)&gt;\.png/);
    assert.match(body, /data-task-action="preview-file" data-file-id="3"/);
    assert.match(body, /data-task-action="download-file" data-file-id="4"/);
    assert.deepEqual([...body.matchAll(/data-task-action="remove-file" data-file-id="(\d+)"/g)].map((match) => match[1]), ['4']);
    assert.match(body, /<span class="tasks-file-badge" aria-hidden="true">csv<\/span>/);
    await tick();
    assert.deepEqual(app.requests.map((request) => request.url), ['/api/admin/tasks/5/attachments/3'], 'only images are fetched for thumbnails');
    assert.equal(app.requests[0].options.headers['X-Admin-Console-Session'], 'required');
    assert.match(app.state.tasks.fileUrls.get(3), /^blob:/);
    app.closeTaskModal();
    assert.equal(app.state.tasks.fileUrls.size, 0, 'previews are released with the dialog');
});

test('an empty task invites files when you can edit it, and says so plainly when you cannot', () => {
    const app = setup();
    app.state.tasks.me = 17;
    app.state.tasks.detail = { task: task(6), timeline: [], attachments: [] };
    app.renderTaskDetail();
    assert.match(app.refs.taskModalBody.innerHTML, /data-task-action="pick-files">Choose files<\/button> or drop them here\. Paste a screenshot/);
    assert.match(app.refs.taskModalBody.innerHTML, /data-task-file-input accept="[^"]*\.png[^"]*"/);
    app.state.tasks.detail = { task: task(6, { can_edit: false }), timeline: [], attachments: [] };
    app.renderTaskDetail();
    assert.match(app.refs.taskModalBody.innerHTML, /No files attached\./);
    assert.doesNotMatch(app.refs.taskModalBody.innerHTML, /data-task-file-input/);
});

test('files dropped on an open task upload at once and refresh it; refused files never leave the browser', async () => {
    const uploaded = [];
    const app = setup((url, options) => {
        if (url === '/api/admin/tasks/5/attachments') {
            uploaded.push(options.body.get('file').name);
            return jsonResponse(detailOf(task(5, { attachment_count: 1 }), [attachment(11, { filename: uploaded[0] })]), 201);
        }
        return jsonResponse(board([task(5)]));
    });
    await app.loadTasks();
    app.state.tasks.openId = 5;
    app.state.tasks.detail = { task: task(5), timeline: [], attachments: [] };
    await app.uploadToOpenTask([fileOf('bug.png'), fileOf('virus.exe')]);
    assert.deepEqual(uploaded, ['bug.png']);
    assert.equal(app.state.tasks.detail.attachments[0].filename, 'bug.png');
    assert.equal(app.state.tasks.items[0].attachment_count, 1);
    assert.equal(app.state.tasks.saving, false);
});

test('a pasted screenshot is attached and named; text pasted into a field stays text', () => {
    const app = setup();
    const form = element('createForm');
    app.refs.taskModal.hidden = false;
    app.refs.taskLightbox.hidden = true;
    app.refs.taskModalBody.querySelector = (selector) => (selector === '[data-task-form="create"]' ? form : null);
    const paste = ({ text = '', inField = true, files = [fileOf('image.png')] } = {}) => {
        const event = { prevented: false, preventDefault() { this.prevented = true; },
            target: { closest: () => (inField ? element('field') : null) },
            clipboardData: { files, items: [], types: ['Files'], getData: () => text } };
        app.handleTaskPaste(event);
        return event;
    };
    const screenshot = paste();
    assert.equal(screenshot.prevented, true);
    assert.match(app.state.tasks.createFiles[0].file.name, /^Screenshot \d{4}-\d\d-\d\d at \d\d\.\d\d\.\d\d\.png$/);
    // Copying cells from a spreadsheet brings a picture of them along: in a text field, paste the text.
    const cells = paste({ text: 'A1\tB1' });
    assert.equal(cells.prevented, false);
    assert.equal(app.state.tasks.createFiles.length, 1);
    assert.equal(paste({ text: 'A1\tB1', inField: false }).prevented, true);
    assert.equal(paste({ files: [] }).prevented, false, 'plain text pastes are untouched');
    assert.equal(paste({ files: [fileOf('diagram.png')] }).prevented, true);
    assert.equal(app.state.tasks.createFiles.at(-1).file.name, 'diagram.png', 'real file names are kept');
});

test('removing a file asks first and refreshes the task', async () => {
    const app = setup((url, options) => (options?.method === 'DELETE'
        ? jsonResponse(detailOf(task(5), []))
        : jsonResponse(board([task(5, { attachment_count: 1 })]))));
    await app.loadTasks();
    app.state.tasks.openId = 5;
    app.state.tasks.detail = { task: task(5), timeline: [], attachments: [attachment(7, { can_delete: true })] };
    vm.runInContext('confirmDialog = async () => false;', app.context);
    await app.removeTaskFile(7);
    assert.equal(app.requests.some((request) => request.options?.method === 'DELETE'), false);
    vm.runInContext('confirmDialog = async () => true;', app.context);
    await app.removeTaskFile(7);
    const removal = app.requests.find((request) => request.options?.method === 'DELETE');
    assert.equal(removal.url, '/api/admin/tasks/5/attachments/7');
    assert.deepEqual(plain(app.state.tasks.detail.attachments), []);
});

test('the image preview lives outside the blurred task overlay and has its own close control', () => {
    assert.match(html, /<div id="adminTaskLightbox" class="tasks-lightbox" role="dialog" aria-modal="true"[^>]*hidden>/);
    assert.ok(html.indexOf('id="adminTaskLightbox"') > html.indexOf('id="adminTaskModalBody"'));
    assert.match(html, /id="adminTaskLightboxClose"[^>]+aria-label="Close preview"/);
});
