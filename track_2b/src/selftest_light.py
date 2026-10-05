"""Focused Light Harness boundary and HTTP approval checks."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
import light_harness as H
import light_server as S

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

    def test_cold_start(self):
        with patch.object(H.llm_client,'demo_mode',return_value=False),patch.object(H.llm_client,'chat',return_value=('We can review the design before confirming feasibility.',{})):
            result=H.process({'inquiry':'Can you assess a custom vest?'})
            self.assertEqual(result['brief']['authorized_company_conditions'],[])

    def test_located_generic_warnings_and_source_tense(self):
        packet=H.normalize(self.cases[0]); text='MOQ 875 pieces per color; the fee includes testing.'
        flags=H.check_draft(text,packet)
        self.assertEqual({f['code'] for f in flags},{'quantity_basis','fee_scope_review'})
        for f in flags:self.assertEqual(text[f['start']:f['end']],f['phrase'])
        packet=H.normalize(self.cases[2])
        self.assertTrue(H.check_draft('We have reviewed the design.',packet))
        self.assertFalse(H.check_draft('We will review the design and check the materials.',packet))

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
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main(verbosity=2)
