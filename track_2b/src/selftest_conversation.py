"""Contract tests for the single-case conversation, not model quality scores."""
from copy import deepcopy
import base64
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.request import urlopen, Request
from urllib.error import HTTPError

from inquiry_v2 import analyze
from inquiry_v2.conversation import Conversation, read_uploads, revise_intent
from inquiry_v2.message_plan import customer_view
from inquiry_v2.message_plan import build
from inquiry_v2.source_registry import build as registry_for
from inquiry_v2.private_context import ContextStore
from inquiry_v2.reply_semantics import CHECKS
from inquiry_v2.reviewer import ReviewConflict, pack, unpack
from selftest_reviewer import fixture


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.request, self.plan, self.proposal = fixture()
        ContextStore(self.root/'seed.sqlite3').record(self.request['company_context'], authority='trusted_company', actor='Synthetic user')
        (self.root/'packet.json').write_text(json.dumps({'inquiry': self.request['inquiry'], 'coverage_note': 'Body only.'}), encoding='utf-8')
        (self.root/'gold.json').write_text('{"reply":"GOLD MUST NEVER REACH THE MODEL"}', encoding='utf-8')
        files = ['packet.json', 'gold.json', 'seed.sqlite3']
        (self.root/'freeze.json').write_text(json.dumps({'files': {f:hashlib.sha256((self.root/f).read_bytes()).hexdigest() for f in files}}), encoding='utf-8')
        self.env={'REVIEW_DB':str(self.root/'events.sqlite3'),'REVIEW_ACTOR':'Synthetic user',
            'CONVERSATION_CASE_PACKET':str(self.root/'packet.json'), 'CONVERSATION_FREEZE':str(self.root/'freeze.json'),
            'CONVERSATION_CONTEXT_SEED':str(self.root/'seed.sqlite3')}
        self.calls=[]
        self.command={'mode':'wording','instruction':'Make it shorter.','changes':[]}
        def chat(messages, **kwargs):
            self.calls.append(deepcopy(messages))
            system=messages[0]['content']
            if system.startswith('Translate the operator'): output=self.command
            elif system.startswith('Review the ACTUAL'): output={'checks':{k:True for k in CHECKS},'issues':[],'speech_acts':[{'text':json.loads(messages[1]['content'])['draft'],'kind':'company_condition'}]}
            elif system.startswith('Realize the supplied'):
                view=json.loads(messages[1]['content'])
                output={'courtesy':'','slots':[{'item_ids':view['required_item_ids'], 'text':self.proposal['slots'][0]['text']}]}
            else: output={'repairs':[]}
            return json.dumps(output),{'mode':'test_mock','latency_ms':0}
        def local(payload, **kwargs):
            return analyze({**payload,'use_model':False}, **kwargs)
        self.service=Conversation(self.env, chat_fn=chat, analyzer=local)

    def start(self):
        return self.service.start({'text':self.request['inquiry']['primary']['text']})

    def test_gold_is_never_in_generation_and_surface_change_preserves_plan(self):
        first=self.start()
        old=self.service._get(first['id'])
        revised=self.service.turn({'id':first['id'],'revision':first['revision'],'text':'缩短一点。'})
        new=self.service._get(first['id'])
        self.assertEqual(old['plan'],new['plan'])
        self.assertNotIn('GOLD MUST NEVER',json.dumps(self.calls))
        self.assertEqual(len(revised['history']),4)
        self.assertGreater(revised['revision'],first['revision'])

    def test_stale_revision_cannot_replace_newer_draft(self):
        first=self.start()
        self.service.turn({'id':first['id'],'revision':first['revision'],'text':'缩短一点。'})
        with self.assertRaises(ReviewConflict):self.service.turn({'id':first['id'],'revision':first['revision'],'text':'再次缩短。'})

    def test_hard_failure_cannot_be_adopted(self):
        first=self.start()
        state=self.service._get(first['id'])
        state['proposal']['courtesy']='Our MOQ is 999 pieces per style.'
        state=self.service._append(state,'test_inject',expected=state['revision'])
        with self.assertRaises(ReviewConflict):self.service.turn({'id':state['id'],'revision':state['revision'],'action':'adopt'})

    def test_frozen_input_changed_is_rejected_before_model_call(self):
        (self.root/'gold.json').write_text('{}',encoding='utf-8')
        with self.assertRaises(ReviewConflict):self.start()
        self.assertEqual(self.calls,[])

    def test_uploads_do_not_invent_read_state_or_write_supplied_path(self):
        sources,blobs=read_uploads([{'name':'../../sketch.pdf','base64':base64.b64encode(b'not parsed').decode()},
            {'name':'brief.txt','base64':base64.b64encode(b'Custom design reference.').decode()}])
        self.assertEqual(sources[0]['status'],'referenced_unread')
        self.assertEqual(sources[0]['text'],'')
        self.assertEqual(blobs[0]['name'],'sketch.pdf')
        self.assertEqual(sources[1]['status'],'read')
        with self.assertRaises(ValueError):read_uploads([{'name':3,'base64':'abc'}])

    def test_intent_revision_changes_no_fact_source_or_authorization(self):
        original=self.plan.document_json
        new=revise_intent(self.plan,[{'target':'primary','operation':'rewrite','text':'Review suitable materials before preliminary construction costing.'}],
            'Review suitable materials before preliminary construction costing.','Synthetic user')
        for field in ['allowed_customer_facts','allowed_company_claims','polarity_constraints','quantity_ownership','source_state']:
            self.assertEqual(self.plan.document[field],new.document[field])
        self.assertNotEqual(self.plan.hash,new.hash)
        self.assertEqual(self.plan.document_json,original)
        with self.assertRaises(ValueError):revise_intent(self.plan,[{'target':'primary','operation':'remove','text':''}], '删掉下一步','Synthetic user')

    def test_customer_context_never_learns_company_truth(self):
        first=self.start()
        before=ContextStore(self.service._get(first['id'])['context_path']).view()
        self.command={'mode':'customer_context','changes':[]}
        self.service.turn({'id':first['id'],'revision':first['revision'],'text':'客户说你们支持 L/C。'})
        after=ContextStore(self.service._get(first['id'])['context_path']).view()
        self.assertEqual(before,after)
        source=self.service._get(first['id'])['request']['inquiry']['thread'][-1]
        self.assertFalse(source['metadata']['original_customer_message'])

    def test_compound_style_and_new_question_preserve_facts(self):
        payload={'inquiry':{'primary':{'text':'Please assess one prototype of a cotton tote bag before deciding future production.'}}}
        plan=build(analyze(payload),registry_for(payload))
        self.assertTrue(any(f['purpose']=='prototype' for f in plan.document['quantity_ownership']))
        line=plan.document['quantity_ownership'][0]['line_ids'][0]
        change={'target':'new_question','operation':'add','text':'If the prototype is approved, what initial production quantity do you expect?',
            'field':'quantity','quantity_purpose':'bulk_interest','line_ids':[line]}
        revised=revise_intent(plan,[change],'少复述，回答之后问影响价格的数量。','Synthetic user')
        self.assertEqual(revised.document['allowed_customer_facts'],plan.document['allowed_customer_facts'])
        self.assertEqual(revised.document['allowed_company_claims'],plan.document['allowed_company_claims'])
        self.assertEqual(revised.document['approved_questions'][-1]['quantity_purpose'],'bulk_interest')
        with self.assertRaises(ValueError):
            revise_intent(plan,[{**change,'quantity_purpose':'prototype','text':'How many prototypes do you need?'}], '问数量','Synthetic user')
        with self.assertRaises(ValueError):
            revise_intent(plan,[{**change,'text':'What production quantity do you need?'}], '问数量','Synthetic user')

    def test_questions_cannot_be_hidden_in_primary_operation(self):
        with self.assertRaises(ValueError):
            revise_intent(self.plan,[{'target':'primary','operation':'rewrite','text':'Review costing; could you confirm the quantity?'}], '问数量','Synthetic user')
        with self.assertRaises(ValueError):
            revise_intent(self.plan,[{'target':'primary','operation':'rewrite','text':'We can develop the exact requested specification.'}], '直接回答客户','Synthetic user')

    def test_failed_renderer_preserves_last_draft_and_approved_plan(self):
        first=self.start();before=self.service._get(first['id'])
        self.service._render=lambda *args,**kwargs:{'proposal':None,'status':'withheld','attempts':[]}
        revised=self.service.turn({'id':first['id'],'revision':first['revision'],'text':'缩短一点。'})
        after=self.service._get(first['id'])
        self.assertEqual(before['plan'],after['plan'])
        self.assertEqual(before['draft'],revised['draft'])
        self.assertTrue(after['history'][-1]['generation_failed'])
        self.assertIn('已保留上一版',revised['hint'])

    def test_project_value_change_preserves_seed_and_previous_version(self):
        seed_before=(self.root/'seed.sqlite3').read_bytes()
        first=self.start()
        self.command={'mode':'company_value','changes':[]}
        revised=self.service.turn({'id':first['id'],'revision':first['revision'],'text':'MOQ 改 300。'})
        state=self.service._get(revised['id'])
        values=ContextStore(state['context_path']).view()['candidates']
        self.assertTrue(any(c['value']==300 and c['scope_spec']=={'project_id':state['id']} for c in values))
        self.assertEqual((self.root/'seed.sqlite3').read_bytes(),seed_before)
        self.assertTrue(any(c['value']==175 for c in values))

    def test_adopt_is_revision_bound_and_never_sends(self):
        first=self.start()
        result=self.service.turn({'id':first['id'],'revision':first['revision'],'action':'adopt'})
        self.assertTrue(result['adopted'])
        self.assertFalse(result['sent'])
        approval=self.service._get(first['id'])['approval']
        self.assertEqual(approval['plan_hash'],unpack(self.service._get(first['id'])['plan']).hash)

    def test_shared_link_and_same_origin_json_boundary(self):
        import server
        html=Path(server.HERE)/'ui/conversation.html'
        with patch.dict('os.environ',self.env),patch.object(server,'UI_PATH',str(html)),patch('inquiry_v2.conversation.Conversation',return_value=self.service):
            http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
            thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            try:
                address='http://127.0.0.1:'+str(http.server_port)
                with urlopen(address+'/ui?id=example') as response:
                    self.assertIn(b'First Reply',response.read())
                request=Request(address+'/conversation/start',data=b'{}',headers={'Content-Type':'application/json','Origin':'https://example.invalid'})
                with self.assertRaises(HTTPError) as denied:urlopen(request)
                self.assertEqual(denied.exception.code,403)
                request=Request(address+'/conversation/start',data=b'{}',headers={'Content-Type':'text/plain'})
                with self.assertRaises(HTTPError) as denied:urlopen(request)
                self.assertEqual(denied.exception.code,415)
            finally:
                http.shutdown();http.server_close();thread.join()


if __name__=='__main__':unittest.main(verbosity=2)
