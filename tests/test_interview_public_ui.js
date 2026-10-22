// The client's self-serve mock interview page (static/interview.html) against the server-side
// session API (pricing v2, 2026-10-22): the start response's run_token is kept in memory and
// presented on every turn and on the one feedback report; the page never sends its own
// transcript or the officer's decision; a 409 on a turn goes to the report, and a run the
// server says is over (409/404 on the report, or a 400 for a missing run token) hands back the
// Start button — while a report refused because no answer was stored keeps the live run.
//
// The page's inline <script> runs in a vm with stub elements keyed by id (no real DOM).

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/interview.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
const source = scripts[scripts.length - 1];
assert.ok(source && source.includes('/api/enterprise/public/interview'), 'interview page script not found');

const API = '/api/enterprise/public/interview';
const TOKEN = 'invite-token-abc';
const jsonResponse = (payload, status = 200) => ({ ok: status < 400, status, json: async () => payload });
const flush = () => new Promise((resolve) => setImmediate(resolve));
async function settle(times = 8) { for (let i = 0; i < times; i += 1) await flush(); }

function classList() {
  const names = new Set();
  return {
    add(...n) { n.forEach((x) => names.add(x)); }, remove(...n) { n.forEach((x) => names.delete(x)); },
    toggle(name, force) { const on = force === undefined ? !names.has(name) : !!force; if (on) names.add(name); else names.delete(name); return on; },
    contains(name) { return names.has(name); },
  };
}
function element(id = '') {
  let markup = '';
  let text = '';
  return {
    id, value: '', disabled: false, className: '', placeholder: '', dataset: {}, style: {}, classList: classList(),
    get innerHTML() { return markup; }, set innerHTML(v) { markup = String(v); text = ''; },
    get textContent() { return text || markup.replace(/<[^>]*>/g, ''); }, set textContent(v) { text = String(v); markup = ''; },
    addEventListener() {}, removeEventListener() {}, appendChild(c) { markup += c.innerHTML || ''; return c; },
    querySelector() { return null; }, remove() {}, focus() {}, scrollIntoView() {}, setAttribute() {},
  };
}

function setup(chat, feedback) {
  const els = new Map();
  const get = (id) => { if (!els.has(id)) els.set(id, element(id)); return els.get(id); };
  const requests = [];
  const fetch = async (url, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : undefined;
    requests.push({ url, method: options.method || 'GET', body });
    if (url === `${API}/${TOKEN}`) return jsonResponse({ organization_name: 'Acme', destination_country: 'United Kingdom', visa_type: 'Student', remaining: 2, masked_email: 'a***@x.test' });
    if (url === `${API}/${TOKEN}/verify`) return jsonResponse({ session_token: 'sess-1', remaining: 2 });
    if (url === `${API}/chat`) return chat(body);
    if (url === `${API}/feedback`) return feedback(body);
    return jsonResponse({ detail: 'not stubbed' }, 404);
  };
  const document = {
    getElementById: get, querySelector: () => null, createElement: () => element(),
    addEventListener() {}, fullscreenElement: null,
  };
  const context = vm.createContext({
    document, window: {}, location: { pathname: `/interview/${TOKEN}` }, navigator: {},
    fetch, setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {}, console,
  });
  vm.runInContext(source, context);
  return { get, requests, context };
}

async function startChat(app) {
  await settle();
  const verify = app.get('verifyBtn');
  app.get('codeInput').value = '123456';
  verify.onclick.call(verify);
  await settle();
  app.get('startBtn').onclick();
  app.get('modeChatBtn').onclick();
  await settle();
}
async function answer(app, text) {
  app.get('answer').value = text;
  app.get('composer').onsubmit({ preventDefault() {} });
  await settle();
}
const posts = (app, suffix) => app.requests.filter((r) => r.url === `${API}${suffix}`).map((r) => r.body);

test('the run token from the start response is what every turn and the report present — no history, no decision', async () => {
  let turn = 0;
  const app = setup(
    (body) => {
      turn += 1;
      if (body.start) return jsonResponse({ reply: 'Why this university?', finished: false, questions_asked: 1, max_questions: 12, remaining: 1, run_token: 'run-xyz' });
      return jsonResponse({ reply: 'Thank you. INTERVIEW_COMPLETE', finished: true, decision: 'approved', questions_asked: 1, max_questions: 12, remaining: 1 });
    },
    () => jsonResponse({ feedback: '**Verdict:** Likely approved', verdict: 'Likely approved', decision: 'Approved', remaining: 1, emailed: true, masked_email: 'a***@x.test' }),
  );
  await startChat(app);
  const [start] = posts(app, '/chat');
  assert.deepEqual(start, { session_token: 'sess-1', start: true, mode: 'chat' });
  await answer(app, 'For its research groups.');
  const chats = posts(app, '/chat');
  assert.deepEqual(chats[1], { session_token: 'sess-1', run_token: 'run-xyz', message: 'For its research groups.', mode: 'chat' });
  const [report] = posts(app, '/feedback');
  assert.deepEqual(report, { session_token: 'sess-1', run_token: 'run-xyz', mode: 'chat' }, 'no history and no decision in the report request');
  assert.ok(app.get('feedback').innerHTML.includes('Visa approved'), "the officer's decision comes back from the server");
  assert.equal(turn, 2);
});

