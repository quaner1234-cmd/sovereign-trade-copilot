"""Human review boundaries: authority, revisions, isolation and measurement."""
from copy import deepcopy
import json
import tempfile
import unittest
from pathlib import Path

from inquiry_v2 import analyze
from inquiry_v2.message_plan import build
from inquiry_v2.source_registry import build as registry_for
from inquiry_v2.reply_renderer import normalize
from inquiry_v2.review_release import evaluate, check_edited_text
from inquiry_v2.reviewer import Reviewer, ReviewConflict, pack

def fixture():
    source='Standard MOQ is 175 pieces per style. Colour/material minima require review. Normal lead time is 55 days for the standard approved material route. We accept a letter of credit.'
    request={'inquiry':{'primary':{'text':'Please assess 410 work vests unchanged. What are your MOQ, normal lead time and payment terms?'}},
             'company_context':{'sources':[{'id':'policy','kind':'company_context','party':'company','status':'read','scope':'company.default',
                 'text':source,'metadata':{'confirmed_by':'Synthetic operator','confirmed_at':'2026-10-05'}}],
                 'candidates':[]}}
    for ident,key,value,unit,conditions in [('moq','moq.style',175,'pcs/style',['Colour/material minima require review.']),
                                           ('lead','lead_time.normal',55,'days',[]),('pay','payment_terms','L/C',None,[])]:
        request['company_context']['candidates'].append({'id':ident,'key':key,'value':value,'unit':unit,'scope':'company.default',
            'scope_spec':{'global':True},'source_id':'policy','status':'company_confirmed','conditions':conditions,
            'provenance':{'span':[0,len(source)],'quote':source}})
    result=analyze(request);plan=build(result,registry_for(request))
    ids=[s['item_ids'][0] for s in plan.document['ordered_message_slots'] if s['required']]
    text='Our MOQ is 175 pieces per style; colour/material minima require review. Normal lead time is 55 days for the standard approved material route. We accept L/C. We will review preliminary construction costing for the 410 work vests.'
    proposal=normalize({'courtesy':'Thank you for your thoughtful request.','slots':[{'item_ids':ids,'text':text}]},plan)
    return request,plan,proposal

class ReleasePolicyTests(unittest.TestCase):
    def setUp(self):self.request,self.plan,self.proposal=fixture()
    def policy(self,text):return check_edited_text(self.plan,text)[1]
    def test_natural_courtesy_and_merge_are_advisory_not_certification(self):
        p=evaluate(self.plan,self.proposal,audit={'issues':['semantic_tone']})
        self.assertTrue(p['passed'],p['issues'])
        self.assertFalse(p['certifies_safety'])
        self.assertIn('unsupported_courtesy',[w['code'] for w in p['warnings']])
    def test_correct_number_wrong_basis_or_unit_blocks(self):
        text=self.proposal['slots'][0]['text']
        self.assertFalse(self.policy(text.replace('per style','per colour'))['passed'])
        self.assertIn('explicit_unit_conflict',self.policy(text.replace('55 days','55 weeks'))['issues'])
        self.assertIn('company_basis_conflict',self.policy('颜色和材质最低数量为 175 件。'+text)['issues'])
    def test_courtesy_is_not_a_company_value_bypass(self):
        bad=deepcopy(self.proposal);bad['courtesy']='Our MOQ is 900 pieces per style.'
        self.assertIn('unsupported_courtesy_number',evaluate(self.plan,bad)['issues'])
        bad['courtesy']='Our MOQ is 410 pieces per style.'
        self.assertIn('company_value_authorization_mismatch:moq',evaluate(self.plan,bad)['issues'])
        bad['courtesy']='Our MOQ is 175 pieces per style, and we will review costing for your 410 work vests.'
        self.assertNotIn('company_value_authorization_mismatch:moq',evaluate(self.plan,bad)['issues'])
    def test_method_acceptance_does_not_authorize_transaction(self):
        text=self.proposal['slots'][0]['text']
        p=self.policy(text.replace('We accept L/C.','We confirm the payment will be handled under L/C terms.'))
        self.assertIn('transaction_authorization_missing',p['issues'])
    def test_order_modifier_and_source_state_are_checked(self):
        text=self.proposal['slots'][0]['text']
        self.assertIn('unconfirmed_order_claim',self.policy(text.replace('the 410 work vests','the 410-piece bulk order of work vests'))['issues'])
        doc=self.plan.document;doc['source_state']=[{'source_id':'brief','state':'referenced_unread','kind':'attachment'}]
        from inquiry_v2.message_plan import MessagePlan,encode
        altered=MessagePlan(encode(doc),self.plan.evidence_json)
        self.assertIn('source_state_conflict',check_edited_text(altered,text+' We have reviewed the attached brief.')[1]['issues'])
    def test_verification_intent_not_execution(self):
        text=self.proposal['slots'][0]['text']
        p=self.policy(text+' We will check whether we can support shipment.')
        self.assertNotIn('execution_authorization_missing',p['issues'])
        self.assertIn('execution_authorization_missing',self.policy(text+' We will ship tomorrow.')['issues'])
    def test_missing_authorized_value_integrity_and_new_question(self):
        text=self.proposal['slots'][0]['text']
        self.assertIn('required_value_missing:A-moq',self.policy(text.replace('175',''))['issues'])
        changed=deepcopy(self.proposal);changed['plan_hash']='changed'
        self.assertIn('immutable_plan_binding_changed',evaluate(self.plan,changed)['issues'])
        self.assertFalse(self.policy(text+' Could you provide your shipping address?')['passed'])
        self.assertFalse(self.policy('Thank you.')['passed'])
    def test_located_spans_and_advisory_cannot_erase_hard_failure(self):
        p=self.policy(self.proposal['slots'][0]['text']+' We will ship tomorrow.')
        for f in p['blockers']+p['warnings']:
            a,b=f['span'];self.assertEqual(f['phrase'],(self.proposal['slots'][0]['text']+' We will ship tomorrow.')[a:b])
        self.assertFalse(p['passed'])

class ReviewerWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);request,plan,proposal=fixture()
        cases=[{'id':'r','title':'Review','mode':'review','cohort':'synthetic_matched','request':request,'plan':pack(plan),'proposal':proposal},
               {'id':'b','mode':'baseline','cohort':'synthetic_matched','request':request}]
        bank=root/'bank.json';bank.write_text(json.dumps({'cases':cases,'schedule':['r','b']}),encoding='utf-8')
        self.service=Reviewer({'REVIEW_DB':str(root/'review.sqlite3'),'REVIEW_ACTOR':'Automated verification','REVIEW_CASES':str(bank)})
        self.run=self.service.start({'kind':'practice','case_id':'r'})
        self.state=self.service.next_task(self.run)
    def action(self,name,**fields):
        self.state=self.service.act({'review_id':self.state['review_id'],'revision':self.state['revision'],'action':name,**fields})
        return self.state
    def test_approval_is_current_snapshot_never_execution_and_stale_denied(self):
        stale=self.state['revision']
        self.action('edit',draft=self.state['draft'].replace('thoughtful','detailed'))
        with self.assertRaises(ReviewConflict):
            self.service.act({'review_id':self.state['review_id'],'revision':stale,'action':'approve'})
        approved=self.action('approve',metrics={'active_ms':1400,'wall_ms':1800,'edit_input_events':1})
        self.assertFalse(approved['approval']['sent'])
        self.assertFalse(approved['approval']['execution_authorized'])
        with self.assertRaises(ReviewConflict):self.action('edit',draft='Different text')
    def test_hard_failure_cannot_be_waived_and_history_kept(self):
        self.action('edit',draft=self.state['draft']+' We will ship tomorrow.')
        with self.assertRaises(ReviewConflict):self.action('approve',metrics={'active_ms':1,'wall_ms':1,'edit_input_events':1})
        with self.assertRaises(ValueError):self.action('warning_fp',code='execution_authorization_missing')
        self.action('reject',note='Execution is not authorized',metrics={'active_ms':1,'wall_ms':1,'edit_input_events':1})
        with self.service._db() as db:
            with self.assertRaises(Exception):db.execute('DELETE FROM review_events')
    def test_question_plan_revision_preserves_fact_authority(self):
        before=self.state['technical']['plan_hash']
        self.action('correct_plan',target='primary',text='Review the stated construction and preliminary cost basis.',reason='Same reversible costing direction, clearer expression.')
        self.assertNotEqual(before,self.state['technical']['plan_hash'])
        self.assertEqual(self.state['company_claims'][0]['value'],175)
    def test_baseline_has_same_company_sources_but_no_ai_plan_or_warnings(self):
        run=self.service.start({'kind':'practice','case_id':'b'})
        b=self.service.next_task(run)
        self.assertIsNone(b['technical']);self.assertIsNone(b['policy']);self.assertIsNone(b['primary'])
        self.assertEqual(b['draft'],'');self.assertTrue(b['company_sources'])
    def test_practice_never_fills_human_metrics(self):
        self.action('approve',metrics={'active_ms':1000,'wall_ms':1000,'edit_input_events':0})
        self.service.next_task(self.run)
        summary=self.service.summary(self.run['run_id'])
        self.assertEqual(summary['human_completed'],0)
        self.assertIsNone(summary['median_review_seconds'])
        self.assertEqual(summary['mvp_verdict'],'NOT_ESTABLISHED')
    def test_old_warning_assessment_is_not_applied_to_edited_text(self):
        code=self.state['policy']['warnings'][0]['code']
        self.action('warning_review',code=code,outcome='helpful')
        self.assertTrue(self.state['warning_reviews'])
        self.action('edit',draft=self.state['draft'].replace('thoughtful','detailed'))
        self.assertEqual(self.state['warning_reviews'],[])
        self.assertEqual(self.state['false_positive_warnings'],[])
        self.assertNotEqual(self.state['company_claims'][0]['expression'],self.state['draft'])
    def test_private_storage_cannot_enter_checkout(self):
        with self.assertRaises(ValueError):Reviewer({'REVIEW_DB':str(Path(__file__).resolve().parent/'bad.sqlite3'),'REVIEW_ACTOR':'Synthetic'})

if __name__=='__main__':unittest.main(verbosity=2)
