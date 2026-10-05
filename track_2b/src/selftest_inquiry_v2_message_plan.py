"""P5.2 module contracts and controlled good/bad semantic minimal pairs."""
import copy
import json
import unittest
from dataclasses import FrozenInstanceError
from inquiry_v2 import analyze
from inquiry_v2.source_registry import build as registry_for
from inquiry_v2.message_plan import build, customer_view
from inquiry_v2.message_gates import validate
from inquiry_v2.reply_renderer import normalize, render_plan
from selftest_inquiry_v2 import payload
from selftest_inquiry_v2_reply import prepared, company_moq, surface, chat_sequence


def plan_for(body, **parts):
    request=payload({'body':body,**parts},cold=True)
    return build(analyze(request),registry_for(request))


def proposal(plan, text, ids=None):
    return normalize({'slots':[{'item_ids':ids or ['primary'],'text':text}]},plan)


class MessagePlanTests(unittest.TestCase):
    def setUp(self):
        self.plan=plan_for('Please assess 420 work vests unchanged. No logo is required.')
        self.good='We will review preliminary construction costing for the work vests.'

    def test_plan_is_deeply_immutable_and_view_has_no_source_authority(self):
        original=self.plan.hash
        view=self.plan.document
        view['primary_advance']['action']='DISPATCH'
        self.assertEqual(self.plan.hash,original)
        with self.assertRaises(FrozenInstanceError):self.plan.document_json='{}'
        public=customer_view(self.plan)
        self.assertNotIn('provenance',json.dumps(public))
        self.assertNotIn('confirmed_by',json.dumps(public))
        self.assertTrue(self.plan.document['primary_advance']['provenance'])

    def test_inputs_are_not_mutated(self):
        result,registry,_=prepared('P5-R10')
        before=copy.deepcopy((result,registry))
        build(result,registry)
        self.assertEqual(before,(result,registry))

    def test_merge_preserves_every_required_binding(self):
        result,registry,contract=prepared('P5-R10')
        plan=build(result,registry)
        wire=surface(company_moq(contract))
        merged={'slots':[{'item_ids':[i for s in wire['slots'] for i in s['item_ids']],
                          'text':' '.join(s['text'] for s in wire['slots'])}]}
        self.assertTrue(validate(plan,normalize(merged,plan))['passed'])

    def test_good_and_execution_commitment_minimal_pair(self):
        self.assertTrue(validate(self.plan,proposal(self.plan,self.good))['passed'])
        guard=validate(self.plan,proposal(self.plan,self.good+' We will ship tomorrow.'))
        self.assertIn('unsupported_commitment',guard['issues'])

    def test_verification_does_not_authorize_separate_stock_claim(self):
        text=self.good+' We will check whether shipping is available.'
        self.assertTrue(validate(self.plan,proposal(self.plan,text))['passed'])
        bad=text+' We have stock.'
        self.assertIn('unsupported_company_stock',validate(self.plan,proposal(self.plan,bad))['issues'])

    def test_moq_cannot_authorize_unrelated_capability(self):
        result,registry,contract=prepared('P5-R10');plan=build(result,registry)
        wire=surface(company_moq(contract))
        wire['slots'][0]['text']+=' We manufacture all technical fabrics.'
        self.assertIn('unsupported_company_capability',validate(plan,normalize(wire,plan))['issues'])

    def test_unit_and_condition_preservation(self):
        result,registry,contract=prepared('P5-R10');plan=build(result,registry)
        wire=surface(company_moq(contract))
        for old,new,code in [('pieces per style','sets per style','unit_or_basis_changed:'),
                ('; colour and material minimums require internal checking.','.','condition_omitted:')]:
            bad=copy.deepcopy(wire);bad['slots'][0]['text']=bad['slots'][0]['text'].replace(old,new)
            self.assertTrue(any(i.startswith(code) for i in validate(plan,normalize(bad,plan))['issues']))

    def test_unread_is_existing_and_never_read_or_absent(self):
        plan=plan_for('Please review 80 work vests. The attached brief contains the construction.',
            attachments=[{'id':'brief','name':'synthetic-brief.pdf','status':'referenced_unread'}])
        for text in ['We have reviewed the attached brief and will review costing.',
                     'You have not provided the brief; we will review material costing.']:
            self.assertFalse(validate(plan,proposal(plan,text))['passed'])
        self.assertTrue(validate(plan,proposal(plan,'We will review the attached brief before assessing the material and construction route.'))['passed'])

    def test_negation_and_known_quantity_question(self):
        bad=self.good+' We will review your logo.'
        self.assertIn('critical_polarity_drift',validate(self.plan,proposal(self.plan,bad))['issues'])
        self.assertIn('extra_customer_question',validate(self.plan,proposal(self.plan,self.good+' What quantity do you need?'))['issues'])

    def test_quantity_product_and_purpose(self):
        plan=plan_for('Please assess 120 work vests and 780 tote bags unchanged, for rough costing.')
        bad='We will review preliminary costing for 780 work vests and 120 tote bags.'
        self.assertIn('actual_quantity_product_binding_mismatch',validate(plan,proposal(plan,bad))['issues'])
        bad='We will review preliminary costing for 120 samples of work vests.'
        self.assertIn('quantity_purpose_changed',validate(plan,proposal(plan,bad))['issues'])

    def test_interest_never_becomes_order(self):
        self.assertIn('inquiry_or_interest_stated_as_order',validate(self.plan,proposal(self.plan,
            'We will review construction costing for your order.'))['issues'])

    def test_local_repair_same_plan_unmodified_other_slots(self):
        result,registry,contract=prepared('P5-R10');plan=build(result,registry)
        good=surface(company_moq(contract));bad=copy.deepcopy(good)
        bad['slots'][0]['text']+=' We guarantee USD 8.25.'
        chat,_=chat_sequence(bad,{'repairs':[{'slot_index':0,'text':good['slots'][0]['text']}]})
        result=render_plan(plan,chat)
        self.assertEqual(result['status'],'ready_for_review',result['guard'])
        self.assertTrue(result['attempts'][1]['unchanged_slots_byte_identical'])
        self.assertTrue(result['attempts'][1]['required_content_preserved'])
        self.assertEqual({a['plan_hash'] for a in result['attempts']},{plan.hash})

    def test_passing_fresh_audit_cannot_clear_hard_failure(self):
        bad={'slots':[{'item_ids':['primary'],'text':self.good+' We will ship tomorrow.'}]}
        repair={'repairs':[{'slot_index':0,'text':bad['slots'][0]['text']}]}
        chat,_=chat_sequence(bad,repair)
        result=render_plan(self.plan,chat)
        self.assertTrue(result['advisory_audit']['passed'])
        self.assertFalse(result['guard']['passed'])
        self.assertEqual(result['status'],'withheld')
        self.assertIsNone(result['draft'])

    def test_missing_primary_requires_upstream_or_plan_review_not_replanning(self):
        bad={'slots':[{'item_ids':['invented-action'],'text':self.good}]}
        chat,calls=chat_sequence(bad)
        result=render_plan(self.plan,chat)
        self.assertEqual(len(calls),1)
        self.assertEqual(result['status'],'withheld')

    def test_language_and_operator_leakage(self):
        for text in ['我们会先核实材料和工艺再进行初步核价。',self.good+' The business_owner must approve WORKING_VALUE.']:
            self.assertFalse(validate(self.plan,proposal(self.plan,text))['passed'])

    def test_bound_question_must_actually_ask(self):
        result,registry,contract=prepared('P5-R10');plan=build(result,registry)
        wire=surface(company_moq(contract))
        wire['slots'][-1]['text']='The standard quantity cannot be confirmed.'
        self.assertIn('approved_question_omitted:PQ1',validate(plan,normalize(wire,plan))['issues'])

    def test_cold_start_unknown_quantity_plan_preserves_approved_questions(self):
        plan=plan_for('Please assess work vests for initial costing.')
        self.assertEqual([q['field'] for q in plan.document['approved_questions']],['quantity','customization'])
        self.assertEqual(plan.document['construction_issues'],[])

    def test_past_work_is_not_next_move(self):
        bad='I have reviewed preliminary construction costing for work vests.'
        self.assertIn('advance_stated_as_completed',validate(self.plan,proposal(self.plan,bad))['issues'])

    def test_courtesy_local_repair_cannot_change_business_slot(self):
        wire={'slots':[{'item_ids':['primary'],'text':self.good}],'courtesy':'Thank you for sharing these details.'}
        chat,_=chat_sequence(wire,{'repairs':[{'slot_index':-1,'text':'Thank you.'}]})
        result=render_plan(self.plan,chat)
        self.assertEqual(result['status'],'ready_for_review')
        self.assertTrue(result['attempts'][1]['unchanged_slots_byte_identical'])
        self.assertEqual(result['proposal']['slots'],wire['slots'])

    def test_authorized_payment_synonym_is_condition_not_execution(self):
        from selftest_inquiry_v2_context import source_context
        cc=source_context('company',ident='payment',value=240)
        source,value=cc['sources'][0],cc['candidates'][0]
        source['text']='Our payment terms accept a letter of credit.'
        value.update(key='payment_terms',value='L/C',unit=None)
        value['provenance'].update(quote=source['text'],span=[0,len(source['text'])])
        result,registry,_=prepared('P5-R01',cc)
        request=payload({'body':'Please assess 420 work vests unchanged. What payment terms apply?'},cold=True)
        request['company_context']=cc
        plan=build(analyze(request),registry_for(request))
        ident=plan.document['required_answers'][0]['id']
        wire={'slots':[{'item_ids':[ident],'text':'We accept a letter of credit.'},
                       {'item_ids':['primary'],'text':self.good}]}
        self.assertTrue(validate(plan,normalize(wire,plan))['passed'])
        wire['slots'][0]['text']='We accept your order by letter of credit.'
        self.assertIn('unsupported_commitment',validate(plan,normalize(wire,plan))['issues'])

    @unittest.expectedFailure
    def test_known_limit_numeric_modifier_must_not_create_order(self):
        plan=plan_for('We are considering 365 work vests for rough costing. No order is confirmed.')
        bad='We will review construction costing for the 365-piece bulk order of work vests.'
        self.assertFalse(validate(plan,proposal(plan,bad))['passed'])

    @unittest.expectedFailure
    def test_known_limit_flexibility_binding_must_not_reask_actual_quantity(self):
        result,registry,contract=prepared('P5-R10');plan=build(result,registry)
        wire=surface(company_moq(contract))
        wire['slots'][-1]['text']='Could the standard minimum work, and how many work vests do you need?'
        self.assertFalse(validate(plan,normalize(wire,plan))['passed'])


if __name__=='__main__':unittest.main()