test('a 409 on a turn asks for the report; a report the server refuses (409) ends the run and offers Start again', async () => {
  const app = setup(
    (body) => (body.start
      ? jsonResponse({ reply: 'Opening question', finished: false, questions_asked: 1, max_questions: 12, remaining: 1, run_token: 'run-1' })
      : jsonResponse({ detail: 'This interview session has expired. Please start a new interview.' }, 409)),
    () => jsonResponse({ detail: 'This interview session has expired. Please start a new interview.' }, 409),
  );
  await startChat(app);
  await answer(app, 'My answer');
  assert.equal(posts(app, '/feedback').length, 1, '409 on the turn → one report request');
  assert.equal(posts(app, '/feedback')[0].run_token, 'run-1');
  assert.ok(app.get('feedback').innerHTML.includes('This interview session has expired'));
  assert.equal(app.get('startBtn').classList.contains('hidden'), false, 'Start is offered again (interviews remain)');
  assert.ok(/Session ended/.test(app.get('ivStatus').textContent));
});

test('a turn without a live run (400) ends the run with the server message instead of retrying', async () => {
  const app = setup(
    (body) => (body.start
      ? jsonResponse({ reply: 'Opening question', finished: false, questions_asked: 1, max_questions: 12, remaining: 1, run_token: 'run-2' })
      : jsonResponse({ detail: 'This interview session has expired. Please start a new interview.' }, 400)),
    () => jsonResponse({}, 500),
  );
  await startChat(app);
  await answer(app, 'Answer');
  assert.equal(posts(app, '/feedback').length, 0);
  assert.ok(app.get('iChatError').textContent.includes('This interview session has expired.'));
  assert.ok(app.get('iChatError').textContent.includes('You can start a new interview.'));
});

test('a first answer that failed (502) is not counted: Finish asks for an answer instead of ending the paid run', async () => {
  const app = setup(
    (body) => (body.start
      ? jsonResponse({ reply: 'Opening question', finished: false, questions_asked: 1, max_questions: 12, remaining: 1, run_token: 'run-xyz' })
      : jsonResponse({ detail: 'The interviewer ran into a problem. Please try again.' }, 502)),
    () => jsonResponse({ detail: 'Answer at least one question first.' }, 400),
  );
  await startChat(app);
  await answer(app, 'My first answer');
  app.get('endBtn').onclick();
  await settle();
  assert.equal(posts(app, '/feedback').length, 0, 'the server stored no answer, so no report is asked for');
  assert.ok(app.get('iChatError').textContent.includes('Answer at least one question first.'));
  assert.ok(!/Session ended/.test(app.get('ivStatus').textContent));
});

test('a report refused for want of an answer (400 with a live run) keeps the run: the next answer still presents its token', async () => {
  let release;
  let chats = 0;
  const app = setup(
    (body) => {
      if (body.start) return jsonResponse({ reply: 'Opening question', finished: false, questions_asked: 1, max_questions: 12, remaining: 1, run_token: 'run-xyz' });
      chats += 1;
      if (chats === 1) return new Promise((resolve) => { release = () => resolve(jsonResponse({ detail: 'Busy' }, 502)); });
      return jsonResponse({ reply: 'Next question', finished: false, questions_asked: 2, max_questions: 12, remaining: 1 });
    },
    () => jsonResponse({ detail: 'Answer at least one question first.' }, 400),
  );
  await startChat(app);
  await answer(app, 'My first answer');               // still waiting on the officer
  app.get('endBtn').onclick();                        // Finish is queued behind it
  release();
  await settle();
  assert.equal(posts(app, '/feedback').length, 1);
  assert.ok(!/Session ended/.test(app.get('ivStatus').textContent), 'the paid run is not thrown away');
  assert.equal(app.get('composer').classList.contains('hidden'), false, 'the student can answer again');
  await answer(app, 'My answer again');
  const last = posts(app, '/chat').pop();
  assert.deepEqual(last, { session_token: 'sess-1', run_token: 'run-xyz', message: 'My answer again', mode: 'chat' });
});
