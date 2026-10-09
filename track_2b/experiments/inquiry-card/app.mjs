import {KEY, CASES, createState, validateState, cardView, readStorage, persistAction} from './model.mjs';

const $ = id => document.getElementById(id);
let state = createState(), writable = false;
const notice = (text, error = false) => {$('notice').textContent = text; $('notice').classList.toggle('error', error);};

function initialize() {
  try {
    state = readStorage(localStorage);
    if (localStorage.getItem(KEY) === null) localStorage.setItem(KEY, JSON.stringify(state));
    writable = true;
  } catch {
    writable = false;
    notice('无法读取或保存演示状态。已有存储未覆盖；请重置此实验，或允许本地存储后刷新。', true);
  }
  render();
}

function render() {
  const view = cardView(state), c = state.cards[state.selected], f = CASES[state.selected];
  for (const [id, text] of Object.entries({inquiry: f.inquiry, 'case-title': f.title, customer: view.customer.name,
    'customer-meta': `${view.customer.country} · ${view.customer.email}`, status: view.status,
    'next-action': view.next_action, 'source-state': `${f.source} · ${view.source_state}`,
    quantity: view.quantity === null ? '尚未确定 · 不阻止当前内部评估' : `${view.quantity} pcs · 预计总量，非订单`,
    'source-title': f.source, 'source-text': f.sourceText, company: f.company,
    'schema-view': JSON.stringify(view, null, 2)})) $(id).textContent = text;
  $('blockers').replaceChildren(...view.blockers.map(text => {const li = document.createElement('li'); li.textContent = text; return li;}));
  $('history').replaceChildren(...c.history.map(text => {const li = document.createElement('li'); li.textContent = text; return li;}));
  $('quantity-input').value = c.quantity ?? '';
  $('draft').value = c.draft;
  $('draft-area').hidden = !c.draft;
  $('draft-version').textContent = `草稿版本 ${c.draftRevision} · 上下文版本 ${c.contextRevision}` + (view.stale ? ' · 上下文已变，请重新准备' : '');
  $('reviewed').checked = false;
  $('approval-note').textContent = c.approval ? `模拟批准绑定草稿版本 ${c.approval.draftRevision}。未发送。` :
    c.rejected ? '此草稿已退回。可保存修改或重新准备；没有自动重试。' : '只记录演示批准；不发送邮件。';
  for (const button of document.querySelectorAll('button')) button.disabled = !writable;
  for (const id of ['show-reset', 'reset', 'cancel-reset']) $(id).disabled = false;
  for (const field of [$('quantity-input'), $('draft'), $('reviewed')]) field.disabled = !writable;
  $('mark-read').disabled = !writable || c.sourceRead;
  $('save-edit').disabled = !writable || view.stale;
  $('approve').disabled = true;
  $('persistence').textContent = writable ? '已保存在此浏览器 · 刷新可恢复 · 无外部请求 · 不发送邮件' :
    '存储不可用或无效：动作暂停，未宣称已保存。';
  for (const button of document.querySelectorAll('[data-case]')) button.setAttribute('aria-pressed', String(button.dataset.case === state.selected));
}

function dispatch(type, extra = {}) {
  if (!writable) return notice('没有可用的演示存储，操作未应用。', true);
  try {
    state = persistAction(localStorage, state, {type, case_id: state.selected, expected_revision: state.revision, ...extra});
    render();
    notice(type === 'SELECT_CASE' ? '已切换虚构案例；其他案例状态保留。' : '操作已保存。未调用模型，也未发送邮件。');
  } catch (error) {
    notice(`${error.message} 操作未应用；上一状态保留。`, true);
  }
}

function requireSavedEdit(action) {
  if ($('draft').value !== state.cards[state.selected].draft) {
    notice('草稿有尚未保存的修改。先保存修改，或恢复文字后再进行此操作。', true);
    return;
  }
  action();
}

