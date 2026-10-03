"""Actual P0-P2 HTTP path; offline and source coverage boundaries."""
import json
import os
os.environ['LLM_BASE_URL'] = ''
os.environ['LLM_API_KEY'] = ''
os.environ['PIPELINE_VERSION'] = 'v4'
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
import server
from selftest_inquiry_v2 import fictional_context


class InquiryHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = HTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(cls.http.server_port)
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()

    def post(self, body):
        req = urllib.request.Request(self.url + '/v2/inquiry', data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
        return json.load(self.opener.open(req, timeout=5))

    def test_cold_start_and_scoped_context(self):
        request = {'inquiry': {'primary': {'text': 'Please review preliminary costing for 400 work vests.'}}}
        for context in ({}, fictional_context()):
            with self.subTest(has_context=bool(context)):
                result = self.post({**request, 'company_context': context})
                self.assertEqual(result['advance']['action'], 'INTERNAL_COSTING')
                self.assertTrue(result['trust']['needs_human_approval'])
                self.assertIsNone(result['trust']['guard']['passed'])
                self.assertIsNone(result['reply']['draft'])

    def test_bad_contract_is_400(self):
        valid = {'inquiry': {'primary': {'text': 'Please assess work vests.'}}}
        bad = [{}, [], {'inquiry': {'primary': {'text': 42}}},
               {**valid, 'candidate_draft': 42}, {**valid, 'use_model': 'yes'},
               {**valid, 'company_context': {'sources': 'wrong'}},
               {'inquiry': {**valid['inquiry'], 'attachments': [42]}}]
        for request in bad:
            with self.subTest(request=request):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    self.post(request)
                self.assertEqual(error.exception.code, 400)

    def test_unread_reference_with_research_disabled_or_enabled_is_honest(self):
        inquiry = {'primary': {'text': 'Could you assess the item in this listing?'},
                   'referenced_urls': ['https://fictional.example.invalid/item']}
        for enabled in (False, True):
            result = self.post({'inquiry': inquiry, 'research': {'enabled': enabled}})
            self.assertFalse(result['trust']['research']['ran'])
            self.assertTrue(result['trust']['research']['pending'])
            self.assertNotIn('product_reference', [q['field'] for q in result['advance']['customer_questions']])

    def test_legacy_health_and_ui_still_available(self):
        health = json.load(self.opener.open(self.url + '/health', timeout=5))
        self.assertEqual((health['mode'], health['pipeline']), ('demo', 'v4'))
        with self.opener.open(self.url + '/ui', timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b'<html', response.read().lower())


if __name__ == '__main__':
    unittest.main(verbosity=2)
