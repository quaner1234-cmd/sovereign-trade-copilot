import assert from 'node:assert/strict';
import {CASES, KEY, createState, validateState, cardView, applyAction, readStorage, persistAction} from './model.mjs';

let count = 0;
function test(name, run) {run(); count++; console.log(`PASS ${name}`);}
function action(s, type, extra = {}) {
  return {type, expected_revision: s.revision, case_id: s.selected, ...extra};
}
function step(s, type, extra = {}) {return applyAction(s, action(s, type, extra));}
function ready(s = createState()) {return step(s, 'PREPARE_DRAFT');}
function approved(s = ready()) {return step(s, 'APPROVE_DRAFT', {reviewed: true});}
function storage() {
  const map = new Map();
  return {getItem: key => map.get(key) ?? null, setItem: (key, value) => map.set(key, value), map};
}

test('Unknown quantity allows source review and a useful first draft', () => {
  const s = step(createState(), 'REVIEW_SOURCE', {confirmed: true});
  assert.equal(s.cards.development.quantity, null);
  assert.match(cardView(s).next_action, /初步核价/);
  assert.match(ready(s).cards.development.draft, /estimated quantity/);
});
test('Opening a source is not an action that upgrades its state', () => {
  const s = createState(); cardView(s);
  assert.equal(s.cards.development.sourceRead, false);
  assert.throws(() => step(s, 'REVIEW_SOURCE'), /确认/);
});
test('Quantity update preserves all other fixtures and customer/company facts', () => {
  const s = createState(), before = JSON.stringify(CASES), sibling = structuredClone(s.cards.known);
  const updated = step(s, 'SET_QUANTITY', {value: 360});
  assert.deepEqual(updated.cards.known, sibling);
  assert.equal(updated.cards.development.sourceRead, false);
  assert.equal(JSON.stringify(CASES), before);
  assert.equal(updated.cards.development.quantity, 360);
});
test('New quantity is used as estimated total and is not re-asked', () => {
  const c = ready(step(createState(), 'SET_QUANTITY', {value: 360})).cards.development;
  assert.match(c.draft, /estimated total of 360 pcs/);
  assert.doesNotMatch(c.draft, /What is your estimated quantity/);
  assert.match(c.draft, /not a confirmed order/);
});
test('Known quantity is neither lost nor repeatedly requested', () => {
  const s = ready(step(createState(), 'SELECT_CASE', {case_id: 'known'}));
  assert.match(s.cards.known.draft, /480 pcs/);
  assert.doesNotMatch(s.cards.known.draft, /What.*quantity|confirmed order/);
});
test('Operator correction replaces quantity in dependent fixture wording', () => {
  let s = step(createState(), 'SELECT_CASE', {case_id: 'known'});
  s = ready(step(s, 'SET_QUANTITY', {value: 600}));
  assert.match(s.cards.known.draft, /600 pcs/);
  assert.doesNotMatch(s.cards.known.draft, /480 pcs/);
});
test('Unverified protective capability remains a blocker', () => {
  const s = ready(step(createState(), 'SELECT_CASE', {case_id: 'protection'}));
  assert.match(cardView(s).blockers.join(' '), /不得确认/);
  assert.match(s.cards.protection.draft, /verification before any commitment/);
});
test('Approval requires explicit review, no empty or rejected draft', () => {
  assert.throws(() => step(createState(), 'APPROVE_DRAFT', {reviewed: true}));
  assert.throws(() => step(ready(), 'APPROVE_DRAFT'));
  assert.throws(() => step(step(ready(), 'REJECT_DRAFT'), 'APPROVE_DRAFT', {reviewed: true}));
});
test('Editing invalidates approval while preserving source facts', () => {
  const s = approved(), edited = step(s, 'EDIT_DRAFT', {value: s.cards.development.draft + '\n\nThank you.'});
  assert.equal(edited.cards.development.approval, null);
  assert.equal(edited.cards.development.contextRevision, s.cards.development.contextRevision);
  assert.equal(edited.cards.development.sourceRead, s.cards.development.sourceRead);
  assert.equal(edited.cards.development.draftRevision, s.cards.development.draftRevision + 1);
});
test('Context update invalidates approval and marks existing draft stale', () => {
  const s = step(approved(), 'SET_QUANTITY', {value: 720});
  assert.equal(s.cards.development.approval, null);
  assert.equal(cardView(s).stale, true);
  assert.throws(() => step(s, 'APPROVE_DRAFT', {reviewed: true}));
});
test('Source update also invalidates approval and requires new draft', () => {
  const s = step(approved(), 'REVIEW_SOURCE', {confirmed: true});
  assert.equal(cardView(s).can_approve, false);
  assert.equal(cardView(s).stale, true);
  assert.match(ready(s).cards.development.draft, /based on your notes/);
});
test('Reject retains exact draft and other facts; new fixture clears rejection', () => {
  const s = approved(), rejected = step(s, 'REJECT_DRAFT');
  assert.equal(rejected.cards.development.draft, s.cards.development.draft);
  assert.equal(rejected.cards.development.quantity, s.cards.development.quantity);
  assert.equal(rejected.cards.development.approval, null);
  assert.equal(ready(rejected).cards.development.rejected, false);
});
test('Ordinary storage restoration retains all revisions, approval and history', () => {
  const store = storage(), s = approved(); store.setItem(KEY, JSON.stringify(s));
  assert.deepEqual(readStorage(store), s);
  assert.match(cardView(readStorage(store)).status, /已模拟批准/);
});
test('Stale event, mismatched case, unknown action and SEND rejected', () => {
  const s = ready();
  assert.throws(() => applyAction(s, {type: 'PREPARE_DRAFT', case_id: s.selected, expected_revision: 0}));
  assert.throws(() => step(s, 'SET_QUANTITY', {case_id: 'known', value: 10}));
  assert.throws(() => step(s, 'SEND'));
  assert.throws(() => step(s, 'CONFIRM_COMPANY_CAPABILITY'));
});
test('Invalid payloads leave confirmed state unchanged', () => {
  const s = approved(), copy = structuredClone(s);
  for (const value of [0, -1, 1.5, '300', NaN, 1000000]) assert.throws(() => step(s, 'SET_QUANTITY', {value}));
  for (const value of ['', ' ', null, 'x'.repeat(8001)]) assert.throws(() => step(s, 'EDIT_DRAFT', {value}));
  assert.deepEqual(s, copy);
});
test('Newer tab cannot be silently overwritten by a stale snapshot', () => {
  const store = storage(), old = createState(); store.setItem(KEY, JSON.stringify(old));
  const newer = persistAction(store, old, action(old, 'SET_QUANTITY', {value: 400}));
  assert.throws(() => persistAction(store, old, action(old, 'SET_QUANTITY', {value: 500})), /另一标签页/);
  assert.deepEqual(readStorage(store), newer);
});
test('Corrupt storage and approval/version mismatch do not auto-restore', () => {
  const store = storage(); store.setItem(KEY, '{broken');
  assert.throws(() => readStorage(store)); assert.equal(store.getItem(KEY), '{broken');
  const s = approved(); s.cards.development.approval.contextRevision++;
  assert.throws(() => validateState(s), /版本/);
});
test('Storage write failure preserves prior state and approval', () => {
  const s = approved(), snapshot = JSON.stringify(s);
  const store = {getItem: () => snapshot, setItem: () => {throw Error('QuotaExceeded');}};
  assert.throws(() => persistAction(store, s, action(s, 'EDIT_DRAFT', {value: 'Changed draft'})), /QuotaExceeded/);
  assert.equal(JSON.stringify(s), snapshot);
});
console.log(`${count} meaningful state/persistence checks passed; no model or email calls.`);
