/* No document HTML is executed. All evidence and source content use textContent. */
const $ = id => document.getElementById(id);
const state = {csrf: '', overview: null, agent: 'collection', cases: [], selected: new Set(), detail: null, gold: null, run: null, runs: []};
const tracks = {standard: '新規範', historical: '歷史格式', anomaly: '異常案例', workflow: '總管流程'};
const statuses = {draft: '待核准', approved: '已核准', returned: '已退回', queued: '排隊中', running: '執行中', completed: '執行完成', failed: '執行失敗', missing: '缺答案'};
const pct = x => x === null || x === undefined ? '—' : `${(x * 100).toFixed(1)}%`;
const json = value => JSON.stringify(value, null, 2);
const when = x => new Date(x * 1000).toLocaleString('zh-TW', {hour12: false});
function node(tag, text, cls) {const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e;}
function clear(id) {$(id).replaceChildren(); return $(id);}
function pill(text, tone = '') {return node('span', text, `pill ${tone}`);}
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; setTimeout(() => $('toast').hidden = true, 7000); }
const errors = {UNAPPROVED_ANSWERS_TRIAL_ONLY: '正式驗收前，請先逐例核准最新標準答案；現在仍可試跑。', LOGIN_REQUIRED: '請重新登入。', CSRF_REQUIRED: '登入狀態已更新，請重新整理頁面。', AGENT_NOT_IMPLEMENTED: '此 Agent 尚未實作，不能執行。', ANSWER_DECISION_IMMUTABLE_CREATE_NEW_VERSION: '既有裁定不能覆寫，請建立答案新版本。', INVALID_PASSWORD: '管理員密碼不正確。', CODE_VERSION_MISMATCH_CREATE_NEW_RUN: '程式已更新。舊執行保留，請建立新執行。'};
async function api(path, options = {}) {
  const r = await fetch('/api' + path, {credentials: 'same-origin', ...options, headers: {'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf, ...(options.headers || {})}});
  const value = await r.json();
  if (!r.ok) { if (r.status === 401) { $('workspace').hidden = true; $('login').hidden = false; } throw new Error(errors[value.detail] || (typeof value.detail === 'string' ? value.detail : json(value.detail))); }
  return value;
}
const post = (path, body) => api(path, {method: 'POST', body: JSON.stringify(body)});
function action(id, callback) {$(id).addEventListener('click', async () => {const button = $(id); button.disabled = true; try {await callback();} catch (error) {toast(error.message);} finally {button.disabled = ['approve','return'].includes(id) && state.gold?.status !== 'draft';}});}
function table(headers, rows) {const wrap = node('div', undefined, 'table-wrap'), t = node('table'), head = node('tr'); headers.forEach(x => head.append(node('th', x))); const h = node('thead'); h.append(head); t.append(h); const body = node('tbody'); rows.forEach(row => {const tr = node('tr'); row.forEach(x => tr.append(node('td', x))); body.append(tr);}); t.append(body); wrap.append(t); return wrap;}
function renderAgents() {
  const area = clear('agents');
  state.overview.agents.forEach((a, i) => {
    const b = node('button', undefined, `agent-card ${state.agent === a.id ? 'active' : ''}`);
    b.append(node('span', String(i + 1).padStart(2, '0'), 'number'), node('strong', a.name), pill(a.implemented ? (a.latest_run?.passed ? '此批達標' : '待驗收') : '待實作', a.implemented ? 'warn' : ''), node('small', a.implemented ? `${a.case_count} 案例 · ${a.approved_count} 已核准` : `${a.specs.length} 項案例規格`));
    b.addEventListener('click', () => selectAgent(a.id).catch(e => toast(e.message))); area.append(b);
  });
}
function scoreCards(run) {
  const area = clear('scoreboard');
  if (!run) {area.append(node('p', '尚無執行。先試跑取得真實基線，再核准標準答案。')); return;}
  Object.entries(run.tracks || {}).forEach(([track, m]) => {
    const card = node('div', undefined, 'score-card'); const h = node('h3', tracks[track] || track);
    h.append(pill(m.passed ? '此軌達標' : run.mode === 'trial' ? '試跑 · 不計達標' : '未達標', m.passed ? 'good' : 'warn')); card.append(h);
    const values = node('div', undefined, 'score-numbers');
    [[pct(m.precision), '自動正確率 ≥95%'], [pct(m.coverage), '自動覆蓋率 ≥80%'], [String(m.critical_errors), '關鍵錯誤 =0']].forEach(([v, l]) => {const d = node('div');d.append(node('b', v), node('span', l));values.append(d);});
    card.append(values, node('small', `完成 ${m.completed}/${m.required} · 自動 ${m.automatic} · 可判定 ${m.decidable} · 執行失敗 ${m.failed}`), node('small', `證據：${m.evidence_ok ? '完整' : '待核對'} ｜答案：${m.approved ? '全數已核准' : '未全數核准'}`)); area.append(card);
  });
}
async function overview() {state.overview = await api('/overview'); $('environment').textContent = state.overview.environment; $('engineering-link').href = state.overview.engineering.url; renderAgents();}
async function selectAgent(agent) {
  state.agent = agent; state.detail = null; state.gold = null; state.run = null; state.selected.clear();
  $('case-detail').hidden = true; $('empty-detail').hidden = false;
  const item = state.overview.agents.find(a => a.id === agent);
  $('agent-title').textContent = item.name; $('agent-scope').textContent = item.scope;
  const c = clear('contract'); c.append(node('p', '能力契約：' + item.capabilities.join(' / '))); const specs = node('details'); specs.append(node('summary', '查看代表性案例規格')); item.specs.forEach(s => specs.append(node('p', '• ' + s))); c.append(specs);
  $('run-suite').disabled = $('run-selected').disabled = !item.implemented;
  renderAgents(); await loadCases(); await loadRuns();
  if (state.runs.length) await showRun(state.runs[0].id); else {scoreCards(null); clear('run-summary'); $('manifest').textContent = '尚無執行。';}
  if (state.cases.length) await selectCase(state.cases[0].id);
}
async function loadCases() {state.cases = await api(`/cases?agent=${state.agent}&split=${$('split').value}`); renderCases();}
function renderCases() {
  const area = clear('cases'); $('case-count').textContent = `${state.cases.length} 件`;
  if (!state.cases.length) area.append(node('p', '尚未建立可執行案例。', 'empty'));
  state.cases.forEach(c => {const row = node('div', undefined, `case-row ${state.detail?.id === c.id ? 'active' : ''}`);const checkbox = node('input'); checkbox.type = 'checkbox'; checkbox.checked = state.selected.has(c.id); checkbox.setAttribute('aria-label', '勾選 ' + c.case_key); checkbox.addEventListener('change', () => checkbox.checked ? state.selected.add(c.id) : state.selected.delete(c.id)); const b = node('button', undefined, 'case-button'); b.append(node('small', `${c.case_key} · ${tracks[c.track]} · ${c.split === 'holdout' ? '保留' : '開發'}`), node('span', c.title), pill(`${statuses[c.answer_status]} · v${c.answer_version}`, c.answer_status === 'approved' ? 'good' : 'warn')); b.addEventListener('click', () => selectCase(c.id).catch(e => toast(e.message))); row.append(checkbox, b); area.append(row);});
}
async function selectCase(id, preferredAnswerId = null) {
  state.detail = await api(`/cases/${id}`); const c = state.detail;
  $('empty-detail').hidden = true; $('case-detail').hidden = false;
  $('case-title').textContent = c.title; $('case-meta').textContent = `${c.case_key} / ${tracks[c.track]} / ${c.split} / ${c.source_family}`;
  $('input-json').textContent = json(c.task); $('provenance').textContent = json(c.provenance);
  const area = clear('input-files');
  c.task.files.forEach(file => {area.append(node('h4', file.filename)); if (/\.(html?|json|csv)$/i.test(file.filename)) {try {const bytes = Uint8Array.from(atob(file.content_base64), c => c.charCodeAt(0));area.append(node('pre', new TextDecoder().decode(bytes)));} catch {area.append(node('p', '無法預覽二進位內容'));}} else {area.append(node('p', `Office／二進位檔 · ${Math.floor(file.content_base64.length * .75)} bytes。解析後的內容與定位見右側證據。`, 'binary-note'));}});
  const version = clear('answer-version'); c.answers.slice().reverse().forEach(a => {const o = node('option', `v${a.version} · ${statuses[a.status]}`);o.value = a.id; version.append(o);});
  const result = currentResult(); if (result && c.answers.some(a => a.id === result.snapshot.answer_id)) version.value = result.snapshot.answer_id;
  if (preferredAnswerId && c.answers.some(a => a.id === preferredAnswerId)) version.value = preferredAnswerId;
  renderAnswer(); renderActual(); renderCases();
}
function renderAnswer() {
  state.gold = state.detail?.answers.find(a => a.id === $('answer-version').value); const gold = state.gold; if (!gold) return;
  $('answer-status').textContent = statuses[gold.status]; $('answer-status').className = `pill ${gold.status === 'approved' ? 'good' : 'warn'}`;
  $('answer-basis').textContent = gold.answer.basis;
  const checks = clear('expected-checks');gold.answer.checks.forEach(c => {const r = node('div', undefined, 'check'); r.append(node('code', `${c.path} · ${c.op || 'eq'}${c.critical === false ? '' : ' · 關鍵'}`), node('b', json(c.value)));checks.append(r);});
  $('expected-evidence').textContent = json(gold.answer.evidence); $('answer-editor').value = json(gold.answer); $('decision-reason').value = '';
  $('approve').disabled = $('return').disabled = gold.status !== 'draft';
  renderActual();
}
function currentResult() {return state.run?.results.find(r => r.case_id === state.detail?.id);}
function renderActual() {
  const result = currentResult(); clear('differences'); clear('actual-evidence'); $('adjudication').hidden = !result || result.state !== 'completed';
  if (!result) {$('result-state').textContent = '尚未執行';$('actual-output').textContent = '此執行未包含本案例，或尚未建立執行。';return;}
  $('result-state').textContent = statuses[result.state];
  const diff = $('differences'); diff.append(node('p', `本次依答案 v${result.snapshot.answer_version} 評分 · ${result.snapshot.approved ? '執行時已核准' : '執行時未核准'}。`));
  if (state.gold?.id !== result.snapshot.answer_id) diff.append(node('div', '目前查看的答案與此執行不同；切换到本次答案版本查看完整對照。', 'diff-error'));
  if (result.error_code) diff.append(node('div', errors[result.error_code] || result.error_code, 'diff-error'));
  if (result.state === 'completed') {
    diff.append(node('div', result.score.correct ? '欄位與要求證據相符；仍須符合整組門檻及核准條件。' : '存在差異，不能當作已通過。', result.score.correct ? 'success-note' : 'diff-error'));
    (result.score.differences || []).forEach(d => diff.append(node('div', `${d.path}\n預期 ${json(d.value)}\n實際 ${json(d.actual)}`, 'diff-error')));
    (result.score.evidence_errors || []).forEach(d => diff.append(node('div', `無法定位證據：${json(d)}`, 'diff-error')));
  }
  const {records, ...actual} = result.actual; $('actual-output').textContent = json(actual);
  (records || []).forEach(r => {const d = node('div', undefined, 'source-record');d.append(node('code', r.locator), node('span', r.text));$('actual-evidence').append(d);});
  if (result.adjudications.length) diff.append(node('p', `人工裁定：${result.adjudications.at(-1).decision} / ${result.adjudications.at(-1).reason}`));
}
async function decide(decision) {
  const reason = $('decision-reason').value.trim(); if (reason.length < 3) throw new Error('請填寫至少 3 個字的核准／退回理由。');
  await post(`/answers/${state.gold.id}/decision`, {decision, reason});toast(decision === 'approve' ? '已核准答案；舊試跑不會追溯變成正式通過。' : '已退回；修訂時請建立新版本。');
  await selectCase(state.detail.id, state.gold.id);await overview();await loadCases();await loadAudit();
}
async function launch(ids) {
  const run = await post('/runs', {agent: state.agent, case_ids: ids, split: $('split').value, mode: $('mode').value, request_key: crypto.randomUUID()});
  toast('已加入驗收佇列；使用真實處理器執行。'); await loadRuns();await showRun(run.id);
}
async function loadRuns() {
  state.runs = await api(`/runs?agent=${state.agent}`);const current = state.run?.id;
  const main = clear('run-select'), compare = clear('compare-select'); const none = node('option', '不比較');none.value = '';compare.append(none);
  if (!state.runs.length) main.append(node('option', '尚無執行紀錄'));
  state.runs.forEach(r => {const label = `${when(r.created_at)} · ${r.mode === 'trial' ? '試跑' : '正式'} · ${statuses[r.state]} · ${r.id.slice(0, 8)}`;for (const select of [main, compare]) {const o = node('option', label);o.value = r.id;select.append(o);}});
  if (current && state.runs.some(r => r.id === current)) main.value = current;
}
async function showRun(id) {
  if (!id) return;state.run = await api(`/runs/${id}`);$('run-select').value = id;scoreCards(state.run);$('manifest').textContent = json(state.run.manifest);
  $('code-download').hidden = !state.run.manifest.code_artifact; if (state.run.manifest.code_artifact) $('code-download').href = `/api/code/${state.run.manifest.code_artifact}`;
  const summary = clear('run-summary');summary.append(node('p', `${statuses[state.run.state]} · ${state.run.passed ? '本次全組達標（不等於整體產品上線）' : '尚未達標'} · ${state.run.inventory_complete ? '首批案例齊備' : '尚缺首批必要案例'}${state.run.full_suite ? '' : ' · 非完整驗收組'}`));
  summary.append(table(['格式軌', '完成 / 必要', '自動正確率', '自動覆蓋率', '關鍵錯誤', '判定'], Object.entries(state.run.tracks).map(([t,m]) => [tracks[t], `${m.completed}/${m.required}`, pct(m.precision), pct(m.coverage), m.critical_errors, m.passed ? '達標' : '未達標'])));
  renderActual(); await compareRuns();
}
async function compareRuns() {
  const area = clear('comparison'), id = $('compare-select').value; if (!id || !state.run) return;
  const other = await api(`/runs/${id}`);area.append(node('h4', `左：目前執行 ${state.run.id.slice(0,8)} ／ 右：比較執行 ${other.id.slice(0,8)}`));
  const keys = new Set([...state.run.results, ...other.results].map(r => r.snapshot.case_key));const rows = [];
  keys.forEach(key => {const a = state.run.results.find(r => r.snapshot.case_key === key), b = other.results.find(r => r.snapshot.case_key === key);const label = r => r ? `答案 v${r.snapshot.answer_version} / ${statuses[r.state]} / 關鍵錯誤 ${r.score.critical_errors ?? '—'}` : '未執行'; rows.push([key, label(a), label(b)]);});
  area.append(table(['案例', '目前版本', '比較版本'], rows));
}
async function loadAudit() {const rows = await api('/audit');clear('audit').append(table(['時間', '操作者', '動作', '對象', '理由 / 依據'], rows.slice(0,25).map(r => [when(r.created_at), r.actor, r.action, r.target_id.slice(0,12), r.details.reason || r.details.answer_hash?.slice(0,16) || r.details.dataset_hash?.slice(0,16) || '—'])));}
async function enter() {$('login').hidden = true; $('workspace').hidden = false;await overview();await selectAgent(state.agent);await loadAudit();}
$('login-form').addEventListener('submit', async event => {event.preventDefault();try {const login = await post('/login', {password: $('password').value});state.csrf = login.csrf;$('password').value = '';await enter();} catch(error) {$('login-error').textContent = error.message;}});
action('logout', async () => {await post('/logout', {});location.reload();});
action('run-suite', () => launch([]));action('run-selected', () => {if (!state.selected.size) throw new Error('請先勾選案例。');return launch([...state.selected]);});action('rerun', () => launch([state.detail.id]));
action('approve', () => decide('approve'));action('return', () => decide('return'));
action('new-version', async () => {let answer;try {answer = JSON.parse($('answer-editor').value);} catch {throw new Error('答案 JSON 格式不正確。');}await post(`/cases/${state.detail.id}/answers`, {answer});toast('新答案草稿已建立；歷史答案與執行保留不變。');await selectCase(state.detail.id);$('answer-version').value = state.detail.answers.at(-1).id;renderAnswer();await loadCases();await overview();await loadAudit();});
for (const [id, decision] of [['accept-result','accept'], ['return-result','return']]) action(id, async () => {const reason = $('adjudication-reason').value.trim();if (reason.length < 3) throw new Error('請填寫裁定依據。');await post(`/results/${currentResult().id}/adjudication`, {decision, reason});await showRun(state.run.id);await loadAudit();toast('裁定已記錄。關鍵錯誤與程式差異不會被人工接受覆蓋。');});
action('refresh', async () => {await overview();await loadCases();await loadRuns();if (state.run) await showRun(state.run.id);await loadAudit();});
action('export-run', async () => {if (!state.run) throw new Error('請先選擇執行紀錄。');const a = node('a');a.href = URL.createObjectURL(new Blob([json(state.run)], {type:'application/json'}));a.download = `acceptance-${state.run.id}.private.json`;a.click();URL.revokeObjectURL(a.href);toast('此匯出包含私有案例與答案，請勿上傳公開 repo。');});
$('split').addEventListener('change', () => {state.selected.clear();loadCases().catch(e => toast(e.message));});
$('answer-version').addEventListener('change', renderAnswer);
$('run-select').addEventListener('change', async () => {try {await showRun($('run-select').value);if (state.detail) await selectCase(state.detail.id);} catch(e) {toast(e.message);}});
$('compare-select').addEventListener('change', () => compareRuns().catch(e => toast(e.message)));
setInterval(async () => {if (state.run && ['queued', 'running'].includes(state.run.state)) {try {await showRun(state.run.id);if (!['queued','running'].includes(state.run.state)) {await overview();await loadRuns();toast('執行完成。請對照各格式軌與案例差異。');}} catch(e) {toast(e.message);}}}, 2200);
(async () => {try {const session = await api('/session');state.csrf = session.csrf;await enter();} catch {$('login').hidden = false;}})();