for (const button of document.querySelectorAll('[data-case]')) button.onclick = () => requireSavedEdit(() => {
  $('source-panel').hidden = true; $('quantity-panel').hidden = true;
  dispatch('SELECT_CASE', {case_id: button.dataset.case});
});
$('show-source').onclick = () => {$('source-panel').hidden = !$('source-panel').hidden;};
$('show-quantity').onclick = () => {$('quantity-panel').hidden = !$('quantity-panel').hidden;};
$('mark-read').onclick = () => requireSavedEdit(() => dispatch('REVIEW_SOURCE', {confirmed: true}));
$('save-quantity').onclick = () => requireSavedEdit(() => dispatch('SET_QUANTITY', {value: Number($('quantity-input').value)}));
$('prepare').onclick = () => requireSavedEdit(() => dispatch('PREPARE_DRAFT'));
$('save-edit').onclick = () => dispatch('EDIT_DRAFT', {value: $('draft').value});
$('reject').onclick = () => requireSavedEdit(() => dispatch('REJECT_DRAFT'));
$('approve').onclick = () => requireSavedEdit(() => dispatch('APPROVE_DRAFT', {reviewed: $('reviewed').checked}));
const approvalButton = () => {
  const unchanged = $('draft').value === state.cards[state.selected].draft;
  $('approve').disabled = !writable || !unchanged || !$('reviewed').checked || !cardView(state).can_approve;
};
$('reviewed').onchange = approvalButton;
$('draft').oninput = () => {
  $('reviewed').checked = false; approvalButton();
  const c = state.cards[state.selected], view = cardView(state), dirty = $('draft').value !== c.draft;
  $('status').textContent = dirty ? '修改未保存 · 旧批准不适用' : view.status;
  $('persistence').textContent = !writable ? '操作已暂停，当前修改未保存。' : dirty ?
    '当前文字尚未保存；刷新会恢复上一保存稿。' : '已保存在此浏览器 · 刷新可恢复 · 无外部请求 · 不发送邮件';
  $('approval-note').textContent = dirty ? '文字已变：旧批准不适用；请保存修改后重新审核。' :
    c.approval ? `模拟批准绑定草稿版本 ${c.approval.draftRevision}。未发送。` : '只记录演示批准；不发送邮件。';
  $('schema-view').textContent = JSON.stringify({...view, status: $('status').textContent,
    draft: $('draft').value, current_text_saved: !dirty, can_approve: !dirty && view.can_approve}, null, 2);
};
$('show-reset').onclick = () => {$('reset-confirm').hidden = false;};
$('cancel-reset').onclick = () => {$('reset-confirm').hidden = true;};
$('reset').onclick = () => {
  try {
    const next = createState();
    localStorage.setItem(KEY, JSON.stringify(next));
    state = next; writable = true;
    for (const id of ['reset-confirm', 'source-panel', 'quantity-panel']) $(id).hidden = true;
    render(); notice('仅本实验的虚构状态已重置。现有外贸 Agent 没有被修改。');
  } catch {notice('无法重置演示存储。当前状态保留。', true);}
};
window.addEventListener('storage', event => {
  if (event.key !== KEY && event.key !== null) return;
  const unsaved = $('draft').value !== state.cards[state.selected].draft;
  if (unsaved) {
    writable = false;
    $('approve').disabled = true;
    $('persistence').textContent = '另一标签页已修改状态：操作暂停；保留未保存文字，请先复制再刷新。';
    notice('其他标签页已改变演示。未保存的文字仍保留；请复制后刷新获取最新状态。', true);
    return;
  }
  try {state = validateState(event.newValue ? JSON.parse(event.newValue) : createState()); writable = true;
    render(); notice('已加载另一标签页的最新模拟状态。');
  } catch {writable = false; render(); notice('另一标签页写入了无效状态，操作暂停。请重置演示。', true);}
});
initialize();
