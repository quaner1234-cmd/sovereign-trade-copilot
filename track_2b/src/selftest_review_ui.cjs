// Tests execute the cache contract embedded in the actual HTML, with no browser or service dependency.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, 'ui/light.html'), 'utf8');
const cacheScript = html.match(/<script id="review-cache">([\s\S]*?)<\/script>/)[1];
const sandbox = {module: {exports: {}}}; vm.runInNewContext(cacheScript, sandbox);
const C = sandbox.module.exports;
function fixture() {
  return {inputs: {inquiry: 'Hello, one prototype only. Bulk remains conditional.', context: '[]',
    sources: '{"body":"read","attachments":[]}', brief: '', 'company-note': '常规 MOQ 为 240 pcs；没有每色最低量。',
    'company-note-scope': 'This project only; preserve unit and conditions.', auth: true}, documents: [],
    result: {status: 'draft_for_human_review', draft_id: 'synthetic_record_123', input_hash: 'a'.repeat(64),
      pipeline: 'light-harness-1.3', raw_draft: 'We will review the design before confirming price.', contextual_hint: '',
      brief: {source_state: {body: 'read', attachments: [{name: 'design.txt', state: 'referenced_unread'}]},
        authorized_company_conditions: [{statement: 'MOQ 240 pcs. No style/color basis.', source: 'Synthetic authorized record', scope: 'General baseline'}],
        provisional_references_not_company_truth: [{statement: 'Observed sample reference only.', source: 'Synthetic public page', scope: 'External reference'}]},
      warnings: [], meta: {mode: 'llm', total_tokens: 123, api_key: 'provider-private-sentinel'},
      raw_model_output: 'provider-output-sentinel', approval: {actor: 'reviewer-private-sentinel'}},
    draft: 'Edited reply: one prototype, not a confirmed bulk order.', inputActive: true,
    exampleLoaded: false, exampleId: '', actor: 'reviewer-private-sentinel', reviewed: true, approved: true};
}
let passed = 0;
function test(name, run) {run(); passed++; console.log('PASS '+name);}
function storage() {const map = new Map(); return {getItem: k => map.get(k) ?? null, setItem: (k,v) => map.set(k,v), map};}
test('Refresh snapshot preserves latest draft, conditions, unit, polarity and unread state', () => {
  const store = storage(), value = fixture(); C.save(store, value); const restored = C.load(store);
  assert.equal(restored.draft, value.draft); assert.equal(restored.inputs['company-note'], value.inputs['company-note']);
  assert.equal(restored.result.brief.source_state.attachments[0].state, 'referenced_unread');
  assert.equal(restored.result.brief.authorized_company_conditions[0].scope, 'General baseline');
});
test('Approval, reviewer, credentials and raw provider output are not persisted', () => {
  const serialized = JSON.stringify(C.snapshot(fixture()));
  for (const marker of ['provider-private-sentinel','provider-output-sentinel','reviewer-private-sentinel','approved','reviewed','approval_id','raw_model_output'])
    assert.ok(!serialized.includes(marker), marker+' was stored');
});
test('Cache keeps only selected source text, original hash/edit marker, and reference status', () => {
  const value = fixture(); value.documents = [{name:'context.txt', text:'Updated working reference', original_text:'Original reference',
    status:'WORKING_VALUE', scope:'Project only', source:'Synthetic context file', reading_state:'read', coverage:'Plain text', sha256:'synthetic'}];
  const restored = C.snapshot(value); assert.equal(restored.documents[0].text, 'Updated working reference');
  assert.equal(restored.documents[0].operator_edited, true);
  assert.equal(restored.documents[0].original_text, undefined);
  assert.ok(!JSON.stringify(restored).includes('Original reference'));
  assert.equal(restored.documents[0].status, 'WORKING_VALUE');
  value.documents[0].status='COMPANY_CONFIRMED'; assert.throws(() => C.snapshot(value));
});
test('Inactive old draft remains recoverable without approval eligibility', () => {
  const value = fixture(); value.inputActive=false; const s=C.snapshot(value);
  assert.equal(s.inputActive,false); assert.equal(s.draft,value.draft); assert.equal(s.result.draft_id,value.result.draft_id);
});
test('Missing backend draft does not invent a new record', () => {
  const value = fixture(); value.result=null; const s=C.snapshot(value);
  assert.equal(s.result,null); assert.equal(s.inputActive,false);
});
test('Malformed source/evidence and unknown storage version fail without overwrite', () => {
  const store = storage(); store.setItem(C.KEY,'{"schema":8}'); assert.throws(() => C.load(store));
  assert.equal(store.getItem(C.KEY),'{"schema":8}');
  const value=fixture(); value.result.brief.source_state.attachments[0].state='sent'; assert.throws(() => C.snapshot(value));
  value.result.brief.source_state.attachments=[]; value.result.brief.authorized_company_conditions={}; assert.throws(() => C.snapshot(value));
});
test('Oversize input is rejected and previous snapshot retained', () => {
  const store=storage(), value=fixture(); C.save(store,value); const before=store.getItem(C.KEY);
  value.inputs.inquiry='x'.repeat(16001); assert.throws(() => C.save(store,value)); assert.equal(store.getItem(C.KEY),before);
});
test('Storage unavailable/write failure never pretends to save', () => {
  const value=fixture(), before=JSON.stringify(value);
  assert.throws(() => C.save({setItem:()=>{throw Error('Storage unavailable');}},value));
  assert.equal(JSON.stringify(value),before);
  assert.throws(() => C.load({getItem:()=>{throw Error('Access denied');}}));
});
// Exercise the actual approval handler: an old request must not invalidate a newer draft.
(async()=>{
  const handlerBody=html.match(/\$\('approve'\)\.onclick=async\(\)=>\{([\s\S]*?)\n\};/)[1];
  const controls={approve:{disabled:false},draft:{value:'Draft A'},actor:{value:'Scripted test'},reviewed:{checked:true}};
  let rejectOld;
  const old={draft_id:'record_A'}, next={draft_id:'record_B'};
  const env={current:old,approving:false,approvalState:'pending', $:id=>controls[id],
    request:()=>new Promise((resolve,reject)=>{rejectOld=reject;}), approvalButton:()=>{}, updateReviewCard:()=>{},
    notice:()=>{}, saveTab:()=>{}, invalidate:()=>{}};
  vm.createContext(env);vm.runInContext('handler=async()=>{'+handlerBody+'\n};',env);
  const pending=env.handler();env.current=next;controls.draft.value='Draft B';
  rejectOld(Object.assign(Error('Expired old record'),{status:409}));await pending;
  assert.equal(env.current,next);assert.equal(controls.draft.value,'Draft B');
  passed++;console.log('PASS late expiry of old approval does not invalidate newer draft');
  console.log(`${passed} privacy/recovery and approval-event checks passed.`);
})().catch(error=>{console.error(error);process.exitCode=1;});
