"""Focused Light Harness boundary and HTTP approval checks."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
import light_harness as H
import light_server as S

def model_reply(draft, hint=''):
    return json.dumps({'draft':draft,'contextual_hint':hint})

class LightTests(unittest.TestCase):
    def setUp(self):
        self.cases=json.loads((H.ROOT/'data/light-demo/cases.json').read_text(encoding='utf-8'))['cases']

    def test_confirmation_and_source_boundary(self):
        with patch.object(H.llm_client,'chat') as call:
            self.assertEqual(H.process(dict(self.cases[0],context_authorized=False))['status'],'confirmation_required')
            call.assert_not_called()
        with self.assertRaises(ValueError):
            H.normalize(dict(self.cases[0],company_context=[{'statement':'We are certified.'}]))

    def test_recorded_playback_is_exact_and_not_new_inference(self):
        records=json.loads((H.ROOT/'data/light-demo/first-drafts.json').read_text(encoding='utf-8'))
        with patch.object(H.llm_client,'demo_mode',return_value=True):
            for body,record in zip(self.cases,records):
                result=H.process(body)
                self.assertEqual(result['raw_draft'],record['raw_draft'])
                self.assertEqual(result['meta']['new_model_calls'],0)
            self.assertEqual(H.process(dict(self.cases[0],business_brief='Different focus'))['status'],'endpoint_required')

    def test_failure_has_one_attempt_and_no_substitute(self):
        with patch.object(H.llm_client,'demo_mode',return_value=False),patch.object(H.llm_client,'chat',return_value=(None,{})) as call:
            result=H.process(self.cases[0])
            self.assertEqual(result['status'],'generation_failed')
            self.assertEqual(result['raw_draft'],'')
            self.assertEqual(call.call_count,1)
            self.assertEqual(call.call_args.kwargs['transport_attempts'],1)

    def test_failure_feedback_distinguishes_safe_error_categories(self):
        for meta, phrase in [({'error_kind':'http_error','http_status':401}, 'HTTP 401'),
                             ({'error_kind':'http_error','http_status':429}, 'HTTP 429'),
                             ({'error_kind':'http_error','http_status':503}, 'temporarily unavailable'),
                             ({'error_kind':'timeout'}, 'timeout'),
                             ({'error_kind':'connection'}, 'connect'),
                             ({'error_kind':'invalid_response'}, 'invalid response'),
                             ({'error_kind':'empty_response'}, 'empty draft')]:
            with self.subTest(meta=meta), patch.object(H.llm_client,'demo_mode',return_value=False), \
                 patch.object(H.llm_client,'chat',return_value=(None,meta)):
                result=H.process({'inquiry':'Synthetic draft request.'})
                self.assertEqual(result['status'],'generation_failed')
                self.assertIn(phrase,result['error'])
                self.assertIn('previous draft are kept',result['error'])

    def test_cold_start(self):
        with patch.object(H.llm_client,'demo_mode',return_value=False),patch.object(H.llm_client,'chat',return_value=(model_reply('We can review the design before confirming feasibility.'),{})):
            result=H.process({'inquiry':'Can you assess a custom vest?'})
            self.assertEqual(result['brief']['authorized_company_conditions'],[])

    def test_operator_facts_do_not_authorize_company_claims_or_change_old_replay_hash(self):
        old=H.normalize(self.cases[0])
        empty=H.normalize(dict(self.cases[0],operator_context='',reply_materials=[]))
        self.assertEqual(H.digest(old),H.digest(empty))
        p=H.normalize({'inquiry':'Please show the product options.',
                       'operator_context':'The product photos are ready. We are certified.',
                       'reply_materials':[{'name':'Product photos','state':'available','source':'Operator'}]})
        self.assertEqual(H.brief_view(p)['authorized_company_conditions'],[])
        self.assertNotEqual(H.digest(p),H.digest(H.normalize({'inquiry':p['inquiry']})))
        with self.assertRaises(ValueError):
            H.normalize(dict(self.cases[0],reply_materials=[{'name':'file','source':'operator','state':'sent'}]))

    def test_operator_reminder_is_separate_and_original_response_is_preserved(self):
        draft='Please find attached the product options. After selection we can review your specifications.'
        raw=model_reply(draft,'Attach the selected product options before sending.')
        with patch.object(H.llm_client,'demo_mode',return_value=False), \
             patch.object(H.llm_client,'chat',return_value=(raw,{})) as call:
            r=H.process({'inquiry':'Please send the product options.',
                         'operator_context':'The product options are ready.'})
        self.assertEqual(r['raw_draft'],draft)
        self.assertEqual(r['draft'],draft)
        self.assertEqual(r['raw_model_output'],raw)
        self.assertIn('before sending',r['contextual_hint'])
        self.assertNotIn('before sending',r['draft'])
        self.assertEqual(call.call_count,1)
        self.assertEqual(call.call_args.kwargs['transport_attempts'],1)

    def test_unrelated_model_hint_cannot_hide_pre_send_attachment_reminder(self):
        draft='Please find attached the product options.'
        with patch.object(H.llm_client,'demo_mode',return_value=False), \
             patch.object(H.llm_client,'chat',return_value=(model_reply(draft,'Check current certification.'),{})):
            r=H.process({'inquiry':'Please send the product options.'})
        self.assertEqual(r['draft'],draft)
        self.assertIn('Check current certification.',r['contextual_hint'])
        self.assertIn('Before sending, attach',r['contextual_hint'])

    def test_bad_reply_envelope_is_not_salvaged_retried_or_persisted(self):
        server=S.ThreadingHTTPServer(('127.0.0.1',0),S.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        before=H.digest(S.RECORDS)
        try:
            for raw in ('Plain unstructured draft.', model_reply(''),
                        json.dumps({'draft':'Email','contextual_hint':[]}),
                        json.dumps({'draft':'Email','contextual_hint':'','extra':'company fact'})):
                with self.subTest(raw=raw),patch.object(H.llm_client,'demo_mode',return_value=False), \
                     patch.object(H.llm_client,'chat',return_value=(raw,{})) as call:
                    req=urllib.request.Request(base+'/process',data=json.dumps({'inquiry':'Synthetic request.'}).encode(),
                                               headers={'Content-Type':'application/json'})
                    with urllib.request.urlopen(req) as response:r=json.load(response)
                self.assertEqual(r['status'],'generation_failed')
                self.assertEqual(r['draft'],'')
                self.assertEqual(r['raw_model_output'],raw)
                self.assertNotIn('draft_id',r)
                self.assertEqual(call.call_count,1)
                self.assertEqual(H.digest(S.RECORDS),before)
        finally:server.shutdown();server.server_close();thread.join()

    def test_located_generic_warnings_and_source_tense(self):
        packet=H.normalize(self.cases[0]); text='MOQ 875 pieces per color; the fee includes testing.'
        flags=H.check_draft(text,packet)
        self.assertEqual({f['code'] for f in flags},{'quantity_basis','fee_scope_review'})
        for f in flags:self.assertEqual(text[f['start']:f['end']],f['phrase'])
        packet=H.normalize(self.cases[2])
        self.assertTrue(H.check_draft('We have reviewed the design.',packet))
        self.assertFalse(H.check_draft('We will review the design and check the materials.',packet))
        packet=H.normalize({'inquiry':'Please send options.',
                            'reply_materials':[{'name':'Product options','state':'not_ready','source':'Operator'}]})
        self.assertIn('material_preparation',{f['code'] for f in H.check_draft('Please find attached the options.',packet)})

    def test_http_approval_preserves_original_and_requires_review(self):
        server=S.ThreadingHTTPServer(('127.0.0.1',0),S.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        def post(path,body,origin=None):
            headers={'Content-Type':'application/json'}
            if origin:headers['Origin']=origin
            req=urllib.request.Request(base+path,data=json.dumps(body).encode(),headers=headers)
            with urllib.request.urlopen(req) as response:return json.load(response)
        try:
            with patch.object(H.llm_client,'demo_mode',return_value=True):
                r=post('/process',self.cases[0]);original=r['raw_draft']
                b={'draft_id':r['draft_id'],'draft':original+'\nReviewed next step.','actor':'Automated test; not human evidence','reviewed':True}
                with self.assertRaises(urllib.error.HTTPError) as e:post('/approve',dict(b,reviewed=False))
                self.assertEqual(e.exception.code,400)
                a=post('/approve',b)
                self.assertTrue(a['edited']);self.assertFalse(a['sending_enabled'])
                self.assertEqual(S.RECORDS[r['draft_id']]['original']['raw_draft'],original)
                self.assertEqual(a['approved_draft_hash'],H.digest(b['draft']))
                with self.assertRaises(urllib.error.HTTPError) as e:post('/approve',b,'https://untrusted.invalid')
                self.assertEqual(e.exception.code,403)
            before=H.digest(S.RECORDS)
            with patch.object(H.llm_client,'demo_mode',return_value=False), \
                 patch.object(H.llm_client,'chat',return_value=(None,{'error_kind':'timeout','transport_attempts':1})):
                failed=post('/process',{'inquiry':'Another synthetic request.'})
            self.assertEqual(failed['status'],'generation_failed')
            self.assertNotIn('draft_id',failed)
            self.assertEqual(H.digest(S.RECORDS),before)
            body={'inquiry':'Assess the supplied artwork.'}
            packet=H.normalize(body)
            packet['source_state']['attachments']=[{'name':'Linked reference 1','state':'partially_read',
                                                    'read_coverage':['visible_text']}]
            with patch.object(H.llm_client,'demo_mode',return_value=False), \
                 patch.object(H.source_reader,'enrich',return_value=packet), \
                 patch.object(H.llm_client,'chat',return_value=(model_reply('We can assess the request.'),{})):
                r=post('/process',body)
            self.assertEqual(S.RECORDS[r['draft_id']]['packet']['source_state'],packet['source_state'])
            a=post('/approve',{'draft_id':r['draft_id'],'draft':'We have reviewed the artwork.',
                               'actor':'Automated test; not human evidence','reviewed':True})
            self.assertIn('source_state',{w['code'] for w in a['warnings']})
            self.assertEqual(a['input_hash'],H.digest(H.normalize(body)))
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main(verbosity=2)
