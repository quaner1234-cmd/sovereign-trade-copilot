"""Actual HTTP reply boundary, without credentials or external inference."""
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from unittest.mock import patch

import server


class ReplyHTTPTests(unittest.TestCase):
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
        try:
            response = self.opener.open(req, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_offline_requested_reply_is_unavailable_core_still_advances(self):
        with patch('llm_client.chat', return_value=(None, {'mode': 'demo', 'latency_ms': 0})):
            status, result = self.post({'inquiry': {'primary': {'text': 'Please cost 420 work vests.'}},
                                        'generate_reply': True})
        self.assertEqual(status, 200)
        self.assertEqual(result['advance']['action'], 'INTERNAL_COSTING')
        self.assertEqual(result['reply']['status'], 'unavailable')
        self.assertIsNone(result['reply']['draft'])
        self.assertTrue(result['trust']['needs_human_approval'])
        self.assertIsNot(result['trust']['guard']['passed'], True)

    def test_reply_opt_in_and_invalid_modes(self):
        base = {'inquiry': {'primary': {'text': 'Please cost 420 work vests.'}}}
        status, result = self.post(base)
        self.assertEqual(status, 200)
        self.assertEqual(result['reply']['status'], 'not_composed')
        for extra in ({'generate_reply': 'yes'}, {'generate_reply': 1},
                      {'generate_reply': True, 'candidate_draft': 'Draft'}):
            with self.subTest(extra=extra):
                self.assertEqual(self.post({**base, **extra})[0], 400)

    def test_generation_does_not_bypass_company_context_authentication(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('COMPANY_CONTEXT_TOKEN', None)
            status, _ = self.post({'inquiry': {'primary': {'text': 'Please cost 420 work vests.'}},
                                   'generate_reply': True, 'company_context': {'sources': [], 'candidates': []}})
        self.assertEqual(status, 403)


if __name__ == '__main__':
    unittest.main(verbosity=2)
